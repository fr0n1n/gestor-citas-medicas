"""Llamadas HTTP a las APIs de los modelos, con la biblioteca estandar.

Sin `requests` ni los SDK de cada proveedor: son peticiones JSON de una
linea y asi la imagen no arrastra una dependencia por cada modelo que se
quiera probar. Lo unico que se pide a cambio es traducir los errores a
algo que la persona pueda leer en la pantalla de revision.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import ErrorAnalisis

#: Un documento largo con un modelo lento puede tardar. Mas que esto es un
#: cuelgue, y la cola se queda bloqueada.
TIEMPO_LIMITE_S = 300


def pedir_json(
    url: str,
    cuerpo: dict,
    cabeceras: dict[str, str] | None = None,
    tiempo_limite: int = TIEMPO_LIMITE_S,
    nombre: str = "el proveedor",
) -> dict:
    """POST con JSON y respuesta JSON. Los fallos salen como ErrorAnalisis."""
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    peticion = urllib.request.Request(
        url,
        data=datos,
        headers={"Content-Type": "application/json", **(cabeceras or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=tiempo_limite) as respuesta:
            return json.loads(respuesta.read())
    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", "replace")[:400]
        raise ErrorAnalisis(
            f"{nombre} respondio {error.code}: {_mensaje(detalle)}"
        ) from error
    except (urllib.error.URLError, OSError) as error:
        raise ErrorAnalisis(f"No se ha podido hablar con {nombre}: {error}") from error
    except json.JSONDecodeError as error:
        raise ErrorAnalisis(f"{nombre} no devolvio JSON.") from error


def _mensaje(cuerpo: str) -> str:
    """Saca el mensaje de error del JSON, si viene en uno.

    Las tres APIs lo meten en sitios parecidos ({"error": {"message": ...}}),
    y ese texto es mucho mas util que el volcado entero.
    """
    try:
        datos = json.loads(cuerpo)
    except json.JSONDecodeError:
        return cuerpo
    error = datos.get("error") if isinstance(datos, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    if isinstance(error, str):
        return error
    return cuerpo
