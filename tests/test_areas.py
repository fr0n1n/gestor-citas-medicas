"""Pruebas del agrupado por area medica."""

from __future__ import annotations

import unittest

from app.areas import COLORES, SIN_AREA, canonica, color, slug, tono


class TestCanonica(unittest.TestCase):
    def test_variantes_reales_de_traumatologia(self):
        # Las tres formas que aparecen en los documentos del usuario.
        for texto in (
            "Cirugía Ortopédica y Traumatología",
            "Cirugía Ortopédica y Traumatología General (HAR Villamar)",
            "Traumatologia",
            "COT",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(canonica(texto), "Traumatología")

    def test_otras_areas(self):
        casos = {
            "Neurología": "Neurología",
            "neurologia": "Neurología",
            "Aparato digestivo": "Digestivo",
            "Medicina de familia": "Médico de cabecera",
            "Médico de cabecera": "Médico de cabecera",
            "Atención primaria": "Médico de cabecera",
            "Enfermería - Atención Primaria": "Enfermería",
            "Análisis clínicos": "Análisis clínicos",
            "Hematología y bioquímica": "Análisis clínicos",
            "RMN de columna": "Traumatología",
            "Radiodiagnóstico": "Radiología",
            "Dependencia": "Dependencia y trámites",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(canonica(texto), esperado)

    def test_el_orden_manda_en_los_casos_mixtos(self):
        # "Traumatología / Radiología" es seguimiento del traumatologo.
        self.assertEqual(canonica("Traumatología / Radiología"), "Traumatología")

    def test_area_desconocida_conserva_su_nombre(self):
        self.assertEqual(canonica("Alergología"), "Alergología")
        self.assertEqual(canonica("Medicina interna (planta 2)"), "Medicina interna")

    def test_vacios(self):
        for vacio in (None, "", "   ", "---"):
            with self.subTest(vacio=vacio):
                self.assertEqual(canonica(vacio), SIN_AREA)


class TestSlug(unittest.TestCase):
    def test_para_la_url(self):
        self.assertEqual(slug("Análisis clínicos"), "analisis-clinicos")
        self.assertEqual(slug("Traumatología"), "traumatologia")
        self.assertEqual(slug(SIN_AREA), "sin-area")

    def test_las_variantes_comparten_slug(self):
        self.assertEqual(slug(canonica("COT")), slug(canonica("Traumatologia")))


class TestTono(unittest.TestCase):
    def test_estable_y_dentro_de_la_rueda(self):
        for area in ("Traumatología", "Neurología", SIN_AREA):
            with self.subTest(area=area):
                self.assertEqual(tono(area), tono(area))
                self.assertTrue(0 <= tono(area) < 360)

    def test_areas_distintas_no_comparten_color(self):
        tonos = {tono(a) for a in ("Traumatología", "Neurología", "Digestivo",
                                   "Médico de cabecera", "Análisis clínicos")}
        self.assertGreaterEqual(len(tonos), 4)


class TestColor(unittest.TestCase):
    def test_dentro_del_rango_de_clases_css(self):
        for area in ("Traumatología", "Neurología", "Digestivo", SIN_AREA, "Alergología"):
            with self.subTest(area=area):
                self.assertIn(color(area), range(COLORES))

    def test_estable(self):
        self.assertEqual(color("Traumatología"), color(canonica("COT")))


if __name__ == "__main__":
    unittest.main()


class TestAdministrativas(unittest.TestCase):
    """A las gestiones no va el enfermo, va un familiar: sin ambulancia."""

    def test_lo_que_es_papeleo(self):
        from app.areas import es_administrativa

        for texto in (
            "Dependencia",
            "Trabajadora social",
            "Bienestar Social",
            "Servicios Sociales",
            "Solicitud de discapacidad",
        ):
            with self.subTest(texto=texto):
                self.assertTrue(es_administrativa(texto))

    def test_lo_que_es_medico_no_lo_es(self):
        from app.areas import es_administrativa

        for texto in (
            "Traumatología",
            "Digestivo",
            "Análisis clínicos",
            "Médico de cabecera",
            "Urgencias",
            None,
            "",
        ):
            with self.subTest(texto=texto):
                self.assertFalse(es_administrativa(texto))
