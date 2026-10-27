"""Generacion de ficheros .ics (RFC 5545) sin dependencias externas.

Sirve para que las citas aparezcan solas en el movil de quien acompane al
paciente: se exporta el calendario y se importa o se suscribe desde Google
Calendar, Apple Calendario, Thunderbird, etc.

Las horas se escriben en "hora flotante" (sin zona horaria ni sufijo Z), que
es justo lo que se quiere aqui: una cita a las 9:30 en el hospital es a las
9:30 del reloj de la pared, sin conversiones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

#: Identificador del producto que genera el fichero.
PRODID = "-//Medicos//Gestor de citas medicas//ES"

#: Longitud maxima de linea que exige el RFC, en octetos.
_MAX_OCTETOS = 75


@dataclass(frozen=True)
class EventoICS:
    """Lo minimo que necesita una cita para viajar a un calendario.

    Se usa un dataclass propio en vez del modelo de base de datos para que
    este modulo siga siendo puro y facil de probar.
    """

    uid: str
    titulo: str
    fecha: date
    hora: time | None = None
    duracion_min: int = 30
    lugar: str = ""
    descripcion: str = ""
    #: Minutos de antelacion para el aviso. None desactiva la alarma.
    aviso_min_antes: int | None = None


def _escapar(texto: str) -> str:
    """Escapa los caracteres con significado especial en un valor de texto."""
    return (
        texto.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _plegar(linea: str) -> list[str]:
    """Parte una linea larga segun las reglas de plegado del RFC 5545.

    El limite son 75 *octetos*, no caracteres: con acentos y enes una linea
    de 75 caracteres puede pasarse de largo, asi que se mide en UTF-8 y se
    corta sin partir un caracter por la mitad.
    """
    crudo = linea.encode("utf-8")
    if len(crudo) <= _MAX_OCTETOS:
        return [linea]

    partes: list[str] = []
    restante = crudo
    limite = _MAX_OCTETOS
    while len(restante) > limite:
        corte = limite
        # No partir un caracter multibyte: retroceder hasta el inicio de uno.
        while corte > 0 and (restante[corte] & 0xC0) == 0x80:
            corte -= 1
        partes.append(restante[:corte].decode("utf-8"))
        restante = restante[corte:]
        # Las lineas de continuacion van precedidas de un espacio, que
        # tambien cuenta para el limite.
        limite = _MAX_OCTETOS - 1
    partes.append(restante.decode("utf-8"))

    return [partes[0]] + [" " + p for p in partes[1:]]


def _fmt_fecha(d: date) -> str:
    return d.strftime("%Y%m%d")


def _fmt_datetime(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _vevento(evento: EventoICS, generado_en: datetime) -> list[str]:
    lineas = [
        "BEGIN:VEVENT",
        f"UID:{evento.uid}",
        f"DTSTAMP:{_fmt_datetime(generado_en)}Z",
    ]

    if evento.hora is None:
        # Evento de dia completo: DTEND es exclusivo, de ahi el +1 dia.
        lineas.append(f"DTSTART;VALUE=DATE:{_fmt_fecha(evento.fecha)}")
        lineas.append(
            f"DTEND;VALUE=DATE:{_fmt_fecha(evento.fecha + timedelta(days=1))}"
        )
    else:
        inicio = datetime.combine(evento.fecha, evento.hora)
        fin = inicio + timedelta(minutes=evento.duracion_min)
        lineas.append(f"DTSTART:{_fmt_datetime(inicio)}")
        lineas.append(f"DTEND:{_fmt_datetime(fin)}")

    lineas.append(f"SUMMARY:{_escapar(evento.titulo)}")
    if evento.lugar:
        lineas.append(f"LOCATION:{_escapar(evento.lugar)}")
    if evento.descripcion:
        lineas.append(f"DESCRIPTION:{_escapar(evento.descripcion)}")

    if evento.aviso_min_antes is not None:
        lineas += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escapar(evento.titulo)}",
            f"TRIGGER:-PT{evento.aviso_min_antes}M",
            "END:VALARM",
        ]

    lineas.append("END:VEVENT")
    return lineas


def generar_ics(
    eventos: Iterable[EventoICS],
    nombre_calendario: str = "Citas medicas",
    generado_en: datetime | None = None,
) -> str:
    """Devuelve el contenido completo de un fichero .ics.

    Las lineas van separadas por CRLF, como exige el RFC: hay clientes de
    calendario que rechazan el fichero si se usa solo LF.
    """
    generado_en = generado_en or datetime.now(timezone.utc)

    lineas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escapar(nombre_calendario)}",
    ]
    for evento in eventos:
        lineas += _vevento(evento, generado_en)
    lineas.append("END:VCALENDAR")

    plegadas: list[str] = []
    for linea in lineas:
        plegadas += _plegar(linea)

    return "\r\n".join(plegadas) + "\r\n"
