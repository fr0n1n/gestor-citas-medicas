#!/usr/bin/env python3
"""Instantanea consistente de la base de datos, para las copias de seguridad.

    docker compose exec -T medicos python scripts/instantanea.py

Copiar `medicos.db` mientras la aplicacion escribe puede dar un fichero a
medias. Esto usa la funcion de respaldo de SQLite, que produce una copia
coherente aunque haya escrituras en marcha, y la deja en:

    <carpeta de datos>/respaldo/medicos.db

Esa copia entra en la copia de seguridad del sistema junto con el resto de
la carpeta de datos. Primero se escribe en un fichero temporal y luego se
renombra, asi que la copia buena nunca queda a medias: si el proceso se
interrumpe, sigue estando la anterior.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import config  # noqa: E402


def main() -> int:
    if not config.ruta_db.exists():
        print(f"No existe la base de datos en {config.ruta_db}", file=sys.stderr)
        return 1

    carpeta = config.data_dir / "respaldo"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / "medicos.db"
    temporal = carpeta / "medicos.db.nueva"

    origen = sqlite3.connect(f"file:{config.ruta_db}?mode=ro", uri=True)
    copia = sqlite3.connect(temporal)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()

    temporal.replace(destino)
    print(f"Instantanea creada: {destino} ({destino.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
