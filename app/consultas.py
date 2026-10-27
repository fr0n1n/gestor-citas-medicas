"""Consultas que alimentan las pantallas.

Se separan de las rutas para que cada vista sea una llamada y no un monton
de `select(...)` repartidos por los controladores.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from sqlmodel import Session, select

from . import areas as _areas
from . import centros as _centros
from . import logica
from .config import ahora_local, config
from .enums import (
    ESTADOS_CERRADOS,
    TipoContacto,
    TRANSPORTE_NECESARIO,
    EstadoEvento,
    EstadoTramite,
)
from .modelos import (
    Centro,
    Contacto,
    Documento,
    Evento,
    Paciente,
    Requisito,
    Tramite,
)

# --------------------------------------------------------------------------
# Basicos
# --------------------------------------------------------------------------


def listar_pacientes(sesion: Session, solo_activos: bool = True) -> list[Paciente]:
    consulta = select(Paciente).order_by(Paciente.nombre)
    if solo_activos:
        consulta = consulta.where(Paciente.activo == True)  # noqa: E712
    return list(sesion.exec(consulta))


def listar_contactos(
    sesion: Session, paciente_id: int | None = None
) -> list[Contacto]:
    """Agenda de telefonos: los generales y los del paciente elegido."""
    consulta = select(Contacto)
    if paciente_id is not None:
        consulta = consulta.where(
            (Contacto.paciente_id == None) | (Contacto.paciente_id == paciente_id)  # noqa: E711
        )
    contactos = list(sesion.exec(consulta))
    orden = {t: i for i, t in enumerate(TipoContacto)}
    contactos.sort(key=lambda c: (orden.get(c.tipo, 99), c.nombre.lower()))
    return contactos


def listar_centros(sesion: Session) -> list[Centro]:
    return list(sesion.exec(select(Centro).order_by(Centro.nombre)))


def _filtrar_paciente(consulta, paciente_id: int | None, columna):
    if paciente_id is not None:
        consulta = consulta.where(columna == paciente_id)
    return consulta


# --------------------------------------------------------------------------
# Agenda
# --------------------------------------------------------------------------


def sala_de_espera(
    sesion: Session, paciente_id: int | None = None
) -> list[Evento]:
    """Citas pedidas que siguen sin fecha, la que mas espera primero.

    Esta es la pantalla que evita que una cita se pierda para siempre.
    """
    consulta = select(Evento).where(
        Evento.estado.in_(
            (EstadoEvento.SOLICITADA, EstadoEvento.POR_SOLICITAR)
        )
    )
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
    eventos = list(sesion.exec(consulta))

    def clave(evento: Evento) -> tuple[int, int]:
        # Primero lo que lleva mas tiempo esperando; lo que ni siquiera se
        # ha solicitado va arriba del todo porque depende solo de nosotros.
        if evento.estado == EstadoEvento.POR_SOLICITAR:
            return (0, 0)
        return (1, -(evento.dias_esperando or 10**6))

    eventos.sort(key=clave)
    return eventos


def eventos_por_dia(
    sesion: Session,
    desde: date,
    hasta: date,
    paciente_id: int | None = None,
) -> dict[date, list[Evento]]:
    """Eventos con fecha dentro de un rango, agrupados por dia."""
    consulta = select(Evento).where(
        Evento.fecha != None,  # noqa: E711
        Evento.fecha >= desde,
        Evento.fecha <= hasta,
        Evento.estado != EstadoEvento.CANCELADA,
    )
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)

    agrupados: dict[date, list[Evento]] = defaultdict(list)
    for evento in sesion.exec(consulta):
        agrupados[evento.fecha].append(evento)
    for lista in agrupados.values():
        lista.sort(key=lambda e: (e.hora is None, e.hora))
    return dict(agrupados)


def especialidades(sesion: Session, paciente_id: int | None = None) -> list[str]:
    consulta = select(Evento.especialidad).where(
        Evento.especialidad != None  # noqa: E711
    )
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
    return sorted({e for e in sesion.exec(consulta) if e})


# --------------------------------------------------------------------------
# Requisitos y tramites
# --------------------------------------------------------------------------


def requisitos_pendientes(
    sesion: Session, paciente_id: int | None = None
) -> list[Requisito]:
    """Preparativos sin hacer de citas vivas, lo mas urgente primero.

    Solo los que hay que llevar o tener hecho ANTES. Lo que se pide en la
    propia consulta no entra: no tiene plazo que vigilar, se hace ese dia, y
    colarlo aqui llenaba la portada de cosas que no requerian nada hoy y
    creaba un recordatorio suelto en el calendario para algo que ya ocurre
    dentro de la cita.
    """
    consulta = (
        select(Requisito)
        .join(Evento)
        .where(
            Requisito.hecho == False,  # noqa: E712
            Requisito.en_la_cita == False,  # noqa: E712
            Evento.estado.not_in(tuple(ESTADOS_CERRADOS)),
        )
    )
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
    requisitos = list(sesion.exec(consulta))

    hoy_ = _hoy()
    requisitos.sort(
        key=lambda r: (
            logica.ORDEN_URGENCIA[
                logica.urgencia(
                    r.fecha_limite, hoy_, config.dias_aviso_requisito
                )
            ],
            logica.clave_orden_agenda(r.fecha_limite),
        )
    )
    return requisitos


def listar_tramites(
    sesion: Session, paciente_id: int | None = None, incluir_cerrados: bool = True
) -> list[Tramite]:
    consulta = select(Tramite)
    consulta = _filtrar_paciente(consulta, paciente_id, Tramite.paciente_id)
    if not incluir_cerrados:
        consulta = consulta.where(
            Tramite.estado.not_in(
                (EstadoTramite.RESUELTO, EstadoTramite.DENEGADO)
            )
        )
    tramites = list(sesion.exec(consulta))
    tramites.sort(
        key=lambda t: (
            t.estado in (EstadoTramite.RESUELTO, EstadoTramite.DENEGADO),
            logica.clave_orden_agenda(t.fecha_limite),
        )
    )
    return tramites


def documentos_pendientes(
    sesion: Session, paciente_id: int | None = None
) -> list[Documento]:
    """Subidos y sin revisar: la bandeja de entrada, lo mas antiguo primero."""
    consulta = (
        select(Documento)
        .where(Documento.revisado == False)  # noqa: E712
        .order_by(Documento.creado_en)
    )
    consulta = _filtrar_paciente(consulta, paciente_id, Documento.paciente_id)
    return list(sesion.exec(consulta))


def temas_documentos(
    sesion: Session, paciente_id: int | None = None
) -> list[str]:
    """Areas presentes en el archivo, para el filtro y las sugerencias."""
    consulta = select(Documento.tema).where(Documento.tema != None)  # noqa: E711
    consulta = _filtrar_paciente(consulta, paciente_id, Documento.paciente_id)
    return sorted({t.strip() for t in sesion.exec(consulta) if t and t.strip()},
                  key=str.lower)


def listar_documentos(
    sesion: Session,
    paciente_id: int | None = None,
    busqueda: str | None = None,
    revisados: bool | None = None,
    tema: str | None = None,
) -> list[Documento]:
    # Por la fecha del propio documento, que es la que importa para seguir
    # la historia; los que no la tienen, al final.
    consulta = select(Documento).order_by(
        Documento.fecha_documento.is_(None),
        Documento.fecha_documento.desc(),
        Documento.creado_en.desc(),
    )
    consulta = _filtrar_paciente(consulta, paciente_id, Documento.paciente_id)
    if revisados is not None:
        consulta = consulta.where(Documento.revisado == revisados)
    if tema:
        consulta = consulta.where(Documento.tema == tema)
    if busqueda:
        patron = f"%{busqueda}%"
        consulta = consulta.where(
            Documento.notas.like(patron)
            | Documento.texto.like(patron)
            | Documento.titulo.like(patron)
            | Documento.nombre_archivo.like(patron)
        )
    return list(sesion.exec(consulta))


# --------------------------------------------------------------------------
# Agrupado por area medica
# --------------------------------------------------------------------------


@dataclass
class Area:
    """Todo lo de una especialidad, junto."""

    nombre: str
    slug: str
    color: int
    abiertas: list[Evento] = field(default_factory=list)
    cerradas: list[Evento] = field(default_factory=list)
    documentos: list[Documento] = field(default_factory=list)

    @property
    def proxima(self) -> Evento | None:
        """La siguiente cita que esta por venir.

        Las de fecha pasada que siguen abiertas no cuentan como proximas:
        esas estan esperando a que se anote lo que dijo el medico, y salen
        aparte en `atrasadas`.
        """
        futuras = [e for e in self.abiertas if e.fecha and e.fecha >= _hoy()]
        return min(futuras, key=lambda e: e.fecha) if futuras else None

    @property
    def atrasadas(self) -> list[Evento]:
        """Citas ya pasadas que siguen sin cerrar."""
        return [e for e in self.abiertas if e.fecha and e.fecha < _hoy()]

    @property
    def sin_fecha(self) -> list[Evento]:
        return [e for e in self.abiertas if not e.fecha]

    @property
    def requisitos_pendientes(self) -> list[Requisito]:
        return [r for e in self.abiertas for r in e.requisitos if not r.hecho]

    @property
    def total(self) -> int:
        return len(self.abiertas) + len(self.cerradas) + len(self.documentos)


def por_areas(sesion: Session, paciente_id: int | None = None) -> list[Area]:
    """Citas y documentos agrupados por especialidad.

    Los documentos escriben la misma especialidad de muchas formas, asi que
    se normaliza (ver `app/areas.py`) para que todo lo del mismo medico
    quede junto.
    """
    from . import areas as _areas

    agrupadas: dict[str, Area] = {}

    def area_de(nombre: str) -> Area:
        if nombre not in agrupadas:
            agrupadas[nombre] = Area(
                nombre=nombre, slug=_areas.slug(nombre), color=_areas.color(nombre)
            )
        return agrupadas[nombre]

    consulta = select(Evento)
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
    for evento in sesion.exec(consulta):
        area = area_de(evento.area)
        if evento.estado in ESTADOS_CERRADOS:
            area.cerradas.append(evento)
        else:
            area.abiertas.append(evento)

    consulta = select(Documento)
    consulta = _filtrar_paciente(consulta, paciente_id, Documento.paciente_id)
    for documento in sesion.exec(consulta):
        area_de(documento.area).documentos.append(documento)

    for area in agrupadas.values():
        area.abiertas.sort(key=lambda e: logica.clave_orden_agenda(e.fecha))
        area.cerradas.sort(key=lambda e: (e.fecha is None, e.fecha), reverse=True)
        area.documentos.sort(
            key=lambda d: (d.fecha_documento is None, d.fecha_documento), reverse=True
        )

    # Primero lo que tiene cita mas proxima; las areas sin citas, al final.
    return sorted(
        agrupadas.values(),
        key=lambda a: (a.proxima.fecha if a.proxima else date(2999, 1, 1), a.nombre),
    )


def area_por_slug(
    sesion: Session, slug: str, paciente_id: int | None = None
) -> Area | None:
    for area in por_areas(sesion, paciente_id):
        if area.slug == slug:
            return area
    return None


# --------------------------------------------------------------------------
# Pantalla de inicio
# --------------------------------------------------------------------------


def _hoy() -> date:
    from .config import hoy

    return hoy()


@dataclass
class Aviso:
    """Una cosa concreta que espera algo de la persona.

    Lleva el objeto consigo para que la portada pueda ofrecer la accion que
    toca -- marcar una casilla, dar una cita por pedida, cerrar una consulta
    -- sin mandar a otra pantalla. `clase` dice cual es esa accion.
    """

    clase: str
    texto: str
    detalle: str
    enlace: str
    objeto: object = None
    urgente: bool = False


@dataclass
class Panel:
    """Todo lo que necesita saber la portada."""

    hoy: date
    proximos: list[Evento] = field(default_factory=list)
    #: Lo que viene, repartido en tramos: hoy, manana, esta semana...
    tramos: list[tuple[str, list[Evento]]] = field(default_factory=list)
    requisitos: list[Requisito] = field(default_factory=list)
    reclamar: list[Evento] = field(default_factory=list)
    #: Pruebas sin fecha que hacen falta para una cita que ya se acerca.
    previas_sin_fecha: list[Evento] = field(default_factory=list)
    por_solicitar: list[Evento] = field(default_factory=list)
    tramites: list[Tramite] = field(default_factory=list)
    sin_resultado: list[Evento] = field(default_factory=list)
    documentos: list[Documento] = field(default_factory=list)
    transporte: list[Evento] = field(default_factory=list)
    confirmar_transporte: list[Evento] = field(default_factory=list)

    @property
    def total_acciones(self) -> int:
        return (
            len(self.requisitos)
            + len(self.reclamar)
            + len(self.previas_sin_fecha)
            + len(self.por_solicitar)
            + len(self.sin_resultado)
            + len(self.documentos)
            + len(self.transporte)
            + len(self.confirmar_transporte)
        )

    @property
    def todo_en_orden(self) -> bool:
        return self.total_acciones == 0

    @property
    def pendientes(self) -> list["Aviso"]:
        """Todo lo que espera algo de la persona, en orden de lo que corre.

        Es la unica lista de la portada: cada cosa nombrada, con lo que hace
        falta para decidir y su accion al lado. Antes esto era un resumen y
        debajo iban los mismos elementos otra vez, en apartados.
        """
        avisos: list[Aviso] = []

        for r in self.requisitos:
            cita = r.evento.titulo if r.evento else "una cita"
            cuando = f", antes del {r.fecha_limite:%d/%m}" if r.fecha_limite else ""
            avisos.append(
                Aviso("requisito", f"{r.descripcion}{cuando}", f"para {cita}",
                      f"/eventos/{r.evento_id}", r, urgente=True)
            )

        for e in self.transporte:
            avisos.append(
                Aviso("transporte", f"Pedir la ambulancia para {e.titulo}",
                      f"la cita es el {e.fecha:%d/%m}" if e.fecha else "",
                      f"/eventos/{e.id}", e, urgente=True)
            )

        for e in self.confirmar_transporte:
            avisos.append(
                Aviso("confirmar_transporte",
                      f"Confirmar la ambulancia de {e.titulo}",
                      f"la cita es el {e.fecha:%d/%m}" if e.fecha else "",
                      f"/eventos/{e.id}", e, urgente=True)
            )

        for e in self.previas_sin_fecha:
            objetivo = e.antes_de
            dias = (objetivo.fecha - self.hoy).days if objetivo.fecha else None
            if dias is not None and dias < 0:
                cuando = f"la cita era el {objetivo.fecha:%d/%m} y ya pasó"
            elif dias == 0:
                cuando = "la cita es hoy"
            else:
                cuando = f"hace falta para el {objetivo.fecha:%d/%m}, dentro de {dias} días"
            avisos.append(
                Aviso("reclamar", f"Reclamar {e.titulo}: sigue sin fecha",
                      f"{cuando} · {objetivo.titulo}", f"/eventos/{e.id}", e,
                      urgente=True)
            )

        for e in self.reclamar:
            espera = (
                f"pedida hace {e.dias_esperando} días"
                if e.dias_esperando is not None
                else "sin noticias"
            )
            avisos.append(
                Aviso("reclamar", f"Reclamar {e.titulo}", espera,
                      f"/eventos/{e.id}", e)
            )

        for e in self.por_solicitar:
            avisos.append(
                Aviso("por_solicitar", f"Pedir cita: {e.titulo}",
                      e.especialidad or "", f"/eventos/{e.id}", e)
            )

        for e in self.sin_resultado:
            avisos.append(
                Aviso("sin_cerrar", f"Cerrar {e.titulo}",
                      f"fue el {e.fecha:%d/%m}" if e.fecha else "",
                      f"/eventos/{e.id}", e)
            )

        for d in self.documentos:
            nombre = d.titulo or d.nombre_original or "documento"
            avisos.append(
                Aviso("documento", f"Revisar {nombre}", "documento subido",
                      f"/documentos/{d.id}", d)
            )

        return avisos


def panel_inicio(sesion: Session, paciente_id: int | None = None) -> Panel:
    """Lo que hay que hacer ahora mismo, y nada mas."""
    hoy_ = _hoy()
    panel = Panel(hoy=hoy_)

    # El horizonte de la portada lo decide `logica`, que tambien reparte los
    # tramos: asi no puede pasar que se traigan citas que ningun tramo
    # recoge, o al reves.
    limite = logica.fin_del_horizonte(hoy_)
    por_dia = eventos_por_dia(sesion, hoy_, limite, paciente_id)
    panel.proximos = [e for dia in sorted(por_dia) for e in por_dia[dia]]

    reparto: dict[str, list[Evento]] = {clave: [] for clave, _ in logica.TRAMOS}
    for evento in panel.proximos:
        tramo = logica.tramo_de(evento.fecha, hoy_) if evento.fecha else None
        if tramo:
            reparto[tramo].append(evento)
    panel.tramos = [
        (nombre, reparto[clave])
        for clave, nombre in logica.TRAMOS
        if reparto[clave] or clave in logica.TRAMOS_SIEMPRE
    ]

    panel.requisitos = [
        r
        for r in requisitos_pendientes(sesion, paciente_id)
        if r.requiere_atencion(config.dias_aviso_requisito)
    ]

    espera = sala_de_espera(sesion, paciente_id)
    # Lo que hay que pedir, salvo lo que no se puede pedir todavia porque
    # sale de una cita que aun no ha ocurrido: eso no es algo que hacer hoy.
    panel.por_solicitar = [
        e
        for e in espera
        if e.estado == EstadoEvento.POR_SOLICITAR and not e.espera_a_otra_cita
    ]
    panel.reclamar = [
        e for e in espera if e.toca_reclamar(config.dias_alerta_espera)
    ]
    # Y lo que hace falta para una cita que ya se acerca: aqui no se espera
    # a llevar un mes pidiendolo, manda el tiempo que queda.
    panel.previas_sin_fecha = [
        e
        for e in espera
        if e.fecha is None
        and e.antes_de is not None
        and logica.urge_reclamar_previa(
            e.antes_de.fecha, hoy_, config.dias_aviso_previa
        )
        and e not in panel.reclamar
    ]

    panel.tramites = [
        t
        for t in listar_tramites(sesion, paciente_id, incluir_cerrados=False)
        if t.fecha_limite is not None
        and logica.urgencia(t.fecha_limite, hoy_, config.dias_aviso_requisito)
        in (logica.Urgencia.VENCIDO, logica.Urgencia.HOY, logica.Urgencia.PROXIMO)
    ]

    # Citas que ya pasaron pero siguen marcadas como confirmadas: hay que
    # cerrarlas y anotar que dijo el medico, o se pierde el hilo.
    consulta = select(Evento).where(
        Evento.estado == EstadoEvento.CONFIRMADA,
        Evento.fecha != None,  # noqa: E711
        Evento.fecha <= hoy_,
    )
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
    ahora_ = ahora_local().replace(tzinfo=None)
    pasadas = [
        e
        for e in sesion.exec(consulta)
        if logica.ya_paso(e.fecha, e.hora, e.duracion_min, ahora_)
    ]
    # Pero en su propio apartado solo van las de dias anteriores: las de hoy
    # se quedan en "Lo que viene", que es donde uno las busca, y salir en los
    # dos sitios era verlas duplicadas.
    panel.sin_resultado = sorted(
        (e for e in pasadas if e.fecha < hoy_),
        key=lambda e: (e.fecha, e.hora or time.min),
        reverse=True,
    )

    # Citas que se acercan y siguen sin ambulancia pedida.
    panel.transporte = [
        e
        for e in panel.proximos
        if e.falta_pedir_ambulancia(config.dias_aviso_transporte)
    ]

    # Ambulancia ya pedida: hay que llamar el dia antes a confirmarla.
    panel.confirmar_transporte = [
        e
        for e in panel.proximos
        if e.toca_confirmar_ambulancia(config.dias_confirmar_transporte)
    ]

    panel.documentos = documentos_pendientes(sesion, paciente_id)

    return panel


# --------------------------------------------------------------------------
# Citas por etapa
# --------------------------------------------------------------------------
#
# Una cita tiene tres momentos y conviene no mezclarlos en la misma lista:
# primero se pide y se espera a que llamen, luego tiene dia y hay que ir, y
# al final queda hecha y puede derivar en pruebas u otras citas.


#: Las etapas, en el orden en que ocurren. La clave va en la URL.
ETAPAS: tuple[tuple[str, str], ...] = (
    ("solicitudes", "Solicitudes"),
    ("fecha", "Con fecha"),
    ("hechas", "Pasadas"),
)

#: Al entrar se ve lo que hay que ir a hacer, que es lo que mas se consulta.
ETAPA_INICIAL = "fecha"


@dataclass
class Grupo:
    """Un monton de citas bajo un mismo rotulo: un centro, un dia, un mes."""

    eventos: list[Evento] = field(default_factory=list)
    #: Rotulo ya escrito (el nombre de un centro, por ejemplo).
    titulo: str = ""
    #: Si el grupo es un dia o un mes, la plantilla lo formatea a su gusto.
    fecha: date | None = None
    mes: bool = False
    #: A donde lleva el rotulo, si lleva a algun sitio.
    enlace: str | None = None
    #: Para pintarlo como algo que reclama atencion.
    aviso: bool = False


def _abiertos(sesion: Session, paciente_id: int | None) -> list[Evento]:
    consulta = select(Evento).where(Evento.estado.not_in(tuple(ESTADOS_CERRADOS)))
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
    return list(sesion.exec(consulta))


def _clave_espera(evento: Evento) -> tuple[int, int]:
    """Lo que mas urge, primero.

    Lo que ni siquiera se ha pedido va arriba del todo: depende solo de
    nosotros. Despues, lo que lleva mas tiempo esperando una llamada.
    """
    if evento.estado == EstadoEvento.POR_SOLICITAR:
        return (0, 0)
    return (1, -(evento.dias_esperando or 10**6))


#: Como se puede agrupar y ordenar lo que se ve. La clave va en la URL.
ORDENES: tuple[tuple[str, str], ...] = (
    ("fecha", "Fecha"),
    ("area", "Área"),
    ("centro", "Centro"),
)

#: Con que orden entra cada etapa, que no es el mismo: en Solicitudes lo
#: primero es a quien hay que llamar; con fecha, que dia toca.
ORDEN_POR_ETAPA: dict[str, str] = {
    "solicitudes": "centro",
    "fecha": "fecha",
    "hechas": "fecha",
}


def _eventos_de_etapa(
    sesion: Session, etapa: str, paciente_id: int | None
) -> list[Evento]:
    """Las citas que le tocan a una etapa, sin agrupar todavia."""
    if etapa == "hechas":
        consulta = select(Evento).where(Evento.estado.in_(tuple(ESTADOS_CERRADOS)))
        consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
        return list(sesion.exec(consulta))

    abiertos = _abiertos(sesion, paciente_id)
    if etapa == "solicitudes":
        return [e for e in abiertos if e.fecha is None]
    return [e for e in abiertos if e.fecha is not None]


def _por_centro(eventos: list[Evento], clave_interna) -> list[Grupo]:
    """Un grupo por centro, el que tiene algo mas urgente primero."""
    por_centro: dict[int | None, list[Evento]] = defaultdict(list)
    for evento in eventos:
        por_centro[evento.centro_id].append(evento)

    grupos: list[Grupo] = []
    for centro_id, lista in por_centro.items():
        lista.sort(key=clave_interna)
        centro = lista[0].centro
        grupos.append(
            Grupo(
                eventos=lista,
                titulo=centro.nombre if centro else "Sin centro asignado",
                enlace=f"/centros/{centro_id}" if centro_id else None,
                aviso=any(
                    e.toca_reclamar(config.dias_alerta_espera) for e in lista
                ),
            )
        )
    grupos.sort(key=lambda g: (-max((e.dias_esperando or 0) for e in g.eventos),
                               g.titulo))
    return grupos


def _por_area(eventos: list[Evento], clave_interna) -> list[Grupo]:
    """Un grupo por especialidad, en orden alfabetico."""
    por_area: dict[str, list[Evento]] = defaultdict(list)
    for evento in eventos:
        por_area[evento.area].append(evento)

    grupos = []
    for nombre in sorted(por_area):
        lista = sorted(por_area[nombre], key=clave_interna)
        grupos.append(
            Grupo(eventos=lista, titulo=nombre, enlace=f"/areas/{_areas.slug(nombre)}")
        )
    return grupos


def _por_dia(eventos: list[Evento]) -> list[Grupo]:
    """Un grupo por jornada. Lo pasado y sin cerrar va junto al principio."""
    hoy = _hoy()
    atrasadas = sorted(
        (e for e in eventos if e.fecha < hoy), key=lambda e: e.fecha, reverse=True
    )
    grupos: list[Grupo] = []
    if atrasadas:
        grupos.append(
            Grupo(eventos=atrasadas, titulo="Ya pasaron y siguen abiertas", aviso=True)
        )

    por_dia: dict[date, list[Evento]] = defaultdict(list)
    for evento in eventos:
        if evento.fecha >= hoy:
            por_dia[evento.fecha].append(evento)
    for dia in sorted(por_dia):
        grupos.append(
            Grupo(eventos=sorted(por_dia[dia], key=lambda e: e.hora or time.min),
                  fecha=dia)
        )
    return grupos


def _por_mes(eventos: list[Evento]) -> list[Grupo]:
    """Un grupo por mes, de lo reciente a lo antiguo."""
    por_mes: dict[tuple[int, int], list[Evento]] = defaultdict(list)
    sin_fecha: list[Evento] = []
    for evento in eventos:
        if evento.fecha is None:
            sin_fecha.append(evento)
        else:
            por_mes[(evento.fecha.year, evento.fecha.month)].append(evento)

    grupos = [
        Grupo(
            eventos=sorted(por_mes[clave], key=lambda e: e.fecha, reverse=True),
            fecha=date(clave[0], clave[1], 1),
            mes=True,
        )
        for clave in sorted(por_mes, reverse=True)
    ]
    if sin_fecha:
        grupos.append(Grupo(eventos=sin_fecha, titulo="Sin fecha"))
    return grupos


def citas_por_etapa(
    sesion: Session,
    etapa: str,
    paciente_id: int | None = None,
    orden: str | None = None,
) -> list[Grupo]:
    """Las citas de una etapa, agrupadas como pida `orden`."""
    eventos = _eventos_de_etapa(sesion, etapa, paciente_id)
    if not eventos:
        return []

    orden = orden or ORDEN_POR_ETAPA.get(etapa, "fecha")

    # Dentro de cada grupo manda el tiempo: lo que mas espera o lo que antes
    # toca. Asi el orden elegido cambia como se reparte, no que va primero.
    if etapa == "solicitudes":
        clave_interna = _clave_espera
    elif etapa == "hechas":
        clave_interna = lambda e: (e.fecha or date.min, e.id)  # noqa: E731
    else:
        clave_interna = lambda e: (e.fecha or date.max, e.hora or time.min)  # noqa: E731

    if orden == "centro":
        return _por_centro(eventos, clave_interna)
    if orden == "area":
        return _por_area(eventos, clave_interna)

    # Por fecha: cada etapa entiende "fecha" a su manera.
    if etapa == "solicitudes":
        return [Grupo(eventos=sorted(eventos, key=_clave_espera),
                      titulo="Por tiempo de espera")]
    if etapa == "hechas":
        return _por_mes(eventos)
    return _por_dia(eventos)


def cuentas_por_etapa(
    sesion: Session, paciente_id: int | None = None
) -> dict[str, int]:
    """Cuantas citas hay en cada etapa, para las pestanas."""
    abiertos = _abiertos(sesion, paciente_id)
    cerrados = select(Evento).where(Evento.estado.in_(tuple(ESTADOS_CERRADOS)))
    cerrados = _filtrar_paciente(cerrados, paciente_id, Evento.paciente_id)
    return {
        "solicitudes": sum(1 for e in abiertos if e.fecha is None),
        "fecha": sum(1 for e in abiertos if e.fecha is not None),
        "hechas": len(list(sesion.exec(cerrados))),
    }


# --------------------------------------------------------------------------
# Centros
# --------------------------------------------------------------------------


@dataclass
class VistaCentro:
    """Todo lo que toca en un hospital o ambulatorio concreto.

    Existe porque dos hospitales distintos se confunden con facilidad: uno
    manda la cita y la prueba se hace en el otro.
    """

    centro: Centro
    proximas: list[Evento] = field(default_factory=list)
    esperando: list[Evento] = field(default_factory=list)
    hechas: list[Evento] = field(default_factory=list)

    @property
    def proxima(self) -> Evento | None:
        return self.proximas[0] if self.proximas else None

    @property
    def abiertas(self) -> int:
        return len(self.proximas) + len(self.esperando)


def _vista_centro(centro: Centro, eventos: list[Evento]) -> VistaCentro:
    hoy = _hoy()
    vista = VistaCentro(centro=centro)
    for evento in eventos:
        if evento.estado in ESTADOS_CERRADOS:
            vista.hechas.append(evento)
        elif evento.fecha is None:
            vista.esperando.append(evento)
        else:
            vista.proximas.append(evento)
    vista.proximas.sort(key=lambda e: (e.fecha < hoy, e.fecha))
    vista.esperando.sort(key=_clave_espera)
    vista.hechas.sort(key=lambda e: e.fecha or date.min, reverse=True)
    return vista


def por_centros(
    sesion: Session, paciente_id: int | None = None
) -> list[VistaCentro]:
    """Un centro por tarjeta, el que tiene la cita mas cercana primero."""
    consulta = select(Evento)
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
    eventos = list(sesion.exec(consulta))

    por_id: dict[int, list[Evento]] = defaultdict(list)
    for evento in eventos:
        if evento.centro_id is not None:
            por_id[evento.centro_id].append(evento)

    vistas = [
        _vista_centro(sesion.get(Centro, centro_id), lista)
        for centro_id, lista in por_id.items()
    ]
    # Los centros sin nada pendiente, al final.
    vistas.sort(
        key=lambda v: (
            v.proxima.fecha if v.proxima else date.max,
            -v.abiertas,
            v.centro.nombre,
        )
    )
    return vistas


def centro_por_id(
    sesion: Session, centro_id: int, paciente_id: int | None = None
) -> VistaCentro | None:
    centro = sesion.get(Centro, centro_id)
    if centro is None:
        return None
    consulta = select(Evento).where(Evento.centro_id == centro_id)
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
    return _vista_centro(centro, list(sesion.exec(consulta)))


# --------------------------------------------------------------------------
# Historia: el recorrido de cada asunto
# --------------------------------------------------------------------------


@dataclass
class Eslabon:
    """Una cita dentro de un hilo, con lo hondo que cuelga."""

    evento: Evento
    hondura: int


@dataclass
class Hilo:
    """Una consulta y todo lo que salio de ella, en orden."""

    eslabones: list[Eslabon] = field(default_factory=list)

    @property
    def raiz(self) -> Evento:
        return self.eslabones[0].evento

    @property
    def total(self) -> int:
        return len(self.eslabones)

    @property
    def abiertos(self) -> int:
        return sum(1 for e in self.eslabones if e.evento.esta_abierto)

    @property
    def area(self) -> str:
        return self.raiz.area

    @property
    def desde(self) -> date | None:
        fechas = [e.evento.fecha for e in self.eslabones if e.evento.fecha]
        return min(fechas) if fechas else None

    @property
    def hasta(self) -> date | None:
        fechas = [e.evento.fecha for e in self.eslabones if e.evento.fecha]
        return max(fechas) if fechas else None


def historia(sesion: Session, paciente_id: int | None = None) -> list[Hilo]:
    """El recorrido completo: cada consulta con lo que salio de ella.

    Los hilos con algo pendiente van primero; luego los cerrados, de lo mas
    reciente a lo mas antiguo. Dentro de cada hilo manda el orden temporal.
    """
    consulta = select(Evento)
    consulta = _filtrar_paciente(consulta, paciente_id, Evento.paciente_id)
    eventos = list(sesion.exec(consulta))
    if not eventos:
        return []

    por_id = {e.id: e for e in eventos}
    padre_de = {e.id: e.evento_padre_id for e in eventos}

    # Lo mas antiguo primero: un hilo se lee de arriba abajo, como ocurrio.
    orden = sorted(
        por_id,
        key=lambda i: (
            por_id[i].fecha or por_id[i].solicitada_en or date.max,
            i,
        ),
    )

    hilos = [
        Hilo(eslabones=[Eslabon(evento=por_id[i], hondura=h) for i, h in cadena])
        for cadena in logica.hilos_de(padre_de, orden)
    ]
    hilos.sort(
        key=lambda h: (
            h.abiertos == 0,                 # primero lo que sigue vivo
            -(h.hasta or date.min).toordinal(),
        )
    )
    return hilos


# --------------------------------------------------------------------------
# Centros: encontrarlos o crearlos
# --------------------------------------------------------------------------


def _nota_de_mapa(mapa: str | None) -> str | None:
    """La linea de notas que guarda el enlace del mapa de un centro."""
    enlace = (mapa or "").strip()
    return f"Mapa: {enlace}" if enlace.startswith(("http://", "https://")) else None


def asegurar_centro(
    sesion: Session,
    nombre: str | None,
    telefono: str | None = None,
    direccion: str | None = None,
    mapa: str | None = None,
) -> int | None:
    """El centro con ese nombre, creandolo si no existe.

    Quien decide si dos nombres son el mismo sitio es `app.centros`: los
    documentos escriben el mismo hospital de muchas formas y antes cada
    documento daba de alta un centro nuevo.

    La direccion y el mapa se guardan EN EL CENTRO, no sueltos en el texto
    de la cita: asi valen para todas las citas de ese sitio y la ficha del
    centro puede ofrecer el "como llegar". A un centro que ya existe solo se
    le anaden los datos que le falten; nunca se pisa lo que ya tiene, que
    puede haberlo corregido una persona.
    """
    if not nombre or not nombre.strip():
        return None
    nombre = nombre.strip()
    nota_mapa = _nota_de_mapa(mapa)

    for centro in sesion.exec(select(Centro)).all():
        if _centros.es_el_mismo(centro.nombre, nombre):
            cambiado = False
            if telefono and not centro.telefono:
                centro.telefono = telefono.strip()
                cambiado = True
            if direccion and not centro.direccion:
                centro.direccion = direccion.strip()
                cambiado = True
            if nota_mapa and "http" not in (centro.notas or ""):
                centro.notas = "\n".join(filter(None, [centro.notas, nota_mapa]))
                cambiado = True
            if cambiado:
                sesion.add(centro)
            return centro.id

    centro = Centro(
        nombre=nombre,
        telefono=(telefono or "").strip() or None,
        direccion=(direccion or "").strip() or None,
        notas=nota_mapa,
    )
    sesion.add(centro)
    sesion.flush()
    return centro.id


def areas_para_elegir(sesion: Session, paciente_id: int | None = None) -> list[str]:
    """Las areas que reconoce la aplicacion, mas las que ya se usan.

    Antes esta lista estaba escrita a mano en la plantilla y se quedaba
    vieja en cuanto se anadia un area nueva a `app/areas.py`.
    """
    conocidas = [nombre for nombre, _ in _areas.AREAS]
    usadas = [e for e in especialidades(sesion, paciente_id) if e]
    vistas, salida = set(), []
    for nombre in conocidas + usadas:
        clave = _areas.slug(nombre)
        if clave not in vistas:
            vistas.add(clave)
            salida.append(nombre)
    return salida


def telefono_ambulancia(sesion: Session, paciente_id: int | None = None) -> str | None:
    """El telefono al que se pide la ambulancia.

    Sale junto al icono en cada cita que la necesita: el dia antes hay que
    llamar para confirmarla, y buscarlo en otra pantalla es justo lo que
    hace que no se llame. Se guarda en la ficha de la persona porque es un
    dato de como se mueve ella, no una agenda.
    """
    for paciente in listar_pacientes(sesion):
        if paciente_id is not None and paciente.id != paciente_id:
            continue
        if paciente.telefono_ambulancia:
            return paciente.telefono_ambulancia.strip()
    return None


def _solo_digitos(numero: str | None) -> str:
    return "".join(ch for ch in (numero or "") if ch.isdigit())


def telefonos_de_centro(
    sesion: Session, centro: Centro, paciente_id: int | None = None
) -> list[Contacto]:
    """Los otros telefonos del centro, aparte del principal.

    El numero principal ya se ve arriba en la ficha del centro, asi que
    repetirlo aqui solo hace dudar de cual es el bueno. Se comparan solo
    los digitos: el mismo numero se escribe de muchas maneras.
    """
    principal = _solo_digitos(centro.telefono)
    return [
        c
        for c in listar_contactos(sesion, paciente_id)
        if c.telefono
        and c.centro_id == centro.id
        and _solo_digitos(c.telefono) != principal
    ]
