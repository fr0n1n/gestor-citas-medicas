"""Como se le pasa un documento a un proveedor que trabaja por API.

Claude por linea de ordenes abre el fichero el mismo con su herramienta de
lectura, asi que le basta la ruta. Las APIs no: reciben exactamente lo que
se les mande, asi que aqui se traduce cada documento a algo que todas
entienden.

    una llamada apuntada  -> texto
    una foto              -> imagen (encogida, que las del movil pesan)
    un PDF                -> sus paginas dibujadas como imagenes, salvo
                             que el proveedor admita el PDF tal cual

Se dibujan como mucho `MAX_PAGINAS` paginas: una citacion ocupa una o dos,
y mandar veinte multiplicaria el coste sin aportar nada.
"""

from __future__ import annotations

import io
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .base import ErrorAnalisis

log = logging.getLogger(__name__)

#: Paginas de un PDF que se mandan como mucho.
MAX_PAGINAS = 8

#: Ancho al que se encogen las imagenes antes de mandarlas. Un folio
#: escaneado se lee de sobra a 1600 px y pesa la cuarta parte.
ANCHO_MAXIMO = 1600

TEXTO = "text/plain"
PDF = "application/pdf"
#: Lo que entienden todas las APIs sin convertir nada.
IMAGENES = ("image/jpeg", "image/png", "image/webp")


@dataclass(frozen=True)
class Parte:
    """Un trozo binario listo para mandar: una foto o un PDF."""

    mime: str
    datos: bytes


@dataclass(frozen=True)
class Entrada:
    """Lo que se le manda al modelo, ya en el formato que admite.

    `referencia` es como se nombra el documento dentro de la peticion, para
    que la frase que lee el modelo diga la verdad: no es lo mismo "analiza
    el texto apuntado" que "analiza las 3 paginas".
    """

    referencia: str
    texto: str | None = None
    partes: list[Parte] = field(default_factory=list)


def preparar(
    archivo: Path,
    mime: str,
    *,
    admite_pdf: bool = False,
    max_paginas: int = MAX_PAGINAS,
) -> Entrada:
    """Traduce un documento a lo que el proveedor puede recibir.

    `admite_pdf` lo dicen los proveedores que leen PDF por su cuenta (la
    API de Anthropic, Gemini); los demas reciben las paginas dibujadas.
    """
    if mime == TEXTO:
        contenido = archivo.read_text(encoding="utf-8", errors="replace").strip()
        if not contenido:
            raise ErrorAnalisis("El documento esta vacio.")
        return Entrada(referencia="que va escrito mas abajo", texto=contenido)

    if mime == PDF:
        if admite_pdf:
            return Entrada(
                referencia="adjunto", partes=[Parte(PDF, archivo.read_bytes())]
            )
        paginas = _dibujar_pdf(archivo, max_paginas)
        cuantas = len(paginas)
        return Entrada(
            referencia="de la imagen adjunta" if cuantas == 1
            else f"de las {cuantas} imagenes adjuntas (son las paginas, en orden)",
            partes=paginas,
        )

    if mime in IMAGENES:
        return Entrada(
            referencia="de la imagen adjunta",
            partes=[Parte(*_encoger(archivo, mime))],
        )

    # HEIC y cualquier otra cosa: Pillow puede o no saber abrirla.
    convertida = _a_jpeg(archivo)
    if convertida is None:
        raise ErrorAnalisis(
            f"Este proveedor no admite documentos {mime}. Sube la foto en "
            "JPEG o PNG, o usa el proveedor claude-cli, que los lee todos."
        )
    return Entrada(referencia="de la imagen adjunta", partes=[Parte("image/jpeg", convertida)])


# --------------------------------------------------------------------------
# Conversiones
# --------------------------------------------------------------------------


def _dibujar_pdf(archivo: Path, max_paginas: int) -> list[Parte]:
    """Las paginas del PDF, en JPEG, con pdftoppm (poppler)."""
    from .. import vistas

    if not vistas.disponible():
        raise ErrorAnalisis(
            "Para mandar un PDF a este proveedor hace falta poppler-utils "
            "(pdftoppm) en el servidor. Sin el, sube el documento como foto "
            "o usa el proveedor claude-cli."
        )

    total = min(vistas.paginas_de(archivo), max_paginas)
    paginas: list[Parte] = []
    with tempfile.TemporaryDirectory(prefix="ia-pdf-") as carpeta:
        for numero in range(1, total + 1):
            base = Path(carpeta) / f"p{numero}"
            if not vistas.dibujar_pagina(archivo, base, ANCHO_MAXIMO, numero):
                continue
            dibujada = base.with_suffix(".jpg")
            if dibujada.exists():
                paginas.append(Parte("image/jpeg", dibujada.read_bytes()))

    if not paginas:
        raise ErrorAnalisis("No se ha podido dibujar ninguna pagina de este PDF.")
    return paginas


def _encoger(archivo: Path, mime: str) -> tuple[str, bytes]:
    """La foto, mas pequena si se puede. Si no, tal cual."""
    convertida = _a_jpeg(archivo)
    if convertida is None:
        return mime, archivo.read_bytes()
    return "image/jpeg", convertida


def _a_jpeg(archivo: Path) -> bytes | None:
    """Pasa una imagen a JPEG encogido. None si no se puede abrir."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None

    try:
        with Image.open(archivo) as imagen:
            # La orientacion de las fotos vive en los metadatos: sin esto
            # el modelo recibe el papel tumbado.
            imagen = ImageOps.exif_transpose(imagen)
            imagen.thumbnail((ANCHO_MAXIMO, ANCHO_MAXIMO * 4), Image.LANCZOS)
            memoria = io.BytesIO()
            imagen.convert("RGB").save(memoria, "JPEG", quality=82, optimize=True)
        return memoria.getvalue()
    except Exception as error:  # noqa: BLE001 - una foto rota no tumba el analisis
        log.warning("no se pudo convertir %s: %s", archivo.name, error)
        return None


__all__ = ["Entrada", "Parte", "preparar", "MAX_PAGINAS", "ANCHO_MAXIMO"]
