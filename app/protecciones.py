"""Filtro por el que pasan todas las peticiones antes de llegar a las rutas.

En este orden:

1. Nombre de host permitido       (DNS rebinding)
2. Formularios de la propia app   (CSRF)
3. Sesion iniciada                (usuario y contrasena)
4. Cabeceras de seguridad en la respuesta
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlmodel import Session

from . import archivos, autenticacion, seguridad
from .config import config
from .db import motor

COOKIE_SESION = "medicos_sesion"

#: Tamano maximo de una peticion de subida completa (con margen para el
#: resto del formulario).
LIMITE_SUBIDA = archivos.MAXIMO_POR_SUBIDA * archivos.TAMANO_MAXIMO + 1024 * 1024

#: Rutas accesibles sin haber iniciado sesion.
RUTAS_PUBLICAS = ("/login", "/salud", "/estatico/")


def _es_publica(ruta: str) -> bool:
    return any(
        ruta == publica or (publica.endswith("/") and ruta.startswith(publica))
        for publica in RUTAS_PUBLICAS
    )


def es_https(request: Request) -> bool:
    """Si el navegador habla con nosotros por HTTPS.

    Detras de `tailscale serve` la conexion con el contenedor es HTTP pero
    el navegador usa HTTPS; el proxy lo indica con X-Forwarded-Proto. Que
    alguien falsee esa cabecera solo haria la cookie mas restrictiva.
    """
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
    )


def _host_rechazado(host: str) -> PlainTextResponse:
    nombre = seguridad.nombre_host(host) if host else "(vacio)"
    return PlainTextResponse(
        "Acceso rechazado: este servidor no responde al nombre "
        f"'{nombre}'.\n\n"
        "Si es el nombre o la IP correctos del servidor, anadelo a "
        "MEDICOS_HOSTS_PERMITIDOS en el fichero .env y reinicia el "
        "contenedor:\n\n"
        f"    MEDICOS_HOSTS_PERMITIDOS={nombre}\n",
        status_code=400,
    )


async def filtro(request: Request, siguiente):
    respuesta = await _decidir(request, siguiente)

    # 4. Cabeceras, tambien en los rechazos y redirecciones.
    for nombre, valor in seguridad.CABECERAS_SEGURIDAD.items():
        if nombre == "Cache-Control" and request.url.path.startswith("/estatico/"):
            # La hoja de estilos y el JS si pueden cachearse.
            continue
        respuesta.headers.setdefault(nombre, valor)
    return respuesta


async def _decidir(request: Request, siguiente):
    ruta = request.url.path
    host = request.headers.get("host", "")
    permitidos = config.lista_hosts

    # 1. DNS rebinding
    if not seguridad.host_permitido(host, permitidos):
        return _host_rechazado(host)

    # 2. CSRF
    if not seguridad.origen_valido(
        request.method,
        request.headers.get("origin"),
        request.headers.get("referer"),
        host,
        permitidos,
    ):
        return PlainTextResponse(
            "Formulario rechazado: no se envio desde esta aplicacion.",
            status_code=403,
        )

    # Las subidas se miden antes de leerlas: si no, un envio gigante
    # llenaria el disco temporal antes de que la ruta pudiera rechazarlo.
    if request.method == "POST" and ruta == "/documentos/subir":
        longitud = request.headers.get("content-length")
        if longitud is None or not longitud.isdigit():
            return PlainTextResponse("Falta el tamano de la subida.", status_code=411)
        if int(longitud) > LIMITE_SUBIDA:
            return PlainTextResponse(
                "La subida es demasiado grande: como mucho "
                f"{archivos.MAXIMO_POR_SUBIDA} ficheros de "
                f"{archivos.TAMANO_MAXIMO // (1024 * 1024)} MB.",
                status_code=413,
            )

    # 3. Sesion
    request.state.usuario = None
    if not _es_publica(ruta):
        with Session(motor) as sesion:
            usuario = autenticacion.usuario_de_token(
                sesion, request.cookies.get(COOKIE_SESION)
            )
            if usuario is not None:
                # Se copia lo necesario: el objeto no debe usarse fuera de
                # la sesion de base de datos en la que se cargo.
                request.state.usuario = {"id": usuario.id, "nombre": usuario.nombre}

        if request.state.usuario is None:
            if request.method in seguridad.METODOS_SEGUROS:
                destino = ruta
                if request.url.query:
                    destino += f"?{request.url.query}"
                return RedirectResponse(
                    f"/login?siguiente={quote(destino)}", status_code=303
                )
            # Un POST sin sesion (caducada a mitad de formulario): no se
            # puede repetir tras el login, asi que se vuelve a la portada.
            return RedirectResponse("/login", status_code=303)

    return await siguiente(request)
