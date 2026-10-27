"""Proveedor por defecto: el binario `claude` con la suscripcion de Claude.

No necesita API key de pago por uso. Se autentica de una de dos formas:

- En un ordenador donde ya se usa Claude Code, con la sesion iniciada.
- En el servidor (Docker), con un token de larga duracion generado con
  `claude setup-token` y puesto en CLAUDE_CODE_OAUTH_TOKEN. Asi no hay que
  montar en el contenedor la carpeta ~/.claude, que guarda el historial y
  las conversaciones.

Claude lee la foto o el PDF directamente: no hace falta OCR.

Esta encerrado a proposito: `--restricted --tools Read` le deja solo leer
ficheros (ni comandos ni internet), `--permission-mode dontAsk` deniega todo
lo que no este permitido de antemano, y se ejecuta en una carpeta temporal
que solo contiene una copia del documento. Un documento con instrucciones escondidas no puede hacer nada
mas que estropear su propia propuesta, que una persona revisa siempre.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from ..config import config
from .base import (
    PROMPT_CENTRO,
    PROMPT_SISTEMA,
    ContextoAnalisis,
    ErrorAnalisis,
    esquema_json,
    json_del_texto,
    prompt_usuario,
)
from .esquema import DocumentoExtraido

#: Un documento de varias paginas puede tardar; mas de esto es un cuelgue.
TIEMPO_LIMITE_S = 300

#: El proceso que se esta ejecutando ahora, para poder cancelarlo desde la
#: web sin esperar a que Claude termine.
_proceso: subprocess.Popen | None = None
_cerrojo = threading.Lock()


def cancelar_en_curso() -> bool:
    """Corta el analisis que este corriendo. True si habia alguno."""
    with _cerrojo:
        proceso = _proceso
    if proceso is None or proceso.poll() is not None:
        return False
    proceso.terminate()
    try:
        proceso.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proceso.kill()
    return True


class AnalizadorClaudeCLI:
    nombre = "claude-cli"

    def __init__(self, binario: str | None = None) -> None:
        self.binario = binario or config.claude_cli_bin

    def disponible(self) -> tuple[bool, str]:
        ruta = shutil.which(self.binario)
        if ruta is None:
            return (
                False,
                f"No se encuentra '{self.binario}'. En Docker, construye la "
                "imagen con CON_CLAUDE_CLI=true (ver README).",
            )
        return True, f"Claude Code en {ruta}, con tu suscripcion."

    def orden(self) -> list[str]:
        """Linea de comandos, sin el prompt (que va por la entrada estandar)."""
        orden = [
            self.binario,
            "--print",
            "--output-format", "json",
            "--json-schema", json.dumps(esquema_json(), ensure_ascii=False),
            "--system-prompt", PROMPT_SISTEMA,
            "--restricted",
            "--tools", "Read",
            "--permission-mode", "dontAsk",
            # Ni servidores MCP ni ajustes personales del usuario.
            "--strict-mcp-config",
        ]
        if config.ia_modelo:
            orden += ["--model", config.ia_modelo]
        return orden

    def buscar_centro(self, nombre: str) -> "CentroBuscado":
        """Busca en internet los datos de un centro sanitario.

        Es la unica llamada de la aplicacion que sale a la web, y sale por
        Claude, no desde este servidor. Solo viaja el nombre del centro que
        ha escrito la persona: ningun dato del paciente ni de sus citas.
        Lo que vuelve es una PROPUESTA; no se guarda nada sin confirmar.
        """
        from .esquema import CentroBuscado, esquema_centro

        listo, motivo = self.disponible()
        if not listo:
            raise ErrorAnalisis(motivo)

        orden = [
            self.binario,
            "--print",
            "--output-format", "json",
            "--json-schema", json.dumps(esquema_centro(), ensure_ascii=False),
            "--system-prompt", PROMPT_CENTRO,
            "--restricted",
            # Solo buscar y leer paginas. Nada de Read, Write ni Bash: aqui
            # no hay ningun fichero que tocar. Hay que nombrarlas dos veces:
            # --tools dice cuales existen y --allowed-tools cuales puede usar
            # sin preguntar. Sin lo segundo, "dontAsk" las bloquea y Claude
            # contesta que no puede buscar.
            "--tools", "WebSearch,WebFetch",
            "--allowed-tools", "WebSearch", "WebFetch",
            "--permission-mode", "dontAsk",
            "--strict-mcp-config",
        ]
        if config.ia_modelo:
            orden += ["--model", config.ia_modelo]

        peticion = (
            "Busca los datos de contacto de este centro sanitario de Espana "
            f"y devuelvelos: \"{nombre.strip()}\""
        )
        with tempfile.TemporaryDirectory(prefix="centro-") as carpeta:
            proceso = self._ejecutar(peticion, Path(carpeta), orden)

        return CentroBuscado.model_validate(
            _datos_de_la_respuesta(proceso.stdout, proceso.stderr, proceso.returncode)
        )

    def analizar(
        self, archivo: Path, mime: str, contexto: ContextoAnalisis
    ) -> DocumentoExtraido:
        listo, motivo = self.disponible()
        if not listo:
            raise ErrorAnalisis(motivo)

        # Cada analisis trabaja en una carpeta temporal propia con una copia
        # del documento: Claude solo puede leer dentro de ella, asi que no
        # ve ningun otro documento pendiente.
        with tempfile.TemporaryDirectory(prefix="analisis-") as carpeta:
            copia = Path(carpeta) / f"documento{archivo.suffix}"
            shutil.copyfile(archivo, copia)
            peticion = prompt_usuario(
                contexto, f"que esta en el fichero ./{copia.name} (leelo con Read)"
            )
            proceso = self._ejecutar(peticion, Path(carpeta))

        return DocumentoExtraido.model_validate(
            _datos_de_la_respuesta(proceso.stdout, proceso.stderr, proceso.returncode)
        )

    def _ejecutar(
        self, peticion: str, carpeta: Path, orden: list[str] | None = None
    ) -> subprocess.CompletedProcess:
        global _proceso
        try:
            # Popen en vez de run() para poder cancelarlo desde fuera.
            with subprocess.Popen(
                orden or self.orden(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=carpeta,
                env=_entorno(),
            ) as proceso:
                with _cerrojo:
                    _proceso = proceso
                try:
                    salida, error = proceso.communicate(
                        peticion, timeout=TIEMPO_LIMITE_S
                    )
                finally:
                    with _cerrojo:
                        _proceso = None
            return subprocess.CompletedProcess(
                proceso.args, proceso.returncode, salida, error
            )
        except subprocess.TimeoutExpired as error:
            raise ErrorAnalisis(
                f"Claude no respondio en {TIEMPO_LIMITE_S // 60} minutos."
            ) from error
        except OSError as error:
            raise ErrorAnalisis(f"No se pudo ejecutar '{self.binario}': {error}") from error


def _entorno() -> dict[str, str]:
    import os

    entorno = dict(os.environ)
    # En el contenedor el sistema de ficheros es de solo lectura: que no
    # intente actualizarse solo.
    entorno.setdefault("DISABLE_AUTOUPDATER", "1")
    return entorno


def _datos_de_la_respuesta(stdout: str, stderr: str, codigo: int) -> dict:
    """Saca los datos del sobre JSON que imprime `claude --output-format json`.

    Con --json-schema la respuesta validada llega en `structured_output`.
    Si en alguna version cambia, se busca el JSON en `result`.
    """
    try:
        sobre = json.loads(stdout)
    except json.JSONDecodeError:
        if codigo != 0:
            raise ErrorAnalisis(
                f"Claude fallo (codigo {codigo}): {(stderr or stdout).strip()[:500]}"
            )
        return json_del_texto(stdout)

    if not isinstance(sobre, dict):
        raise ErrorAnalisis("Respuesta inesperada de Claude.")

    if sobre.get("is_error") or codigo != 0:
        detalle = sobre.get("result") or sobre.get("subtype") or stderr
        raise ErrorAnalisis(f"Claude devolvio un error: {str(detalle).strip()[:500]}")

    estructurado = sobre.get("structured_output")
    if isinstance(estructurado, dict):
        return estructurado

    resultado = sobre.get("result")
    if isinstance(resultado, str) and resultado.strip():
        return json_del_texto(resultado)

    raise ErrorAnalisis("Claude no devolvio ningun resultado.")
