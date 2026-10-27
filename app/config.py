"""Configuracion de la aplicacion, leida del entorno o del fichero .env."""

from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEDICOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Carpeta con la base de datos y los documentos. Todo lo que hay que
    #: copiar para tener una copia de seguridad completa esta aqui dentro.
    data_dir: Path = Path("./data")

    zona_horaria: str = "Europe/Madrid"

    # Umbrales de aviso
    dias_aviso_requisito: int = 7
    dias_alerta_espera: int = 30
    #: Con cuanta antelacion se reclama una prueba que hace falta para otra
    #: cita y sigue sin fecha. No se espera a `dias_alerta_espera`: lo que
    #: manda es el tiempo que queda para la cita en la que hace falta.
    dias_aviso_previa: int = 15
    dias_horizonte: int = 14
    #: Con cuanta antelacion avisa de que falta pedir la ambulancia.
    dias_aviso_transporte: int = 7
    #: Con cuanta antelacion recuerda confirmar la ambulancia ya pedida.
    dias_confirmar_transporte: int = 1

    # Acceso y seguridad
    #: Nombres e IPs por los que se llega al servidor, separados por comas.
    #: Cualquier otro se rechaza (proteccion contra DNS rebinding).
    #: localhost y 127.0.0.1 estan siempre incluidos.
    hosts_permitidos: str = ""
    #: Cuantos dias dura una sesion sin volver a pedir la contrasena. Cada
    #: uso la prolonga, asi que en el movil no hace falta entrar cada dia.
    dias_sesion: int = 30

    # IA (v2: ingesta de documentos escaneados)
    ia_proveedor: str = "claude-cli"
    ia_modelo: str | None = None
    claude_cli_bin: str = "claude"
    ollama_url: str = "http://localhost:11434"

    @property
    def ruta_db(self) -> Path:
        return self.data_dir / "medicos.db"

    @property
    def dir_documentos(self) -> Path:
        return self.data_dir / "documentos"

    @property
    def lista_hosts(self) -> frozenset[str]:
        from .seguridad import HOSTS_LOCALES, nombre_host

        extra = {
            nombre_host(h) for h in self.hosts_permitidos.split(",") if h.strip()
        }
        return HOSTS_LOCALES | extra

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.zona_horaria)

    def preparar_directorios(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.dir_documentos.mkdir(parents=True, exist_ok=True)


@lru_cache
def obtener_config() -> Config:
    return Config()


config = obtener_config()


def ahora() -> datetime:
    """El instante actual, en UTC y con zona horaria.

    Todo lo que se guarda en la base de datos usa esta funcion. Dos razones:
    SQLModel exige desde la version 0.0.43 que los datetime lleven zona, y
    SQLite se come el desfase al guardarlos, asi que al leerlos se dan por
    UTC. Guardar hora local seria leerla mal mas tarde.

    Para ensenarsela a una persona hay que pasarla por `a_local()`.
    """
    return datetime.now(timezone.utc)


def ahora_local() -> datetime:
    """El instante actual en hora de Espana, para comparar con una cita.

    Las citas se guardan con la hora de pared (las 10:30 son las 10:30), asi
    que para saber si ya han pasado hay que mirar el reloj de aqui, no UTC.
    """
    return datetime.now(config.tz)


def a_local(momento: datetime | None) -> datetime | None:
    """La misma hora, vista desde Espana. Solo para mostrarla."""
    if momento is None:
        return None
    if momento.tzinfo is None:
        # Una fila antigua que se quedo sin migrar: se da por UTC, que es
        # como la leeria SQLModel de todas formas.
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(config.tz)


def hoy() -> date:
    """El dia de hoy en la zona horaria configurada.

    Se centraliza aqui para no esparcir `date.today()` por el codigo: dentro
    del contenedor el reloj suele estar en UTC, y a partir de las 23:00 en
    Espana eso significa que "hoy" ya seria manana.
    """
    return datetime.now(config.tz).date()
