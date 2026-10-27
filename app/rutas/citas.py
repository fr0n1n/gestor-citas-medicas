"""Las citas, separadas por la etapa en la que estan, y los centros.

Una cita no es siempre lo mismo: primero es una solicitud esperando a que
llamen, luego una cita con dia y hora a la que hay que ir, y al final algo
ya hecho de lo que pueden salir pruebas u otras citas. Verlas todas en la
misma lista era justo lo que las mezclaba.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from sqlmodel import select

from .. import consultas, logica
from ..modelos import Evento
from .comun import PacienteDep, SesionDep, entero_de, render, volver

router = APIRouter()


def _disponibilidad_ia() -> tuple[bool, str]:
    """Si se puede mandar algo a Claude, y por que no si no se puede."""
    from ..ia.base import obtener_analizador

    try:
        return obtener_analizador().disponible()
    except ValueError as error:
        return False, str(error)


def _ia_lista() -> bool:
    return _disponibilidad_ia()[0]


def _ia_motivo() -> str:
    return _disponibilidad_ia()[1]


@router.get("/citas")
def citas(
    request: Request,
    sesion: SesionDep,
    paciente_id: PacienteDep,
    etapa: str = consultas.ETAPA_INICIAL,
    orden: str | None = None,
):
    """Las tres etapas, en pestanas, para no verlas revueltas."""
    claves = [clave for clave, _ in consultas.ETAPAS]
    if etapa not in claves:
        etapa = consultas.ETAPA_INICIAL

    if orden not in [clave for clave, _ in consultas.ORDENES]:
        orden = consultas.ORDEN_POR_ETAPA.get(etapa, "fecha")

    return render(
        request,
        "citas.html",
        sesion,
        paciente_id,
        grupos=consultas.citas_por_etapa(sesion, etapa, paciente_id, orden),
        cuentas=consultas.cuentas_por_etapa(sesion, paciente_id),
        etapa=etapa,
        etapas=consultas.ETAPAS,
        orden=orden,
        ordenes=consultas.ORDENES,
        ia_lista=_ia_lista(),
        ia_motivo=_ia_motivo(),
        titulo="Citas",
    )


# Las direcciones antiguas siguen funcionando: estaban en el menu, en el
# historial del navegador y en enlaces que yo mismo deje por la aplicacion.
@router.get("/agenda")
def agenda_antigua():
    return RedirectResponse("/citas?etapa=fecha", status_code=301)


@router.get("/espera")
def espera_antigua():
    return RedirectResponse("/citas?etapa=solicitudes", status_code=301)


@router.get("/historial")
def historial_antiguo():
    return RedirectResponse("/citas?etapa=hechas", status_code=301)


@router.get("/historia")
def historia(request: Request, sesion: SesionDep, paciente_id: PacienteDep):
    """El recorrido de cada asunto: una consulta y lo que salio de ella."""
    return render(
        request,
        "historia.html",
        sesion,
        paciente_id,
        hilos=consultas.historia(sesion, paciente_id),
        titulo="Historia",
    )


@router.get("/centros")
def centros(request: Request, sesion: SesionDep, paciente_id: PacienteDep):
    """Un sitio por tarjeta: donde hay que ir y a que telefono llamar."""
    return render(
        request,
        "centros.html",
        sesion,
        paciente_id,
        centros=consultas.por_centros(sesion, paciente_id),
        titulo="Centros",
    )


@router.get("/centros/nuevo")
def formulario_centro(request: Request, sesion: SesionDep, paciente_id: PacienteDep):
    """Alta de un centro, con la opcion de que Claude busque los datos."""
    from ..ia.base import obtener_analizador

    try:
        analizador = obtener_analizador()
        puede_buscar = hasattr(analizador, "buscar_centro") and analizador.disponible()[0]
    except ValueError:
        puede_buscar = False

    return render(
        request,
        "centro_form.html",
        sesion,
        paciente_id,
        propuesta=None,
        nombre="",
        puede_buscar=puede_buscar,
        titulo="Nuevo centro",
    )


@router.post("/centros/buscar")
def buscar_centro(
    request: Request,
    sesion: SesionDep,
    paciente_id: PacienteDep,
    nombre: Annotated[str, Form()] = "",
):
    """Pide a Claude los datos del centro y los ensena para confirmarlos.

    No guarda nada: lo que vuelve es una propuesta. El telefono y la
    direccion de un centro sanitario no se dan por buenos sin que una
    persona los mire.
    """
    from ..ia.base import obtener_analizador

    nombre = nombre.strip()
    if not nombre:
        return volver("/centros/nuevo", "Escribe primero el nombre del centro.")

    propuesta, error = None, None
    try:
        propuesta = obtener_analizador().buscar_centro(nombre)
    except (ValueError, AttributeError):
        error = "El proveedor de IA configurado no sabe buscar centros."
    except Exception as fallo:  # noqa: BLE001 - se ensena y se sigue a mano
        error = f"No se pudo buscar: {fallo}"

    return render(
        request,
        "centro_form.html",
        sesion,
        paciente_id,
        propuesta=propuesta,
        nombre=nombre,
        error_busqueda=error,
        puede_buscar=True,
        titulo="Nuevo centro",
    )


@router.get("/centros/{centro_id}")
def centro(
    request: Request, sesion: SesionDep, paciente_id: PacienteDep, centro_id: int
):
    vista = consultas.centro_por_id(sesion, centro_id, paciente_id)
    if vista is None:
        raise HTTPException(404, "Ese centro no existe")

    return render(
        request,
        "centro_detalle.html",
        sesion,
        paciente_id,
        vista=vista,
        telefonos=consultas.telefonos_de_centro(sesion, vista.centro, paciente_id),
        titulo=vista.centro.nombre,
    )
