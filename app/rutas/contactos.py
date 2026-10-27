"""Agenda de telefonos: lo que hay que tener a mano para llamar."""

from __future__ import annotations

from typing import Annotated

from fastapi.responses import RedirectResponse
from fastapi import APIRouter, Form, HTTPException, Request

from .. import consultas
from ..enums import ICONOS_CONTACTO, TipoContacto
from ..modelos import Contacto
from .comun import PacienteDep, SesionDep, entero_de, render, texto, volver

router = APIRouter()


@router.get("/telefonos")
def listar():
    """La agenda ya no es una pantalla aparte: vive dentro de Centros."""
    return RedirectResponse("/centros", status_code=301)


@router.post("/telefonos")
def crear(
    sesion: SesionDep,
    nombre: Annotated[str, Form()],
    telefono: Annotated[str, Form()],
    tipo: Annotated[str, Form()] = TipoContacto.OTRO,
    notas: Annotated[str, Form()] = "",
    paciente: Annotated[str, Form()] = "",
    centro: Annotated[str, Form()] = "",
):
    try:
        tipo_enum = TipoContacto(tipo)
    except ValueError:
        raise HTTPException(400, f"Tipo de contacto no valido: {tipo}")

    sesion.add(
        Contacto(
            nombre=nombre.strip(),
            telefono=telefono.strip(),
            tipo=tipo_enum,
            notas=texto(notas),
            paciente_id=entero_de(paciente),
            centro_id=entero_de(centro),
        )
    )
    sesion.commit()
    return volver("/centros", "Teléfono guardado.")


@router.post("/telefonos/{contacto_id}")
def actualizar(
    sesion: SesionDep,
    contacto_id: int,
    nombre: Annotated[str, Form()],
    telefono: Annotated[str, Form()],
    tipo: Annotated[str, Form()] = TipoContacto.OTRO,
    notas: Annotated[str, Form()] = "",
    paciente: Annotated[str, Form()] = "",
    centro: Annotated[str, Form()] = "",
):
    contacto = sesion.get(Contacto, contacto_id)
    if contacto is None:
        raise HTTPException(404, "El contacto no existe")

    try:
        contacto.tipo = TipoContacto(tipo)
    except ValueError:
        raise HTTPException(400, f"Tipo de contacto no valido: {tipo}")

    contacto.nombre = nombre.strip()
    contacto.telefono = telefono.strip()
    contacto.notas = texto(notas)
    contacto.paciente_id = entero_de(paciente)

    sesion.add(contacto)
    sesion.commit()
    return volver("/telefonos", "Cambios guardados.")


@router.post("/telefonos/{contacto_id}/borrar")
def borrar(sesion: SesionDep, contacto_id: int):
    contacto = sesion.get(Contacto, contacto_id)
    if contacto is None:
        raise HTTPException(404, "El contacto no existe")
    sesion.delete(contacto)
    sesion.commit()
    return volver("/telefonos", "Teléfono eliminado.")
