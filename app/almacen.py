"""Ficheros de los documentos en disco.

    data/documentos/entrada/  subidos y pendientes de revisar (nombre aleatorio)
    data/documentos/archivo/  revisados, con su nombre normalizado

Las reglas (que tipos se aceptan, como se llaman) estan en `archivos.py`.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from starlette.datastructures import UploadFile
from sqlmodel import Session, select

from . import archivos
from .config import config
from .modelos import Documento, Evento, Tramite

_TROZO = 1024 * 1024


def dir_entrada() -> Path:
    return config.dir_documentos / "entrada"


def dir_archivo() -> Path:
    return config.dir_documentos / "archivo"


def preparar() -> None:
    for carpeta in (dir_entrada(), dir_archivo()):
        carpeta.mkdir(parents=True, exist_ok=True)


def ruta_de(documento: Documento) -> Path | None:
    """Ruta absoluta del fichero, o None si no existe o esta fuera de sitio.

    Aunque las rutas las genera siempre la aplicacion, se comprueba que
    caen dentro de la carpeta de documentos: si la base se manipulase, no
    se podria usar para servir ficheros arbitrarios del servidor.
    """
    base = config.dir_documentos.resolve()
    ruta = (base / documento.ruta_relativa).resolve()
    if not ruta.is_relative_to(base) or not ruta.is_file():
        return None
    return ruta


# --------------------------------------------------------------------------
# Subida
# --------------------------------------------------------------------------


@dataclass
class ResultadoSubida:
    nombre: str
    documento: Documento | None = None
    #: Si ya existia un documento identico.
    repetido: Documento | None = None
    error: str | None = None


async def guardar_subida(
    sesion: Session,
    subida: UploadFile,
    paciente_id: int,
    evento_id: int | None = None,
    tramite_id: int | None = None,
    notas: str | None = None,
) -> ResultadoSubida:
    """Guarda un fichero subido en la bandeja de entrada.

    Se lee por trozos, calculando la huella y vigilando el tamano, y se
    escribe en un temporal que solo se renombra al final: un fichero a
    medias o rechazado nunca queda en la carpeta de documentos.
    """
    nombre = archivos.nombre_original_seguro(subida.filename)
    preparar()

    temporal = dir_entrada() / f".subiendo-{secrets.token_hex(8)}"
    huella = hashlib.sha256()
    tamano = 0
    cabecera = b""

    try:
        with temporal.open("wb") as destino:
            while trozo := await subida.read(_TROZO):
                if len(cabecera) < 16:
                    cabecera = (cabecera + trozo)[:16]
                tamano += len(trozo)
                if tamano > archivos.TAMANO_MAXIMO:
                    return ResultadoSubida(
                        nombre,
                        error=f"supera el maximo de "
                        f"{archivos.TAMANO_MAXIMO // (1024 * 1024)} MB",
                    )
                huella.update(trozo)
                destino.write(trozo)

        if tamano == 0:
            return ResultadoSubida(nombre, error="esta vacio")

        tipo = archivos.detectar_tipo(cabecera)
        if tipo is None:
            return ResultadoSubida(
                nombre, error=f"no es un documento valido ({archivos.TIPOS_ACEPTADOS})"
            )

        hash_hex = huella.hexdigest()
        existente = sesion.exec(
            select(Documento).where(Documento.hash_sha256 == hash_hex)
        ).first()
        if existente is not None:
            return ResultadoSubida(nombre, repetido=existente)

        final = dir_entrada() / f"{secrets.token_hex(12)}.{tipo.extension}"
        os.replace(temporal, final)

        documento = Documento(
            paciente_id=paciente_id,
            notas=notas,
            nombre_archivo=final.name,
            ruta_relativa=str(final.relative_to(config.dir_documentos)),
            mime=tipo.mime,
            hash_sha256=hash_hex,
            tamano_bytes=tamano,
            nombre_original=nombre,
        )
        # Si se sube desde una cita o un tramite, queda vinculado a el.
        if evento_id:
            documento.eventos.append(sesion.get(Evento, evento_id))
        if tramite_id:
            documento.tramites.append(sesion.get(Tramite, tramite_id))

        sesion.add(documento)
        sesion.commit()
        sesion.refresh(documento)
        return ResultadoSubida(nombre, documento=documento)
    finally:
        temporal.unlink(missing_ok=True)
        await subida.close()


def guardar_texto(
    sesion: Session,
    contenido: str,
    paciente_id: int,
    evento_id: int | None = None,
    tramite_id: int | None = None,
    notas: str | None = None,
    nombre: str = "llamada.txt",
) -> Documento | None:
    """Guarda como documento lo que se apunta de una llamada.

    Cuando llaman del hospital no hay papel: hay una persona copiando a
    mano el dia, la hora y la planta mientras se lo dicen. Eso entra por el
    mismo sitio que una foto -- se guarda, lo lee Claude y propone la cita
    --, porque el trabajo que viene despues es identico.

    Devuelve None si no hay nada escrito, o si eso mismo ya se guardo antes.
    """
    texto_limpio = contenido.strip()
    if not texto_limpio:
        return None

    preparar()
    datos = texto_limpio.encode("utf-8")
    hash_hex = hashlib.sha256(datos).hexdigest()
    existente = sesion.exec(
        select(Documento).where(Documento.hash_sha256 == hash_hex)
    ).first()
    if existente is not None:
        return None

    final = dir_entrada() / f"{secrets.token_hex(12)}.{archivos.TEXTO.extension}"
    final.write_bytes(datos)

    documento = Documento(
        paciente_id=paciente_id,
        notas=notas,
        nombre_archivo=final.name,
        ruta_relativa=str(final.relative_to(config.dir_documentos)),
        mime=archivos.TEXTO.mime,
        hash_sha256=hash_hex,
        tamano_bytes=len(datos),
        nombre_original=nombre,
        texto=texto_limpio,
    )
    if evento_id:
        documento.eventos.append(sesion.get(Evento, evento_id))
    if tramite_id:
        documento.tramites.append(sesion.get(Tramite, tramite_id))

    sesion.add(documento)
    sesion.commit()
    sesion.refresh(documento)
    return documento


# --------------------------------------------------------------------------
# Archivar y borrar
# --------------------------------------------------------------------------


def archivar(documento: Documento, nombre_deseado: str) -> None:
    """Mueve el fichero a archivo/ con su nombre normalizado.

    No hace commit: quien llama decide cuando confirmar, para que el cambio
    de ruta y el resto de cambios del documento vayan juntos.
    """
    origen = ruta_de(documento)
    if origen is None:
        raise FileNotFoundError("El fichero del documento no esta en el disco.")

    preparar()
    actual = origen.parent == dir_archivo().resolve() and origen.name == nombre_deseado
    if actual:
        return

    nombre = archivos.nombre_libre(
        nombre_deseado, lambda n: (dir_archivo() / n).exists()
    )
    destino = dir_archivo() / nombre
    shutil.move(origen, destino)
    documento.nombre_archivo = nombre
    documento.ruta_relativa = str(destino.relative_to(config.dir_documentos))


def borrar_fichero(documento: Documento) -> None:
    ruta = ruta_de(documento)
    if ruta is not None:
        ruta.unlink(missing_ok=True)
