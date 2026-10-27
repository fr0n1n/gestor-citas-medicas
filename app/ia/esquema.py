"""El contrato de la extraccion: que se le pide a la IA que devuelva.

Es el mismo para todos los proveedores: cambiar de Claude a otro no cambia
nada de lo que ve el resto de la aplicacion.

Las fechas viajan como texto ISO (`YYYY-MM-DD`) en vez de como fechas: los
modelos las generan asi de forma fiable, y convertirlas nosotros permite
descartar una fecha imposible sin que se caiga toda la validacion.
"""

from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field


class RequisitoExtraido(BaseModel):
    """Algo que el documento dice que hay que hacer antes de la cita."""

    descripcion: str = Field(
        description="Que hay que hacer, en pocas palabras. "
        "Ejemplo: 'Analitica de sangre en ayunas'"
    )
    tipo: str = Field(
        default="otro",
        description="Uno de: analitica, prueba_previa, ayunas, medicacion, "
        "documentacion, preparacion, transporte, otro",
    )
    offset_dias: int | None = Field(
        default=None,
        description="Dias de antelacion respecto a la cita. Si el documento "
        "dice 'analitica 15 dias antes', aqui va 15.",
    )
    fecha_limite: str | None = Field(
        default=None,
        description="Fecha concreta YYYY-MM-DD, solo si el documento da un "
        "dia exacto en vez de una antelacion.",
    )
    en_la_cita: bool = Field(
        default=False,
        description="True si es algo que se PIDE O PREGUNTA en la consulta "
        "('pedir que repitan la analitica', 'solicitar un informe para "
        "Dependencia'). False si es algo que hay que LLEVAR o TENER HECHO "
        "antes ('venir en ayunas', 'traer el informe de Traumatologia', "
        "'hacerse la analitica 15 dias antes').",
    )


class EventoExtraido(BaseModel):
    """Una cita, prueba o revision mencionada en el documento."""

    evento_existente_id: int | None = Field(
        default=None,
        description="Si es una cita que YA esta en la lista de citas "
        "registradas, su id. Por ejemplo, la citacion con fecha de una "
        "prueba que estaba esperando llamada. Si es nueva, null.",
    )
    origen_evento_id: int | None = Field(
        default=None,
        description="Si esta cita SALE de otra que ya esta registrada, el id "
        "de aquella. Por ejemplo: una consulta pide una resonancia, y la "
        "resonancia sale de esa consulta. Sirve para reconstruir el recorrido "
        "del paciente. Si no sale de ninguna, null.",
    )
    titulo: str = Field(description="Titulo corto y claro de la cita")
    tipo: str = Field(
        default="cita",
        description="Uno de: cita, prueba, revision, cirugia, ingreso, "
        "tratamiento, otro",
    )
    estado: str = Field(
        default="confirmada",
        description="Uno de: por_solicitar (el documento dice que hay que "
        "pedirla), solicitada (pedida pero sin fecha, pendiente de que "
        "llamen), confirmada (tiene dia asignado), realizada (ya ocurrio, "
        "p. ej. un informe de una consulta)",
    )
    especialidad: str | None = Field(default=None, description="Traumatologia, Digestivo...")
    centro: str | None = Field(
        default=None,
        description="NOMBRE del hospital, ambulatorio o clinica. Solo el "
        "nombre, sin la direccion: 'Centro de Diagnostico Scanner', no "
        "'Centro de Diagnostico Scanner, Av. de Andalucia 27'.",
    )
    centro_direccion: str | None = Field(
        default=None,
        description="La direccion postal de ese centro, si aparece: calle, "
        "numero, codigo postal y ciudad.",
    )
    centro_mapa: str | None = Field(
        default=None,
        description="Enlace a un mapa del centro (Google Maps u otro), si el "
        "documento o la nota de la persona lo trae. Tal cual, sin tocarlo.",
    )
    profesional: str | None = Field(default=None, description="Nombre del medico")
    ubicacion: str | None = Field(default=None, description="Planta, consulta, sala")
    fecha: str | None = Field(
        default=None,
        description="Fecha de la cita YYYY-MM-DD. Vacio si el documento no la da.",
    )
    hora: str | None = Field(default=None, description="Hora HH:MM de 24 horas")
    motivo: str | None = Field(default=None, description="Motivo de la consulta")
    transporte: str = Field(
        default="no_necesita",
        description="Transporte sanitario (ambulancia). Uno de: no_necesita, "
        "pendiente (el documento dice que hace falta pedirlo o que el "
        "paciente tiene derecho a el), solicitado, confirmado (el documento "
        "confirma la ambulancia)",
    )
    resultado: str | None = Field(
        default=None,
        description="Si es un informe de una consulta ya realizada: "
        "diagnostico, tratamiento y proximos pasos, resumidos",
    )
    telefono: str | None = Field(
        default=None,
        description="Telefono que da el documento para esta cita o servicio "
        "(cambios de cita, informacion). Tal cual aparece.",
    )
    referencia: str | None = Field(
        default=None,
        description="Numero de cita, de volante, de peticion o de historia "
        "que aparezca en el documento, para poder citarlo al llamar",
    )
    requisitos: list[RequisitoExtraido] = Field(
        default_factory=list,
        description="Preparativos que el documento exige antes de la cita",
    )

    def fecha_real(self) -> date | None:
        return _fecha(self.fecha)

    def hora_real(self) -> time | None:
        if not self.hora:
            return None
        try:
            return time.fromisoformat(self.hora.strip())
        except ValueError:
            return None


class TramiteExtraido(BaseModel):
    """Una gestion administrativa: dependencia, incapacidad, ayudas..."""

    tramite_existente_id: int | None = Field(
        default=None,
        description="Si es un tramite que YA esta en la lista de tramites "
        "registrados, su id. Si es nuevo, null.",
    )
    titulo: str = Field(description="Titulo corto del tramite")
    organismo: str | None = Field(default=None, description="Quien lo gestiona")
    expediente: str | None = Field(default=None, description="Numero de expediente")
    estado: str = Field(
        default="en_curso",
        description="Uno de: pendiente, en_curso, presentado, resuelto, denegado",
    )
    fecha_limite: str | None = Field(
        default=None, description="Plazo que da el documento, YYYY-MM-DD"
    )
    pasos: list[str] = Field(
        default_factory=list,
        description="Pasos concretos que el documento pide hacer, en orden",
    )

    def fecha_limite_real(self) -> date | None:
        return _fecha(self.fecha_limite)


class TelefonoExtraido(BaseModel):
    """Un telefono que aparece en el documento."""

    nombre: str = Field(description="De quien es: 'Cita previa', 'Radiologia'...")
    telefono: str = Field(description="El numero, tal cual aparece")
    tipo: str = Field(
        default="otro",
        description="Uno de: ambulancia, centro, administracion, profesional, "
        "urgencias, otro",
    )
    notas: str | None = Field(
        default=None, description="Horario o instrucciones: 'de 8 a 14 h'"
    )


class DocumentoExtraido(BaseModel):
    """Todo lo que la IA ha entendido de un documento."""

    titulo_documento: str = Field(
        description="Titulo breve del papel. Ejemplo: 'Citacion consulta de "
        "Digestivo' o 'Informe de alta de Traumatologia'"
    )
    tipo_documento: str = Field(
        default="otro",
        description="Uno de: citacion, informe, volante, resultado, receta, "
        "resolucion, solicitud, justificante, otro",
    )
    tema: str | None = Field(
        default=None,
        description="Area o especialidad principal del documento, en una "
        "o dos palabras y con su nombre habitual en Espana: Digestivo, "
        "Traumatologia, Cardiologia, Neurologia, Radiologia, Analisis "
        "clinicos, Rehabilitacion, Medico de cabecera, Dependencia... "
        "Sirve para agrupar el archivo por areas y para nombrar el fichero.",
    )
    fecha_documento: str | None = Field(
        default=None, description="Fecha del propio documento, YYYY-MM-DD"
    )
    paciente: str | None = Field(default=None, description="Nombre del paciente si aparece")
    resumen: str = Field(
        default="", description="Dos o tres frases con lo esencial del documento"
    )
    eventos: list[EventoExtraido] = Field(default_factory=list)
    tramites: list[TramiteExtraido] = Field(default_factory=list)
    telefonos: list[TelefonoExtraido] = Field(
        default_factory=list,
        description="TODOS los telefonos que aparezcan en el documento, con "
        "para que sirve cada uno",
    )
    avisos: list[str] = Field(
        default_factory=list,
        description="Dudas, datos ilegibles o ambiguos que una persona debe revisar",
    )

    def fecha_documento_real(self) -> date | None:
        return _fecha(self.fecha_documento)


def _fecha(valor: str | None) -> date | None:
    """Texto ISO a fecha, o None si no es valida.

    Un modelo puede inventarse un '2026-02-31'. Mejor perder el dato y que
    la persona lo rellene que guardar una fecha falsa.
    """
    if not valor:
        return None
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        return None


class CentroBuscado(BaseModel):
    """Datos de un centro sanitario, buscados a peticion de la persona.

    Todo es opcional a proposito: un hueco se rellena a mano en diez
    segundos, un telefono inventado hace perder una manana.
    """

    nombre: str = Field(
        description="Nombre oficial completo del centro, tal como aparece en "
        "su web o en la del Servicio Andaluz de Salud"
    )
    direccion: str | None = Field(
        default=None, description="Direccion postal completa con codigo postal"
    )
    telefono: str | None = Field(
        default=None,
        description="Telefono principal de centralita o de citas. Solo si lo "
        "has visto escrito; si no, null",
    )
    notas: str | None = Field(
        default=None,
        description="Una o dos frases utiles: a que area pertenece, si es "
        "publico o privado, para que sirve. Nada de publicidad",
    )
    fuente: str | None = Field(
        default=None,
        description="La direccion de internet de donde salen los datos, para "
        "que la persona pueda comprobarlos",
    )
    avisos: list[str] = Field(
        default_factory=list,
        description="Lo que no has podido confirmar, o si hay varios centros "
        "con nombre parecido y no esta claro cual es",
    )


def esquema_centro() -> dict:
    return CentroBuscado.model_json_schema()
