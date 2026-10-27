"""Pacientes y centros sanitarios: los datos que se rellenan una vez."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request

from .. import consultas
from ..modelos import Centro, Paciente
from .comun import (
    PacienteDep,
    SesionDep,
    fecha_de,
    render,
    texto,
    volver,
)

router = APIRouter()


@router.get("/pacientes")
def listar(request: Request, sesion: SesionDep, paciente_id: PacienteDep):
    return render(
        request,
        "pacientes.html",
        sesion,
        paciente_id,
        todos=consultas.listar_pacientes(sesion, solo_activos=False),
        centros=consultas.listar_centros(sesion),
        titulo="Pacientes y centros",
    )


@router.post("/pacientes")
def crear_paciente(
    sesion: SesionDep,
    nombre: Annotated[str, Form()],
    fecha_nacimiento: Annotated[str, Form()] = "",
    tarjeta_sanitaria: Annotated[str, Form()] = "",
    telefono: Annotated[str, Form()] = "",
    transporte_siempre: Annotated[str, Form()] = "",
    transporte_detalle: Annotated[str, Form()] = "",
    telefono_ambulancia: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    sesion.add(
        Paciente(
            nombre=nombre.strip(),
            fecha_nacimiento=fecha_de(fecha_nacimiento),
            tarjeta_sanitaria=texto(tarjeta_sanitaria),
            telefono=texto(telefono),
            transporte_siempre=bool(transporte_siempre),
            transporte_detalle=texto(transporte_detalle),
            telefono_ambulancia=texto(telefono_ambulancia),
            notas=texto(notas),
        )
    )
    sesion.commit()
    return volver("/pacientes", "Paciente creado.")


@router.post("/pacientes/{persona_id}")
def actualizar_paciente(
    sesion: SesionDep,
    persona_id: int,
    nombre: Annotated[str, Form()],
    fecha_nacimiento: Annotated[str, Form()] = "",
    tarjeta_sanitaria: Annotated[str, Form()] = "",
    telefono: Annotated[str, Form()] = "",
    transporte_siempre: Annotated[str, Form()] = "",
    transporte_detalle: Annotated[str, Form()] = "",
    telefono_ambulancia: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
    activo: Annotated[str, Form()] = "",
):
    persona = sesion.get(Paciente, persona_id)
    if persona is None:
        raise HTTPException(404, "El paciente no existe")

    persona.nombre = nombre.strip()
    persona.fecha_nacimiento = fecha_de(fecha_nacimiento)
    persona.tarjeta_sanitaria = texto(tarjeta_sanitaria)
    persona.telefono = texto(telefono)
    persona.transporte_siempre = bool(transporte_siempre)
    persona.transporte_detalle = texto(transporte_detalle)
    persona.telefono_ambulancia = texto(telefono_ambulancia)
    persona.notas = texto(notas)
    persona.activo = bool(activo)

    sesion.add(persona)
    sesion.commit()
    return volver("/pacientes", "Cambios guardados.")


@router.post("/centros")
def crear_centro(
    sesion: SesionDep,
    nombre: Annotated[str, Form()],
    direccion: Annotated[str, Form()] = "",
    telefono: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
    destino: Annotated[str, Form()] = "/pacientes",
):
    sesion.add(
        Centro(
            nombre=nombre.strip(),
            direccion=texto(direccion),
            telefono=texto(telefono),
            notas=texto(notas),
        )
    )
    sesion.commit()
    return volver(destino or "/pacientes", "Centro creado.")


@router.post("/centros/{centro_id}")
def actualizar_centro(
    sesion: SesionDep,
    centro_id: int,
    nombre: Annotated[str, Form()],
    direccion: Annotated[str, Form()] = "",
    telefono: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    centro = sesion.get(Centro, centro_id)
    if centro is None:
        raise HTTPException(404, "El centro no existe")

    centro.nombre = nombre.strip()
    centro.direccion = texto(direccion)
    centro.telefono = texto(telefono)
    centro.notas = texto(notas)

    sesion.add(centro)
    sesion.commit()
    return volver("/pacientes", "Cambios guardados.")
