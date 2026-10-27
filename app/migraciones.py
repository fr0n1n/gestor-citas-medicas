"""Actualizacion del esquema sin perder datos.

`create_all` crea las tablas que faltan, pero no toca las que ya existen: si
un modelo gana un campo nuevo, la columna no aparece en una base antigua y
la aplicacion falla. Esto anade las columnas que falten.

Solo cubre cambios que suman (columnas nuevas, que deben admitir NULL o
tener valor por defecto), que son los habituales. Renombrar o borrar
columnas exigiria una migracion escrita a mano, y es preferible que falle
de forma visible a que se pierdan datos en silencio.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

log = logging.getLogger("medicos.migraciones")


def _por_defecto_sql(columna) -> str:
    """Clausula DEFAULT para ALTER TABLE, si el modelo define un valor fijo."""
    defecto = columna.default
    if defecto is None or not getattr(defecto, "is_scalar", False):
        return ""
    valor = defecto.arg
    # Los Enum se guardan por su nombre ("NO_NECESITA"), no por su valor.
    # Como StrEnum tambien es str, hay que comprobarlo antes que el texto.
    if isinstance(valor, Enum):
        return " DEFAULT '" + valor.name.replace("'", "''") + "'"
    if isinstance(valor, bool):
        return f" DEFAULT {int(valor)}"
    if isinstance(valor, (int, float)):
        return f" DEFAULT {valor}"
    if isinstance(valor, str):
        return " DEFAULT '" + valor.replace("'", "''") + "'"
    return ""


def anadir_columnas_nuevas(motor: Engine) -> list[str]:
    """Anade a cada tabla existente las columnas nuevas de su modelo.

    Devuelve la lista de columnas anadidas ("tabla.columna").
    """
    inspector = inspect(motor)
    existentes = set(inspector.get_table_names())
    anadidas: list[str] = []

    with motor.begin() as conexion:
        for tabla in SQLModel.metadata.sorted_tables:
            if tabla.name not in existentes:
                continue  # create_all ya la ha creado entera
            columnas_bd = {c["name"] for c in inspector.get_columns(tabla.name)}
            for columna in tabla.columns:
                if columna.name in columnas_bd:
                    continue
                defecto = _por_defecto_sql(columna)
                if not columna.nullable and not defecto:
                    raise RuntimeError(
                        f"La columna nueva {tabla.name}.{columna.name} es "
                        "obligatoria y no tiene valor por defecto: necesita "
                        "una migracion escrita a mano."
                    )
                tipo = columna.type.compile(dialect=motor.dialect)
                conexion.execute(
                    text(
                        f'ALTER TABLE "{tabla.name}" ADD COLUMN '
                        f'"{columna.name}" {tipo}{defecto}'
                    )
                )
                anadidas.append(f"{tabla.name}.{columna.name}")
                log.warning("Columna anadida: %s.%s", tabla.name, columna.name)

    return anadidas


# --------------------------------------------------------------------------
# Fechas: de hora local a UTC
# --------------------------------------------------------------------------
#
# Hasta 2026-09-23 la aplicacion guardaba `datetime.now()`, es decir hora de
# Espana y sin zona horaria. SQLModel 0.0.43 en adelante exige que lleven
# zona, y como SQLite se come el desfase al escribirlas, al leerlas las da
# por UTC. Las filas antiguas se leerian con una o dos horas de adelanto.
#
# Esta migracion las reescribe una sola vez. Es la unica que no se limita a
# sumar, asi que deja constancia de haberse hecho para no repetirse: pasarla
# dos veces restaria las horas dos veces.

#: Columnas que guardan un instante (no una fecha suelta como `Evento.fecha`).
COLUMNAS_INSTANTE: tuple[tuple[str, str], ...] = (
    ("paciente", "creado_en"),
    ("centro", "creado_en"),
    ("evento", "creado_en"),
    ("evento", "actualizado_en"),
    ("tramite", "creado_en"),
    ("documento", "creado_en"),
    ("documento", "ia_actualizado_en"),
    ("contacto", "creado_en"),
    ("usuario", "creado_en"),
    ("usuario", "ultimo_acceso"),
    ("sesion", "creada_en"),
    ("sesion", "expira_en"),
)

_TABLA_CONTROL = "migracion_hecha"


def _ya_hecha(conexion, nombre: str) -> bool:
    conexion.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {_TABLA_CONTROL} ("
            "nombre TEXT PRIMARY KEY, hecha_en TEXT)"
        )
    )
    fila = conexion.execute(
        text(f"SELECT 1 FROM {_TABLA_CONTROL} WHERE nombre = :n"), {"n": nombre}
    ).first()
    return fila is not None


def _anotar(conexion, nombre: str) -> None:
    conexion.execute(
        text(
            f"INSERT OR REPLACE INTO {_TABLA_CONTROL} (nombre, hecha_en) "
            "VALUES (:n, :c)"
        ),
        {"n": nombre, "c": datetime.now(timezone.utc).isoformat()},
    )


def fechas_a_utc(motor: Engine, zona: ZoneInfo) -> int:
    """Pasa a UTC los instantes guardados en hora local. Devuelve cuantos.

    Se apoya en `zona` para respetar el horario de verano de cada fecha: no
    es lo mismo una fila de enero (+1) que una de agosto (+2).
    """
    nombre = "fechas_a_utc"
    inspector = inspect(motor)
    tablas = set(inspector.get_table_names())
    convertidas = 0

    with motor.begin() as conexion:
        if _ya_hecha(conexion, nombre):
            return 0

        for tabla, columna in COLUMNAS_INSTANTE:
            if tabla not in tablas:
                continue
            if columna not in {c["name"] for c in inspector.get_columns(tabla)}:
                continue

            filas = conexion.execute(
                text(f"SELECT id, {columna} FROM {tabla} WHERE {columna} IS NOT NULL")
            ).all()

            for id_fila, valor in filas:
                nuevo = _a_utc(valor, zona)
                if nuevo is None or nuevo == valor:
                    continue
                conexion.execute(
                    text(f"UPDATE {tabla} SET {columna} = :v WHERE id = :id"),
                    {"v": nuevo, "id": id_fila},
                )
                convertidas += 1

        _anotar(conexion, nombre)

    if convertidas:
        log.info("fechas pasadas de hora local a UTC: %d", convertidas)
    return convertidas


def _a_utc(valor, zona: ZoneInfo) -> str | None:
    """El texto de SQLite, interpretado como hora local y devuelto en UTC.

    Si ya trae zona horaria no se toca: es una fila escrita despues del
    cambio, o una migracion a medias que se reanuda.
    """
    if isinstance(valor, datetime):
        momento = valor
    else:
        try:
            momento = datetime.fromisoformat(str(valor))
        except ValueError:
            log.warning("fecha que no se entiende, se deja como esta: %r", valor)
            return None

    if momento.tzinfo is not None:
        return None

    en_utc = momento.replace(tzinfo=zona).astimezone(timezone.utc)
    # SQLite guarda los datetime sin desfase; se escribe en el mismo formato
    # que usa SQLAlchemy para que se lean igual.
    return en_utc.replace(tzinfo=None).isoformat(sep=" ")
