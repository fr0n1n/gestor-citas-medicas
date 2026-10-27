"""Tramites administrativos: dependencia, incapacidad, ayudas, recursos."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request

from .. import consultas
from ..config import hoy
from ..enums import EstadoTramite, Prioridad
from ..modelos import PasoTramite, Tramite
from .comun import (
    PacienteDep,
    SesionDep,
    entero_de,
    fecha_de,
    render,
    texto,
    volver,
)

router = APIRouter()


def _ia_lista() -> bool:
    from ..ia.base import obtener_analizador

    try:
        return obtener_analizador().disponible()[0]
    except ValueError:
        return False


def _buscar(sesion: SesionDep, tramite_id: int) -> Tramite:
    tramite = sesion.get(Tramite, tramite_id)
    if tramite is None:
        raise HTTPException(404, "El tramite no existe")
    return tramite


@router.get("/tramites")
def listar(request: Request, sesion: SesionDep, paciente_id: PacienteDep):
    return render(
        request,
        "tramites.html",
        sesion,
        paciente_id,
        tramites=consultas.listar_tramites(sesion, paciente_id),
        titulo="Tramites",
    )


@router.post("/tramites")
def crear(
    sesion: SesionDep,
    titulo: Annotated[str, Form()],
    paciente: Annotated[int, Form()],
    organismo: Annotated[str, Form()] = "",
    estado: Annotated[str, Form()] = EstadoTramite.PENDIENTE,
    prioridad: Annotated[str, Form()] = Prioridad.NORMAL,
    expediente: Annotated[str, Form()] = "",
    iniciado_en: Annotated[str, Form()] = "",
    fecha_limite: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    tramite = Tramite(
        paciente_id=paciente,
        titulo=titulo.strip(),
        organismo=texto(organismo),
        estado=EstadoTramite(estado),
        prioridad=Prioridad(prioridad),
        expediente=texto(expediente),
        iniciado_en=fecha_de(iniciado_en),
        fecha_limite=fecha_de(fecha_limite),
        notas=texto(notas),
    )
    sesion.add(tramite)
    sesion.commit()
    sesion.refresh(tramite)
    return volver(f"/tramites/{tramite.id}", "Tramite creado.")


@router.get("/tramites/{tramite_id}")
def detalle(
    request: Request,
    sesion: SesionDep,
    paciente_id: PacienteDep,
    tramite_id: int,
):
    tramite = _buscar(sesion, tramite_id)
    return render(
        request,
        "tramite_detalle.html",
        sesion,
        paciente_id,
        ia_lista=_ia_lista(),
        tramite=tramite,
        titulo=tramite.titulo,
    )


@router.post("/tramites/{tramite_id}")
def actualizar(
    sesion: SesionDep,
    tramite_id: int,
    titulo: Annotated[str, Form()],
    organismo: Annotated[str, Form()] = "",
    estado: Annotated[str, Form()] = EstadoTramite.PENDIENTE,
    prioridad: Annotated[str, Form()] = Prioridad.NORMAL,
    expediente: Annotated[str, Form()] = "",
    iniciado_en: Annotated[str, Form()] = "",
    fecha_limite: Annotated[str, Form()] = "",
    resuelto_en: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    tramite = _buscar(sesion, tramite_id)

    tramite.titulo = titulo.strip()
    tramite.organismo = texto(organismo)
    tramite.estado = EstadoTramite(estado)
    tramite.prioridad = Prioridad(prioridad)
    tramite.expediente = texto(expediente)
    tramite.iniciado_en = fecha_de(iniciado_en)
    tramite.fecha_limite = fecha_de(fecha_limite)
    tramite.resuelto_en = fecha_de(resuelto_en)
    tramite.notas = texto(notas)

    # Cerrar un tramite sin anotar cuando deja el expediente cojo para
    # cualquier reclamacion posterior, asi que se rellena solo.
    if (
        tramite.estado in (EstadoTramite.RESUELTO, EstadoTramite.DENEGADO)
        and tramite.resuelto_en is None
    ):
        tramite.resuelto_en = hoy()

    sesion.add(tramite)
    sesion.commit()
    return volver(f"/tramites/{tramite_id}", "Cambios guardados.")


@router.post("/tramites/{tramite_id}/borrar")
def borrar(sesion: SesionDep, tramite_id: int):
    sesion.delete(_buscar(sesion, tramite_id))
    sesion.commit()
    return volver("/tramites", "Tramite eliminado.")


# --------------------------------------------------------------------------
# Pasos
# --------------------------------------------------------------------------


@router.post("/tramites/{tramite_id}/pasos")
def anadir_paso(
    sesion: SesionDep,
    tramite_id: int,
    descripcion: Annotated[str, Form()],
    fecha_limite: Annotated[str, Form()] = "",
):
    tramite = _buscar(sesion, tramite_id)
    sesion.add(
        PasoTramite(
            tramite_id=tramite_id,
            descripcion=descripcion.strip(),
            fecha_limite=fecha_de(fecha_limite),
            orden=len(tramite.pasos),
        )
    )
    sesion.commit()
    return volver(f"/tramites/{tramite_id}", "Paso anadido.")


@router.post("/pasos/{paso_id}/alternar")
def alternar_paso(
    sesion: SesionDep, paso_id: int, destino: Annotated[str, Form()] = "/tramites"
):
    paso = sesion.get(PasoTramite, paso_id)
    if paso is None:
        raise HTTPException(404, "El paso no existe")

    paso.hecho = not paso.hecho
    paso.hecho_en = hoy() if paso.hecho else None
    sesion.add(paso)
    sesion.commit()
    return volver(destino)


@router.post("/pasos/{paso_id}/borrar")
def borrar_paso(sesion: SesionDep, paso_id: int):
    paso = sesion.get(PasoTramite, paso_id)
    if paso is None:
        raise HTTPException(404, "El paso no existe")

    tramite_id = paso.tramite_id
    sesion.delete(paso)
    sesion.commit()
    return volver(f"/tramites/{tramite_id}")
