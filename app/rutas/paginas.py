"""Pantallas de consulta: inicio, agenda, en espera, calendario,
historial, documentos y exportacion a .ics.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .. import consultas, logica
from ..config import config, hoy
from ..enums import EstadoEvento, etiqueta
from ..ics import EventoICS, generar_ics
from .comun import COOKIE_PACIENTE, PacienteDep, SesionDep, render, volver

router = APIRouter()


def _ia_disponible() -> bool:
    """Si Claude puede leer un documento recien subido."""
    from ..ia.base import obtener_analizador

    try:
        return obtener_analizador().disponible()[0]
    except ValueError:
        return False


@router.get("/")
def inicio(request: Request, sesion: SesionDep, paciente_id: PacienteDep):
    return render(
        request,
        "inicio.html",
        sesion,
        paciente_id,
        panel=consultas.panel_inicio(sesion, paciente_id),
        ia_lista=_ia_disponible(),
        titulo="Hoy",
    )


@router.get("/calendario")
def calendario(
    request: Request,
    sesion: SesionDep,
    paciente_id: PacienteDep,
    anio: int | None = None,
    mes: int | None = None,
):
    hoy_ = hoy()
    anio = anio or hoy_.year
    mes = mes or hoy_.month
    if not 1 <= mes <= 12:
        anio, mes = hoy_.year, hoy_.month

    semanas = logica.rejilla_mes(anio, mes)
    por_dia = consultas.eventos_por_dia(
        sesion, semanas[0][0], semanas[-1][-1], paciente_id
    )

    return render(
        request,
        "calendario.html",
        sesion,
        paciente_id,
        anio=anio,
        mes=mes,
        semanas=semanas,
        por_dia=por_dia,
        anterior=logica.mes_anterior(anio, mes),
        siguiente=logica.mes_siguiente(anio, mes),
        sin_fecha=[
            e
            for e in consultas.sala_de_espera(sesion, paciente_id)
            if e.estado == EstadoEvento.SOLICITADA
        ],
        titulo=f"{logica.nombre_mes(mes).capitalize()} {anio}",
    )


@router.get("/seleccionar-paciente")
def seleccionar_paciente(id: str = "todos", destino: str = "/"):
    """Cambia el paciente activo y vuelve a donde se estaba."""
    respuesta = volver(destino)
    respuesta.set_cookie(
        COOKIE_PACIENTE,
        id,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="lax",
    )
    return respuesta


TEMAS = ("auto", "claro", "oscuro")


@router.get("/tema")
def cambiar_tema(valor: str = "auto", destino: str = "/"):
    """Guarda el tema elegido (automatico, claro u oscuro).

    Va en una cookie y no en el perfil del usuario a proposito: cada
    dispositivo recuerda el suyo, y el movil puede ir en oscuro por la
    noche mientras el ordenador sigue en claro.
    """
    respuesta = volver(destino)
    respuesta.set_cookie(
        "medicos_tema",
        valor if valor in TEMAS else "auto",
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="lax",
    )
    return respuesta


# --------------------------------------------------------------------------
# Exportacion a calendario
# --------------------------------------------------------------------------


@router.get("/calendario.ics")
def exportar_ics(
    sesion: SesionDep, paciente_id: PacienteDep, aviso_horas: int = 24
):
    """Calendario descargable o suscribible desde el movil.

    Incluye tanto las citas con fecha como los requisitos previos que ya la
    tienen calculada: enterarse de la analitica el dia de la cita no sirve
    de nada.
    """
    hoy_ = hoy()
    salida: list[EventoICS] = []

    # Un rango amplio: todo el historial reciente y el futuro conocido.
    por_dia = consultas.eventos_por_dia(
        sesion, hoy_ - timedelta(days=365), date(2099, 12, 31), paciente_id
    )
    for dia in sorted(por_dia):
        for evento in por_dia[dia]:
            partes = [
                p
                for p in (
                    evento.motivo,
                    f"Medico: {evento.profesional}" if evento.profesional else None,
                    f"Estado: {evento.estado.value}",
                    f"Transporte: {etiqueta(evento.transporte)}"
                    if evento.necesita_ambulancia
                    else None,
                    evento.notas,
                )
                if p
            ]
            lugar = ", ".join(
                p
                for p in (
                    evento.centro.nombre if evento.centro else None,
                    evento.ubicacion,
                )
                if p
            )
            salida.append(
                EventoICS(
                    uid=f"evento-{evento.id}@medicos.local",
                    titulo=evento.titulo,
                    fecha=evento.fecha,
                    hora=evento.hora,
                    duracion_min=evento.duracion_min,
                    lugar=lugar,
                    descripcion="\n".join(partes),
                    aviso_min_antes=aviso_horas * 60 if aviso_horas else None,
                )
            )

    for requisito in consultas.requisitos_pendientes(sesion, paciente_id):
        if requisito.fecha_limite is None:
            continue
        evento = requisito.evento
        salida.append(
            EventoICS(
                uid=f"requisito-{requisito.id}@medicos.local",
                titulo=f"Antes de la cita: {requisito.descripcion}",
                fecha=requisito.fecha_limite,
                descripcion=(
                    f"Requisito previo de: {evento.titulo}"
                    if evento
                    else requisito.descripcion
                ),
            )
        )

    cuerpo = generar_ics(salida, nombre_calendario="Citas medicas")
    return Response(
        content=cuerpo,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="citas-medicas.ics"'
        },
    )
