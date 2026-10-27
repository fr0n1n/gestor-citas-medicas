"""Enlaces dentro del texto libre, y como llegar a un sitio.

Los documentos y las notas traen direcciones de internet: un enlace de
Google Maps, la web de un centro. Escritas a pelo no se pueden pulsar, y en
el movil copiar una direccion a mano no lo hace nadie.

Modulo puro: ni base de datos ni framework, solo texto. Lo que produce se
inserta en el HTML, asi que escapa primero y enlaza despues; nunca al reves.
"""

from __future__ import annotations

import re
from html import escape
from urllib.parse import quote, unquote

#: Solo http y https. Nada de javascript:, data: ni file:.
_URL = re.compile(r"https?://[^\s<>\"']+")

#: Signos que suelen ir pegados al final de una frase y no son del enlace.
_COLA = ").,;:!?»”"


def urls_de(texto: str | None) -> list[str]:
    """Las direcciones que aparecen en un texto, ya limpias de puntuacion."""
    if not texto:
        return []
    return [u.rstrip(_COLA) for u in _URL.findall(texto)]


def sin_urls(texto: str | None) -> str:
    """El mismo texto sin las direcciones ni la coletilla que las presenta.

    Sirve para ensenar "Av. del Puerto, 27, Vistamar" en vez de
    "Av. del Puerto, 27, Vistamar (enlace: https://...)".
    """
    if not texto:
        return ""
    # Se marca donde estaba cada direccion: el parentesis de cierre suele
    # quedar pegado a la URL, y borrandola a secas queda un "(enlace"
    # huerfano.
    marca = "\x00"
    limpio = _URL.sub(marca, texto)
    # "(enlace: X)", "(mapa X", "[link: X]"...
    limpio = re.sub(
        r"[\(\[]\s*(enlace|mapa|link|ubicacion|ubicación)?\s*:?\s*" + marca + r"\s*[\)\]]?",
        "",
        limpio,
        flags=re.I,
    )
    limpio = limpio.replace(marca, "")
    limpio = re.sub(r"\s{2,}", " ", limpio)
    return limpio.strip(" \t\n\r-–—,;:(")


def enlazar(texto: str | None) -> str:
    """El texto listo para el HTML, con sus direcciones ya pulsables.

    Escapa SIEMPRE antes de enlazar: lo que llega puede venir de un
    documento escaneado y no es de fiar. Devuelve texto corriente para que
    este modulo siga probandose sin instalar nada; quien lo pinta es quien
    lo marca como HTML seguro.
    """
    if not texto:
        return ""

    seguro = escape(texto, quote=True)

    def ancla(encontrado: re.Match[str]) -> str:
        crudo = encontrado.group(0)
        cola = ""
        while crudo and crudo[-1] in _COLA:
            cola = crudo[-1] + cola
            crudo = crudo[:-1]
        return (
            f'<a href="{crudo}" target="_blank" rel="noopener noreferrer">{crudo}</a>'
            + cola
        )

    return _URL.sub(ancla, seguro)


def mapa_de(direccion: str | None) -> str | None:
    """Enlace para abrir una direccion en un mapa.

    Se construye aqui, no se pide a nadie: es el navegador de la persona
    quien abre el mapa cuando lo pulsa. La aplicacion no habla con Google.
    """
    limpia = sin_urls(direccion)
    if not limpia:
        return None
    return "https://www.google.com/maps/search/?api=1&query=" + quote(limpia)


#: En un enlace largo de Google Maps el sitio va detras de "/maps/place/".
_SITIO_MAPA = re.compile(r"/maps/place/([^/@?]+)")


def nombre_de_mapa(texto: str | None) -> str | None:
    """El nombre del sitio que lleva dentro un enlace de Google Maps.

    Solo lee lo que ya viene en la direccion: la aplicacion no le pregunta
    nada a Google. Con los enlaces cortos (maps.app.goo.gl) no hay nada que
    leer, porque el nombre no viaja en ellos.

    De ".../maps/place/Centro+de+Diagnostico+Scanner,+Av.+de+Andalucia,+27..."
    saca "Centro de Diagnostico Scanner": lo que va antes de la primera
    coma, que es el sitio; lo demas es su direccion.
    """
    for url in urls_de(texto):
        encontrado = _SITIO_MAPA.search(url)
        if not encontrado:
            continue
        crudo = unquote(encontrado.group(1)).replace("+", " ")
        nombre = crudo.split(",")[0].strip()
        if nombre:
            return " ".join(nombre.split())
    return None
