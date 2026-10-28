"""Alta, edicion y seguimiento de citas, y sus requisitos previos."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from sqlmodel import select

from .. import consultas, logica
from ..config import ahora, config, hoy
from ..enums import EstadoEvento, EstadoTransporte, Prioridad, TipoEvento, TipoRequisito
from ..modelos import Evento, Requisito, transporte_inicial
from .comun import (
    PacienteDep,
    SesionDep,
    entero_de,
    fecha_de,
    hora_de,
    render,
    texto,
    volver,
)

router = APIRouter()


def _ia_lista() -> bool:
    from ..ia.base import obtener_analizador

    try:
        return obtener_analizador().disponible()[0]
    except ValueError:
        return False


def _de_quien_sigue(evento: Evento) -> Evento:
    """La cita de la que hereda especialidad y centro lo que salga de esta.

    Despues de una prueba, quien toca es el especialista que la pidio: se
    vuelve a el con el resultado. Detras de una consulta, el mismo que la
    paso. Si la prueba no cuelga de nadie, no hay a quien volver y se queda
    con lo suyo.
    """
    if evento.tipo == TipoEvento.PRUEBA and evento.origen is not None:
        return evento.origen
    return evento


def _centro_del_formulario(
    sesion: SesionDep,
    centro: str,
    nombre_nuevo: str,
    direccion: str,
    telefono: str,
    mapa: str,
    actual: int | None = None,
) -> int | None:
    """El centro elegido en la lista, o el que se acaba de escribir.

    Lo escrito a mano manda: si alguien se molesta en teclear el nombre es
    porque el de la lista no valia. Si ese nombre resulta ser uno que ya
    existe escrito de otra forma, se reutiliza en vez de duplicarlo.

    `centro == "nuevo"` es la opcion "+ Nuevo centro..." del desplegable.
    Si se elige y no se escribe ningun nombre, se queda el centro que ya
    tenia la cita (`actual`): no se borra por haber abierto el alta.
    """
    if nombre_nuevo.strip():
        return consultas.asegurar_centro(
            sesion, nombre_nuevo, telefono, direccion, mapa
        )
    if centro == "nuevo":
        return actual
    return entero_de(centro)


def _buscar(sesion: SesionDep, evento_id: int) -> Evento:
    evento = sesion.get(Evento, evento_id)
    if evento is None:
        raise HTTPException(404, "La cita no existe")
    return evento


def _enum(clase, valor: str, campo: str):
    try:
        return clase(valor)
    except ValueError:
        raise HTTPException(400, f"Valor no valido para {campo}: {valor}")


# --------------------------------------------------------------------------
# Alta
# --------------------------------------------------------------------------


@router.get("/eventos/nuevo")
def formulario_nuevo(
    request: Request,
    sesion: SesionDep,
    paciente_id: PacienteDep,
    centro: int | None = None,
):
    """El formulario de alta. `centro` lo trae el boton de un hospital."""
    pacientes = consultas.listar_pacientes(sesion)
    if not pacientes:
        return volver(
            "/pacientes",
            "Da de alta primero a la persona a la que acompanas.",
        )
    return render(
        request,
        "evento_form.html",
        sesion,
        paciente_id,
        evento=None,
        centros=consultas.listar_centros(sesion),
        centro_elegido=centro,
        areas=consultas.areas_para_elegir(sesion, paciente_id),
        titulo="Nueva cita",
    )


@router.post("/eventos")
def crear(
    sesion: SesionDep,
    titulo: Annotated[str, Form()],
    paciente: Annotated[int, Form()],
    tipo: Annotated[str, Form()] = TipoEvento.CITA,
    estado: Annotated[str, Form()] = EstadoEvento.POR_SOLICITAR,
    especialidad: Annotated[str, Form()] = "",
    centro: Annotated[str, Form()] = "",
    centro_nuevo: Annotated[str, Form()] = "",
    centro_direccion: Annotated[str, Form()] = "",
    centro_telefono: Annotated[str, Form()] = "",
    centro_mapa: Annotated[str, Form()] = "",
    profesional: Annotated[str, Form()] = "",
    ubicacion: Annotated[str, Form()] = "",
    fecha: Annotated[str, Form()] = "",
    hora: Annotated[str, Form()] = "",
    duracion_min: Annotated[str, Form()] = "30",
    solicitada_en: Annotated[str, Form()] = "",
    prioridad: Annotated[str, Form()] = Prioridad.NORMAL,
    transporte: Annotated[str, Form()] = EstadoTransporte.NO_NECESITA,
    transporte_notas: Annotated[str, Form()] = "",
    motivo: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    estado_enum = _enum(EstadoEvento, estado, "estado")

    # Si la persona necesita ambulancia siempre, la cita nace con ella
    # pendiente salvo que se haya elegido otra cosa en el formulario.
    transporte_enum = _enum(EstadoTransporte, transporte, "transporte")
    notas_transporte = texto(transporte_notas)
    if transporte_enum == EstadoTransporte.NO_NECESITA:
        from ..modelos import Paciente, transporte_inicial

        transporte_enum, por_defecto = transporte_inicial(
            sesion.get(Paciente, paciente), especialidad
        )
        notas_transporte = notas_transporte or por_defecto

    evento = Evento(
        paciente_id=paciente,
        titulo=titulo.strip(),
        tipo=_enum(TipoEvento, tipo, "tipo"),
        estado=estado_enum,
        especialidad=texto(especialidad),
        centro_id=_centro_del_formulario(
            sesion, centro, centro_nuevo, centro_direccion, centro_telefono, centro_mapa
        ),
        profesional=texto(profesional),
        ubicacion=texto(ubicacion),
        fecha=fecha_de(fecha),
        hora=hora_de(hora),
        duracion_min=entero_de(duracion_min, 30) or 30,
        solicitada_en=fecha_de(solicitada_en),
        prioridad=_enum(Prioridad, prioridad, "prioridad"),
        transporte=transporte_enum,
        transporte_notas=notas_transporte,
        motivo=texto(motivo),
        notas=texto(notas),
    )

    # Si se da de alta ya como solicitada y no se dijo cuando, se asume hoy:
    # sin esa fecha no se podrian contar los dias de espera despues.
    if estado_enum == EstadoEvento.SOLICITADA and evento.solicitada_en is None:
        evento.solicitada_en = hoy()

    sesion.add(evento)
    sesion.commit()
    sesion.refresh(evento)
    return volver(f"/eventos/{evento.id}", "Cita creada.")


# --------------------------------------------------------------------------
# Detalle y edicion
# --------------------------------------------------------------------------


@router.get("/eventos/{evento_id}")
def detalle(
    request: Request,
    sesion: SesionDep,
    paciente_id: PacienteDep,
    evento_id: int,
):
    evento = _buscar(sesion, evento_id)
    return render(
        request,
        "evento_detalle.html",
        sesion,
        paciente_id,
        ia_lista=_ia_lista(),
        evento=evento,
        destinos=sorted(logica.TRANSICIONES.get(evento.estado, frozenset())),
        estados_transporte=list(EstadoTransporte),
        centros=consultas.listar_centros(sesion),
        # Las demas citas de la persona, para poder decir de cual sale esta.
        citas_hilo=[
            c for c in sesion.exec(
                select(Evento)
                .where(Evento.paciente_id == evento.paciente_id)
                .order_by(Evento.fecha.desc())
            )
            if c.id != evento.id
        ],
        titulo=evento.titulo,
    )


@router.get("/eventos/{evento_id}/editar")
def formulario_editar(
    request: Request,
    sesion: SesionDep,
    paciente_id: PacienteDep,
    evento_id: int,
):
    return render(
        request,
        "evento_form.html",
        sesion,
        paciente_id,
        evento=_buscar(sesion, evento_id),
        centros=consultas.listar_centros(sesion),
        centro_elegido=_buscar(sesion, evento_id).centro_id,
        areas=consultas.areas_para_elegir(sesion, paciente_id),
        titulo="Editar cita",
    )


@router.post("/eventos/{evento_id}")
def actualizar(
    sesion: SesionDep,
    evento_id: int,
    titulo: Annotated[str, Form()],
    paciente: Annotated[int, Form()],
    tipo: Annotated[str, Form()] = TipoEvento.CITA,
    especialidad: Annotated[str, Form()] = "",
    centro: Annotated[str, Form()] = "",
    centro_nuevo: Annotated[str, Form()] = "",
    centro_direccion: Annotated[str, Form()] = "",
    centro_telefono: Annotated[str, Form()] = "",
    centro_mapa: Annotated[str, Form()] = "",
    profesional: Annotated[str, Form()] = "",
    ubicacion: Annotated[str, Form()] = "",
    fecha: Annotated[str, Form()] = "",
    hora: Annotated[str, Form()] = "",
    duracion_min: Annotated[str, Form()] = "30",
    solicitada_en: Annotated[str, Form()] = "",
    prioridad: Annotated[str, Form()] = Prioridad.NORMAL,
    transporte: Annotated[str, Form()] = EstadoTransporte.NO_NECESITA,
    transporte_notas: Annotated[str, Form()] = "",
    motivo: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
    resultado: Annotated[str, Form()] = "",
):
    evento = _buscar(sesion, evento_id)

    evento.titulo = titulo.strip()
    evento.paciente_id = paciente
    evento.tipo = _enum(TipoEvento, tipo, "tipo")
    evento.especialidad = texto(especialidad)
    evento.centro_id = _centro_del_formulario(
        sesion, centro, centro_nuevo, centro_direccion, centro_telefono, centro_mapa,
        actual=evento.centro_id,
    )
    evento.profesional = texto(profesional)
    evento.ubicacion = texto(ubicacion)
    evento.fecha = fecha_de(fecha)
    evento.hora = hora_de(hora)
    evento.duracion_min = entero_de(duracion_min, 30) or 30
    evento.solicitada_en = fecha_de(solicitada_en)
    evento.prioridad = _enum(Prioridad, prioridad, "prioridad")
    evento.transporte = _enum(EstadoTransporte, transporte, "transporte")
    evento.transporte_notas = texto(transporte_notas)
    evento.motivo = texto(motivo)
    evento.notas = texto(notas)
    evento.resultado = texto(resultado)
    evento.actualizado_en = ahora()

    sesion.add(evento)
    sesion.commit()
    return volver(f"/eventos/{evento_id}", "Cambios guardados.")


@router.post("/eventos/{evento_id}/ficha")
def guardar_ficha(
    sesion: SesionDep,
    evento_id: int,
    titulo: Annotated[str, Form()] = "",
    especialidad: Annotated[str, Form()] = "",
    centro: Annotated[str, Form()] = "",
    centro_nuevo: Annotated[str, Form()] = "",
    centro_telefono: Annotated[str, Form()] = "",
    ubicacion: Annotated[str, Form()] = "",
    profesional: Annotated[str, Form()] = "",
    motivo: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
    resultado: Annotated[str, Form()] = "",
    solicitada_en: Annotated[str, Form()] = "",
    destino: Annotated[str, Form()] = "",
):
    """Los datos de una cita, editados desde su propia tarjeta.

    No es el formulario entero de la ficha: ese pide tambien tipo, duracion,
    prioridad y transporte, y mandar solo una parte los borraria. Aqui se
    tocan los campos que se corrigen al vuelo -- el telefono que te dan por
    telefono, la planta, el nombre del medico -- y lo demas se queda como
    estaba.
    """
    evento = _buscar(sesion, evento_id)

    nuevo_titulo = titulo.strip()
    if nuevo_titulo:
        evento.titulo = nuevo_titulo
    evento.especialidad = texto(especialidad)
    # Admite "+ Nuevo centro..." desde la tarjeta, igual que el formulario.
    evento.centro_id = _centro_del_formulario(
        sesion, centro, centro_nuevo, "", centro_telefono, "",
        actual=evento.centro_id,
    )
    evento.ubicacion = texto(ubicacion)
    evento.profesional = texto(profesional)
    evento.motivo = texto(motivo)
    evento.notas = texto(notas)
    evento.resultado = texto(resultado)
    evento.solicitada_en = fecha_de(solicitada_en)
    evento.actualizado_en = ahora()

    sesion.add(evento)
    sesion.commit()
    return volver(destino or f"/eventos/{evento_id}", "Cambios guardados.")


@router.post("/eventos/{evento_id}/estado")
def cambiar_estado(
    sesion: SesionDep,
    evento_id: int,
    estado: Annotated[str, Form()],
    fecha: Annotated[str, Form()] = "",
    hora: Annotated[str, Form()] = "",
    destino: Annotated[str, Form()] = "",
):
    evento = _buscar(sesion, evento_id)
    nuevo = _enum(EstadoEvento, estado, "estado")

    # La fecha del formulario, si viene, pisa a la que ya hubiera: es el
    # caso tipico de "nos han llamado, la cita es el dia X".
    fecha_nueva = fecha_de(fecha) or evento.fecha

    try:
        cambio = logica.aplicar_cambio_estado(
            evento.estado, nuevo, fecha_nueva, evento.solicitada_en, hoy()
        )
    except ValueError as error:
        raise HTTPException(400, str(error))

    evento.estado = cambio.estado
    evento.fecha = cambio.fecha
    evento.solicitada_en = cambio.solicitada_en
    if cambio.fecha is not None:
        nueva_hora = hora_de(hora)
        if nueva_hora is not None:
            evento.hora = nueva_hora
    else:
        evento.hora = None
    evento.actualizado_en = ahora()

    sesion.add(evento)
    sesion.commit()

    mensaje = cambio.aviso or f"Cita marcada como {nuevo.value.replace('_', ' ')}."
    # Al confirmar con fecha, el aviso repite lo que ha quedado apuntado
    # ("... confirmada: lunes 16 de noviembre de 2026 a las 10:30"): se ve
    # al momento si se ha tecleado mal el dia o la hora.
    if cambio.estado == EstadoEvento.CONFIRMADA and evento.fecha:
        cuando = (
            f"{logica.nombre_dia(evento.fecha)} {evento.fecha.day} de "
            f"{logica.nombre_mes(evento.fecha.month)} de {evento.fecha.year}"
        )
        if evento.hora:
            cuando += f" a las {evento.hora.strftime('%H:%M')}"
        mensaje = f"«{evento.titulo}» confirmada: {cuando}."
        if cambio.aviso:
            mensaje += f" {cambio.aviso}"
    # `destino` deja volver a la cita desde la que se edito, que es donde
    # estaba la persona: una prueba se pone al dia desde la cita para la
    # que hace falta, sin pasar por su propia ficha.
    return volver(destino or f"/eventos/{evento_id}", mensaje)


@router.post("/eventos/{evento_id}/al-dia")
def poner_al_dia(
    sesion: SesionDep,
    evento_id: int,
    estado: Annotated[str, Form()] = "",
    fecha: Annotated[str, Form()] = "",
    hora: Annotated[str, Form()] = "",
    centro: Annotated[str, Form()] = "",
    centro_nuevo: Annotated[str, Form()] = "",
    transporte: Annotated[str, Form()] = "",
    transporte_hora: Annotated[str, Form()] = "",
    destino: Annotated[str, Form()] = "",
):
    """Pone al dia una cita entera desde otra pantalla.

    Cuando llaman para dar la fecha de una prueba, en la misma llamada se
    sabe todo: el dia, la hora, donde es y si hace falta ambulancia.
    Repartirlo en cuatro formularios obligaba a dar cuatro vueltas.
    """
    evento = _buscar(sesion, evento_id)

    nuevo_centro = _centro_del_formulario(sesion, centro, centro_nuevo, "", "", "")
    if nuevo_centro is not None:
        evento.centro_id = nuevo_centro

    if transporte:
        evento.transporte = _enum(EstadoTransporte, transporte, "transporte")
    evento.transporte_hora = hora_de(transporte_hora) or evento.transporte_hora

    if estado:
        nuevo_estado = _enum(EstadoEvento, estado, "estado")
        fecha_nueva = fecha_de(fecha) or evento.fecha
        try:
            cambio = logica.aplicar_cambio_estado(
                evento.estado, nuevo_estado, fecha_nueva, evento.solicitada_en, hoy()
            )
        except ValueError as error:
            raise HTTPException(400, str(error))
        evento.estado = cambio.estado
        evento.fecha = cambio.fecha
        evento.solicitada_en = cambio.solicitada_en
        if cambio.fecha is not None:
            nueva_hora = hora_de(hora)
            if nueva_hora is not None:
                evento.hora = nueva_hora
        else:
            evento.hora = None

    evento.actualizado_en = ahora()
    sesion.add(evento)
    sesion.commit()
    return volver(destino or f"/eventos/{evento_id}", f"«{evento.titulo}» al día.")


@router.post("/eventos/{evento_id}/transporte")
def cambiar_transporte(
    sesion: SesionDep,
    evento_id: int,
    transporte: Annotated[str, Form()],
    destino: Annotated[str, Form()] = "",
    hora_paso: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    """Cambio rapido de la ambulancia, sin abrir el formulario entero."""
    evento = _buscar(sesion, evento_id)
    evento.transporte = _enum(EstadoTransporte, transporte, "transporte")
    evento.transporte_hora = hora_de(hora_paso)
    if notas.strip():
        evento.transporte_notas = texto(notas)
    evento.actualizado_en = ahora()
    sesion.add(evento)
    sesion.commit()
    return volver(destino or f"/eventos/{evento_id}")


@router.post("/eventos/{evento_id}/borrar")
def borrar(
    sesion: SesionDep,
    evento_id: int,
    destino: Annotated[str, Form()] = "",
):
    evento = _buscar(sesion, evento_id)
    titulo = evento.titulo
    sesion.delete(evento)
    sesion.commit()
    return volver(destino or "/citas?etapa=fecha", f"Eliminada «{titulo}».")


# --------------------------------------------------------------------------
# Requisitos previos
# --------------------------------------------------------------------------


@router.post("/eventos/{evento_id}/pendiente")
def anadir_pendiente(
    sesion: SesionDep,
    evento_id: int,
    descripcion: Annotated[str, Form()],
    clase: Annotated[str, Form()] = "llevar",
    offset_dias: Annotated[str, Form()] = "",
    estado: Annotated[str, Form()] = EstadoEvento.SOLICITADA,
    tipo: Annotated[str, Form()] = TipoEvento.PRUEBA,
    fecha: Annotated[str, Form()] = "",
    hora: Annotated[str, Form()] = "",
    destino: Annotated[str, Form()] = "",
):
    """Anade algo que hace falta para una cita, sea de la clase que sea.

    Un solo formulario para los tres casos, porque para quien lo apunta son
    lo mismo -- cosas que faltan para esa cita -- y elegir entre tres
    pantallas distintas era pedirle que supiera como lo guarda la aplicacion.
    """
    evento = _buscar(sesion, evento_id)
    vuelta = destino or f"/eventos/{evento_id}"
    texto_limpio = descripcion.strip()
    if not texto_limpio:
        return volver(vuelta)

    if clase == "prueba":
        # Es una cita en si misma: se crea enlazada y con su plazo.
        estado_enum = _enum(EstadoEvento, estado, EstadoEvento.SOLICITADA)
        from ..modelos import Paciente

        # Una prueba ya hecha no hay que pedirla ni llevarla a ningun sitio:
        # se apunta para que conste que ese requisito esta cubierto.
        ya_hecha = estado_enum == EstadoEvento.REALIZADA
        transporte, notas = transporte_inicial(
            sesion.get(Paciente, evento.paciente_id), evento.especialidad
        )
        if ya_hecha:
            transporte, notas = EstadoTransporte.NO_NECESITA, None
        sesion.add(
            Evento(
                paciente_id=evento.paciente_id,
                titulo=texto_limpio,
                tipo=_enum(TipoEvento, tipo, TipoEvento.PRUEBA),
                estado=estado_enum,
                especialidad=evento.especialidad,
                centro_id=evento.centro_id,
                antes_de_id=evento.id,
                fecha=fecha_de(fecha),
                hora=hora_de(hora),
                solicitada_en=hoy() if estado_enum == EstadoEvento.SOLICITADA else None,
                transporte=transporte,
                transporte_notas=notas,
            )
        )
    else:
        sesion.add(
            Requisito(
                evento_id=evento.id,
                descripcion=texto_limpio,
                tipo=TipoRequisito.OTRO,
                en_la_cita=(clase == "pedir"),
                offset_dias=0 if clase == "pedir" else entero_de(offset_dias),
            )
        )

    sesion.commit()
    return volver(vuelta, "Añadido.")


@router.post("/eventos/{evento_id}/requisitos")
def anadir_requisito(
    sesion: SesionDep,
    evento_id: int,
    descripcion: Annotated[str, Form()],
    tipo: Annotated[str, Form()] = TipoRequisito.OTRO,
    en_la_cita: Annotated[str, Form()] = "",
    offset_dias: Annotated[str, Form()] = "",
    fecha_limite_manual: Annotated[str, Form()] = "",
    notas: Annotated[str, Form()] = "",
):
    _buscar(sesion, evento_id)
    sesion.add(
        Requisito(
            evento_id=evento_id,
            descripcion=descripcion.strip(),
            tipo=_enum(TipoRequisito, tipo, "tipo"),
            en_la_cita=bool(en_la_cita),
            offset_dias=entero_de(offset_dias),
            fecha_limite_manual=fecha_de(fecha_limite_manual),
            notas=texto(notas),
        )
    )
    sesion.commit()
    return volver(f"/eventos/{evento_id}", "Requisito anadido.")


@router.post("/requisitos/{requisito_id}/alternar")
def alternar_requisito(
    sesion: SesionDep, requisito_id: int, destino: Annotated[str, Form()] = "/"
):
    requisito = sesion.get(Requisito, requisito_id)
    if requisito is None:
        raise HTTPException(404, "El requisito no existe")

    requisito.hecho = not requisito.hecho
    requisito.hecho_en = hoy() if requisito.hecho else None
    sesion.add(requisito)
    sesion.commit()
    return volver(destino)


@router.post("/requisitos/{requisito_id}/editar")
def editar_requisito(
    sesion: SesionDep,
    requisito_id: int,
    descripcion: Annotated[str, Form()],
    offset_dias: Annotated[str, Form()] = "",
    fecha_limite_manual: Annotated[str, Form()] = "",
    destino: Annotated[str, Form()] = "",
):
    """Corrige lo que pone un preparativo, y para cuando hace falta.

    Casi todo se apunta de oido por telefono ("llevar el informe") y luego
    hay que matizarlo ("el informe del alta de octubre"). Borrarlo y
    escribirlo otra vez perdia lo que ya estuviera marcado y el plazo.
    """
    requisito = sesion.get(Requisito, requisito_id)
    if requisito is None:
        raise HTTPException(404, "El requisito no existe")

    texto_nuevo = descripcion.strip()
    if texto_nuevo:
        requisito.descripcion = texto_nuevo
    # Lo que se pide en la consulta se hace ese dia por definicion: ahi no
    # hay plazo que tocar y el formulario ni lo ensena.
    if not requisito.en_la_cita:
        requisito.offset_dias = entero_de(offset_dias)
        requisito.fecha_limite_manual = fecha_de(fecha_limite_manual)
    sesion.add(requisito)
    sesion.commit()
    return volver(destino or f"/eventos/{requisito.evento_id}", "Cambiado.")


@router.post("/requisitos/{requisito_id}/momento")
def cambiar_momento(sesion: SesionDep, requisito_id: int):
    """Pasa algo de "antes de la cita" a "pedir en la consulta", o al reves.

    Se apunta sobre la marcha y luego uno cae en que era lo otro: "entregar
    el informe" se lleva, pero "pedir que repitan la analitica" se dice
    alli. Cambiarlo tiene que costar un clic, no borrar y reescribir.
    """
    requisito = sesion.get(Requisito, requisito_id)
    if requisito is None:
        raise HTTPException(404, "El requisito no existe")

    requisito.en_la_cita = not requisito.en_la_cita
    # Lo que se pide en la consulta se hace ese dia por definicion: una
    # antelacion propia no significa nada.
    if requisito.en_la_cita:
        requisito.offset_dias = 0
        requisito.fecha_limite_manual = None
    sesion.add(requisito)
    sesion.commit()
    destino = f"/eventos/{requisito.evento_id}"
    donde = "lo que hay que pedir en la consulta" if requisito.en_la_cita else "lo que hay que llevar"
    return volver(destino, f"Movido a {donde}.")


@router.post("/requisitos/{requisito_id}/mover")
def mover_requisito(
    sesion: SesionDep,
    requisito_id: int,
    evento: Annotated[str, Form()] = "",
):
    """Pasa un preparativo a otra cita.

    Hace falta cuando uno se da cuenta despues: la ambulancia se apunto en
    la consulta del cabecera y en realidad era para la del traumatologo. Sin
    esto habia que borrarlo y volver a escribirlo entero.

    La fecha limite no se guarda, se calcula de la cita, asi que al mover el
    preparativo se recoloca solo.
    """
    requisito = sesion.get(Requisito, requisito_id)
    if requisito is None:
        raise HTTPException(404, "El requisito no existe")

    origen_id = requisito.evento_id
    destino_id = entero_de(evento)
    if destino_id is None or destino_id == origen_id:
        return volver(f"/eventos/{origen_id}")

    destino = sesion.get(Evento, destino_id)
    if destino is None or destino.paciente_id != requisito.evento.paciente_id:
        raise HTTPException(400, "Esa cita no existe o es de otra persona.")

    # Una fecha puesta a mano estaba atada a la cita de la que viene. Se
    # convierte en la antelacion equivalente para que se recoloque sola.
    antelacion = logica.antelacion_al_mover(
        requisito.fecha_limite_manual,
        requisito.evento.fecha if requisito.evento else None,
    )
    if antelacion is not None:
        requisito.offset_dias = antelacion
        requisito.fecha_limite_manual = None

    requisito.evento_id = destino.id
    sesion.add(requisito)
    sesion.commit()
    return volver(
        f"/eventos/{destino.id}",
        f"Preparativo movido a «{destino.titulo}».",
    )


@router.post("/requisitos/{requisito_id}/borrar")
def borrar_requisito(
    sesion: SesionDep,
    requisito_id: int,
    destino: Annotated[str, Form()] = "",
):
    requisito = sesion.get(Requisito, requisito_id)
    if requisito is None:
        raise HTTPException(404, "El requisito no existe")

    evento_id = requisito.evento_id
    descripcion = requisito.descripcion
    sesion.delete(requisito)
    sesion.commit()
    return volver(
        destino or f"/eventos/{evento_id}", f"Eliminado «{descripcion}»."
    )


@router.post("/eventos/{evento_id}/origen")
def cambiar_origen(
    sesion: SesionDep,
    evento_id: int,
    origen: Annotated[str, Form()] = "",
):
    """Dice de que cita sale esta, o deshace el enlace.

    Hace falta porque muchas veces las dos citas ya existen cuando uno cae
    en la cuenta de que una salio de la otra: la consulta pide una prueba y
    la citacion de esa prueba llega semanas despues.
    """
    evento = _buscar(sesion, evento_id)
    origen_id = entero_de(origen)

    if origen_id is None:
        evento.evento_padre_id = None
    else:
        otro = sesion.get(Evento, origen_id)
        if otro is None or otro.paciente_id != evento.paciente_id:
            raise HTTPException(400, "Esa cita no existe o es de otra persona.")

        padres = {
            e.id: e.evento_padre_id
            for e in sesion.exec(
                select(Evento).where(Evento.paciente_id == evento.paciente_id)
            )
        }
        if logica.crearia_ciclo(evento.id, origen_id, padres):
            return volver(
                f"/eventos/{evento_id}",
                "No se puede: esa cita ya sale de esta, y se haria un bucle.",
            )
        evento.evento_padre_id = origen_id

    evento.actualizado_en = ahora()
    sesion.add(evento)
    sesion.commit()
    return volver(f"/eventos/{evento_id}", "Hilo actualizado.")


@router.post("/eventos/{evento_id}/cerrar")
def cerrar(
    sesion: SesionDep,
    evento_id: int,
    resultado: Annotated[str, Form()] = "",
    derivada_titulo: Annotated[str, Form()] = "",
    derivada_tipo: Annotated[str, Form()] = TipoEvento.PRUEBA,
    destino: Annotated[str, Form()] = "",
):
    """Da una cita por hecha y, si salio algo de ella, lo crea enlazado.

    Es el mismo gesto que se hace al salir de la consulta: apuntar que han
    dicho y que han mandado. Separarlo en dos pantallas hacia que lo segundo
    no se apuntara nunca.
    """
    evento = _buscar(sesion, evento_id)
    evento.estado = EstadoEvento.REALIZADA
    if resultado.strip():
        evento.resultado = texto(resultado)
    evento.actualizado_en = ahora()
    sesion.add(evento)

    aviso = f"«{evento.titulo}» marcada como realizada."
    if derivada_titulo.strip():
        from ..modelos import Paciente, transporte_inicial

        transporte, notas_transporte = transporte_inicial(
            sesion.get(Paciente, evento.paciente_id), evento.especialidad
        )
        derivada = Evento(
            paciente_id=evento.paciente_id,
            titulo=derivada_titulo.strip(),
            tipo=_enum(TipoEvento, derivada_tipo, TipoEvento.PRUEBA),
            estado=EstadoEvento.POR_SOLICITAR,
            # De quien es la cita que sale de aqui. Tras una prueba se
            # vuelve al especialista que la pidio, no al servicio que la
            # hizo: la RMN la hace Radiologia, pero quien la lee y decide
            # es Traumatologia.
            especialidad=_de_quien_sigue(evento).especialidad,
            centro_id=_de_quien_sigue(evento).centro_id,
            evento_padre_id=evento.id,
            transporte=transporte,
            transporte_notas=notas_transporte,
        )
        sesion.add(derivada)
        aviso += f" Falta pedir «{derivada.titulo}»."

    sesion.commit()
    return volver(destino or f"/eventos/{evento_id}", aviso)


@router.post("/eventos/{evento_id}/antes-de")
def cambiar_antes_de(
    sesion: SesionDep,
    evento_id: int,
    evento: Annotated[str, Form()] = "",
):
    """Dice para que cita hace falta tener esto hecho.

    No es lo mismo que "de donde sale": aquello cuenta el pasado y esto
    pone un plazo. Es lo que permite reclamar a tiempo una prueba que sigue
    sin fecha cuando la cita en la que hace falta ya se acerca.
    """
    esta = _buscar(sesion, evento_id)
    objetivo_id = entero_de(evento)

    if objetivo_id is None:
        esta.antes_de_id = None
    else:
        if objetivo_id == esta.id:
            return volver(f"/eventos/{evento_id}", "Una cita no va antes de si misma.")
        objetivo = sesion.get(Evento, objetivo_id)
        if objetivo is None or objetivo.paciente_id != esta.paciente_id:
            raise HTTPException(400, "Esa cita no existe o es de otra persona.")
        esta.antes_de_id = objetivo.id

    esta.actualizado_en = ahora()
    sesion.add(esta)
    sesion.commit()
    return volver(f"/eventos/{evento_id}", "Actualizado.")


@router.post("/eventos/{evento_id}/derivada")
def enlazar_derivada(
    sesion: SesionDep,
    evento_id: int,
    evento: Annotated[str, Form()] = "",
):
    """Dice que una cita que YA existe sale de esta.

    Es el mismo enlace que "de donde viene", visto desde el otro lado: a
    veces uno esta en la consulta y quiere colgar de ella la prueba que
    apunto la semana pasada, sin ir a buscarla.
    """
    origen = _buscar(sesion, evento_id)
    hija_id = entero_de(evento)
    if hija_id is None or hija_id == origen.id:
        return volver(f"/eventos/{evento_id}")

    hija = sesion.get(Evento, hija_id)
    if hija is None or hija.paciente_id != origen.paciente_id:
        raise HTTPException(400, "Esa cita no existe o es de otra persona.")

    padres = {
        e.id: e.evento_padre_id
        for e in sesion.exec(
            select(Evento).where(Evento.paciente_id == origen.paciente_id)
        )
    }
    if logica.crearia_ciclo(hija.id, origen.id, padres):
        return volver(
            f"/eventos/{evento_id}",
            "No se puede: esta cita ya sale de esa, y se haria un bucle.",
        )

    hija.evento_padre_id = origen.id
    hija.actualizado_en = ahora()
    sesion.add(hija)
    sesion.commit()
    return volver(f"/eventos/{evento_id}", f"«{hija.titulo}» ahora sale de esta cita.")


@router.post("/eventos/{evento_id}/derivar")
def derivar(
    sesion: SesionDep,
    evento_id: int,
    titulo: Annotated[str, Form()],
    tipo: Annotated[str, Form()] = TipoEvento.PRUEBA,
    especialidad: Annotated[str, Form()] = "",
    centro: Annotated[str, Form()] = "",
    centro_nuevo: Annotated[str, Form()] = "",
    centro_direccion: Annotated[str, Form()] = "",
    centro_telefono: Annotated[str, Form()] = "",
    centro_mapa: Annotated[str, Form()] = "",
    estado: Annotated[str, Form()] = EstadoEvento.POR_SOLICITAR,
):
    """Crea la prueba o la revision que sale de una cita, ya enlazada.

    De una consulta salen pruebas y revisiones. Darlas de alta desde la
    cita que las origina deja escrito el porque, que es lo que luego no
    hay manera de reconstruir.
    """
    origen = _buscar(sesion, evento_id)
    estado_enum = _enum(EstadoEvento, estado, "estado")

    from ..modelos import Paciente, transporte_inicial

    transporte_enum, notas_transporte = transporte_inicial(
        sesion.get(Paciente, origen.paciente_id),
        texto(especialidad) or origen.especialidad,
    )

    derivada = Evento(
        paciente_id=origen.paciente_id,
        titulo=titulo.strip(),
        tipo=_enum(TipoEvento, tipo, "tipo"),
        estado=estado_enum,
        # Sin decir otra cosa, hereda la especialidad y el centro de la cita
        # de la que sale: casi siempre es el mismo medico quien la pide.
        especialidad=texto(especialidad) or origen.especialidad,
        centro_id=_centro_del_formulario(
            sesion, centro, centro_nuevo, centro_direccion, centro_telefono, centro_mapa
        ) or origen.centro_id,
        evento_padre_id=origen.id,
        transporte=transporte_enum,
        transporte_notas=notas_transporte,
        solicitada_en=hoy() if estado_enum == EstadoEvento.SOLICITADA else None,
    )
    sesion.add(derivada)
    sesion.commit()
    sesion.refresh(derivada)
    return volver(f"/eventos/{derivada.id}")
