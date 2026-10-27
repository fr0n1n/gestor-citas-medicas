#!/usr/bin/env python3
"""Comprueba que el proveedor de IA configurado funciona.

    docker compose exec medicos python scripts/probar_ia.py
    docker compose exec medicos python scripts/probar_ia.py --fichero /data/documentos/entrada/x.pdf
    docker compose exec medicos python scripts/probar_ia.py --fichero /tmp/llamada.txt

Sin --fichero solo comprueba que esta disponible (y no gasta nada). Con
--fichero analiza ese documento y muestra lo que ha entendido, sin guardar
nada en la base de datos.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import archivos  # noqa: E402
from app.config import config, hoy  # noqa: E402
from app.ia.base import ContextoAnalisis, ErrorAnalisis, obtener_analizador  # noqa: E402


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    analizador.add_argument("--fichero", type=Path, help="foto o PDF a analizar")
    args = analizador.parse_args()

    print(f"Proveedor configurado: {config.ia_proveedor}")
    try:
        proveedor = obtener_analizador()
    except ValueError as error:
        print(f"  ERROR: {error}")
        return 1

    listo, motivo = proveedor.disponible()
    print(f"  Disponible: {'si' if listo else 'NO'} - {motivo}")
    if not listo or not args.fichero:
        return 0 if listo else 1

    # Un .txt es lo que se apunta de una llamada: no tiene marca en sus
    # primeros bytes, asi que se reconoce por la extension y solo aqui.
    if args.fichero.suffix.lower() == ".txt":
        mime = archivos.TEXTO.mime
    else:
        tipo = archivos.detectar_tipo(args.fichero.read_bytes()[:16])
        if tipo is None:
            print(f"  ERROR: no es un documento valido ({archivos.TIPOS_ACEPTADOS})")
            return 1
        mime = tipo.mime

    print("\nAnalizando... (suele tardar menos de un minuto)\n")
    contexto = ContextoAnalisis(paciente="(prueba)", hoy=hoy().isoformat(), citas=[], tramites=[])
    try:
        resultado = proveedor.analizar(args.fichero, mime, contexto)
    except ErrorAnalisis as error:
        print(f"ERROR: {error}")
        return 1

    print(json.dumps(resultado.model_dump(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
