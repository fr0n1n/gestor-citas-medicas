"""Vocabulario del dominio.

Los valores son los que se guardan en la base de datos: no los cambies sin
migrar los datos existentes. Las etiquetas son lo que ve el usuario.
"""

from __future__ import annotations

from enum import StrEnum


class TipoEvento(StrEnum):
    CITA = "cita"
    PRUEBA = "prueba"
    REVISION = "revision"
    CIRUGIA = "cirugia"
    INGRESO = "ingreso"
    TRATAMIENTO = "tratamiento"
    OTRO = "otro"


class EstadoEvento(StrEnum):
    """Ciclo de vida de una cita.

    El estado SOLICITADA es el corazon de la aplicacion: la cita esta pedida
    pero el hospital todavia no ha llamado con una fecha. Son las que se
    pierden de vista y las que la pantalla "En espera" vigila.
    """

    POR_SOLICITAR = "por_solicitar"
    SOLICITADA = "solicitada"
    CONFIRMADA = "confirmada"
    REALIZADA = "realizada"
    APLAZADA = "aplazada"
    CANCELADA = "cancelada"


class TipoRequisito(StrEnum):
    """Cosas que hay que hacer *antes* de una cita para que sea util."""

    ANALITICA = "analitica"
    PRUEBA_PREVIA = "prueba_previa"
    AYUNAS = "ayunas"
    MEDICACION = "medicacion"
    DOCUMENTACION = "documentacion"
    PREPARACION = "preparacion"
    TRANSPORTE = "transporte"
    OTRO = "otro"


class TipoContacto(StrEnum):
    """Para agrupar la agenda de telefonos."""

    AMBULANCIA = "ambulancia"
    CENTRO = "centro"
    ADMINISTRACION = "administracion"
    PROFESIONAL = "profesional"
    URGENCIAS = "urgencias"
    OTRO = "otro"


class EstadoTransporte(StrEnum):
    """Transporte sanitario (ambulancia) para acudir a una cita.

    Va como campo de la cita y no como un requisito mas porque hay que
    poder responder de un vistazo a "¿que citas necesitan ambulancia y
    cuales estan ya pedidas?".
    """

    NO_NECESITA = "no_necesita"
    PENDIENTE = "pendiente"
    SOLICITADO = "solicitado"
    CONFIRMADO = "confirmado"


class EstadoTramite(StrEnum):
    PENDIENTE = "pendiente"
    EN_CURSO = "en_curso"
    PRESENTADO = "presentado"
    RESUELTO = "resuelto"
    DENEGADO = "denegado"


class Prioridad(StrEnum):
    BAJA = "baja"
    NORMAL = "normal"
    ALTA = "alta"


#: Estados en los que la cita sigue viva y requiere seguimiento.
ESTADOS_ABIERTOS: frozenset[str] = frozenset(
    {
        EstadoEvento.POR_SOLICITAR,
        EstadoEvento.SOLICITADA,
        EstadoEvento.CONFIRMADA,
        EstadoEvento.APLAZADA,
    }
)

#: Estados que ya no exigen nada y salen de las vistas de accion.
ESTADOS_CERRADOS: frozenset[str] = frozenset(
    {EstadoEvento.REALIZADA, EstadoEvento.CANCELADA}
)

#: Citas en las que hace falta ambulancia (esten pedidas o no).
TRANSPORTE_NECESARIO: frozenset[str] = frozenset(
    {
        EstadoTransporte.PENDIENTE,
        EstadoTransporte.SOLICITADO,
        EstadoTransporte.CONFIRMADO,
    }
)

#: Estados que, por definicion, todavia no tienen fecha asignada.
ESTADOS_SIN_FECHA: frozenset[str] = frozenset(
    {EstadoEvento.POR_SOLICITAR, EstadoEvento.SOLICITADA, EstadoEvento.APLAZADA}
)


ETIQUETAS: dict[str, str] = {
    # TipoEvento
    TipoEvento.CITA: "Cita",
    TipoEvento.PRUEBA: "Prueba",
    TipoEvento.REVISION: "Revisión",
    TipoEvento.CIRUGIA: "Cirugía",
    TipoEvento.INGRESO: "Ingreso",
    TipoEvento.TRATAMIENTO: "Tratamiento",
    TipoEvento.OTRO: "Otro",
    # EstadoEvento
    EstadoEvento.POR_SOLICITAR: "Por solicitar",
    EstadoEvento.SOLICITADA: "Esperando llamada",
    EstadoEvento.CONFIRMADA: "Confirmada",
    EstadoEvento.REALIZADA: "Realizada",
    EstadoEvento.APLAZADA: "Aplazada",
    EstadoEvento.CANCELADA: "Cancelada",
    # TipoRequisito
    TipoRequisito.ANALITICA: "Analítica",
    TipoRequisito.PRUEBA_PREVIA: "Prueba previa",
    TipoRequisito.AYUNAS: "Ayunas",
    TipoRequisito.MEDICACION: "Medicación",
    TipoRequisito.DOCUMENTACION: "Documentación",
    TipoRequisito.PREPARACION: "Preparación",
    TipoRequisito.TRANSPORTE: "Transporte",
    TipoRequisito.OTRO: "Otro",
    # TipoContacto
    TipoContacto.AMBULANCIA: "Ambulancias",
    TipoContacto.CENTRO: "Centros sanitarios",
    TipoContacto.ADMINISTRACION: "Administración",
    TipoContacto.PROFESIONAL: "Profesionales",
    TipoContacto.URGENCIAS: "Urgencias",
    TipoContacto.OTRO: "Otros",
    # EstadoTransporte
    EstadoTransporte.NO_NECESITA: "No necesita",
    EstadoTransporte.PENDIENTE: "Ambulancia por solicitar",
    EstadoTransporte.SOLICITADO: "Ambulancia solicitada",
    EstadoTransporte.CONFIRMADO: "Ambulancia confirmada",
    # EstadoTramite
    EstadoTramite.PENDIENTE: "Pendiente",
    EstadoTramite.EN_CURSO: "En curso",
    EstadoTramite.PRESENTADO: "Presentado",
    EstadoTramite.RESUELTO: "Resuelto",
    EstadoTramite.DENEGADO: "Denegado",
    # Prioridad
    Prioridad.BAJA: "Baja",
    Prioridad.NORMAL: "Normal",
    Prioridad.ALTA: "Alta",
}


#: Icono de cada tipo de contacto, para reconocerlo de un vistazo.
ICONOS_CONTACTO: dict[str, str] = {
    TipoContacto.AMBULANCIA: "🚑",
    TipoContacto.CENTRO: "🏥",
    TipoContacto.ADMINISTRACION: "🏛️",
    TipoContacto.PROFESIONAL: "👩‍⚕️",
    TipoContacto.URGENCIAS: "🚨",
    TipoContacto.OTRO: "📞",
}


def etiqueta(valor: str | None) -> str:
    """Texto legible para un valor del dominio."""
    if valor is None:
        return ""
    return ETIQUETAS.get(valor, str(valor).replace("_", " ").capitalize())
