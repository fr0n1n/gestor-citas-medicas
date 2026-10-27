"""Agrupar citas y documentos por area medica.

Los papeles llaman a lo mismo de muchas formas: "Cirugia Ortopedica y
Traumatologia", "Traumatologia / Radiologia", "COT". Para poder ver junto
todo lo de un mismo especialista hay que reconocer esas variantes.

Modulo puro: ni base de datos ni framework, solo texto.
"""

from __future__ import annotations

import re
import unicodedata

#: Areas conocidas y las palabras que las delatan. El orden importa: gana
#: la primera que encaje, asi que van de mas concreta a mas general.
AREAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Traumatología", ("traumatolog", "cot", "ortoped", "columna", "rodilla")),
    ("Neurología", ("neurolog", "neurofisiolog")),
    ("Digestivo", ("digestiv", "endoscop", "colonoscop", "hepat")),
    ("Cardiología", ("cardiolog", "corazon", "electrocardio")),
    ("Radiología", ("radiolog", "radiodiagn", "resonancia", "rmn", "ecograf",
                    "radiografia", "escaner", "tac", "mamograf")),
    ("Análisis clínicos", ("analisis", "analitic", "laboratorio", "hematolog",
                           "bioquimic", "serolog", "extraccion de sangre")),
    ("Rehabilitación", ("rehabilit", "fisioterap")),
    ("Enfermería", ("enfermer",)),
    ("Médico de cabecera", ("familia", "cabecera", "primaria", "generalista",
                            "medicina general", "medico general")),
    ("Oftalmología", ("oftalmolog", "ocular", "vista")),
    ("Endocrinología", ("endocrin", "diabet")),
    ("Urología", ("urolog",)),
    ("Dermatología", ("dermatolog",)),
    ("Otorrinolaringología", ("otorrino", "audiolog")),
    ("Salud mental", ("psiquiatr", "psicolog", "salud mental")),
    ("Dependencia y trámites", ("dependencia", "trabajo social", "trabajadora social",
                                "incapacidad", "discapacidad", "prestacion",
                                "bienestar social", "servicios sociales",
                                "asuntos sociales")),
    ("Urgencias", ("urgencia",)),
)

#: Cuando no se sabe de que area es.
SIN_AREA = "Sin área"


def _limpiar(texto: str) -> str:
    """Minusculas y sin tildes, para comparar sin sorpresas."""
    sin_tildes = (
        unicodedata.normalize("NFKD", texto.lower())
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sin_tildes).split())


def canonica(texto: str | None) -> str:
    """El area a la que pertenece un texto de especialidad o tema.

    Si no se reconoce, se devuelve el texto tal cual (capitalizado): mejor
    un area propia con el nombre del documento que meterlo todo en un
    cajon de sastre.
    """
    if not texto or not texto.strip():
        return SIN_AREA

    limpio = _limpiar(texto)
    if not limpio:
        return SIN_AREA

    for area, palabras in AREAS:
        if any(palabra in limpio for palabra in palabras):
            return area

    # Desconocida: se respeta lo que diga el documento, sin la coletilla
    # del centro entre parentesis.
    return re.sub(r"\s*\(.*?\)\s*", " ", texto).strip().capitalize() or SIN_AREA


def slug(area: str) -> str:
    """Identificador para la URL: 'Análisis clínicos' -> 'analisis-clinicos'."""
    return re.sub(r"[^a-z0-9]+", "-", _limpiar(area)).strip("-") or "sin-area"


def tono(area: str) -> int:
    """Un color estable para cada area, en grados de la rueda de color.

    Se calcula del nombre, asi que un area siempre se ve del mismo color
    sin tener que mantener una lista de colores a mano.
    """
    if area == SIN_AREA:
        return 220
    valor = 0
    for caracter in _limpiar(area):
        valor = (valor * 31 + ord(caracter)) % 360
    # Se evita la franja rojiza, reservada para los avisos de la interfaz.
    return (valor % 320) + 20


#: Cuantos colores distintos hay preparados en la hoja de estilos.
#: Hay mas que areas frecuentes, para que no se repitan entre si.
COLORES = 16


#: Orden de las areas conocidas, para darles un color fijo y distinto.
_ORDEN = {nombre: i for i, (nombre, _) in enumerate(AREAS)}


def color(area: str) -> int:
    """El numero de color (0-11) que le toca a un area.

    Las areas conocidas llevan color fijo por orden de la lista, asi las
    mas frecuentes no se repiten entre si. Las desconocidas lo sacan de su
    nombre, que al menos es estable.

    Se usa como clase CSS (`area-color-7`) en vez de un estilo en linea,
    porque la politica de seguridad de la aplicacion no permite estilos
    incrustados en el HTML.
    """
    if area in _ORDEN:
        return _ORDEN[area] % COLORES
    if area == SIN_AREA:
        return 0
    return tono(area) * COLORES // 360


#: Areas en las que la cita es una gestion, no una consulta medica: a esas
#: no va el enfermo, va un familiar, asi que no hace falta ambulancia.
AREAS_ADMINISTRATIVAS: frozenset[str] = frozenset({"Dependencia y trámites"})


def es_administrativa(texto: str | None) -> bool:
    """Si una cita es una gestion administrativa y no una consulta."""
    return canonica(texto) in AREAS_ADMINISTRATIVAS
