"""Entrar y salir de la aplicacion."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from .. import autenticacion, seguridad
from ..config import config
from ..protecciones import COOKIE_SESION, es_https
from .comun import SesionDep, plantillas

router = APIRouter()


def _pagina_login(
    request: Request,
    sesion: Session,
    siguiente: str,
    error: str | None = None,
    nombre: str = "",
    codigo: int = 200,
):
    return plantillas.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "siguiente": seguridad.ruta_segura(siguiente),
            "error": error,
            "nombre": nombre,
            "sin_usuarios": not autenticacion.hay_usuarios(sesion),
        },
        status_code=codigo,
    )


@router.get("/login")
def formulario(request: Request, sesion: SesionDep, siguiente: str = "/"):
    return _pagina_login(request, sesion, siguiente)


@router.post("/login")
def entrar(
    request: Request,
    sesion: SesionDep,
    nombre: Annotated[str, Form()],
    password: Annotated[str, Form()],
    siguiente: Annotated[str, Form()] = "/",
):
    try:
        usuario = autenticacion.autenticar(sesion, nombre, password)
    except autenticacion.ErrorAcceso as error:
        return _pagina_login(
            request, sesion, siguiente, str(error), nombre, codigo=401
        )

    token = autenticacion.abrir_sesion(
        sesion, usuario, request.headers.get("user-agent")
    )
    respuesta = RedirectResponse(seguridad.ruta_segura(siguiente), status_code=303)
    respuesta.set_cookie(
        COOKIE_SESION,
        token,
        max_age=config.dias_sesion * 24 * 3600,
        httponly=True,
        # Lax: la cookie no viaja en formularios enviados desde otras webs,
        # pero si al abrir un enlace a la app (por ejemplo desde el movil).
        samesite="lax",
        secure=es_https(request),
        path="/",
    )
    return respuesta


@router.post("/salir")
def salir(request: Request, sesion: SesionDep):
    autenticacion.cerrar_sesion(sesion, request.cookies.get(COOKIE_SESION))
    respuesta = RedirectResponse("/login", status_code=303)
    respuesta.delete_cookie(COOKIE_SESION, path="/")
    return respuesta
