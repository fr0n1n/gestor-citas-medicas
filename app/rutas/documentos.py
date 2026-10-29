"""Documentos: subir, revisar, analizar con IA, archivar y descargar."""

from __future__ import annotations

from datetime import datetime

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
# El UploadFile de Starlette, no el de FastAPI: request.form() devuelve
# el de Starlette, y el de FastAPI es una subclase, asi que un
# isinstance() con el de FastAPI no reconoceria ningun fichero.
from fastapi.responses import FileResponse
from sqlmodel import select
from starlette.datastructures import UploadFile

from .. import almacen, archivos, cola, consultas, propuestas, vistas
from ..config import ahora
from ..enums import EstadoEvento
from ..ia.base import obtener_analizador
from ..modelos import Documento, Evento, Paciente, Tramite
from .comun import (
    PacienteDep,
    SesionDep,
    entero_de,
    fecha_de,
    hora_de,
    render,
    texto,
    volver,
)

router = APIRouter()

#: Estados de cita entre los que se puede elegir al revisar una propuesta.
ESTADOS_PROPUESTA = [
    EstadoEvento.POR_SOLICITAR,
    EstadoEvento.SOLICITADA,
    EstadoEvento.CONFIRMADA,
    EstadoEvento.REALIZADA,
]


def _buscar(sesion: SesionDep, documento_id: int) -> Documento:
    documento = sesion.get(Documento, documento_id)
    if documento is None:
        raise HTTPException(404, "El documento no existe")
    return documento


def _disponibilidad_ia() -> tuple[bool, str]:
    try:
        return obtener_analizador().disponible()
    except ValueError as error:
        return False, str(error)


# --------------------------------------------------------------------------
# Listado y subida
# --------------------------------------------------------------------------


@router.get("/documentos")
def listar(
    request: Request,
    sesion: SesionDep,
    paciente_id: PacienteDep,
    q: str | None = None,
    tema: str | None = None,
):
    ia_lista, ia_motivo = _disponibilidad_ia()
    pendientes = consultas.documentos_pendientes(sesion, paciente_id)
    # Para el selector "Para que cita" al subir: las que siguen abiertas
    # (las realizadas o canceladas ya no esperan papeles), del paciente
    # elegido si lo hay. Las que tienen fecha, primero.
    consulta_citas = select(Evento).where(
        Evento.estado.not_in((EstadoEvento.REALIZADA, EstadoEvento.CANCELADA))
    )
    if paciente_id:
        consulta_citas = consulta_citas.where(Evento.paciente_id == paciente_id)
    citas_abiertas = sorted(
        sesion.exec(consulta_citas).all(),
        key=lambda e: (e.fecha is None, e.fecha or datetime.max.date(), e.titulo),
    )
    return render(
        request,
        "documentos.html",
        sesion,
        paciente_id,
        pendientes=pendientes,
        documentos=consultas.listar_documentos(
            sesion, paciente_id, q, revisados=True, tema=tema
        ),
        temas=consultas.temas_documentos(sesion, paciente_id),
        tema_activo=tema or "",
        busqueda=q or "",
        ia_lista=ia_lista,
        ia_motivo=ia_motivo,
        citas_abiertas=citas_abiertas,
        refrescar=any(d.analizando for d in pendientes),
        titulo="Documentos",
    )


def _paciente_de_la_subida(
    sesion: SesionDep,
    formulario,
    paciente_cookie: int | None,
    evento_id: int | None,
    tramite_id: int | None,
) -> int | None:
    """A que paciente pertenece lo que se sube.

    Si se sube desde una cita o un tramite, el suyo. Si no, el elegido en
    el formulario, el que se esta mirando, o el unico que haya.
    """
    if evento_id and (evento := sesion.get(Evento, evento_id)):
        return evento.paciente_id
    if tramite_id and (tramite := sesion.get(Tramite, tramite_id)):
        return tramite.paciente_id
    elegido = entero_de(formulario.get("paciente")) or paciente_cookie
    if elegido and sesion.get(Paciente, elegido):
        return elegido
    todos = consultas.listar_pacientes(sesion)
    return todos[0].id if len(todos) == 1 else None


@router.post("/documentos/subir")
async def subir(request: Request, sesion: SesionDep, paciente_id: PacienteDep):
    formulario = await request.form(
        max_files=archivos.MAXIMO_POR_SUBIDA, max_fields=20
    )
    destino = str(formulario.get("destino") or "/documentos")
    subidas = [
        f for f in formulario.getlist("archivos")
        if isinstance(f, UploadFile) and f.filename
    ]
    if not subidas:
        return volver(destino, "No has elegido ningun fichero.")

    evento_id = entero_de(formulario.get("evento"))
    tramite_id = entero_de(formulario.get("tramite"))
    paciente = _paciente_de_la_subida(sesion, formulario, paciente_id, evento_id, tramite_id)
    if paciente is None:
        for f in subidas:
            await f.close()
        return volver(destino, "Elige a que paciente pertenecen los documentos.")

    notas = texto(formulario.get("notas"))
    resultados = [
        await almacen.guardar_subida(
            sesion, f, paciente, evento_id, tramite_id, notas
        )
        for f in subidas
    ]

    guardados = [r.documento for r in resultados if r.documento]
    if formulario.get("analizar") == "si" and _disponibilidad_ia()[0]:
        for documento in guardados:
            cola.encolar(sesion, documento)

    partes = []
    if guardados:
        n = len(guardados)
        partes.append(f"{n} documento{'s' if n != 1 else ''} subido{'s' if n != 1 else ''}")
        if formulario.get("analizar") == "si":
            partes[-1] += " y enviado" + ("s" if n != 1 else "") + " a Claude"
    for r in resultados:
        if r.repetido:
            partes.append(f"'{r.nombre}' ya estaba subido")
        elif r.error:
            partes.append(f"'{r.nombre}' rechazado: {r.error}")

    # Si solo se subio uno, directo a su ficha.
    if len(guardados) == 1 and len(resultados) == 1 and destino == "/documentos":
        destino = f"/documentos/{guardados[0].id}"
    return volver(destino, ". ".join(partes) + ".")


@router.post("/documentos/llamada")
def apuntar_llamada(
    sesion: SesionDep,
    paciente_id: PacienteDep,
    texto_llamada: Annotated[str, Form(alias="texto")] = "",
    paciente: Annotated[str, Form()] = "",
    evento: Annotated[str, Form()] = "",
    destino: Annotated[str, Form()] = "/citas?etapa=fecha",
):
    """Lo que te dicen por telefono entra como entra un papel.

    Cuando llaman del hospital no hay nada que escanear: hay alguien
    copiando el dia, la hora y la planta mientras se lo dicen. Se guarda
    igual que un documento, lo lee Claude y propone la cita, que una
    persona confirma. Sin esto habia que crear la cita a mano y rellenar
    diez campos con el telefono todavia en la oreja.
    """
    escrito = texto_llamada.strip()
    if not escrito:
        return volver(destino, "No has escrito nada de la llamada.")

    evento_id = entero_de(evento)
    elegido = entero_de(paciente) or paciente_id
    if evento_id and (cita := sesion.get(Evento, evento_id)):
        elegido = cita.paciente_id
    if not elegido or not sesion.get(Paciente, elegido):
        todos = consultas.listar_pacientes(sesion)
        elegido = todos[0].id if len(todos) == 1 else None
    if elegido is None:
        return volver(destino, "Elige de quien es la cita.")

    documento = almacen.guardar_texto(
        sesion,
        escrito,
        elegido,
        evento_id=evento_id,
        notas="Apuntado de una llamada",
    )
    if documento is None:
        return volver(destino, "Eso mismo ya estaba apuntado.")

    listo, motivo = _disponibilidad_ia()
    if listo:
        cola.encolar(sesion, documento)
        return volver(
            f"/documentos/{documento.id}",
            "Apuntado. Claude lo esta leyendo para proponer la cita.",
        )
    return volver(f"/documentos/{documento.id}", f"Apuntado. {motivo}")


# --------------------------------------------------------------------------
# Ficha
# --------------------------------------------------------------------------


@router.get("/documentos/{documento_id}")
def detalle(
    request: Request, sesion: SesionDep, paciente_id: PacienteDep, documento_id: int
):
    documento = _buscar(sesion, documento_id)
    ia_lista, ia_motivo = _disponibilidad_ia()
    propuesta = propuestas.propuesta_de(documento)
    nombre_propuesto = None
    if propuesta is not None:
        nombre_propuesto = archivos.nombre_normalizado(
            propuesta.fecha_documento_real(),
            [propuesta.tema, propuesta.tipo_documento],
            documento.nombre_archivo.rsplit(".", 1)[-1],
        )

    citas = sesion.exec(
        select(Evento)
        .where(Evento.paciente_id == documento.paciente_id)
        .order_by(Evento.fecha.desc())
    ).all()
    tramites = sesion.exec(
        select(Tramite).where(Tramite.paciente_id == documento.paciente_id)
    ).all()

    # Cuantas paginas dibujar en la vista previa. Si el fichero no esta o
    # no se puede leer, se queda en 0 y la ficha ofrece la descarga.
    # Lo apuntado de una llamada no se dibuja: se lee tal cual.
    ruta = almacen.ruta_de(documento)
    dibujable = bool(ruta) and not documento.es_imagen_visible and documento.mime != "text/plain"
    paginas = vistas.paginas_de(ruta) if dibujable else 0

    return render(
        request,
        "documento_detalle.html",
        sesion,
        paciente_id,
        documento=documento,
        paginas=paginas,
        propuesta=propuesta,
        nombre_propuesto=nombre_propuesto,
        citas=citas,
        citas_por_id={c.id: c for c in citas},
        temas=consultas.temas_documentos(sesion, paciente_id),
        tramites=tramites,
        tramites_por_id={t.id: t for t in tramites},
        ia_lista=ia_lista,
        ia_motivo=ia_motivo,
        estados_propuesta=ESTADOS_PROPUESTA,
        refrescar=documento.analizando,
        titulo=documento.titulo or "Documento",
    )


@router.get("/documentos/{documento_id}/fichero")
def fichero(sesion: SesionDep, documento_id: int, descargar: bool = False):
    """El fichero original.

    Las fotos se muestran en la propia pagina; los PDF y el resto se
    descargan siempre (el movil los abre con su visor). Asi ningun fichero
    subido se interpreta nunca como una pagina de esta web.
    """
    documento = _buscar(sesion, documento_id)
    ruta = almacen.ruta_de(documento)
    if ruta is None:
        raise HTTPException(404, "El fichero de este documento no esta en el disco.")

    en_linea = documento.es_imagen_visible and not descargar
    nombre = documento.nombre_archivo if documento.revisado else (
        documento.nombre_original or documento.nombre_archivo
    )
    return FileResponse(
        ruta,
        media_type=documento.mime or "application/octet-stream",
        filename=nombre,
        content_disposition_type="inline" if en_linea else "attachment",
    )


@router.get("/documentos/{documento_id}/vista")
def vista(
    sesion: SesionDep,
    documento_id: int,
    pagina: int = 1,
    ancho: int = vistas.ANCHO_MINIATURA,
):
    """Una pagina del documento dibujada como imagen.

    Es lo que permite ver el papel dentro de la aplicacion sin incrustar el
    PDF: se sirve como una imagen propia y la politica de seguridad no hay
    que tocarla.
    """
    documento = _buscar(sesion, documento_id)
    origen = almacen.ruta_de(documento)
    if origen is None:
        raise HTTPException(404, "El fichero de este documento no esta en el disco.")

    # Solo los dos tamanos previstos: nadie puede pedir mil dibujados
    # distintos del mismo papel y llenar el disco.
    if ancho not in (vistas.ANCHO_MINIATURA, vistas.ANCHO_VISTA):
        ancho = vistas.ANCHO_MINIATURA

    imagen = vistas.imagen_de(documento.id, origen, pagina=pagina, ancho=ancho)
    if imagen is None:
        raise HTTPException(404, "No hay vista previa de este documento.")

    return FileResponse(imagen, media_type="image/jpeg")


# --------------------------------------------------------------------------
# Analisis con IA
# --------------------------------------------------------------------------


@router.post("/documentos/{documento_id}/analizar")
def analizar(sesion: SesionDep, documento_id: int):
    documento = _buscar(sesion, documento_id)
    ia_lista, ia_motivo = _disponibilidad_ia()
    if not ia_lista:
        return volver(f"/documentos/{documento_id}", ia_motivo)
    if documento.analizando:
        return volver(f"/documentos/{documento_id}")
    cola.encolar(sesion, documento)
    return volver(
        f"/documentos/{documento_id}",
        "Enviado a Claude. Puedes cerrar la pagina: la propuesta quedara "
        "guardada aqui.",
    )


@router.post("/documentos/{documento_id}/cancelar")
def cancelar(sesion: SesionDep, documento_id: int, ):
    """Saca el documento de la cola de Claude."""
    documento = _buscar(sesion, documento_id)
    if cola.cancelar(sesion, documento):
        return volver(f"/documentos/{documento_id}", "Análisis cancelado.")
    return volver(f"/documentos/{documento_id}", "No había ningún análisis en marcha.")


@router.post("/documentos/{documento_id}/descartar")
def descartar(sesion: SesionDep, documento_id: int):
    documento = _buscar(sesion, documento_id)
    documento.estado_ia = None
    documento.datos_extraidos = None
    documento.error_ia = None
    documento.ia_actualizado_en = ahora()
    sesion.add(documento)
    sesion.commit()
    return volver(f"/documentos/{documento_id}", "Propuesta descartada.")


@router.post("/documentos/{documento_id}/aplicar")
async def aplicar(request: Request, sesion: SesionDep, documento_id: int):
    documento = _buscar(sesion, documento_id)
    propuesta = propuestas.propuesta_de(documento)
    if propuesta is None or documento.estado_ia != "propuesta":
        return volver(f"/documentos/{documento_id}", "No hay ninguna propuesta pendiente.")

    f = await request.form()
    eventos = [
        propuestas.EventoRevisado(
            indice=i,
            incluir=f.get(f"e{i}_incluir") == "si",
            titulo=texto(f.get(f"e{i}_titulo")) or e.titulo,
            estado=str(f.get(f"e{i}_estado") or e.estado),
            fecha=fecha_de(f.get(f"e{i}_fecha")),
            hora=hora_de(f.get(f"e{i}_hora")),
            evento_existente_id=entero_de(f.get(f"e{i}_existente")),
            requisitos_incluidos={
                j for j in range(len(e.requisitos)) if f.get(f"e{i}_r{j}") == "si"
            },
        )
        for i, e in enumerate(propuesta.eventos)
    ]
    tramites = [
        propuestas.TramiteRevisado(
            indice=i,
            incluir=f.get(f"t{i}_incluir") == "si",
            tramite_existente_id=entero_de(f.get(f"t{i}_existente")),
        )
        for i in range(len(propuesta.tramites))
    ]

    try:
        resultado = propuestas.aplicar(
            sesion,
            documento,
            propuesta,
            eventos,
            tramites,
            titulo=texto(f.get("titulo")) or propuesta.titulo_documento,
            fecha_documento=fecha_de(f.get("fecha_documento")),
            tema=texto(f.get("tema")) or propuesta.tema,
        )
    except FileNotFoundError as error:
        sesion.rollback()
        return volver(f"/documentos/{documento_id}", str(error))

    return volver(f"/documentos/{documento_id}", resultado.resumen())


# --------------------------------------------------------------------------
# Revision a mano, sin IA
# --------------------------------------------------------------------------


@router.post("/documentos/{documento_id}/archivar")
async def archivar(request: Request, sesion: SesionDep, documento_id: int):
    """Asocia el documento a mano y lo archiva con su nombre normalizado."""
    documento = _buscar(sesion, documento_id)
    f = await request.form()

    # Se puede marcar mas de una: una citacion puede valer para dos citas.
    documento.eventos.clear()
    documento.tramites.clear()
    for valor in f.getlist("asociar"):
        valor = str(valor)
        if valor.startswith("e:"):
            evento = sesion.get(Evento, entero_de(valor[2:]) or 0)
            if evento and evento.paciente_id == documento.paciente_id:
                documento.eventos.append(evento)
        elif valor.startswith("t:"):
            tramite = sesion.get(Tramite, entero_de(valor[2:]) or 0)
            if tramite and tramite.paciente_id == documento.paciente_id:
                documento.tramites.append(tramite)

    tema = texto(f.get("tema"))
    if not tema and documento.eventos:
        tema = documento.eventos[0].especialidad

    try:
        propuestas.archivar_documento(
            documento,
            titulo=texto(f.get("titulo")),
            fecha_documento=fecha_de(f.get("fecha_documento")),
            tema=tema,
            tipo_documento=texto(f.get("tipo_documento")),
        )
    except FileNotFoundError as error:
        sesion.rollback()
        return volver(f"/documentos/{documento_id}", str(error))

    documento.notas = texto(f.get("notas")) or documento.notas
    sesion.add(documento)
    sesion.commit()
    return volver(f"/documentos/{documento_id}", f"Archivado como {documento.nombre_archivo}.")


@router.post("/documentos/{documento_id}/deshacer")
def deshacer(sesion: SesionDep, documento_id: int):
    """Revierte lo que creo este documento al confirmarse."""
    documento = _buscar(sesion, documento_id)
    if not documento.creados:
        return volver(
            f"/documentos/{documento_id}", "Este documento no creó nada."
        )

    resultado = propuestas.deshacer(sesion, documento)
    partes = []
    if resultado.creados:
        partes.append("Eliminado: " + "; ".join(resultado.creados))
    if resultado.avisos:
        partes.append("Ojo: " + "; ".join(resultado.avisos))
    partes.append("El documento vuelve a los pendientes")
    return volver(f"/documentos/{documento_id}", ". ".join(partes) + ".")


@router.post("/documentos/{documento_id}/borrar")
def borrar(
    sesion: SesionDep,
    documento_id: int,
    destino: Annotated[str, Form()] = "/documentos",
):
    documento = _buscar(sesion, documento_id)
    # Se puede borrar aunque Claude lo este leyendo: primero se corta.
    cola.cancelar(sesion, documento)
    almacen.borrar_fichero(documento)
    vistas.borrar_vistas(documento.id)
    sesion.delete(documento)
    sesion.commit()
    return volver(str(destino or "/documentos"), "Documento eliminado.")

