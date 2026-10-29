#!/usr/bin/env python3
"""Rellena la base de datos con datos de ejemplo, inventados.

    python3 scripts/demo.py

Sirve para ver como se comporta la aplicacion antes de meter datos reales, y
para que alguien que clone el repositorio entienda de que va sin tener que
inventarse un caso.

Se niega a ejecutarse si ya hay datos, para no ensuciar una base real.
"""

from __future__ import annotations

import sys
from datetime import date, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.config import config, hoy  # noqa: E402
from app.db import crear_tablas, motor  # noqa: E402
from app.enums import (  # noqa: E402
    EstadoEvento,
    EstadoTramite,
    Prioridad,
    TipoEvento,
    TipoRequisito,
)
from app.modelos import (  # noqa: E402
    Centro,
    Documento,
    Evento,
    Paciente,
    PasoTramite,
    Requisito,
    Tramite,
)


def pdf_sencillo(titulo: str, texto: str) -> bytes:
    """Un PDF de una pagina con el titulo y el texto, sin librerias.

    Los documentos de la demo eran solo la ficha, sin fichero: no se podian
    ver ni tenian miniatura. Con esto la demo se ensena entera (y sirve para
    las capturas del README). Fuente Helvetica estandar del PDF: el texto va
    en latin-1 (los de la demo no llevan tildes).
    """
    def esc(t: str) -> str:
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    lineas = [f"BT /F1 18 Tf 72 760 Td ({esc(titulo)}) Tj ET"]
    y = 720
    for parrafo in (texto or "").split("\n"):
        lineas.append(f"BT /F1 12 Tf 72 {y} Td ({esc(parrafo)}) Tj ET")
        y -= 18
    lineas.append("BT /F1 9 Tf 72 60 Td (Documento de ejemplo generado por scripts/demo.py) Tj ET")
    contenido = "\n".join(lineas).encode("latin-1", "replace")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(contenido)).encode() + b" >>\nstream\n" + contenido + b"\nendstream",
    ]
    salida = bytearray(b"%PDF-1.4\n")
    posiciones = []
    for n, obj in enumerate(objetos, 1):
        posiciones.append(len(salida))
        salida += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    for pos in posiciones:
        salida += f"{pos:010d} 00000 n \n".encode()
    salida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
        f"startxref\n{inicio_xref}\n%%EOF\n"
    ).encode()
    return bytes(salida)


def main() -> int:
    crear_tablas()

    with Session(motor) as sesion:
        if sesion.exec(select(Paciente)).first():
            print("Ya hay datos en la base. No se toca nada.")
            print("Borra data/medicos.db si quieres empezar de cero.")
            return 1

        h = hoy()

        paciente = Paciente(
            nombre="Ejemplo Apellido Apellido",
            fecha_nacimiento=date(1948, 6, 12),
            tarjeta_sanitaria="0000000000",
            notas="Datos de ejemplo. Borra este paciente antes de usar la "
            "aplicacion de verdad.",
        )
        sesion.add(paciente)
        sesion.commit()
        sesion.refresh(paciente)

        hospital = Centro(
            nombre="Hospital Comarcal",
            direccion="Avenida de Ejemplo, 1",
            telefono="900000001",
        )
        centro_salud = Centro(
            nombre="Centro de Salud del barrio",
            direccion="Calle de Ejemplo, 5",
            telefono="900000002",
        )
        sesion.add(hospital)
        sesion.add(centro_salud)
        sesion.commit()
        sesion.refresh(hospital)
        sesion.refresh(centro_salud)

        # 1. Cita confirmada con analitica previa: el caso que justifica
        #    toda la maquinaria de requisitos con antelacion.
        digestivo = Evento(
            paciente_id=paciente.id,
            titulo="Consulta de Digestivo",
            tipo=TipoEvento.CITA,
            estado=EstadoEvento.CONFIRMADA,
            especialidad="Digestivo",
            centro_id=hospital.id,
            ubicacion="Planta 2, consulta 7",
            fecha=h + timedelta(days=20),
            hora=time(10, 30),
            solicitada_en=h - timedelta(days=45),
            motivo="Molestias abdominales persistentes",
        )
        sesion.add(digestivo)
        sesion.commit()
        sesion.refresh(digestivo)

        sesion.add(
            Requisito(
                evento_id=digestivo.id,
                tipo=TipoRequisito.ANALITICA,
                descripcion="Analitica de sangre en el centro de salud",
                offset_dias=15,
                notas="Pedir el volante al medico de cabecera antes.",
            )
        )
        sesion.add(
            Requisito(
                evento_id=digestivo.id,
                tipo=TipoRequisito.AYUNAS,
                descripcion="Acudir en ayunas de 8 horas",
                offset_dias=0,
            )
        )
        sesion.add(
            Requisito(
                evento_id=digestivo.id,
                tipo=TipoRequisito.DOCUMENTACION,
                descripcion="Llevar los informes de traumatologia",
                offset_dias=1,
            )
        )

        # 2. Cita pedida hace mucho que sigue sin fecha: aparece en la sala
        #    de espera marcada para reclamar.
        sesion.add(
            Evento(
                paciente_id=paciente.id,
                titulo="Ecografia abdominal",
                tipo=TipoEvento.PRUEBA,
                estado=EstadoEvento.SOLICITADA,
                especialidad="Radiologia",
                centro_id=hospital.id,
                solicitada_en=h - timedelta(days=62),
                motivo="Solicitada en la consulta de digestivo. "
                "Dijeron que avisarian por telefono.",
            )
        )

        # 3. Cita pedida hace poco: todavia no toca reclamar.
        sesion.add(
            Evento(
                paciente_id=paciente.id,
                titulo="Revision de Traumatologia",
                tipo=TipoEvento.REVISION,
                estado=EstadoEvento.SOLICITADA,
                especialidad="Traumatologia",
                centro_id=hospital.id,
                solicitada_en=h - timedelta(days=8),
            )
        )

        # 4. Cita que ni siquiera se ha pedido.
        sesion.add(
            Evento(
                paciente_id=paciente.id,
                titulo="Cita con el medico de cabecera",
                tipo=TipoEvento.CITA,
                estado=EstadoEvento.POR_SOLICITAR,
                especialidad="Medicina de familia",
                centro_id=centro_salud.id,
                prioridad=Prioridad.ALTA,
                motivo="Pedir volante para la analitica y renovar recetas",
            )
        )

        # 5. Cita ya pasada y cerrada, con su resultado anotado.
        sesion.add(
            Evento(
                paciente_id=paciente.id,
                titulo="Consulta de Traumatologia",
                tipo=TipoEvento.CITA,
                estado=EstadoEvento.REALIZADA,
                especialidad="Traumatologia",
                centro_id=hospital.id,
                fecha=h - timedelta(days=30),
                hora=time(12, 0),
                resultado="Artrosis de rodilla. Pauta rehabilitacion y "
                "revision en seis meses. Pide ecografia abdominal por las "
                "molestias que comento.",
            )
        )

        # 6. Cita pasada sin cerrar: la portada avisa de que hay que anotar
        #    el resultado.
        sesion.add(
            Evento(
                paciente_id=paciente.id,
                titulo="Analitica de control",
                tipo=TipoEvento.PRUEBA,
                estado=EstadoEvento.CONFIRMADA,
                especialidad="Analisis clinicos",
                centro_id=centro_salud.id,
                fecha=h - timedelta(days=5),
                hora=time(8, 15),
            )
        )

        # 7. Tramite administrativo con pasos.
        dependencia = Tramite(
            paciente_id=paciente.id,
            titulo="Solicitud de reconocimiento de dependencia",
            organismo="Servicios Sociales",
            estado=EstadoTramite.EN_CURSO,
            prioridad=Prioridad.ALTA,
            iniciado_en=h - timedelta(days=20),
            fecha_limite=h + timedelta(days=10),
            notas="Presentar en el registro del ayuntamiento con cita previa.",
        )
        sesion.add(dependencia)
        sesion.commit()
        sesion.refresh(dependencia)

        pasos = [
            ("Descargar y rellenar el formulario oficial", True, None),
            ("Pedir el informe de salud al medico de cabecera", False, 5),
            ("Reunir el certificado de empadronamiento", False, 7),
            ("Presentar la solicitud en el registro", False, 10),
        ]
        for orden, (descripcion, hecho, dias) in enumerate(pasos):
            sesion.add(
                PasoTramite(
                    tramite_id=dependencia.id,
                    descripcion=descripcion,
                    orden=orden,
                    hecho=hecho,
                    hecho_en=h - timedelta(days=15) if hecho else None,
                    fecha_limite=h + timedelta(days=dias) if dias else None,
                )
            )

        sesion.commit()

        # 8. Documentos ya archivados, con el nombre normalizado que se les
        #    pone al procesarlos: fecha del documento, especialidad y tipo.
        #    Solo son registros de ejemplo: no hay ficheros detras.
        def buscar(titulo: str) -> Evento | None:
            return sesion.exec(
                select(Evento).where(Evento.titulo == titulo)
            ).first()

        documentos = [
            (
                h - timedelta(days=30),
                "traumatologia_informe-consulta",
                "Informe de la consulta de Traumatologia",
                "Consulta de Traumatologia",
                "Diagnostico: artrosis de rodilla. Rehabilitacion y revision "
                "en seis meses. Se solicita ecografia abdominal.",
            ),
            (
                h - timedelta(days=45),
                "digestivo_citacion",
                "Citacion para la consulta de Digestivo",
                "Consulta de Digestivo",
                "Aportar analitica realizada como maximo 15 dias antes. "
                "Acudir en ayunas de 8 horas.",
            ),
            (
                h - timedelta(days=62),
                "radiologia_solicitud-ecografia",
                "Solicitud de ecografia abdominal",
                "Ecografia abdominal",
                "Pendiente de asignar fecha. Se avisara telefonicamente.",
            ),
            (
                h - timedelta(days=20),
                "dependencia_formulario-solicitud",
                "Formulario de solicitud de dependencia",
                None,
                "Solicitud de reconocimiento de la situacion de dependencia.",
            ),
        ]
        for fecha, nombre, titulo, cita, texto in documentos:
            archivo = f"{fecha.isoformat()}_{nombre}.pdf"
            # El fichero de verdad, para poder verlo y tener miniatura.
            destino = config.dir_documentos / "archivo" / archivo
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(pdf_sencillo(titulo, texto))
            documento = Documento(
                    paciente_id=paciente.id,
                    nombre_archivo=archivo,
                    ruta_relativa=f"archivo/{archivo}",
                    mime="application/pdf",
                    fecha_documento=fecha,
                    titulo=titulo,
                    texto=texto,
                    revisado=True,
                )
            # La relacion admite varias citas por documento.
            evento_asociado = buscar(cita) if cita else None
            if evento_asociado is not None:
                documento.eventos.append(evento_asociado)
            sesion.add(documento)

        sesion.commit()

    print("Datos de ejemplo creados.")
    print("Arranca la aplicacion y entra en http://localhost:8080")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
