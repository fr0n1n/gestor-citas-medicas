"""Punto de entrada de la aplicacion.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import config
from .db import crear_tablas
from .protecciones import filtro
from . import almacen, cola
from .rutas import (
    acceso,
    areas,
    citas,
    contactos,
    documentos,
    eventos,
    pacientes,
    paginas,
    tramites,
)
from .rutas.comun import DIR_APP, plantillas, volver


@asynccontextmanager
async def ciclo_vida(_app: FastAPI):
    config.preparar_directorios()
    crear_tablas()
    almacen.preparar()
    cola.arrancar()
    yield
    cola.parar()


app = FastAPI(
    title="Medicos",
    description="Gestor de citas, pruebas y tramites medicos",
    version="0.1.0",
    lifespan=ciclo_vida,
    # La documentacion automatica de la API describe todas las rutas y no
    # la necesita nadie que use la aplicacion.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.middleware("http")(filtro)

app.mount(
    "/estatico",
    StaticFiles(directory=str(DIR_APP / "estatico")),
    name="estatico",
)

app.include_router(acceso.router)
app.include_router(paginas.router)
app.include_router(eventos.router)
app.include_router(tramites.router)
app.include_router(pacientes.router)
app.include_router(documentos.router)
app.include_router(contactos.router)
app.include_router(areas.router)
app.include_router(citas.router)


@app.exception_handler(StarletteHTTPException)
async def error_http(request: Request, exc: StarletteHTTPException):
    """Paginas de error en HTML en vez del JSON por defecto.

    Quien usa esto no es desarrollador: un `{"detail": "Not Found"}` no le
    dice nada.
    """
    return plantillas.TemplateResponse(
        request,
        "error.html",
        {
            "request": request,
            "codigo": exc.status_code,
            "detalle": exc.detail,
            "pacientes": [],
            "paciente_id": None,
            "usuario": getattr(request.state, "usuario", None),
            "titulo": f"Error {exc.status_code}",
        },
        status_code=exc.status_code,
    )


#: Donde mandar a la persona cuando una direccion no se puede mostrar.
#: Hay colecciones que no tienen pagina propia: las citas se ven en la
#: agenda, y los centros dentro de Ajustes.
PAGINA_DE_VUELTA = {
    "eventos": "/agenda",
    "requisitos": "/",
    "centros": "/pacientes",
    "pasos": "/tramites",
    "documentos": "/documentos",
    "tramites": "/tramites",
    "telefonos": "/telefonos",
    "pacientes": "/pacientes",
}


def _volver_a(ruta: str) -> str:
    """Una pagina que exista, a partir de la direccion que ha fallado."""
    partes = [p for p in ruta.split("/") if p]
    if not partes:
        return "/"
    # /documentos/3/aplicar -> /documentos/3
    if len(partes) >= 3 and partes[1].isdigit():
        destino = f"/{partes[0]}/{partes[1]}"
        if partes[0] in ("requisitos", "pasos", "centros"):
            return PAGINA_DE_VUELTA.get(partes[0], "/")
        return destino
    destino = PAGINA_DE_VUELTA.get(partes[0], "/")
    # Nunca devolver a la misma direccion que ha fallado: seria un bucle.
    return "/" if destino.rstrip("/") == ruta.rstrip("/") else destino


@app.exception_handler(RequestValidationError)
async def datos_no_validos(request: Request, exc: RequestValidationError):
    """Peticion con datos que no encajan (por ejemplo, un id que no es numero).

    El caso tipico no es un fallo del usuario: un formulario cuyo envio se
    corta para pedir identificacion vuelve como navegacion normal, y una
    direccion como /documentos/subir acaba interpretandose como "ver el
    documento numero 'subir'". Se devuelve a la persona a su sitio con una
    explicacion, en vez de ensenarle el error tecnico.
    """
    if request.method in ("GET", "HEAD"):
        return volver(
            _volver_a(request.url.path),
            "No se envió el formulario y no se ha subido ni cambiado nada. "
            "Suele pasar cuando caduca la sesión al enviarlo: inténtalo de nuevo.",
        )

    return plantillas.TemplateResponse(
        request,
        "error.html",
        {
            "request": request,
            "codigo": 422,
            "detalle": "Algún dato del formulario no es válido. Revísalo e inténtalo otra vez.",
            "pacientes": [],
            "paciente_id": None,
            "usuario": getattr(request.state, "usuario", None),
            "titulo": "Datos no válidos",
        },
        status_code=422,
    )


@app.exception_handler(405)
async def metodo_no_permitido(request: Request, exc: StarletteHTTPException):
    """Cuando se entra navegando a una direccion que solo acepta formularios.

    Pasa tipicamente cuando algo por delante (Cloudflare Access, un proxy)
    corta el envio de un formulario para pedir identificacion y luego
    devuelve al navegador a la misma direccion, ya sin los datos. El
    formulario no llego a enviarse, asi que no se ha cambiado nada: se
    devuelve a la persona a la pagina de la que venia, explicandolo.
    """
    return volver(
        _volver_a(request.url.path),
        "No se envió el formulario y no se ha cambiado nada. Suele pasar "
        "cuando caduca la sesión al enviarlo: revisa los datos y vuelve a "
        "confirmar.",
    )


@app.get("/salud", response_class=HTMLResponse, include_in_schema=False)
def salud() -> str:
    """Comprobacion usada por el healthcheck de Docker."""
    return "ok"
