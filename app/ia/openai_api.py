"""Proveedor por API de OpenAI (GPT), para quien no use Claude.

Se habla por HTTP con la biblioteca estandar, sin instalar el SDK: son dos
peticiones JSON y asi la imagen no arrastra una dependencia mas. La clave
va en `OPENAI_API_KEY` del `.env`.

Los PDF se mandan como paginas dibujadas (ver `entrada.py`), porque la API
de chat solo admite imagenes.

Aviso: aqui viajan documentos medicos a un servicio de terceros. Si eso no
es aceptable, el proveedor `ollama` lo hace todo en casa.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from ..config import config
from .base import (
    PROMPT_SISTEMA,
    ContextoAnalisis,
    ErrorAnalisis,
    esquema_json,
    json_del_texto,
    prompt_usuario,
)
from .entrada import preparar
from .esquema import DocumentoExtraido
from .red import pedir_json

MODELO_POR_DEFECTO = "gpt-4o"
URL = "https://api.openai.com/v1/chat/completions"


class AnalizadorOpenAI:
    nombre = "openai"

    def __init__(self, modelo: str | None = None) -> None:
        self.modelo = modelo or config.ia_modelo or MODELO_POR_DEFECTO

    def disponible(self) -> tuple[bool, str]:
        if not os.environ.get("OPENAI_API_KEY"):
            return False, "Falta OPENAI_API_KEY en el .env."
        return True, f"API de OpenAI, modelo {self.modelo}."

    def analizar(
        self, archivo: Path, mime: str, contexto: ContextoAnalisis
    ) -> DocumentoExtraido:
        listo, motivo = self.disponible()
        if not listo:
            raise ErrorAnalisis(motivo)

        entrada = preparar(archivo, mime)
        contenido: list[dict] = []
        peticion = prompt_usuario(contexto, entrada.referencia)
        if entrada.texto:
            peticion = f"{peticion}\n\n---\n{entrada.texto}\n---"
        contenido.append({"type": "text", "text": peticion})
        for parte in entrada.partes:
            datos = base64.standard_b64encode(parte.datos).decode("ascii")
            contenido.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{parte.mime};base64,{datos}"},
                }
            )

        cuerpo = {
            "model": self.modelo,
            "temperature": 0,
            "response_format": {
                # Salida estructurada con el mismo esquema que los demas.
                "type": "json_schema",
                "json_schema": {
                    "name": "documento_extraido",
                    "strict": False,
                    "schema": esquema_json(),
                },
            },
            "messages": [
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": contenido},
            ],
        }

        datos = pedir_json(
            URL,
            cuerpo,
            cabeceras={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            nombre="OpenAI",
        )
        return DocumentoExtraido.model_validate(json_del_texto(_texto_de(datos)))


def _texto_de(respuesta: dict) -> str:
    opciones = respuesta.get("choices") or []
    if not opciones:
        raise ErrorAnalisis("OpenAI no devolvio ninguna respuesta.")
    mensaje = opciones[0].get("message") or {}
    if mensaje.get("refusal"):
        raise ErrorAnalisis(f"El modelo declino analizarlo: {mensaje['refusal']}")
    texto = mensaje.get("content") or ""
    if not texto.strip():
        raise ErrorAnalisis(
            "OpenAI devolvio una respuesta vacia "
            f"(terminó por: {opciones[0].get('finish_reason')})."
        )
    return texto


__all__ = ["AnalizadorOpenAI", "MODELO_POR_DEFECTO"]
