"""Pruebas del generador de .ics."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time

from app.ics import EventoICS, generar_ics

GENERADO_EN = datetime(2026, 3, 17, 12, 0, 0)


def _desplegar(ics: str) -> str:
    """Deshace el plegado de lineas para poder buscar valores completos."""
    return ics.replace("\r\n ", "")


class TestGenerarICS(unittest.TestCase):
    def test_calendario_vacio_sigue_siendo_valido(self):
        ics = generar_ics([], generado_en=GENERADO_EN)
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(ics.endswith("END:VCALENDAR\r\n"))
        self.assertIn("VERSION:2.0", ics)

    def test_todas_las_lineas_terminan_en_crlf(self):
        ics = generar_ics(
            [EventoICS(uid="a@medicos", titulo="Cita", fecha=date(2026, 4, 1))],
            generado_en=GENERADO_EN,
        )
        self.assertNotIn("\n", ics.replace("\r\n", ""))

    def test_cita_con_hora(self):
        ics = generar_ics(
            [
                EventoICS(
                    uid="evento-1@medicos",
                    titulo="Traumatologo",
                    fecha=date(2026, 4, 1),
                    hora=time(9, 30),
                    duracion_min=30,
                    lugar="Hospital",
                )
            ],
            generado_en=GENERADO_EN,
        )
        self.assertIn("DTSTART:20260401T093000", ics)
        self.assertIn("DTEND:20260401T100000", ics)
        self.assertIn("LOCATION:Hospital", ics)
        # Hora flotante: sin sufijo Z en DTSTART.
        self.assertNotIn("DTSTART:20260401T093000Z", ics)

    def test_la_duracion_puede_cruzar_la_medianoche(self):
        ics = generar_ics(
            [
                EventoICS(
                    uid="e@medicos",
                    titulo="Prueba larga",
                    fecha=date(2026, 4, 1),
                    hora=time(23, 30),
                    duracion_min=60,
                )
            ],
            generado_en=GENERADO_EN,
        )
        self.assertIn("DTEND:20260402T003000", ics)

    def test_cita_sin_hora_es_de_dia_completo(self):
        ics = generar_ics(
            [
                EventoICS(
                    uid="evento-2@medicos",
                    titulo="Analitica",
                    fecha=date(2026, 4, 1),
                )
            ],
            generado_en=GENERADO_EN,
        )
        self.assertIn("DTSTART;VALUE=DATE:20260401", ics)
        # DTEND es exclusivo: el dia siguiente.
        self.assertIn("DTEND;VALUE=DATE:20260402", ics)

    def test_escapa_comas_y_puntoycoma(self):
        ics = generar_ics(
            [
                EventoICS(
                    uid="e@medicos",
                    titulo="Cita: digestivo, planta 3; consulta 12",
                    fecha=date(2026, 4, 1),
                )
            ],
            generado_en=GENERADO_EN,
        )
        plano = _desplegar(ics)
        self.assertIn(
            "SUMMARY:Cita: digestivo\\, planta 3\\; consulta 12", plano
        )

    def test_escapa_saltos_de_linea(self):
        ics = generar_ics(
            [
                EventoICS(
                    uid="e@medicos",
                    titulo="Cita",
                    fecha=date(2026, 4, 1),
                    descripcion="Traer informes.\nVenir en ayunas.",
                )
            ],
            generado_en=GENERADO_EN,
        )
        plano = _desplegar(ics)
        self.assertIn(
            "DESCRIPTION:Traer informes.\\nVenir en ayunas.", plano
        )

    def test_las_lineas_no_pasan_de_75_octetos(self):
        ics = generar_ics(
            [
                EventoICS(
                    uid="e@medicos",
                    titulo="Revision de traumatologia con el doctor "
                    "en el hospital comarcal de la provincia",
                    fecha=date(2026, 4, 1),
                    descripcion="Descripcion muy larga " * 20,
                )
            ],
            generado_en=GENERADO_EN,
        )
        for linea in ics.split("\r\n"):
            with self.subTest(linea=linea[:40]):
                self.assertLessEqual(len(linea.encode("utf-8")), 75)

    def test_el_plegado_no_parte_caracteres_multibyte(self):
        # Titulo largo lleno de acentos: el corte cae en medio de un
        # caracter de dos bytes si se mide en caracteres en vez de octetos.
        titulo = "Revision cardiologia " + "n" * 20 + "aeiou" * 12
        titulo = titulo.replace("n", "ñ").replace("a", "á")
        ics = generar_ics(
            [EventoICS(uid="e@medicos", titulo=titulo, fecha=date(2026, 4, 1))],
            generado_en=GENERADO_EN,
        )
        # Si el plegado partiese un caracter, esto lanzaria al decodificar.
        ics.encode("utf-8").decode("utf-8")
        for linea in ics.split("\r\n"):
            self.assertLessEqual(len(linea.encode("utf-8")), 75)
        # Y el titulo debe reconstruirse intacto al deshacer el plegado.
        self.assertIn(f"SUMMARY:{titulo}", _desplegar(ics))

    def test_alarma_opcional(self):
        sin_alarma = generar_ics(
            [EventoICS(uid="e@medicos", titulo="Cita", fecha=date(2026, 4, 1))],
            generado_en=GENERADO_EN,
        )
        self.assertNotIn("BEGIN:VALARM", sin_alarma)

        con_alarma = generar_ics(
            [
                EventoICS(
                    uid="e@medicos",
                    titulo="Cita",
                    fecha=date(2026, 4, 1),
                    aviso_min_antes=1440,
                )
            ],
            generado_en=GENERADO_EN,
        )
        self.assertIn("BEGIN:VALARM", con_alarma)
        self.assertIn("TRIGGER:-PT1440M", con_alarma)

    def test_varios_eventos(self):
        ics = generar_ics(
            [
                EventoICS(uid="a@medicos", titulo="A", fecha=date(2026, 4, 1)),
                EventoICS(uid="b@medicos", titulo="B", fecha=date(2026, 4, 2)),
            ],
            generado_en=GENERADO_EN,
        )
        self.assertEqual(ics.count("BEGIN:VEVENT"), 2)
        self.assertEqual(ics.count("END:VEVENT"), 2)


if __name__ == "__main__":
    unittest.main()
