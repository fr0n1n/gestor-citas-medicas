"""Proveedor por API de Anthropic (API key propia, pago por uso).

Alternativa a `claude-cli` para quien no tenga suscripcion de Claude o
prefiera no usar el CLI. Admite PDF, JPEG, PNG y WEBP; no HEIC.

    pip install 'medicos[anthropic]'
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from ..config import config
from .base import PROMPT_SISTEMA, ContextoAnalisis, ErrorAnalisis, prompt_usuario
from .entrada import preparar
from .esquema import DocumentoExtraido

MODELO_POR_DEFECTO = "claude-opus-5"


class AnalizadorAnthropic:
    nombre = "anthropic"

    def __init__(self, modelo: str | None = None) -> None:
        self.modelo = modelo or config.ia_modelo or MODELO_POR_DEFECTO

    def disponible(self) -> tuple[bool, str]:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "Falta la libreria: pip install 'medicos[anthropic]'."
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False, "Falta ANTHROPIC_API_KEY en el .env."
        return True, f"API de Anthropic, modelo {self.modelo}."

    def analizar(
        self, archivo: Path, mime: str, contexto: ContextoAnalisis
    ) -> DocumentoExtraido:
        listo, motivo = self.disponible()
        if not listo:
            raise ErrorAnalisis(motivo)

        # Claude lee el PDF por su cuenta; lo demas pasa por `entrada`,
        # que encoge las fotos y convierte lo que no sea JPEG/PNG/WEBP.
        entrada = preparar(archivo, mime, admite_pdf=True)
        bloques: list[dict] = []
        for parte in entrada.partes:
            datos = base64.standard_b64encode(parte.datos).decode("ascii")
            tipo = "document" if parte.mime == "application/pdf" else "image"
            bloques.append(
                {
                    "type": tipo,
                    "source": {
                        "type": "base64",
                        "media_type": parte.mime,
                        "data": datos,
                    },
                }
            )
        peticion = prompt_usuario(contexto, entrada.referencia)
        if entrada.texto:
            peticion = f"{peticion}\n\n---\n{entrada.texto}\n---"
        bloques.append({"type": "text", "text": peticion})

        import anthropic

        try:
            respuesta = anthropic.Anthropic().messages.parse(
                model=self.modelo,
                max_tokens=16000,
                system=PROMPT_SISTEMA,
                messages=[{"role": "user", "content": bloques}],
                output_format=DocumentoExtraido,
            )
        except anthropic.APIError as error:
            raise ErrorAnalisis(f"Error de la API de Anthropic: {error}") from error

        if respuesta.stop_reason == "refusal":
            raise ErrorAnalisis("El modelo declino analizar este documento.")
        if respuesta.parsed_output is None:
            raise ErrorAnalisis("La API no devolvio datos estructurados.")
        return respuesta.parsed_output
