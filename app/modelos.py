"""Modelo de datos.

La entidad central es `Evento`: una cita, prueba o revision. Lo que la hace
distinta de una entrada de calendario normal es que **la fecha puede ser
nula**: la mitad del trabajo real de acompanar a un paciente consiste en
seguir la pista de cosas pedidas que todavia no tienen dia.
"""

# Sin `from __future__ import annotations` a proposito: SQLModel necesita
# evaluar las anotaciones de verdad para montar las relaciones. Con esa
# linea le llegan como texto ("list['Evento']") y el mapeo falla al arrancar.

from datetime import date, datetime, time

from sqlmodel import Field, Relationship, SQLModel

from . import logica
from .config import hoy
from .enums import (
    EstadoEvento,
    TipoContacto,
    EstadoTramite,
    EstadoTransporte,
    Prioridad,
    TipoEvento,
    TipoRequisito,
)


def _ahora() -> datetime:
    """El instante actual en UTC. Ver `config.ahora()` para el porque."""
    from .config import ahora

    return ahora()


class EventoDocumento(SQLModel, table=True):
    """Une citas y documentos, en los dos sentidos.

    Un mismo papel suele servir para varias cosas: una citacion con dos
    consultas, o un informe que hace falta en la revision y en la cita del
    especialista. Y una cita puede tener varios documentos.
    """

    evento_id: int | None = Field(
        default=None, foreign_key="evento.id", primary_key=True
    )
    documento_id: int | None = Field(
        default=None, foreign_key="documento.id", primary_key=True
    )


class TramiteDocumento(SQLModel, table=True):
    """Lo mismo para los tramites administrativos."""

    tramite_id: int | None = Field(
        default=None, foreign_key="tramite.id", primary_key=True
    )
    documento_id: int | None = Field(
        default=None, foreign_key="documento.id", primary_key=True
    )


class Paciente(SQLModel, table=True):
    """La persona a la que se acompana. Se admiten varias."""

    id: int | None = Field(default=None, primary_key=True)
    nombre: str
    fecha_nacimiento: date | None = None
    #: Numero de la tarjeta sanitaria o de la Seguridad Social. Se pide en
    #: casi todas las gestiones y nunca se tiene a mano.
    tarjeta_sanitaria: str | None = None
    telefono: str | None = None
    #: Si esta persona necesita ambulancia para TODAS sus citas. Las citas
    #: nuevas nacen entonces con el transporte pendiente de solicitar.
    transporte_siempre: bool = False
    #: Como hay que pedirla: "Con conductor y ayudante", "silla de ruedas"...
    #: Se copia en cada cita nueva para tenerlo a mano al llamar.
    transporte_detalle: str | None = None
    #: El numero al que se pide la ambulancia. Sale en cada cita que la
    #: necesita, asi que vive aqui y no en una agenda aparte: es un dato de
    #: como se mueve esta persona, no una lista de telefonos.
    telefono_ambulancia: str | None = None
    notas: str | None = None
    activo: bool = True
    creado_en: datetime = Field(default_factory=_ahora)

    eventos: list["Evento"] = Relationship(back_populates="paciente")
    tramites: list["Tramite"] = Relationship(back_populates="paciente")


def transporte_inicial(
    paciente: "Paciente | None", especialidad: str | None = None
) -> tuple[str, str | None]:
    """Estado y notas de transporte con que nace una cita nueva.

    Si la persona necesita ambulancia siempre, no tiene sentido marcarlo
    cita por cita: se marca en su ficha una vez.

    Con una excepcion: a las gestiones administrativas -- Dependencia,
    Bienestar Social, papeleo -- no va el enfermo, va un familiar. Pedir
    ambulancia para eso es pedirla para nadie.
    """
    from . import areas

    if areas.es_administrativa(especialidad):
        return EstadoTransporte.NO_NECESITA, None
    if paciente is not None and paciente.transporte_siempre:
        return EstadoTransporte.PENDIENTE, paciente.transporte_detalle
    return EstadoTransporte.NO_NECESITA, None


class Centro(SQLModel, table=True):
    """Hospital, ambulatorio o centro de especialidades.

    El telefono es el campo que mas se usa: es al que hay que llamar para
    reclamar una cita que no llega.
    """

    id: int | None = Field(default=None, primary_key=True)
    nombre: str
    direccion: str | None = None
    telefono: str | None = None
    notas: str | None = None

    eventos: list["Evento"] = Relationship(back_populates="centro")


class Contacto(SQLModel, table=True):
    """Un telefono util: ambulancias, cita previa, trabajadora social...

    Los centros sanitarios ya tienen el suyo en `Centro`; esto es para todo
    lo demas, que antes acababa en un campo de notas y no habia forma de
    encontrarlo cuando hacia falta llamar.
    """

    id: int | None = Field(default=None, primary_key=True)
    nombre: str
    telefono: str
    tipo: TipoContacto = TipoContacto.OTRO
    #: "Llamar el dia antes", "preguntar por Marisa", horario...
    notas: str | None = None
    #: Si el contacto es de una persona concreta; vacio = vale para todos.
    paciente_id: int | None = Field(default=None, foreign_key="paciente.id")
    #: El centro al que pertenece este telefono, si es de alguno. Los que no
    #: son de ninguno -- ambulancias, el 112, los del paciente -- se quedan
    #: sin centro y salen aparte.
    centro_id: int | None = Field(
        default=None, foreign_key="centro.id", index=True
    )
    creado_en: datetime = Field(default_factory=_ahora)



class Evento(SQLModel, table=True):
    """Una cita, prueba, revision o ingreso."""

    id: int | None = Field(default=None, primary_key=True)
    paciente_id: int = Field(foreign_key="paciente.id", index=True)

    titulo: str
    tipo: TipoEvento = TipoEvento.CITA
    estado: EstadoEvento = Field(default=EstadoEvento.POR_SOLICITAR, index=True)
    especialidad: str | None = None

    centro_id: int | None = Field(default=None, foreign_key="centro.id")
    #: Nombre del medico. Texto libre a proposito: en la practica se conoce
    #: el nombre mucho antes de que merezca la pena darlo de alta en ningun
    #: sitio, y a veces nunca se llega a saber.
    profesional: str | None = None
    #: "Planta 3, consulta 12". El detalle que siempre se olvida.
    ubicacion: str | None = None

    #: Nula mientras la cita no tenga dia asignado. Este es el campo que
    #: obliga a que toda la aplicacion sepa tratar el "todavia no se sabe".
    fecha: date | None = Field(default=None, index=True)
    hora: time | None = None
    duracion_min: int = 30

    #: Cuando se pidio la cita. Es lo que permite contar los dias de espera
    #: y decidir cuando toca volver a llamar.
    solicitada_en: date | None = None

    #: Transporte sanitario (ambulancia). Es un campo de la cita y no un
    #: requisito mas para poder responder de un vistazo a que citas lo
    #: necesitan y cuales lo tienen ya pedido.
    transporte: EstadoTransporte = Field(
        default=EstadoTransporte.NO_NECESITA, index=True
    )
    #: Empresa, telefono o numero de expediente del transporte.
    transporte_notas: str | None = None
    #: A que hora pasa a recoger la ambulancia. No es la hora de la cita:
    #: suele pasar bastante antes y es el dato que de verdad organiza la
    #: manana de quien acompana.
    transporte_hora: time | None = None

    prioridad: Prioridad = Prioridad.NORMAL
    motivo: str | None = None
    notas: str | None = None
    #: Que dijo el medico. Se rellena despues de la cita.
    resultado: str | None = None

    #: La cita de la que sale esta: de una consulta salen pruebas y
    #: revisiones. Es el hilo del proceso medico; sin el, una prueba
    #: aparece suelta y nadie recuerda por que se pidio.
    evento_padre_id: int | None = Field(default=None, foreign_key="evento.id")

    #: La cita para la que hace falta tener esto hecho. No es lo mismo que
    #: `evento_padre_id`: aquello dice de donde SALE, esto dice para cuando
    #: hace falta. Un escaner sale de una resonancia y hace falta para la
    #: consulta del mes que viene.
    antes_de_id: int | None = Field(default=None, foreign_key="evento.id")

    creado_en: datetime = Field(default_factory=_ahora)
    actualizado_en: datetime = Field(default_factory=_ahora)

    paciente: Paciente | None = Relationship(back_populates="eventos")
    centro: Centro | None = Relationship(back_populates="eventos")
    requisitos: list["Requisito"] = Relationship(
        back_populates="evento",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "Requisito.id",
        },
    )
    documentos: list["Documento"] = Relationship(
        back_populates="eventos", link_model=EventoDocumento
    )

    #: De donde viene esta cita y que ha salido de ella. Las dos puntas del
    #: mismo enlace: "remote_side" es lo que le dice a SQLAlchemy cual de
    #: los dos lados es el padre, porque la tabla se apunta a si misma.
    origen: "Evento" = Relationship(
        back_populates="derivadas",
        sa_relationship_kwargs={
            "remote_side": "Evento.id",
            "foreign_keys": "Evento.evento_padre_id",
        },
    )
    derivadas: list["Evento"] = Relationship(
        back_populates="origen",
        sa_relationship_kwargs={
            "foreign_keys": "Evento.evento_padre_id",
            "order_by": "Evento.fecha, Evento.id",
        },
    )

    #: Para que cita hace falta esto, y que cosas hacen falta para esta.
    antes_de: "Evento" = Relationship(
        back_populates="previas",
        sa_relationship_kwargs={
            "remote_side": "Evento.id",
            "foreign_keys": "Evento.antes_de_id",
        },
    )
    previas: list["Evento"] = Relationship(
        back_populates="antes_de",
        sa_relationship_kwargs={
            "foreign_keys": "Evento.antes_de_id",
            "order_by": "Evento.fecha, Evento.id",
        },
    )

    # -- Derivados -------------------------------------------------------

    @property
    def area(self) -> str:
        from . import areas

        return areas.canonica(self.especialidad)

    @property
    def dias_esperando(self) -> int | None:
        return logica.dias_esperando(self.solicitada_en, hoy())

    @property
    def ya_paso(self) -> bool:
        """Si la cita ya ocurrio y sigue sin cerrar.

        Cuenta la hora, no solo el dia: una cita de las 9 esta pasada a
        mediodia, y esperar a manana para preguntar por ella es tarde.
        """
        from .config import ahora_local
        from .enums import EstadoEvento

        if self.estado != EstadoEvento.CONFIRMADA:
            return False
        return logica.ya_paso(
            self.fecha,
            self.hora,
            self.duracion_min,
            ahora_local().replace(tzinfo=None),
        )

    @property
    def hermanas(self) -> list["Evento"]:
        """Las otras citas que salieron del mismo sitio que esta.

        Hace falta porque el hilo solo ensenaba de donde viene y que salio,
        y muchas veces lo que importa esta al lado: de una resonancia salen
        una consulta y un escaner, y desde la consulta hay que poder ver que
        el escaner sigue sin fecha.
        """
        if self.origen is None:
            return []
        return [e for e in self.origen.derivadas if e.id != self.id]

    @property
    def espera_a_otra_cita(self) -> bool:
        """Si esta cita no se puede pedir todavia porque depende de otra.

        Una prueba que hay que pedir en una consulta no se puede pedir antes
        de esa consulta. Mientras la de origen siga abierta, esta no tiene
        que aparecer entre las cosas que hacer hoy: no hay nada que hacer.
        """
        from .enums import ESTADOS_ABIERTOS, EstadoEvento

        if self.estado != EstadoEvento.POR_SOLICITAR or self.origen is None:
            return False
        return self.origen.estado in ESTADOS_ABIERTOS

    @property
    def esta_abierto(self) -> bool:
        from .enums import ESTADOS_ABIERTOS

        return self.estado in ESTADOS_ABIERTOS

    @property
    def preparativos(self) -> list["Requisito"]:
        """Lo que hay que llevar o tener hecho ANTES. Tiene fecha limite."""
        return [r for r in self.requisitos if not r.en_la_cita]

    @property
    def gestiones(self) -> list["Requisito"]:
        """Lo que hay que pedir o preguntar EN la consulta."""
        return [r for r in self.requisitos if r.en_la_cita]

    @property
    def preparativos_pendientes(self) -> list["Requisito"]:
        return [r for r in self.preparativos if not r.hecho]

    @property
    def gestiones_pendientes(self) -> list["Requisito"]:
        return [r for r in self.gestiones if not r.hecho]

    @property
    def requisitos_pendientes(self) -> list["Requisito"]:
        return [r for r in self.requisitos if not r.hecho]

    @property
    def necesita_ambulancia(self) -> bool:
        from .enums import TRANSPORTE_NECESARIO

        return self.transporte in TRANSPORTE_NECESARIO

    def falta_pedir_ambulancia(self, dias_aviso: int) -> bool:
        return logica.falta_pedir_ambulancia(
            self.transporte, self.fecha, hoy(), dias_aviso
        )

    def toca_confirmar_ambulancia(self, dias_antes: int) -> bool:
        return logica.toca_confirmar_ambulancia(
            self.transporte, self.fecha, hoy(), dias_antes
        )

    def toca_reclamar(self, dias_alerta: int) -> bool:
        return logica.toca_reclamar(
            self.estado, self.solicitada_en, hoy(), dias_alerta
        )

    @property
    def cuando(self) -> str:
        """Texto corto para listados."""
        if self.fecha is None:
            return "Sin fecha"
        texto = self.fecha.strftime("%d/%m/%Y")
        if self.hora is not None:
            texto += self.hora.strftime(" %H:%M")
        return texto


class Requisito(SQLModel, table=True):
    """Algo que hay que hacer antes de una cita para que sirva de algo.

    El caso que motiva toda esta tabla: "analitica 15 dias antes". Si no se
    hace a tiempo, se va la cita entera y vuelta a empezar.
    """

    id: int | None = Field(default=None, primary_key=True)
    evento_id: int = Field(foreign_key="evento.id", index=True)

    tipo: TipoRequisito = TipoRequisito.OTRO
    descripcion: str

    #: Dias de antelacion respecto a la cita. La fecha limite se calcula,
    #: no se guarda: si la cita se mueve, la antelacion sigue valiendo.
    offset_dias: int | None = None
    #: Fecha puesta a mano, que manda sobre el calculo anterior.
    fecha_limite_manual: date | None = None

    #: Si es algo que se pide o se pregunta EN la consulta, no algo que
    #: haya que traer hecho de antes. Son dos cosas distintas: si falla un
    #: preparativo la cita no sirve; si se olvida una gestion, se pide en la
    #: siguiente. Mezclarlas hacia ilegible la lista.
    en_la_cita: bool = False

    hecho: bool = False
    hecho_en: date | None = None
    notas: str | None = None

    evento: Evento | None = Relationship(back_populates="requisitos")

    # -- Derivados -------------------------------------------------------

    @property
    def fecha_limite(self) -> date | None:
        fecha_evento = self.evento.fecha if self.evento else None
        return logica.fecha_limite_requisito(
            fecha_evento, self.offset_dias, self.fecha_limite_manual
        )

    def urgencia(self, dias_aviso: int) -> logica.Urgencia:
        return logica.urgencia(self.fecha_limite, hoy(), dias_aviso)

    def requiere_atencion(self, dias_aviso: int) -> bool:
        return logica.requiere_atencion(
            self.fecha_limite, self.hecho, hoy(), dias_aviso
        )


class Tramite(SQLModel, table=True):
    """Gestion administrativa: dependencia, incapacidad, ayudas, recursos.

    No es una cita y no encaja en el calendario, pero compite por el mismo
    tiempo y se olvida igual de facil, asi que vive junto a lo demas.
    """

    id: int | None = Field(default=None, primary_key=True)
    paciente_id: int = Field(foreign_key="paciente.id", index=True)

    titulo: str
    organismo: str | None = None
    estado: EstadoTramite = EstadoTramite.PENDIENTE
    prioridad: Prioridad = Prioridad.NORMAL

    #: Numero de expediente. Lo piden en cada llamada.
    expediente: str | None = None

    iniciado_en: date | None = None
    #: Plazo legal o administrativo, si lo hay.
    fecha_limite: date | None = None
    resuelto_en: date | None = None

    notas: str | None = None
    creado_en: datetime = Field(default_factory=_ahora)

    paciente: Paciente | None = Relationship(back_populates="tramites")
    pasos: list["PasoTramite"] = Relationship(
        back_populates="tramite",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "PasoTramite.orden",
        },
    )
    # Al borrar el tramite se deshacen los vinculos, pero los documentos
    # se conservan: un informe medico no debe desaparecer con el.
    documentos: list["Documento"] = Relationship(
        back_populates="tramites", link_model=TramiteDocumento
    )

    @property
    def progreso(self) -> tuple[int, int]:
        hechos = sum(1 for p in self.pasos if p.hecho)
        return hechos, len(self.pasos)


class PasoTramite(SQLModel, table=True):
    """Un paso concreto dentro de un tramite."""

    id: int | None = Field(default=None, primary_key=True)
    tramite_id: int = Field(foreign_key="tramite.id", index=True)

    descripcion: str
    orden: int = 0
    hecho: bool = False
    hecho_en: date | None = None
    fecha_limite: date | None = None

    tramite: Tramite | None = Relationship(back_populates="pasos")


class Documento(SQLModel, table=True):
    """Un informe, citacion o papel escaneado o fotografiado.

    Ciclo de vida: se sube y queda *pendiente de revisar* en la carpeta
    `entrada/` con un nombre interno aleatorio. Al revisarlo (a mano, o en
    la fase 2 con la propuesta de la IA) se asocia a una cita o tramite y se
    mueve a `archivo/` con su nombre normalizado.
    """

    id: int | None = Field(default=None, primary_key=True)
    paciente_id: int = Field(foreign_key="paciente.id", index=True)

    nombre_archivo: str
    #: Ruta relativa a la carpeta de documentos, nunca absoluta: asi la
    #: carpeta de datos se puede mover o restaurar en otra maquina.
    ruta_relativa: str
    mime: str | None = None
    #: Para detectar que un papel ya se habia escaneado antes.
    hash_sha256: str | None = Field(default=None, index=True)
    tamano_bytes: int | None = None
    #: Como se llamaba el fichero al subirlo. Solo para mostrarlo: nunca se
    #: usa para construir rutas.
    nombre_original: str | None = None

    fecha_documento: date | None = None
    titulo: str | None = None
    #: Area o especialidad del documento: Digestivo, Traumatologia,
    #: Dependencia... Sirve para agrupar el archivo y se usa tambien para
    #: nombrar el fichero.
    tema: str | None = Field(default=None, index=True)
    #: Texto plano extraido (OCR). Es lo que hace el archivo buscable.
    texto: str | None = None
    #: Lo que escribio la persona al subirlo: "analitica de la abuela",
    #: "papeles que dio la trabajadora social"... Es lo que permite saber
    #: a que corresponde un papel antes de abrirlo.
    notas: str | None = None
    #: JSON con lo que propuso la IA, tal cual lo devolvio.
    datos_extraidos: str | None = None
    #: JSON con lo que se creo al confirmar la propuesta (ids de citas,
    #: tramites y requisitos). Es lo que permite deshacerlo despues.
    cambios_aplicados: str | None = None
    #: La IA propone, una persona confirma. Nada entra en la agenda sin esto.
    revisado: bool = False

    #: Estado del analisis con IA. Se guarda en la base y no en el
    #: navegador: si se cierra la web o se pierde la conexion a mitad, el
    #: analisis sigue en el servidor y la propuesta queda esperando.
    #: None -> en_cola -> analizando -> propuesta | error -> aplicada
    estado_ia: str | None = Field(default=None, index=True)
    error_ia: str | None = None
    ia_actualizado_en: datetime | None = None

    creado_en: datetime = Field(default_factory=_ahora)

    eventos: list[Evento] = Relationship(
        back_populates="documentos", link_model=EventoDocumento
    )
    tramites: list[Tramite] = Relationship(
        back_populates="documentos", link_model=TramiteDocumento
    )

    @property
    def area(self) -> str:
        from . import areas

        return areas.canonica(self.tema)

    @property
    def creados(self) -> dict:
        """Que se creo al confirmar este documento (vacio si no se aplico)."""
        import json

        if not self.cambios_aplicados:
            return {}
        try:
            return json.loads(self.cambios_aplicados)
        except ValueError:
            return {}

    @property
    def analizando(self) -> bool:
        return self.estado_ia in ("en_cola", "analizando")

    @property
    def es_imagen_visible(self) -> bool:
        return self.mime in ("image/jpeg", "image/png", "image/webp")

    @property
    def asociado_a(self) -> list[str]:
        """Titulos de las citas y tramites a los que pertenece."""
        return [e.titulo for e in self.eventos] + [t.titulo for t in self.tramites]


class Usuario(SQLModel, table=True):
    """Persona que puede entrar en la aplicacion.

    No hay pagina de registro a proposito: en un servidor accesible desde
    la red, una pagina asi permitiria que cualquiera de la red se diese de
    alta. Los usuarios se crean desde la consola con scripts/usuario.py.
    """

    id: int | None = Field(default=None, primary_key=True)
    nombre: str = Field(index=True, sa_column_kwargs={"unique": True})
    hash_password: str
    activo: bool = True
    creado_en: datetime = Field(default_factory=_ahora)
    ultimo_acceso: datetime | None = None


class Sesion(SQLModel, table=True):
    """Una sesion abierta (un navegador con la cookie de acceso).

    Se guarda el hash del token, nunca el token: con una copia de la base
    no se puede suplantar a nadie. Borrar la fila cierra la sesion al
    momento, cosa que una cookie firmada sin estado en el servidor no
    permitiria.
    """

    id: int | None = Field(default=None, primary_key=True)
    hash_token: str = Field(index=True, sa_column_kwargs={"unique": True})
    usuario_id: int = Field(foreign_key="usuario.id", index=True)
    creada_en: datetime = Field(default_factory=_ahora)
    expira_en: datetime
    #: Navegador y sistema, solo para poder reconocer la sesion.
    agente: str | None = None

