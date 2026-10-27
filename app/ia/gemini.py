"""Proveedor por API de Google Gemini.

Lee fotos y PDF directamente, y tiene un plan gratuito con limites, asi
que es la alternativa mas barata a Claude para probar la aplicacion.

Se habla por HTTP con la biblioteca estandar: no hace falta instalar nada.
La clave va en `GEMINI_API_KEY` (o `GOOGLE_API_KEY`) del `.env`.

Aviso que conviene tener presente: aqui viajan documentos medicos a un
servicio de terceros. Lo mismo vale para OpenAI y para Anthropic; si eso
no es aceptable, el proveedor `ollama` lo hace todo en casa.
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

MODELO_POR_DEFECTO = "gemini-2.5-flash"
URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _clave() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


class AnalizadorGemini:
    nombre = "gemini"

    def __init__(self, modelo: str | None = None) -> None:
        self.modelo = modelo or config.ia_modelo or MODELO_POR_DEFECTO

    def disponible(self) -> tuple[bool, str]:
        if not _clave():
            return False, "Falta GEMINI_API_KEY en el .env."
        return True, f"API de Google Gemini, modelo {self.modelo}."

    def analizar(
        self, archivo: Path, mime: str, contexto: ContextoAnalisis
    ) -> DocumentoExtraido:
        listo, motivo = self.disponible()
        if not listo:
            raise ErrorAnalisis(motivo)

        # Gemini lee el PDF por su cuenta: no hace falta dibujar paginas.
        entrada = preparar(archivo, mime, admite_pdf=True)
        partes: list[dict] = []
        for parte in entrada.partes:
            partes.append(
                {
                    "inline_data": {
                        "mime_type": parte.mime,
                        "data": base64.standard_b64encode(parte.datos).decode("ascii"),
                    }
                }
            )
        peticion = prompt_usuario(contexto, entrada.referencia)
        if entrada.texto:
            peticion = f"{peticion}\n\n---\n{entrada.texto}\n---"
        partes.append({"text": peticion})

        cuerpo = {
            "system_instruction": {"parts": [{"text": PROMPT_SISTEMA}]},
            "contents": [{"role": "user", "parts": partes}],
            "generationConfig": {
                # Salida estructurada: se le da el mismo esquema que a los
                # demas, asi la respuesta encaja sin adivinar nada.
                "responseMimeType": "application/json",
                "responseSchema": _esquema_para_gemini(esquema_json()),
                "temperature": 0,
            },
        }

        datos = pedir_json(
            f"{URL_BASE}/{self.modelo}:generateContent",
            cuerpo,
            cabeceras={"x-goog-api-key": _clave() or ""},
            nombre="Gemini",
        )
        return DocumentoExtraido.model_validate(json_del_texto(_texto_de(datos)))


def _texto_de(respuesta: dict) -> str:
    """El texto de la respuesta, o un error explicando por que no hay."""
    candidatos = respuesta.get("candidates") or []
    if not candidatos:
        motivo = (respuesta.get("promptFeedback") or {}).get("blockReason")
        raise ErrorAnalisis(
            f"Gemini no devolvio nada (motivo: {motivo})" if motivo
            else "Gemini no devolvio ninguna respuesta."
        )
    partes = (candidatos[0].get("content") or {}).get("parts") or []
    texto = "".join(p.get("text", "") for p in partes)
    if not texto.strip():
        raise ErrorAnalisis(
            "Gemini devolvio una respuesta vacia "
            f"(terminó por: {candidatos[0].get('finishReason')})."
        )
    return texto


#: Palabras del esquema de Pydantic que la API de Gemini no admite. Se
#: quitan en vez de escribir un esquema aparte, que acabaria desfasado.
_NO_ADMITIDAS = (
    "$schema", "$defs", "additionalProperties", "definitions",
    "allOf", "anyOf", "oneOf", "default", "examples", "title",
)


def _esquema_para_gemini(esquema: dict) -> dict:
    """Adapta el esquema JSON de Pydantic al subconjunto que acepta Gemini.

    Pydantic genera referencias ($ref/$defs) y palabras que Gemini rechaza
    con un 400. Aqui se resuelven las referencias y se podan las demas.
    """
    definiciones = esquema.get("$defs", {})

    def limpiar(nodo):
        if isinstance(nodo, list):
            return [limpiar(x) for x in nodo]
        if not isinstance(nodo, dict):
            return nodo

        if "$ref" in nodo:
            nombre = nodo["$ref"].rsplit("/", 1)[-1]
            return limpiar(definiciones.get(nombre, {}))

        # Un campo opcional se escribe como anyOf [tipo, null]: se queda
        # con el tipo de verdad, que es lo unico que Gemini entiende.
        for clave in ("anyOf", "oneOf", "allOf"):
            if clave in nodo:
                opciones = [
                    o for o in nodo[clave]
                    if not (isinstance(o, dict) and o.get("type") == "null")
                ]
                if opciones:
                    elegido = limpiar(opciones[0])
                    if isinstance(elegido, dict) and nodo.get("description"):
                        elegido.setdefault("description", nodo["description"])
                    return elegido

        return {
            clave: limpiar(valor)
            for clave, valor in nodo.items()
            if clave not in _NO_ADMITIDAS
        }

    return limpiar(esquema)
