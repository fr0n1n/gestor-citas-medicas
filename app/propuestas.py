"""Del analisis de un documento a cambios en la agenda.

Dos piezas:

- `contexto_para`: lo que ya se sabe (citas y tramites abiertos), para que
  la IA reconozca "esta citacion es la de la ecografia que esperabamos" en
  vez de crear un duplicado.
- `aplicar`: convierte la propuesta, ya revisada por una persona, en citas,
  requisitos y tramites, y archiva el documento con su nombre normalizado.

Aplicar nunca borra informacion que ya existia: solo rellena lo que falta
o actualiza lo que el documento trae.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlmodel import Session, select

from . import almacen, archivos, consultas, logica
from .config import ahora, hoy
from .enums import (
    ESTADOS_CERRADOS,
    TipoContacto,
    EstadoEvento,
    EstadoTramite,
    EstadoTransporte,
    TipoEvento,
    TipoRequisito,
    etiqueta,
)
from .ia.base import ContextoAnalisis
from .ia.esquema import DocumentoExtraido
from .modelos import (
    Centro,
    Contacto,
    transporte_inicial,
    Documento,
    Evento,
    Paciente,
    PasoTramite,
    Requisito,
    Tramite,
)

# --------------------------------------------------------------------------
# Contexto para la IA
# --------------------------------------------------------------------------


def _linea_evento(e: Evento) -> str:
    partes = [f"[id={e.id}] {e.titulo}"]
    if e.especialidad:
        partes.append(e.especialidad)
    if e.fecha:
        cuando = e.fecha.isoformat() + (f" {e.hora.strftime('%H:%M')}" if e.hora else "")
        partes.append(f"{etiqueta(e.estado).lower()} {cuando}")
    elif e.estado == EstadoEvento.SOLICITADA and e.solicitada_en:
        partes.append(f"esperando llamada desde {e.solicitada_en.isoformat()} (sin fecha)")
    else:
        partes.append(etiqueta(e.estado).lower())
    return " · ".join(partes)


def _linea_tramite(t: Tramite) -> str:
    partes = [f"[id={t.id}] {t.titulo}"]
    if t.organismo:
        partes.append(t.organismo)
    partes.append(etiqueta(t.estado).lower())
    if t.expediente:
        partes.append(f"expediente {t.expediente}")
    return " · ".join(partes)


def contexto_para(sesion: Session, documento: Documento) -> ContextoAnalisis:
    paciente = sesion.get(Paciente, documento.paciente_id)
    eventos = sesion.exec(
        select(Evento).where(
            Evento.paciente_id == documento.paciente_id,
            Evento.estado.not_in(tuple(ESTADOS_CERRADOS)),
        )
    ).all()
    tramites = sesion.exec(
        select(Tramite).where(
            Tramite.paciente_id == documento.paciente_id,
            Tramite.estado.not_in((EstadoTramite.RESUELTO, EstadoTramite.DENEGADO)),
        )
    ).all()
    return ContextoAnalisis(
        paciente=paciente.nombre if paciente else "(desconocido)",
        hoy=hoy().isoformat(),
        citas=[_linea_evento(e) for e in eventos],
        tramites=[_linea_tramite(t) for t in tramites],
        nota=documento.notas,
    )


def propuesta_de(documento: Documento) -> DocumentoExtraido | None:
    if not documento.datos_extraidos:
        return None
    try:
        return DocumentoExtraido.model_validate_json(documento.datos_extraidos)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Aplicar
# --------------------------------------------------------------------------


def _enum(clase, valor, por_defecto):
    try:
        return clase(valor)
    except ValueError:
        return por_defecto


def _centro(
    sesion: Session,
    nombre: str | None,
    telefono: str | None = None,
    direccion: str | None = None,
    mapa: str | None = None,
) -> int | None:
    """Atajo al de `consultas`, que es quien sabe de centros."""
    return consultas.asegurar_centro(sesion, nombre, telefono, direccion, mapa)


@dataclass
class Resultado:
    creados: list[str] = field(default_factory=list)
    ids_eventos: list[int] = field(default_factory=list)
    ids_tramites: list[int] = field(default_factory=list)
    ids_requisitos: list[int] = field(default_factory=list)
    actualizados: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def resumen(self) -> str:
        trozos = []
        if self.creados:
            trozos.append("Creado: " + "; ".join(self.creados))
        if self.actualizados:
            trozos.append("Actualizado: " + "; ".join(self.actualizados))
        if self.avisos:
            trozos.append("Ojo: " + "; ".join(self.avisos))
        return ". ".join(trozos) or "Documento archivado."


@dataclass
class EventoRevisado:
    """Una cita de la propuesta, tal como la ha dejado la persona."""

    indice: int
    incluir: bool
    titulo: str
    estado: str
    fecha: date | None
    hora: time | None
    evento_existente_id: int | None
    requisitos_incluidos: set[int]


@dataclass
class TramiteRevisado:
    indice: int
    incluir: bool
    tramite_existente_id: int | None


def _origen_valido(
    sesion: Session, origen_id: int | None, documento: Documento
) -> int | None:
    """El id de la cita de la que sale esta, si es creible.

    Se comprueba que exista y que sea del mismo paciente: un enlace a la
    cita de otra persona seria peor que no tener enlace.
    """
    if not origen_id:
        return None
    origen = sesion.get(Evento, origen_id)
    if origen is None or origen.paciente_id != documento.paciente_id:
        return None
    return origen.id


def _aplicar_evento(
    sesion: Session,
    documento: Documento,
    extraido,
    revisado: EventoRevisado,
    resultado: Resultado,
) -> Evento:
    existente = None
    if revisado.evento_existente_id:
        existente = sesion.get(Evento, revisado.evento_existente_id)
        if existente is not None and existente.paciente_id != documento.paciente_id:
            existente = None

    estado = _enum(EstadoEvento, revisado.estado, EstadoEvento.CONFIRMADA)

    if existente is None:
        transporte = _enum(
            EstadoTransporte, extraido.transporte, EstadoTransporte.NO_NECESITA
        )
        notas_transporte = None
        if transporte == EstadoTransporte.NO_NECESITA:
            transporte, notas_transporte = transporte_inicial(
                sesion.get(Paciente, documento.paciente_id), extraido.especialidad
            )
        evento = Evento(
            paciente_id=documento.paciente_id,
            titulo=revisado.titulo or extraido.titulo,
            tipo=_enum(TipoEvento, extraido.tipo, TipoEvento.CITA),
            estado=estado,
            especialidad=extraido.especialidad,
            centro_id=_centro(
                sesion,
                extraido.centro,
                extraido.telefono,
                getattr(extraido, "centro_direccion", None),
                getattr(extraido, "centro_mapa", None),
            ),
            profesional=extraido.profesional,
            ubicacion=extraido.ubicacion,
            fecha=revisado.fecha,
            hora=revisado.hora,
            motivo=extraido.motivo,
            resultado=extraido.resultado,
            notas=(f"Referencia: {extraido.referencia}" if extraido.referencia else None),
            transporte=transporte,
            transporte_notas=notas_transporte,
            solicitada_en=hoy() if estado == EstadoEvento.SOLICITADA else None,
            # De que cita sale esta. Es lo que enhebra el recorrido: de una
            # consulta salen sus pruebas y su revision.
            evento_padre_id=_origen_valido(
                sesion, getattr(extraido, "origen_evento_id", None), documento
            ),
        )
        sesion.add(evento)
        sesion.flush()
        resultado.creados.append(evento.titulo)
        resultado.ids_eventos.append(evento.id)
    else:
        evento = existente
        if estado != evento.estado:
            if logica.transicion_valida(evento.estado, estado):
                cambio = logica.aplicar_cambio_estado(
                    evento.estado, estado, revisado.fecha or evento.fecha,
                    evento.solicitada_en, hoy(),
                )
                evento.estado, evento.fecha, evento.solicitada_en = (
                    cambio.estado, cambio.fecha, cambio.solicitada_en,
                )
            else:
                resultado.avisos.append(
                    f"'{evento.titulo}' sigue {etiqueta(evento.estado).lower()}: "
                    f"no se puede pasar a {etiqueta(estado).lower()} directamente"
                )
        if revisado.fecha and evento.estado not in (
            EstadoEvento.SOLICITADA, EstadoEvento.POR_SOLICITAR, EstadoEvento.APLAZADA
        ):
            evento.fecha = revisado.fecha
        if revisado.hora and evento.fecha:
            evento.hora = revisado.hora
        # Solo se rellena lo que falta: nunca se pisa lo que ya habia.
        for campo in ("especialidad", "profesional", "ubicacion", "motivo", "resultado"):
            nuevo = getattr(extraido, campo)
            if nuevo and not getattr(evento, campo):
                setattr(evento, campo, nuevo)
        if extraido.centro:
            nuevo_centro = _centro(sesion, extraido.centro, extraido.telefono)
            if not evento.centro_id:
                evento.centro_id = nuevo_centro
        # Solo se anade la ambulancia si la cita no tenia nada anotado: si
        # ya estaba pedida, un documento antiguo no debe echarlo atras.
        transporte = _enum(
            EstadoTransporte, extraido.transporte, EstadoTransporte.NO_NECESITA
        )
        if (
            transporte != EstadoTransporte.NO_NECESITA
            and evento.transporte == EstadoTransporte.NO_NECESITA
        ):
            evento.transporte = transporte
        evento.actualizado_en = ahora()
        sesion.add(evento)
        resultado.actualizados.append(evento.titulo)

    ya = {r.descripcion.strip().lower() for r in evento.requisitos}
    for j, requisito in enumerate(extraido.requisitos):
        if j not in revisado.requisitos_incluidos:
            continue
        if requisito.descripcion.strip().lower() in ya:
            continue
        nuevo_requisito = Requisito(
            evento_id=evento.id,
            tipo=_enum(TipoRequisito, requisito.tipo, TipoRequisito.OTRO),
            descripcion=requisito.descripcion.strip(),
            # Lo que se pide en la consulta va a su propia lista y no tiene
            # antelacion: se hace ese dia por definicion.
            en_la_cita=bool(getattr(requisito, "en_la_cita", False)),
            offset_dias=requisito.offset_dias,
            fecha_limite_manual=(
                date.fromisoformat(requisito.fecha_limite)
                if requisito.fecha_limite and _es_fecha(requisito.fecha_limite)
                else None
            ),
        )
        sesion.add(nuevo_requisito)
        sesion.flush()
        resultado.ids_requisitos.append(nuevo_requisito.id)
    return evento


def _es_fecha(valor: str) -> bool:
    try:
        date.fromisoformat(valor)
        return True
    except ValueError:
        return False


def _aplicar_tramite(
    sesion: Session, documento: Documento, extraido, revisado: TramiteRevisado,
    resultado: Resultado,
) -> Tramite:
    existente = None
    if revisado.tramite_existente_id:
        existente = sesion.get(Tramite, revisado.tramite_existente_id)
        if existente is not None and existente.paciente_id != documento.paciente_id:
            existente = None

    estado = _enum(EstadoTramite, extraido.estado, EstadoTramite.EN_CURSO)
    if existente is None:
        tramite = Tramite(
            paciente_id=documento.paciente_id,
            titulo=extraido.titulo,
            organismo=extraido.organismo,
            expediente=extraido.expediente,
            estado=estado,
            fecha_limite=extraido.fecha_limite_real(),
            iniciado_en=documento.fecha_documento or hoy(),
        )
        sesion.add(tramite)
        sesion.flush()
        resultado.creados.append(tramite.titulo)
        resultado.ids_tramites.append(tramite.id)
    else:
        tramite = existente
        tramite.estado = estado
        for campo, valor in (
            ("organismo", extraido.organismo),
            ("expediente", extraido.expediente),
            ("fecha_limite", extraido.fecha_limite_real()),
        ):
            if valor and not getattr(tramite, campo):
                setattr(tramite, campo, valor)
        sesion.add(tramite)
        resultado.actualizados.append(tramite.titulo)

    ya = {p.descripcion.strip().lower() for p in tramite.pasos}
    orden = len(tramite.pasos)
    for paso in extraido.pasos:
        if paso.strip() and paso.strip().lower() not in ya:
            sesion.add(PasoTramite(tramite_id=tramite.id, descripcion=paso.strip(), orden=orden))
            orden += 1
    return tramite


def archivar_documento(
    documento: Documento,
    titulo: str | None,
    fecha_documento: date | None,
    tema: str | None,
    tipo_documento: str | None,
) -> None:
    """Pone titulo, fecha y tema, y mueve el fichero a archivo/ renombrado."""
    documento.titulo = titulo or documento.titulo
    # Se guarda, no solo se usa para el nombre: si mas adelante hay que
    # renombrar el fichero, la fecha tiene que seguir estando.
    documento.fecha_documento = fecha_documento or documento.fecha_documento
    documento.tema = tema or documento.tema
    extension = documento.nombre_archivo.rsplit(".", 1)[-1]
    almacen.archivar(
        documento,
        archivos.nombre_normalizado(
            documento.fecha_documento, [tema, tipo_documento], extension
        ),
    )
    documento.revisado = True


def aplicar(
    sesion: Session,
    documento: Documento,
    propuesta: DocumentoExtraido,
    eventos: list[EventoRevisado],
    tramites: list[TramiteRevisado],
    titulo: str | None,
    fecha_documento: date | None,
    tema: str | None,
) -> Resultado:
    """Aplica la propuesta revisada. Todo o nada: un unico commit."""
    resultado = Resultado()
    primero_evento = primero_tramite = None
    vinculados_evento: list[Evento] = []
    vinculados_tramite: list[Tramite] = []

    for revisado in eventos:
        if not revisado.incluir or revisado.indice >= len(propuesta.eventos):
            continue
        evento = _aplicar_evento(
            sesion, documento, propuesta.eventos[revisado.indice], revisado, resultado
        )
        primero_evento = primero_evento or evento
        if evento not in vinculados_evento:
            vinculados_evento.append(evento)

    for revisado in tramites:
        if not revisado.incluir or revisado.indice >= len(propuesta.tramites):
            continue
        tramite = _aplicar_tramite(
            sesion, documento, propuesta.tramites[revisado.indice], revisado, resultado
        )
        primero_tramite = primero_tramite or tramite
        if tramite not in vinculados_tramite:
            vinculados_tramite.append(tramite)

    # El documento queda vinculado a TODO lo que ha creado o actualizado:
    # una misma citacion puede traer dos consultas y un tramite.
    for evento in vinculados_evento:
        if evento not in documento.eventos:
            documento.eventos.append(evento)
    for tramite in vinculados_tramite:
        if tramite not in documento.tramites:
            documento.tramites.append(tramite)

    # Los telefonos del documento se guardan en el centro de la cita que
    # los trajo: un numero suelto, sin saber a quien llama ni para que, no
    # se busca nunca. Si el documento no trae cita, no hay donde ponerlo.
    centro_del_documento = (
        primero_evento.centro_id if primero_evento is not None else None
    )
    for telefono in propuesta.telefonos:
        numero = (telefono.telefono or "").strip()
        if not numero:
            continue
        solo_digitos = "".join(ch for ch in numero if ch.isdigit())
        ya_esta = any(
            "".join(ch for ch in c.telefono if ch.isdigit()) == solo_digitos
            for c in sesion.exec(select(Contacto)).all()
        )
        if ya_esta:
            continue
        sesion.add(
            Contacto(
                nombre=telefono.nombre.strip() or "Sin nombre",
                telefono=numero,
                tipo=_enum(TipoContacto, telefono.tipo, TipoContacto.OTRO),
                notas=telefono.notas,
                paciente_id=documento.paciente_id,
                centro_id=centro_del_documento,
            )
        )
        resultado.creados.append(f"teléfono {telefono.nombre}")

    # El resumen hace que el documento aparezca en el buscador.
    documento.texto = propuesta.resumen or documento.texto
    # Si la IA no dio tema, se hereda la especialidad de la cita asociada.
    if not tema and primero_evento is not None:
        tema = primero_evento.especialidad
    # Muchas citaciones no llevan fecha de emision impresa. Archivarlas como
    # "sin-fecha" no ayuda a encontrarlas: se usa el dia de la cita, que es
    # justo lo que la persona recuerda.
    if fecha_documento is None and primero_evento is not None:
        fecha_documento = primero_evento.fecha
    archivar_documento(
        documento, titulo, fecha_documento, tema, propuesta.tipo_documento
    )
    documento.estado_ia = "aplicada"
    documento.cambios_aplicados = json.dumps(
        {
            "eventos": resultado.ids_eventos,
            "tramites": resultado.ids_tramites,
            "requisitos": resultado.ids_requisitos,
        }
    )
    documento.ia_actualizado_en = ahora()
    sesion.add(documento)
    sesion.commit()
    return resultado


def deshacer(sesion: Session, documento: Documento) -> Resultado:
    """Borra lo que se creo al confirmar este documento.

    Solo toca lo que creo el documento: lo que existia antes y solo se
    actualizo no se puede revertir (no se guarda como estaba). Y no borra
    una cita o tramite al que se hayan enlazado despues otros documentos:
    en ese caso seguramente ya se use para otra cosa.
    """
    resultado = Resultado()
    creados = documento.creados

    for requisito_id in creados.get("requisitos", []):
        requisito = sesion.get(Requisito, requisito_id)
        if requisito is not None:
            sesion.delete(requisito)

    for evento_id in creados.get("eventos", []):
        evento = sesion.get(Evento, evento_id)
        if evento is None:
            continue
        otros = [d for d in evento.documentos if d.id != documento.id]
        if otros:
            resultado.avisos.append(
                f"'{evento.titulo}' se conserva: tiene otros documentos"
            )
            continue
        resultado.creados.append(evento.titulo)
        sesion.delete(evento)

    for tramite_id in creados.get("tramites", []):
        tramite = sesion.get(Tramite, tramite_id)
        if tramite is None:
            continue
        otros = [d for d in tramite.documentos if d.id != documento.id]
        if otros:
            resultado.avisos.append(
                f"'{tramite.titulo}' se conserva: tiene otros documentos"
            )
            continue
        resultado.creados.append(tramite.titulo)
        sesion.delete(tramite)

    # El documento vuelve a la bandeja, con su propuesta intacta por si se
    # quiere revisar y confirmar otra vez.
    documento.cambios_aplicados = None
    documento.revisado = False
    documento.estado_ia = "propuesta" if documento.datos_extraidos else None
    documento.ia_actualizado_en = ahora()
    sesion.add(documento)
    sesion.commit()
    return resultado


def guardar_propuesta(documento: Documento, propuesta: DocumentoExtraido) -> None:
    documento.datos_extraidos = json.dumps(
        propuesta.model_dump(), ensure_ascii=False
    )
