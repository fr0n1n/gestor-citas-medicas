"""Cola de analisis con IA, en segundo plano dentro del servidor.

Pulsar "Analizar con Claude" no espera a Claude: marca el documento como
`en_cola` en la base de datos y vuelve al momento. Un hilo del servidor va
cogiendo documentos de la cola y guarda el resultado tambien en la base.

Por eso da igual cerrar la web, bloquear el movil o perder la conexion: el
trabajo y su resultado viven en el servidor. Y si el propio servidor se
reinicia a mitad de un analisis, al arrancar ese documento vuelve a la cola.

Los documentos se analizan de uno en uno: cada llamada a Claude tarda unos
segundos, y en paralelo solo se consumirian antes los limites de la
suscripcion sin ganar nada.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from sqlalchemy import update
from sqlmodel import Session, select

from . import almacen
from .config import ahora
from .db import motor
from .ia.base import ErrorAnalisis, obtener_analizador
from .modelos import Documento
from .propuestas import contexto_para, guardar_propuesta

log = logging.getLogger("medicos.cola")

#: Cada cuanto se mira la cola si nadie avisa (por ejemplo, tras un reinicio).
_ESPERA_S = 30

_despertar = threading.Event()
_parar = threading.Event()
_hilo: threading.Thread | None = None

#: Documentos cuyo analisis se ha cancelado desde la web. Si el resultado
#: llega despues, se tira: la persona ya dijo que no lo queria.
_cancelados: set[int] = set()


def encolar(sesion: Session, documento: Documento) -> None:
    documento.estado_ia = "en_cola"
    documento.error_ia = None
    documento.ia_actualizado_en = ahora()
    sesion.add(documento)
    sesion.commit()
    _despertar.set()


def cancelar(sesion: Session, documento: Documento) -> bool:
    """Saca un documento de la cola y corta su analisis si estaba en marcha."""
    if documento.estado_ia not in ("en_cola", "analizando"):
        return False

    _cancelados.add(documento.id)
    if documento.estado_ia == "analizando":
        from .ia.claude_cli import cancelar_en_curso

        cancelar_en_curso()

    documento.estado_ia = None
    documento.error_ia = None
    documento.ia_actualizado_en = ahora()
    sesion.add(documento)
    sesion.commit()
    return True


def _recuperar_interrumpidos() -> None:
    """Lo que estaba a medias cuando se paro el servidor vuelve a la cola."""
    with Session(motor) as sesion:
        resultado = sesion.exec(
            update(Documento)
            .where(Documento.estado_ia == "analizando")
            .values(estado_ia="en_cola")
        )
        sesion.commit()
        if resultado.rowcount:
            log.warning("%d analisis interrumpidos vuelven a la cola", resultado.rowcount)


def _reclamar_siguiente(sesion: Session) -> Documento | None:
    """Coge el siguiente de la cola y lo marca como `analizando`.

    La marca es condicional (solo si sigue `en_cola`) para que nunca se
    analice dos veces el mismo documento.
    """
    candidato = sesion.exec(
        select(Documento)
        .where(Documento.estado_ia == "en_cola")
        .order_by(Documento.ia_actualizado_en)
    ).first()
    if candidato is None:
        return None
    marcado = sesion.exec(
        update(Documento)
        .where(Documento.id == candidato.id, Documento.estado_ia == "en_cola")
        .values(estado_ia="analizando", ia_actualizado_en=ahora())
    )
    sesion.commit()
    if not marcado.rowcount:
        return None
    sesion.refresh(candidato)
    return candidato


def analizar_uno(sesion: Session, documento: Documento) -> None:
    """Analiza un documento y deja el resultado guardado."""
    try:
        ruta = almacen.ruta_de(documento)
        if ruta is None:
            raise ErrorAnalisis("El fichero no esta en el disco.")
        propuesta = obtener_analizador().analizar(
            ruta, documento.mime or "", contexto_para(sesion, documento)
        )
    except (ErrorAnalisis, ValueError) as error:
        documento.estado_ia = "error"
        documento.error_ia = str(error)[:1000]
        log.warning("Analisis del documento %s fallido: %s", documento.id, error)
    except Exception as error:  # noqa: BLE001 - la cola no debe morir nunca
        documento.estado_ia = "error"
        documento.error_ia = f"Error inesperado: {error}"[:1000]
        log.exception("Error inesperado analizando el documento %s", documento.id)
    else:
        guardar_propuesta(documento, propuesta)
        documento.estado_ia = "propuesta"
        documento.error_ia = None
        log.info("Documento %s analizado", documento.id)

    if documento.id in _cancelados:
        # Lo cancelaron mientras Claude leia: el resultado se descarta y el
        # documento se queda como estaba.
        _cancelados.discard(documento.id)
        log.info("Analisis del documento %s descartado: cancelado", documento.id)
        sesion.rollback()
        return

    documento.ia_actualizado_en = ahora()
    sesion.add(documento)
    sesion.commit()


def _bucle() -> None:
    _recuperar_interrumpidos()
    while not _parar.is_set():
        try:
            with Session(motor) as sesion:
                while not _parar.is_set():
                    documento = _reclamar_siguiente(sesion)
                    if documento is None:
                        break
                    analizar_uno(sesion, documento)
        except Exception:  # noqa: BLE001
            log.exception("Fallo en la cola de analisis; se reintenta")
        _despertar.wait(_ESPERA_S)
        _despertar.clear()


def arrancar() -> None:
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return
    _parar.clear()
    _hilo = threading.Thread(target=_bucle, name="cola-analisis", daemon=True)
    _hilo.start()


def parar() -> None:
    _parar.set()
    _despertar.set()
