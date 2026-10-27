"""Vista por areas: todo lo de cada especialista, junto."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .. import consultas
from .comun import PacienteDep, SesionDep, render

router = APIRouter()


@router.get("/areas")
def listar(request: Request, sesion: SesionDep, paciente_id: PacienteDep):
    """Una tarjeta por especialidad, con lo que hay pendiente en cada una."""
    return render(
        request,
        "areas.html",
        sesion,
        paciente_id,
        areas=consultas.por_areas(sesion, paciente_id),
        titulo="Áreas",
    )


@router.get("/areas/{slug}")
def detalle(
    request: Request, sesion: SesionDep, paciente_id: PacienteDep, slug: str
):
    """El expediente completo de una especialidad."""
    area = consultas.area_por_slug(sesion, slug, paciente_id)
    if area is None:
        raise HTTPException(404, "No hay nada de esa especialidad")

    return render(
        request,
        "area_detalle.html",
        sesion,
        paciente_id,
        area=area,
        titulo=area.nombre,
    )
