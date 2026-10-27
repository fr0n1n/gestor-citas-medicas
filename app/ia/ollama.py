"""Proveedor local con Ollama: ningun dato sale de tu red.

Es la opcion para quien no quiera mandar documentos medicos a ningun
servicio de terceros. A cambio necesita una maquina que mueva el modelo y
acierta menos que Claude o Gemini: la pantalla de revision deja de ser una
formalidad y hay que leerla de verdad.

Necesita un modelo con vision (por ejemplo `llama3.2-vision` o
`qwen2.5vl`). Los PDF se mandan como paginas dibujadas (ver `entrada.py`).

Se habla por HTTP con la biblioteca estandar: no hace falta instalar nada.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
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

MODELO_POR_DEFECTO = "llama3.2-vision"
#: Un modelo local va mucho mas lento que una API: aqui se espera mas.
TIEMPO_LIMITE_S = 900


class AnalizadorOllama:
    nombre = "ollama"

    def __init__(self, modelo: str | None = None, url: str | None = None) -> None:
        self.modelo = modelo or config.ia_modelo or MODELO_POR_DEFECTO
        self.url = (url or config.ollama_url).rstrip("/")

    def disponible(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=5) as r:
                datos = json.loads(r.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
            return False, f"No se puede contactar con Ollama en {self.url}: {error}"
        modelos = [m.get("name", "") for m in datos.get("models", [])]
        if not any(m.startswith(self.modelo) for m in modelos):
            return (
                False,
                f"Ollama no tiene '{self.modelo}'. Descargalo: "
                f"ollama pull {self.modelo}",
            )
        return True, f"Ollama en {self.url}, modelo {self.modelo}."

    def analizar(
        self, archivo: Path, mime: str, contexto: ContextoAnalisis
    ) -> DocumentoExtraido:
        listo, motivo = self.disponible()
        if not listo:
            raise ErrorAnalisis(motivo)

        entrada = preparar(archivo, mime)
        peticion = prompt_usuario(contexto, entrada.referencia)
        if entrada.texto:
            peticion = f"{peticion}\n\n---\n{entrada.texto}\n---"

        mensaje: dict = {"role": "user", "content": peticion}
        if entrada.partes:
            mensaje["images"] = [
                base64.b64encode(p.datos).decode("ascii") for p in entrada.partes
            ]

        datos = pedir_json(
            f"{self.url}/api/chat",
            {
                "model": self.modelo,
                "stream": False,
                # Ollama acepta el esquema JSON tal cual en "format".
                "format": esquema_json(),
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": PROMPT_SISTEMA},
                    mensaje,
                ],
            },
            tiempo_limite=TIEMPO_LIMITE_S,
            nombre="Ollama",
        )

        contenido = (datos.get("message") or {}).get("content", "")
        if not contenido.strip():
            raise ErrorAnalisis("Ollama devolvio una respuesta vacia.")
        return DocumentoExtraido.model_validate(json_del_texto(contenido))


__all__ = ["AnalizadorOllama", "MODELO_POR_DEFECTO"]
