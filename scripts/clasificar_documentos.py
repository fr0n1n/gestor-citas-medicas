#!/usr/bin/env python3
"""Rellena el area (tema) de los documentos que no la tengan.

    docker compose exec -T medicos python scripts/clasificar_documentos.py
    docker compose exec -T medicos python scripts/clasificar_documentos.py --aplicar

Sin --aplicar solo enseña lo que haria. El area se busca, en este orden:

1. La que ya propuso Claude al analizarlo (guardada en el documento).
2. La especialidad de la cita a la que esta asociado.
3. La que se uso para nombrar el fichero al archivarlo.

Lo que no encaje en ninguna se queda sin area, para ponerla a mano desde la
ficha del documento.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.db import motor  # noqa: E402
from app.modelos import Documento  # noqa: E402
from app.propuestas import propuesta_de  # noqa: E402


def tema_de(sesion: Session, documento: Documento) -> tuple[str, str] | None:
    """(area, de donde sale) o None si no se puede deducir."""
    propuesta = propuesta_de(documento)
    if propuesta is not None and propuesta.tema:
        return propuesta.tema.strip(), "lo que extrajo Claude"

    if documento.evento is not None and documento.evento.especialidad:
        return documento.evento.especialidad.strip(), "la cita asociada"

    # Nombre normalizado: AAAA-MM-DD_area_tipo.ext
    partes = documento.nombre_archivo.rsplit(".", 1)[0].split("_")
    if documento.revisado and len(partes) >= 3:
        area = partes[1].replace("-", " ").strip()
        if area and area != "documento":
            return area.capitalize(), "el nombre del fichero"

    return None


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    analizador.add_argument(
        "--aplicar", action="store_true", help="guardar los cambios"
    )
    args = analizador.parse_args()

    with Session(motor) as sesion:
        documentos = sesion.exec(
            select(Documento).where(Documento.tema == None)  # noqa: E711
        ).all()
        if not documentos:
            print("Todos los documentos tienen area.")
            return 0

        cambios = 0
        for documento in documentos:
            resultado = tema_de(sesion, documento)
            nombre = documento.titulo or documento.nombre_archivo
            if resultado is None:
                print(f"  (sin area) {nombre}")
                continue
            area, origen = resultado
            print(f"  {area:<22} <- {nombre}   [{origen}]")
            if args.aplicar:
                documento.tema = area
                sesion.add(documento)
                cambios += 1

        if args.aplicar:
            sesion.commit()
            print(f"\n{cambios} documento(s) clasificados.")
        else:
            print("\nNada guardado. Repite con --aplicar para hacerlo.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
