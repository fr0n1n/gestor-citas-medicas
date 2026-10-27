"""Proveedor vacio: el analisis automatico esta desactivado.

Existe para que el resto del codigo no tenga que preguntar si hay IA o no.
"""

from __future__ import annotations

from pathlib import Path

from .base import ContextoAnalisis, ErrorAnalisis
from .esquema import DocumentoExtraido


class AnalizadorDesactivado:
    nombre = "ninguno"

    def disponible(self) -> tuple[bool, str]:
        return False, "El analisis con IA esta desactivado (MEDICOS_IA_PROVEEDOR=ninguno)."

    def analizar(
        self, archivo: Path, mime: str, contexto: ContextoAnalisis
    ) -> DocumentoExtraido:
        raise ErrorAnalisis(self.disponible()[1])
