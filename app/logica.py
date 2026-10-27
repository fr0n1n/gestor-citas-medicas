"""Logica de dominio pura.

Este modulo no importa FastAPI, ni SQLModel, ni toca la red o el disco: solo
recibe datos y devuelve datos. Todo lo que es facil equivocarse (calculo de
fechas limite, dias de espera, rejilla del calendario) vive aqui para que se
pueda probar de forma aislada y rapida.
"""

from __future__ import annotations

import calendar as _calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from .enums import EstadoEvento

# --------------------------------------------------------------------------
# Requisitos previos
# --------------------------------------------------------------------------


def fecha_limite_requisito(
    fecha_evento: date | None,
    offset_dias: int | None,
    fecha_limite_manual: date | None = None,
) -> date | None:
    """Cuando hay que tener hecho un requisito previo.

    Reglas, en orden:

    1. Una fecha puesta a mano siempre manda: si el medico dijo un dia
       concreto, no lo recalculamos.
    2. Si la cita ya tiene fecha y el requisito tiene antelacion, se resta.
       "Analitica 15 dias antes" de una cita el 20 de marzo -> 5 de marzo.
    3. Si la cita todavia no tiene fecha (esperando llamada), no hay fecha
       limite que calcular: devuelve None y la interfaz lo muestra como
       "pendiente de que la cita tenga fecha".
    """
    if fecha_limite_manual is not None:
        return fecha_limite_manual
    if fecha_evento is None or offset_dias is None:
        return None
    return fecha_evento - timedelta(days=offset_dias)


class Urgencia(StrEnum):
    """Como de apremiante es algo con fecha limite."""

    SIN_FECHA = "sin_fecha"
    VENCIDO = "vencido"
    HOY = "hoy"
    PROXIMO = "proximo"
    FUTURO = "futuro"


#: Orden para listar primero lo que mas arde.
ORDEN_URGENCIA: dict[str, int] = {
    Urgencia.VENCIDO: 0,
    Urgencia.HOY: 1,
    Urgencia.PROXIMO: 2,
    Urgencia.SIN_FECHA: 3,
    Urgencia.FUTURO: 4,
}


def urgencia(
    fecha_limite: date | None, hoy: date, dias_aviso: int = 7
) -> Urgencia:
    """Clasifica una fecha limite respecto a hoy.

    `dias_aviso` es con cuanta antelacion algo pasa a considerarse PROXIMO.
    """
    if fecha_limite is None:
        return Urgencia.SIN_FECHA
    if fecha_limite < hoy:
        return Urgencia.VENCIDO
    if fecha_limite == hoy:
        return Urgencia.HOY
    if (fecha_limite - hoy).days <= dias_aviso:
        return Urgencia.PROXIMO
    return Urgencia.FUTURO


def requiere_atencion(
    fecha_limite: date | None, hecho: bool, hoy: date, dias_aviso: int = 7
) -> bool:
    """Si un requisito pendiente debe aparecer en la pantalla de inicio."""
    if hecho:
        return False
    return urgencia(fecha_limite, hoy, dias_aviso) in (
        Urgencia.VENCIDO,
        Urgencia.HOY,
        Urgencia.PROXIMO,
    )


# --------------------------------------------------------------------------
# Citas sin fecha: la pantalla "En espera"
# --------------------------------------------------------------------------


def dias_esperando(solicitada_en: date | None, hoy: date) -> int | None:
    """Dias transcurridos desde que se pidio la cita.

    Devuelve None si no sabemos cuando se solicito. Nunca devuelve negativo:
    una fecha de solicitud en el futuro se trata como 0 dias.
    """
    if solicitada_en is None:
        return None
    return max(0, (hoy - solicitada_en).days)


def toca_reclamar(
    estado: str,
    solicitada_en: date | None,
    hoy: date,
    dias_alerta: int = 30,
) -> bool:
    """Si conviene llamar al hospital para preguntar por una cita.

    Solo aplica a citas solicitadas que siguen sin fecha y que llevan
    esperando mas dias de la cuenta.
    """
    if estado != EstadoEvento.SOLICITADA:
        return False
    dias = dias_esperando(solicitada_en, hoy)
    if dias is None:
        # Sin fecha de solicitud no podemos medir la espera, pero tampoco
        # queremos que la cita se pierda: se marca para revisar.
        return True
    return dias >= dias_alerta


# --------------------------------------------------------------------------
# Transporte sanitario (ambulancia)
# --------------------------------------------------------------------------


def falta_pedir_ambulancia(
    transporte: str,
    fecha: date | None,
    hoy: date,
    dias_aviso: int = 7,
) -> bool:
    """Si hay que avisar de que falta solicitar la ambulancia.

    Solo tiene sentido avisar cuando la cita ya tiene dia: sin fecha no se
    puede pedir el transporte. Se avisa desde `dias_aviso` antes y hasta el
    dia de la cita; despues ya no sirve de nada.
    """
    from .enums import EstadoTransporte

    if transporte != EstadoTransporte.PENDIENTE or fecha is None:
        return False
    return hoy <= fecha <= hoy + timedelta(days=dias_aviso)


def toca_confirmar_ambulancia(
    transporte: str, fecha: date | None, hoy: date, dias_antes: int = 1
) -> bool:
    """Si hay que llamar para confirmar la ambulancia ya pedida.

    Las empresas de transporte sanitario suelen pedir que se confirme el
    dia antes; si no, el servicio puede no presentarse.
    """
    from .enums import EstadoTransporte

    if transporte != EstadoTransporte.SOLICITADO or fecha is None:
        return False
    return hoy <= fecha <= hoy + timedelta(days=dias_antes)


# --------------------------------------------------------------------------
# Ordenacion de la agenda
# --------------------------------------------------------------------------

#: Fecha centinela para ordenar: las citas sin fecha van al final.
_LEJOS = date(9999, 12, 31)


def crearia_ciclo(
    hijo_id: int, origen_id: int, padre_de: dict[int, int | None]
) -> bool:
    """Si decir que `hijo` viene de `origen` cerraria un bucle.

    Una cita no puede salir de si misma, ni de una que ya desciende de ella:
    seria su propia nieta y recorrer el hilo no terminaria nunca.

    `padre_de` es el mapa actual de cita -> cita de la que sale.
    """
    if hijo_id == origen_id:
        return True
    visto = set()
    actual: int | None = origen_id
    while actual is not None and actual not in visto:
        if actual == hijo_id:
            return True
        visto.add(actual)
        actual = padre_de.get(actual)
    return False


def hilos_de(
    padre_de: dict[int, int | None], orden: list[int]
) -> list[list[tuple[int, int]]]:
    """Agrupa las citas en hilos y las devuelve listas para dibujar.

    Cada hilo empieza en una cita que no sale de ninguna otra, y detras van
    sus descendientes con la profundidad a la que cuelgan, para poder
    sangrarlos. `orden` fija en que orden se recorre todo.

    Aguanta que los datos traigan un bucle: se corta al repetir una cita en
    vez de girar para siempre.
    """
    hijos: dict[int | None, list[int]] = {}
    for hijo in orden:
        padre = padre_de.get(hijo)
        # Un padre que no esta en la lista cuenta como si no hubiera padre:
        # si no, su rama entera desapareceria de la vista.
        if padre is not None and padre not in padre_de:
            padre = None
        hijos.setdefault(padre, []).append(hijo)

    hilos: list[list[tuple[int, int]]] = []
    for raiz in hijos.get(None, []):
        cadena: list[tuple[int, int]] = []
        pila = [(raiz, 0)]
        visto: set[int] = set()
        while pila:
            actual, hondura = pila.pop()
            if actual in visto:
                continue
            visto.add(actual)
            cadena.append((actual, hondura))
            for siguiente in reversed(hijos.get(actual, [])):
                pila.append((siguiente, hondura + 1))
        hilos.append(cadena)
    return hilos


def antelacion_al_mover(
    fecha_manual: date | None, fecha_origen: date | None
) -> int | None:
    """Cuantos dias antes de su cita estaba un preparativo con fecha fija.

    Al pasar un preparativo de una cita a otra, una fecha puesta a mano deja
    de tener sentido: estaba atada a la cita de la que viene. Lo que si
    sigue valiendo es la antelacion ("el mismo dia", "quince dias antes"),
    asi que se convierte en eso y se recoloca sola.

    Devuelve None si no habia fecha fija o si no se puede calcular, y
    entonces se deja como estaba.
    """
    if fecha_manual is None or fecha_origen is None:
        return None
    dias = (fecha_origen - fecha_manual).days
    return dias if dias >= 0 else None


#: Los tramos en que se reparte lo que viene, con su rotulo. En este orden.
TRAMOS: tuple[tuple[str, str], ...] = (
    ("hoy", "Hoy"),
    ("manana", "Mañana"),
    ("esta_semana", "Esta semana"),
    ("semana_siguiente", "La semana que viene"),
    ("dos_semanas", "En dos semanas"),
    ("cuatro_semanas", "En cuatro semanas"),
)

#: Tramos que se pintan siempre, aunque esten vacios: saber que hoy no hay
#: nada es una respuesta, y la portada tiene que darla sin que haya que
#: deducirla de una ausencia.
TRAMOS_SIEMPRE: frozenset[str] = frozenset({"hoy", "manana", "esta_semana"})

#: Hasta donde llega la portada. Mas alla esta en Citas y aqui solo haria
#: ruido. Se cuenta desde el domingo de esta semana, no desde hoy, para que
#: los tramos acaben todos en domingo.
SEMANAS_HORIZONTE = 4


def _hasta_domingo(hoy: date) -> int:
    """Dias que faltan para el domingo de esta semana (lunes = 0)."""
    return 6 - hoy.weekday()


def fin_del_horizonte(hoy: date) -> date:
    """El ultimo dia que entra en la portada."""
    return hoy + timedelta(days=_hasta_domingo(hoy) + 7 * SEMANAS_HORIZONTE)


def tramo_de(fecha: date, hoy: date) -> str | None:
    """En que tramo cae una fecha: hoy, manana, esta semana...

    Las semanas acaban en domingo, no a los siete dias: cuando alguien dice
    "esta semana" piensa en el calendario, no en un contador. Por eso un
    viernes, "esta semana" son dos dias y "la que viene" son nueve.
    """
    dias = (fecha - hoy).days
    if dias < 0:
        return None
    if dias == 0:
        return "hoy"
    if dias == 1:
        return "manana"

    domingo = _hasta_domingo(hoy)
    for semanas, clave in (
        (0, "esta_semana"),
        (1, "semana_siguiente"),
        (2, "dos_semanas"),
        (SEMANAS_HORIZONTE, "cuatro_semanas"),
    ):
        if dias <= domingo + 7 * semanas:
            return clave
    return None


def ya_paso(
    fecha: date | None,
    hora: time | None,
    duracion_min: int,
    ahora: datetime,
) -> bool:
    """Si el momento de una cita ya quedo atras.

    Con hora se espera a que termine (la hora mas lo que dure): una cita de
    las 10:30 no esta "pasada" a las 10:31, y preguntar por ella mientras la
    persona esta dentro de la consulta seria absurdo. Sin hora, cuenta el
    dia entero: no se da por pasada hasta el dia siguiente.
    """
    if fecha is None:
        return False
    if hora is None:
        return fecha < ahora.date()
    fin = datetime.combine(fecha, hora) + timedelta(minutes=max(duracion_min, 0))
    return fin < ahora.replace(tzinfo=None)


#: Palabras que delatan un telefono al que NO se llama para pedir la
#: ambulancia: un fax, una linea de incidencias, una admision.
_NO_ES_PARA_PEDIR = ("fax", "incidencia", "admision", "admisión", "reclamac")


def elegir_telefono_ambulancia(
    contactos: list[tuple[str, str]]
) -> str | None:
    """De la agenda, el numero al que se pide la ambulancia.

    Recibe pares (nombre, telefono) ya filtrados por tipo. Varios contactos
    del transporte no sirven para pedirla -- un fax, la linea de
    incidencias, la admision de un centro -- y ensenar uno de esos en cada
    cita seria peor que no ensenar ninguno: se llamaria a quien no es.

    Se prefiere el que se llama "Ambulancias" o parecido; si no hay
    ninguno, el primero que no sea claramente otra cosa.
    """
    utiles = [
        (nombre, telefono)
        for nombre, telefono in contactos
        if telefono and not any(p in nombre.lower() for p in _NO_ES_PARA_PEDIR)
    ]
    if not utiles:
        return None
    for nombre, telefono in utiles:
        if "ambulancia" in nombre.lower():
            return telefono
    return utiles[0][1]


def urge_reclamar_previa(
    fecha_objetivo: date | None, hoy: date, dias_aviso: int
) -> bool:
    """Si hay que reclamar ya una prueba que aun no tiene fecha.

    No se espera a llevar N dias pidiendola: se mira el tiempo que queda
    para la cita en la que hace falta. Si esa cita esta a la vuelta de la
    esquina y la prueba sigue sin dia, hay que llamar hoy.

    Y sigue urgiendo aunque la cita ya haya pasado: que se pasara la fecha
    no arregla nada, y apagar el aviso ahi seria justo lo contrario de lo
    que hace falta.
    """
    if fecha_objetivo is None:
        return False
    return (fecha_objetivo - hoy).days <= dias_aviso


def clave_orden_agenda(fecha: date | None) -> tuple[int, date]:
    """Clave de ordenacion que coloca lo que no tiene fecha al final.

    Ordenar por fecha directamente falla en cuanto hay None. Esta clave
    mantiene juntas las citas con fecha, en orden, y deja despues el bloque
    de las que siguen esperando llamada.
    """
    if fecha is None:
        return (1, _LEJOS)
    return (0, fecha)


def en_horizonte(fecha: date | None, hoy: date, dias: int) -> bool:
    """Si una fecha cae dentro de la ventana que muestra la portada."""
    if fecha is None:
        return False
    return hoy <= fecha <= hoy + timedelta(days=dias)


# --------------------------------------------------------------------------
# Calendario
# --------------------------------------------------------------------------

NOMBRES_MES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

DIAS_SEMANA = ("Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom")

#: Completos, para encabezar un dia de la agenda. Saber que cae en
#: sabado importa: hay centros que no abren.
DIAS_SEMANA_LARGOS = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)


def nombre_dia(fecha: date) -> str:
    return DIAS_SEMANA_LARGOS[fecha.weekday()]


def nombre_mes(mes: int) -> str:
    return NOMBRES_MES[mes - 1]


def rejilla_mes(anio: int, mes: int) -> list[list[date]]:
    """Semanas completas (de lunes a domingo) que cubren un mes.

    Incluye los dias de relleno del mes anterior y siguiente para que todas
    las filas tengan siete celdas. La plantilla distingue los de relleno
    comparando `dia.month` con el mes pedido.
    """
    cal = _calendar.Calendar(firstweekday=0)  # 0 = lunes
    return [list(semana) for semana in cal.monthdatescalendar(anio, mes)]


def mes_anterior(anio: int, mes: int) -> tuple[int, int]:
    return (anio - 1, 12) if mes == 1 else (anio, mes - 1)


def mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


# --------------------------------------------------------------------------
# Transiciones de estado
# --------------------------------------------------------------------------

#: A que estados puede pasar cada estado. Evita saltos sin sentido como
#: marcar como realizada una cita que ni siquiera se ha solicitado.
TRANSICIONES: dict[str, frozenset[str]] = {
    EstadoEvento.POR_SOLICITAR: frozenset(
        {EstadoEvento.SOLICITADA, EstadoEvento.CONFIRMADA, EstadoEvento.CANCELADA}
    ),
    EstadoEvento.SOLICITADA: frozenset(
        {
            EstadoEvento.CONFIRMADA,
            EstadoEvento.CANCELADA,
            EstadoEvento.POR_SOLICITAR,
        }
    ),
    EstadoEvento.CONFIRMADA: frozenset(
        {
            EstadoEvento.REALIZADA,
            EstadoEvento.APLAZADA,
            EstadoEvento.CANCELADA,
            EstadoEvento.SOLICITADA,
        }
    ),
    EstadoEvento.APLAZADA: frozenset(
        {
            EstadoEvento.CONFIRMADA,
            EstadoEvento.SOLICITADA,
            EstadoEvento.CANCELADA,
        }
    ),
    EstadoEvento.REALIZADA: frozenset({EstadoEvento.CONFIRMADA}),
    EstadoEvento.CANCELADA: frozenset(
        {EstadoEvento.POR_SOLICITAR, EstadoEvento.SOLICITADA}
    ),
}


def transicion_valida(origen: str, destino: str) -> bool:
    """Si se puede pasar de un estado a otro.

    Quedarse en el mismo estado siempre vale: guardar un formulario sin
    tocar el estado no deberia fallar.
    """
    if origen == destino:
        return True
    return destino in TRANSICIONES.get(origen, frozenset())


@dataclass(frozen=True)
class CambioEstado:
    """Resultado de pedir un cambio de estado sobre una cita."""

    estado: str
    fecha: date | None
    solicitada_en: date | None
    aviso: str | None = None


def aplicar_cambio_estado(
    estado_actual: str,
    estado_nuevo: str,
    fecha: date | None,
    solicitada_en: date | None,
    hoy: date,
) -> CambioEstado:
    """Ajusta los campos que dependen del estado, de forma coherente.

    Los efectos secundarios que interesan:

    - Al pasar a SOLICITADA se anota la fecha de solicitud (si no la habia),
      que es lo que luego permite contar los dias de espera, y se borra la
      fecha de la cita: por definicion todavia no la tenemos.
    - Al CONFIRMAR sin fecha se avisa, porque una cita confirmada sin dia no
      sirve de nada y lo mas probable es un despiste al rellenar.
    - Al APLAZAR se olvida la fecha vieja para que no siga apareciendo en el
      calendario como si fuese a ocurrir.
    """
    if not transicion_valida(estado_actual, estado_nuevo):
        raise ValueError(
            f"No se puede pasar de '{estado_actual}' a '{estado_nuevo}'"
        )

    aviso: str | None = None

    if estado_nuevo == EstadoEvento.SOLICITADA:
        solicitada_en = solicitada_en or hoy
        fecha = None
    elif estado_nuevo == EstadoEvento.APLAZADA:
        fecha = None
        aviso = "La cita se ha quedado sin fecha: recuerda volver a pedirla."
    elif estado_nuevo == EstadoEvento.CONFIRMADA and fecha is None:
        aviso = "Has confirmado la cita sin indicar fecha."
    elif estado_nuevo == EstadoEvento.CANCELADA:
        aviso = None

    return CambioEstado(
        estado=estado_nuevo,
        fecha=fecha,
        solicitada_en=solicitada_en,
        aviso=aviso,
    )
