"""Miniaturas y vistas previas de los documentos.

Un escaneo solo es util si se reconoce de un vistazo. En vez de incrustar el
PDF en la pagina -- que obligaria a abrir la politica de seguridad y ademas
en el movil se ve mal -- las paginas se dibujan como imagenes en el servidor
y se sirven como cualquier otra imagen propia.

Las imagenes generadas se guardan junto a los documentos y se reutilizan: un
PDF se dibuja una sola vez.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .config import config

log = logging.getLogger("medicos.vistas")

#: Ancho en pixeles de cada tamano. La miniatura es para reconocer el papel
#: de un vistazo; la vista previa, para leerlo sin descargarlo.
ANCHO_MINIATURA = 320
ANCHO_VISTA = 1400

#: Mas paginas que esto no se dibujan: un documento larguisimo no debe
#: bloquear la peticion ni llenar el disco.
MAX_PAGINAS = 20

#: Cuanto se espera a que se dibuje una pagina.
SEGUNDOS_LIMITE = 30


def dir_vistas() -> Path:
    return config.dir_documentos / "vistas"


def _carpeta(documento_id: int) -> Path:
    return dir_vistas() / str(documento_id)


def disponible() -> bool:
    """Si el sistema puede dibujar PDFs (pdftoppm, de poppler-utils)."""
    return shutil.which("pdftoppm") is not None


def dibujar_pagina(origen: Path, destino_base: Path, ancho: int, pagina: int) -> bool:
    """Dibuja una pagina del PDF. Devuelve si lo consiguio.

    En JPEG y no en PNG: un folio escaneado en PNG pesa cerca de 700 KB y
    en JPEG unos 150, y esto se ve sobre todo desde el movil.
    """
    orden = [
        "pdftoppm", "-jpeg", "-jpegopt", "quality=82", "-r", "150",
        "-scale-to-x", str(ancho), "-scale-to-y", "-1",
        "-f", str(pagina), "-l", str(pagina),
        "-singlefile", str(origen), str(destino_base),
    ]
    try:
        resultado = subprocess.run(
            orden, capture_output=True, timeout=SEGUNDOS_LIMITE, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log.warning("no se pudo dibujar %s: %s", origen.name, error)
        return False
    if resultado.returncode != 0:
        log.warning(
            "pdftoppm fallo con %s: %s",
            origen.name,
            resultado.stderr.decode("utf-8", "replace")[:200],
        )
        return False
    return True


def _encoger_imagen(origen: Path, destino: Path, ancho: int) -> bool:
    """Hace una copia mas pequena de una foto. Las del movil pesan varios MB."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        log.warning("Pillow no esta instalado: no se encogen las imagenes")
        return False
    try:
        with Image.open(origen) as imagen:
            # Las fotos llevan la orientacion en los metadatos: sin esto
            # salen tumbadas.
            imagen = ImageOps.exif_transpose(imagen)
            imagen.thumbnail((ancho, ancho * 4), Image.LANCZOS)
            imagen.convert("RGB").save(destino, "JPEG", quality=82, optimize=True)
        return True
    except Exception as error:  # noqa: BLE001 - una foto rota no debe tumbar nada
        log.warning("no se pudo encoger %s: %s", origen.name, error)
        return False


def paginas_de(ruta: Path) -> int:
    """Cuantas paginas tiene el documento (1 si es una imagen)."""
    if ruta.suffix.lower() != ".pdf":
        return 1
    try:
        salida = subprocess.run(
            ["pdfinfo", str(ruta)], capture_output=True,
            timeout=SEGUNDOS_LIMITE, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1
    for linea in salida.stdout.decode("utf-8", "replace").splitlines():
        if linea.startswith("Pages:"):
            try:
                return max(1, min(MAX_PAGINAS, int(linea.split(":", 1)[1])))
            except ValueError:
                break
    return 1


def imagen_de(
    documento_id: int, origen: Path, pagina: int = 1, ancho: int = ANCHO_MINIATURA
) -> Path | None:
    """La imagen de una pagina, dibujandola la primera vez que se pide.

    Devuelve None si no se puede (formato raro, PDF protegido, falta
    poppler): quien llama enseña entonces el icono de siempre.
    """
    if pagina < 1 or pagina > MAX_PAGINAS or not origen.exists():
        return None

    carpeta = _carpeta(documento_id)
    destino = carpeta / f"p{pagina}-{ancho}.jpg"
    if destino.exists():
        return destino

    carpeta.mkdir(parents=True, exist_ok=True)

    if origen.suffix.lower() == ".pdf":
        # pdftoppm anade el ".png" por su cuenta.
        hecho = dibujar_pagina(origen, destino.with_suffix(""), ancho, pagina)
    elif pagina == 1:
        hecho = _encoger_imagen(origen, destino, ancho)
    else:
        hecho = False

    return destino if hecho and destino.exists() else None


def borrar_vistas(documento_id: int) -> None:
    """Quita las imagenes generadas de un documento que se borra."""
    shutil.rmtree(_carpeta(documento_id), ignore_errors=True)
