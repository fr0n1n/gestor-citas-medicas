"""Reglas sobre los ficheros subidos: que se acepta y como se llaman.

Puro: no toca disco ni base de datos (lo que necesita saber del disco se le
pasa como funcion), para poder probarlo a fondo.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

#: Tamano maximo por fichero. Una foto de movil ronda 3-8 MB; un PDF
#: escaneado de varias paginas, algo mas.
TAMANO_MAXIMO = 20 * 1024 * 1024

#: Ficheros por subida.
MAXIMO_POR_SUBIDA = 10


@dataclass(frozen=True)
class TipoArchivo:
    extension: str
    mime: str
    #: Si el navegador puede mostrarlo dentro de la pagina con <img>.
    es_imagen_visible: bool


PDF = TipoArchivo("pdf", "application/pdf", False)
JPEG = TipoArchivo("jpg", "image/jpeg", True)
PNG = TipoArchivo("png", "image/png", True)
WEBP = TipoArchivo("webp", "image/webp", True)
# Las fotos del iPhone. Solo Safari sabe mostrarlas; en el resto se ofrecen
# para descargar.
HEIC = TipoArchivo("heic", "image/heic", False)

#: Lo que se apunta de una llamada. No se acepta como fichero subido -- un
#: .txt no tiene marca que mirar en sus primeros bytes, asi que cualquier
#: cosa pasaria por texto --: lo escribe la aplicacion con lo que la persona
#: teclea, que es otra cosa.
TEXTO = TipoArchivo("txt", "text/plain", False)

_MARCAS_HEIF = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


def detectar_tipo(cabecera: bytes) -> TipoArchivo | None:
    """Tipo real de un fichero a partir de sus primeros bytes.

    Nunca se mira la extension ni el tipo que declara el navegador: los
    dos los controla quien sube el fichero. Un ejecutable renombrado a
    .pdf no empieza por "%PDF-" y se rechaza.
    """
    if cabecera.startswith(b"%PDF-"):
        return PDF
    if cabecera.startswith(b"\xff\xd8\xff"):
        return JPEG
    if cabecera.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WEBP":
        return WEBP
    if cabecera[4:8] == b"ftyp" and cabecera[8:12] in _MARCAS_HEIF:
        return HEIC
    return None


TIPOS_ACEPTADOS = "PDF, JPEG, PNG, WEBP o HEIC"


# --------------------------------------------------------------------------
# Nombres
# --------------------------------------------------------------------------


def slug(texto: str | None) -> str:
    """'Traumatología / Revisión' -> 'traumatologia-revision'.

    Sin tildes, sin espacios, sin mayusculas: nombres que no dan problemas
    en ningun sistema de ficheros ni al copiarlos a otro sitio.
    """
    if not texto:
        return ""
    sin_tildes = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    limpio = re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower())
    return limpio.strip("-")[:40].strip("-")


def nombre_normalizado(
    fecha: date | None, partes: list[str | None], extension: str
) -> str:
    """Nombre de archivo definitivo: ``AAAA-MM-DD_especialidad_tipo.ext``.

    Empieza por la fecha del propio documento, asi cualquier explorador de
    archivos los ordena solos en orden cronologico.
    """
    prefijo = fecha.isoformat() if fecha else "sin-fecha"
    trozos = [s for s in (slug(p) for p in partes) if s]
    # Evita "digestivo_digestivo" si la especialidad y el titulo coinciden.
    unicos = list(dict.fromkeys(trozos)) or ["documento"]
    return f"{prefijo}_{'_'.join(unicos)}.{extension}"


def nombre_libre(nombre: str, existe: Callable[[str], bool]) -> str:
    """El mismo nombre, o con -2, -3... si ya esta ocupado.

    Dos informes de digestivo del mismo dia no deben pisarse.
    """
    if not existe(nombre):
        return nombre
    base, punto, extension = nombre.rpartition(".")
    if not punto:
        base, extension = nombre, ""
    for n in range(2, 1000):
        candidato = f"{base}-{n}.{extension}" if extension else f"{base}-{n}"
        if not existe(candidato):
            return candidato
    raise RuntimeError(f"Demasiados ficheros con el nombre {nombre}")


def nombre_original_seguro(nombre: str | None) -> str:
    """El nombre que puso el usuario, solo para mostrarlo, nunca como ruta.

    Se queda con la ultima parte (un navegador podria enviar
    "C:\\fotos\\x.jpg" o "../../x.jpg") y quita caracteres de control.
    """
    if not nombre:
        return "sin-nombre"
    ultimo = re.split(r"[\\/]", nombre)[-1]
    limpio = "".join(c for c in ultimo if c.isprintable()).strip()
    return limpio[:120] or "sin-nombre"
