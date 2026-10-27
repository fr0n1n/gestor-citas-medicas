"""Reconocer que dos nombres son el mismo hospital.

Los documentos escriben el mismo sitio de muchas maneras: "H.U. Virgen de
del Faro (Vistamar)", "A.H. Virgen del Faro - Hospital de
Especialidades", "Hospital Virgen del Faro (A.H. Virgen de la
Faro)". Comparando los nombres enteros no se parecen, y cada documento
acababa dando de alta un centro nuevo.

Pero tampoco vale con ser tolerante sin mas: el hospital de Villamar y
el centro de salud de Villamar comparten la unica palabra que los
distingue, y son sitios distintos. Por eso se mira tambien de que clase de
centro se trata.

Modulo puro: ni base de datos ni framework, solo texto.
"""

from __future__ import annotations

import re
import unicodedata

#: Palabras que dicen que clase de sitio es, pero no cual: si se comparan
#: los nombres con ellas dentro, todos los hospitales se parecen entre si.
GENERICAS: frozenset[str] = frozenset(
    """
    hospital hospitales universitario universitaria clinico clinica
    regional comarcal provincial alta resolucion centro salud consultorio
    hospitalaria hospitalario
    ambulatorio complejo area sanitaria distrito especialidades consultas
    externas servicio andaluz sas de del la las los el y e en
    """.split()
)


def normalizar(nombre: str) -> str:
    """Minusculas, sin tildes y con las abreviaturas desplegadas."""
    texto = unicodedata.normalize("NFKD", nombre.lower())
    texto = texto.encode("ascii", "ignore").decode("ascii")
    # "C.S." y "CAP" son lo mismo que "centro de salud"; "H.U." que
    # "hospital universitario"; "HAR" que "hospital de alta resolucion".
    texto = re.sub(r"\bc\.?\s?s\.?\b|\bcap\b", "centro de salud", texto)
    texto = re.sub(r"\ba\.?\s?h\.?\b", "area hospitalaria", texto)
    texto = re.sub(r"\bh\.?\s?u\.?\b|\bhu\b", "hospital universitario", texto)
    # CHARE y HARE son como llama a lo mismo el Servicio Andaluz de
    # Salud: Centro Hospitalario de Alta Resolucion de Especialidades.
    texto = re.sub(r"\bc?hare?\b", "hospital de alta resolucion", texto)
    texto = re.sub(r"\bh\.\s?", "hospital ", texto)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", texto).split())


def clase(nombre: str) -> str:
    """"hospital", "centro de salud" o "" si el nombre no lo dice.

    Sirve para no fundir nunca un ambulatorio con un hospital aunque esten
    en el mismo pueblo y compartan nombre.
    """
    texto = normalizar(nombre)
    if "centro de salud" in texto or "consultorio" in texto or "ambulatorio" in texto:
        return "centro de salud"
    if "hospital" in texto:
        return "hospital"
    return ""


def _trozo_del_centro(nombre: str) -> str:
    """El trozo del nombre que nombra el centro, sin el servicio.

    El servicio aparece a un lado u otro del guion segun el documento:
    "H.U. Virgen del Faro - Medicina Fisica", pero tambien
    "Laboratorios Clinicos - H.U. Virgen del Faro". Se queda el
    trozo que dice ser un centro; si ninguno lo dice, el primero.
    """
    trozos = [t.strip() for t in re.split(r"\s[-–—]\s", nombre) if t.strip()]
    if not trozos:
        return nombre
    con_clase = [t for t in trozos if clase(t)]
    return con_clase[0] if con_clase else trozos[0]


def distintivas(nombre: str) -> frozenset[str]:
    """Las palabras que de verdad identifican al centro.

    Se quita lo que va entre parentesis ("(Vistamar)") y el servicio que
    cuelga del guion: eso dice a que seccion vas, no a que hospital.
    """
    base = re.sub(r"\(.*?\)", " ", nombre)
    palabras = normalizar(_trozo_del_centro(base)).split()
    return frozenset(p for p in palabras if len(p) > 1 and p not in GENERICAS)


#: Nombres coloquiales que no se parecen en nada al oficial: en cada
#: provincia los suyos ("el Clinico", "el Materno"...). Por telefono los
#: usan siempre y, sin esto, cada llamada daria de alta un hospital nuevo.
#:
#: Cada entrada es: (palabra que lo delata, palabras que pueden acompanarla,
#: palabras del hospital de verdad). La segunda lista es la que hace que
#: esto sea seguro: con ("clinico", {"vistamar"}, {"virgen", "faro"}),
#: "Hospital Clinico San Carlos" no se toca, porque "san carlos" no esta
#: entre las permitidas.
#:
#: Aqui va vacia a proposito: los de tu zona se ponen en
#: `app/alias_locales.py`, que no va al repositorio, con esta forma:
#:
#:     ALIAS = (("clinico", frozenset({"vistamar"}),
#:               frozenset({"virgen", "faro"})),)
ALIAS: tuple[tuple[str, frozenset[str], frozenset[str]], ...] = ()

try:  # pragma: no cover - depende de cada instalacion
    from .alias_locales import ALIAS as _ALIAS_LOCALES

    ALIAS = ALIAS + tuple(_ALIAS_LOCALES)
except ImportError:
    pass


def _resolver_alias(nombre: str, palabras: frozenset[str]) -> frozenset[str]:
    """Cambia un nombre coloquial por las palabras del hospital de verdad."""
    texto = normalizar(nombre)
    for pista, permitidas, reales in ALIAS:
        if pista in texto and palabras <= permitidas:
            return reales
    return palabras


def es_el_mismo(uno: str, otro: str) -> bool:
    """Si los dos nombres se refieren al mismo centro."""
    if not uno or not otro:
        return False

    clase_uno, clase_otro = clase(uno), clase(otro)
    if clase_uno and clase_otro and clase_uno != clase_otro:
        return False

    palabras_uno = _resolver_alias(uno, distintivas(uno))
    palabras_otro = _resolver_alias(otro, distintivas(otro))
    if not palabras_uno or not palabras_otro:
        return False

    # Con una sola palabra distintiva no hay margen para equivocarse: dos
    # centros del mismo pueblo se distinguen solo por ella.
    if len(palabras_uno) < 2 or len(palabras_otro) < 2:
        return palabras_uno == palabras_otro

    return palabras_uno <= palabras_otro or palabras_otro <= palabras_uno


#: Como se abrevian los nombres largos para que quepan en una pastilla.
#: Es como los escribe la gente de todas formas.
ABREVIATURAS: tuple[tuple[str, str], ...] = (
    ("hospital de alta resolucion de ", "HAR "),
    ("hospital de alta resolucion ", "HAR "),
    ("hospital universitario ", "H.U. "),
    ("hospital regional universitario de ", "H.R.U. "),
    ("centro de salud de ", "C.S. "),
    ("centro de salud ", "C.S. "),
    ("consultorio ", "C. "),
    ("area hospitalaria ", "A.H. "),
)


def nombre_corto(nombre: str, maximo: int = 26) -> str:
    """El nombre del centro abreviado para que quepa donde hay poco sitio.

    Abrevia los prefijos largos, quita lo que va entre parentesis y, si aun
    asi no cabe, se queda con la parte anterior al guion: en
    "Arroyo Blanco-Villamar" lo que distingue es lo primero.
    """
    if not nombre:
        return ""

    texto = re.sub(r"\s*\(.*?\)", "", nombre).strip()

    # Aqui NO vale `normalizar`: esa despliega las abreviaturas, y entonces
    # un nombre que ya viene abreviado ("HAR Villamar") pareceria empezar
    # por el prefijo largo y se le cortarian palabras de mas.
    llano = " ".join(
        unicodedata.normalize("NFKD", texto.lower())
        .encode("ascii", "ignore")
        .decode("ascii")
        .split()
    )
    for largo, corto in ABREVIATURAS:
        if llano.startswith(largo):
            palabras = largo.split()
            texto = corto + " ".join(texto.split()[len(palabras):])
            texto = " ".join(texto.split())
            break

    if len(texto) > maximo and "-" in texto:
        texto = texto.split("-", 1)[0].strip()
    return texto
