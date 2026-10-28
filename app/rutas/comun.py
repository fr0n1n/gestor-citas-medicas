"""Piezas compartidas por todas las rutas: plantillas, dependencias y
conversion de los campos de formulario.
"""

from __future__ import annotations

import hashlib

from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlmodel import Session

from .. import areas as _areas
from .. import centros as _centros
from .. import iconos as _iconos
from .. import enlaces as _enlaces
from .. import consultas, logica
from ..config import a_local, config, hoy
from ..db import obtener_sesion
from ..seguridad import ruta_segura
from ..enums import (
    EstadoEvento,
    EstadoTramite,
    EstadoTransporte,
    Prioridad,
    TipoEvento,
    TipoRequisito,
    etiqueta,
)

DIR_APP = Path(__file__).resolve().parent.parent

plantillas = Jinja2Templates(directory=str(DIR_APP / "plantillas"))

#: Nombre de la cookie que recuerda a que paciente se esta mirando.
COOKIE_PACIENTE = "medicos_paciente"


# --------------------------------------------------------------------------
# Filtros de plantilla
# --------------------------------------------------------------------------


def _fmt_fecha(valor: date | None) -> str:
    return valor.strftime("%d/%m/%Y") if valor else ""


def _fmt_fecha_larga(valor: date | None) -> str:
    if not valor:
        return ""
    return f"{valor.day} de {logica.nombre_mes(valor.month)} de {valor.year}"


def _dia_local(valor: datetime | None) -> date | None:
    """La fecha de un instante, vista desde Espana.

    Los instantes se guardan en UTC, asi que un documento subido a las 00:30
    de un martes esta guardado como las 22:30 del lunes. Sin convertir,
    diria que se subio un dia antes.
    """
    momento = a_local(valor)
    return momento.date() if momento else None


def _fmt_dia(valor: date | None) -> str:
    """Rotulo de una jornada: "jueves, 24 de septiembre"."""
    if not valor:
        return ""
    return (
        f"{logica.nombre_dia(valor)}, {valor.day} "
        f"de {logica.nombre_mes(valor.month)}"
    )


def _fmt_hora(valor: time | None) -> str:
    return valor.strftime("%H:%M") if valor else ""


def _iso(valor: date | time | None) -> str:
    """Valor para un <input type=date|time>, que siempre usa formato ISO."""
    return valor.isoformat() if valor else ""


def _dias_relativos(valor: date | None, referencia: date | None = None) -> str:
    """"hoy", "manana", "en 3 dias", "hace 5 dias"."""
    if valor is None:
        return ""
    referencia = referencia or hoy()
    dias = (valor - referencia).days
    if dias == 0:
        return "hoy"
    if dias == 1:
        return "manana"
    if dias == -1:
        return "ayer"
    if dias > 0:
        return f"en {dias} dias"
    return f"hace {abs(dias)} dias"


plantillas.env.filters["fecha"] = _fmt_fecha
plantillas.env.filters["fecha_larga"] = _fmt_fecha_larga
plantillas.env.filters["dia"] = _fmt_dia
plantillas.env.filters["dia_local"] = _dia_local
plantillas.env.filters["hora"] = _fmt_hora
plantillas.env.filters["iso"] = _iso
plantillas.env.filters["relativo"] = _dias_relativos
plantillas.env.filters["etiqueta"] = etiqueta
# `enlazar` ya escapa por dentro; aqui solo se marca que el resultado es
# HTML, para que Jinja no lo vuelva a escapar.
plantillas.env.filters["enlazado"] = lambda t: Markup(_enlaces.enlazar(t))
plantillas.env.filters["sin_enlaces"] = _enlaces.sin_urls
plantillas.env.filters["mapa"] = _enlaces.mapa_de
plantillas.env.filters["sitio_mapa"] = _enlaces.nombre_de_mapa
plantillas.env.filters["urls"] = _enlaces.urls_de
plantillas.env.filters["centro_corto"] = _centros.nombre_corto
# {{ icono("telefono") }}: iconos SVG en vez de emojis (ver app/iconos.py).
plantillas.env.globals["icono"] = _iconos.icono
plantillas.env.filters["slug_area"] = _areas.slug
plantillas.env.filters["color_area"] = _areas.color

def _version_estatica() -> str:
    """Huella del contenido de los ficheros estaticos.

    Va como "?v=..." en el enlace de la hoja de estilos. Sin esto, el
    navegador (y Cloudflare por delante) se quedan con la copia vieja y un
    cambio de diseno no se ve: paso de verdad el 2026-09-23.
    """
    huella = hashlib.sha256()
    for nombre in ("estilo.css", "app.js"):
        fichero = DIR_APP / "estatico" / nombre
        if fichero.exists():
            huella.update(fichero.read_bytes())
    return huella.hexdigest()[:12]


VERSION_ESTATICA = _version_estatica()


plantillas.env.globals.update(
    version_estatica=VERSION_ESTATICA,
    config=config,
    TipoEvento=TipoEvento,
    EstadoEvento=EstadoEvento,
    TipoRequisito=TipoRequisito,
    EstadoTramite=EstadoTramite,
    EstadoTransporte=EstadoTransporte,
    Prioridad=Prioridad,
    Urgencia=logica.Urgencia,
    DIAS_SEMANA=logica.DIAS_SEMANA,
    nombre_mes=logica.nombre_mes,
    transicion_valida=logica.transicion_valida,
    # Los estados a los que puede pasar una cita, para los
    # desplegables que la editan desde otra pantalla.
    transiciones=lambda estado: sorted(
        logica.TRANSICIONES.get(estado, frozenset())
    ),
)


# --------------------------------------------------------------------------
# Dependencias
# --------------------------------------------------------------------------

SesionDep = Annotated[Session, Depends(obtener_sesion)]


def paciente_activo(request: Request) -> int | None:
    """Id del paciente seleccionado, o None para "todos".

    Se guarda en una cookie en vez de arrastrarlo por la URL: asi ningun
    enlace de la aplicacion tiene que acordarse de propagarlo.
    """
    crudo = request.cookies.get(COOKIE_PACIENTE)
    if not crudo or crudo == "todos":
        return None
    try:
        return int(crudo)
    except ValueError:
        return None


PacienteDep = Annotated[int | None, Depends(paciente_activo)]


# Nombre que ve la persona segun el proveedor configurado: la web dice
# quien lee los documentos (con datos medicos, importa saber a quien se
# envian) y no "Claude" a fuego aunque se use otro.
NOMBRES_IA = {
    "claude-cli": "Claude",
    "anthropic": "Claude",
    "openai": "GPT",
    "gemini": "Gemini",
    "ollama": "Ollama",
}


def estado_ia() -> SimpleNamespace:
    """Si hay IA para analizar documentos, como se llama y, si no, por que.

    Sin cuenta de IA configurada (o con el proveedor "ninguno") las
    plantillas no ensenan ninguna opcion de IA: la app funciona igual, a
    mano. El motivo se muestra solo en Ajustes.
    """
    from ..ia.base import obtener_analizador

    try:
        analizador = obtener_analizador()
        lista, motivo = analizador.disponible()
    except ValueError as error:
        return SimpleNamespace(lista=False, nombre=None, proveedor=None, motivo=str(error))
    return SimpleNamespace(
        lista=lista,
        # "ninguno" no es un nombre que ensenar: sin IA, sin nombre.
        nombre=None if analizador.nombre == "ninguno" else NOMBRES_IA.get(analizador.nombre, analizador.nombre),
        proveedor=analizador.nombre,
        motivo=motivo,
    )


def contexto(
    request: Request,
    sesion: Session,
    paciente_id: int | None,
    **extra,
) -> dict:
    """Contexto base que espera `base.html`."""
    base = {
        "request": request,
        "hoy": hoy(),
        # Para ensenarlo junto al icono de la ambulancia en cada tarjeta.
        "telefono_ambulancia": consultas.telefono_ambulancia(sesion, paciente_id),
        "pacientes": consultas.listar_pacientes(sesion),
        # El desplegable de "donde es" sale en cada tarjeta, no solo en la
        # ficha: tiene que estar en el contexto de todas las pantallas.
        "centros": consultas.listar_centros(sesion),
        "paciente_id": paciente_id,
        "aviso": request.query_params.get("aviso"),
        "usuario": getattr(request.state, "usuario", None),
        "ia": estado_ia(),
    }
    base.update(extra)
    return base


def render(
    request: Request,
    plantilla: str,
    sesion: Session,
    paciente_id: int | None,
    **extra,
):
    return plantillas.TemplateResponse(
        request, plantilla, contexto(request, sesion, paciente_id, **extra)
    )


# --------------------------------------------------------------------------
# Redirecciones
# --------------------------------------------------------------------------


def volver(destino: str, aviso: str | None = None) -> RedirectResponse:
    """Redireccion tras un POST, opcionalmente con un mensaje.

    El 303 es importante: obliga al navegador a convertir el POST en un GET,
    de modo que recargar la pagina no repita la operacion.

    El destino puede venir de un formulario o de la URL, asi que se filtra:
    solo se admiten rutas internas de la aplicacion.
    """
    destino = ruta_segura(destino)
    if aviso:
        union = "&" if "?" in destino else "?"
        destino = f"{destino}{union}aviso={quote(aviso)}"
    return RedirectResponse(destino, status_code=303)


# --------------------------------------------------------------------------
# Conversion de campos de formulario
# --------------------------------------------------------------------------


def texto(valor: str | None) -> str | None:
    """Normaliza un campo de texto: los vacios se guardan como NULL.

    Sin esto la base de datos acaba llena de cadenas vacias que no son
    iguales a NULL y rompen los filtros.
    """
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None


def fecha_de(valor: str | None) -> date | None:
    valor = texto(valor)
    if valor is None:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


def hora_de(valor: str | None) -> time | None:
    valor = texto(valor)
    if valor is None:
        return None
    try:
        return time.fromisoformat(valor)
    except ValueError:
        return None


def entero_de(valor: str | None, por_defecto: int | None = None) -> int | None:
    valor = texto(valor)
    if valor is None:
        return por_defecto
    try:
        return int(valor)
    except ValueError:
        return por_defecto
