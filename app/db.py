"""Conexion a la base de datos.

Un unico fichero SQLite dentro de la carpeta de datos. Esa decision es
deliberada: la copia de seguridad es copiar una carpeta, y llevarse los
datos a otro ordenador tambien.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import config

config.preparar_directorios()

motor = create_engine(
    f"sqlite:///{config.ruta_db}",
    # SQLite cierra la conexion por hilo; FastAPI atiende en varios.
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(Engine, "connect")
def _configurar_sqlite(conexion, _record):  # pragma: no cover - efecto de E/S
    """Activa las opciones que SQLite trae desactivadas por defecto.

    Las claves ajenas vienen apagadas de fabrica, y sin ellas el borrado en
    cascada de requisitos y pasos no se aplicaria a nivel de base de datos.
    El modo WAL evita que una lectura bloquee una escritura.
    """
    cursor = conexion.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def crear_tablas() -> None:
    # Importa los modelos para que queden registrados en los metadatos
    # antes de crear el esquema.
    from . import modelos  # noqa: F401

    SQLModel.metadata.create_all(motor)

    # Las tablas que ya existian pueden necesitar columnas nuevas.
    from .config import config
    from .migraciones import anadir_columnas_nuevas, fechas_a_utc

    anadir_columnas_nuevas(motor)

    # Y las fechas guardadas en hora local, pasarlas a UTC (una sola vez).
    fechas_a_utc(motor, config.tz)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesion por peticion."""
    with Session(motor) as sesion:
        yield sesion
