"""Pruebas del reconocimiento de centros.

Los nombres son los que de verdad aparecieron en los documentos, incluidos
los cuatro que dieron de alta cuatro veces el mismo hospital.
"""

from __future__ import annotations

import unittest

from app.centros import clase, distintivas, es_el_mismo, normalizar

# Las cuatro formas en que los papeles llamaron al mismo hospital.
FARO = (
    "Hospital Universitario Virgen del Faro (Vistamar)",
    "A.H. Virgen del Faro - Hospital de Especialidades Virgen del Faro",
    "Hospital Universitario Virgen del Faro - Medicina Física y Rehabilitación",
    "Hospital Virgen del Faro (A.H. Virgen del Faro)",
    "H.U. Virgen del Faro",
    # Aqui el servicio va delante del guion, no detras.
    "Laboratorios Clínicos - Hospital Universitario Virgen del Faro",
)

VILLAMAR = (
    "Hospital de Alta Resolución de Villamar",
    "HAR Villamar",
    "Hospital de Alta Resolución Villamar (Costa Norte)",
    # Como lo llama el SAS y como se lo dijeron al usuario por telefono:
    # Centro Hospitalario de Alta Resolucion de Especialidades.
    "CHARE Villamar",
    "HARE de Villamar",
    "Centro Hospitalario de Alta Resolución de Especialidades de Villamar",
)

ARROYO = (
    "Centro de Salud Arroyo Blanco-Villamar",
    "C.S. Arroyo Blanco",
    "CAP Arroyo Blanco",
)


class TestMismoCentro(unittest.TestCase):
    def test_todas_las_formas_del_mismo_hospital(self):
        for nombre in FARO:
            with self.subTest(nombre=nombre):
                self.assertTrue(es_el_mismo(FARO[0], nombre))

    def test_todas_las_formas_del_har_de_villamar(self):
        for nombre in VILLAMAR:
            with self.subTest(nombre=nombre):
                self.assertTrue(es_el_mismo(VILLAMAR[0], nombre))

    def test_todas_las_formas_del_centro_de_salud(self):
        for nombre in ARROYO:
            with self.subTest(nombre=nombre):
                self.assertTrue(es_el_mismo(ARROYO[0], nombre))

    def test_el_hospital_y_el_ambulatorio_del_mismo_pueblo_no_se_mezclan(self):
        # Los dos son "de Villamar" y son sitios distintos.
        for hospital in VILLAMAR:
            for ambulatorio in ARROYO:
                with self.subTest(hospital=hospital, ambulatorio=ambulatorio):
                    self.assertFalse(es_el_mismo(hospital, ambulatorio))

    def test_dos_hospitales_distintos_no_se_mezclan(self):
        for uno in VILLAMAR:
            for otro in FARO:
                with self.subTest(uno=uno, otro=otro):
                    self.assertFalse(es_el_mismo(uno, otro))

    def test_hospitales_de_la_misma_ciudad_que_no_son_el_mismo(self):
        otros = (
            "Hospital Regional Universitario de Vistamar (Los Álamos)",
            "Hospital Civil de Vistamar",
            "Hospital Costa Norte",
            "Hospital Materno Infantil",
        )
        for uno in otros:
            for otro in otros:
                if uno != otro:
                    with self.subTest(uno=uno, otro=otro):
                        self.assertFalse(es_el_mismo(uno, otro))
        for otro in otros:
            with self.subTest(otro=otro):
                self.assertFalse(es_el_mismo(FARO[0], otro))

    def test_vacios(self):
        for vacio in ("", "   ", None):
            with self.subTest(vacio=vacio):
                self.assertFalse(es_el_mismo(vacio or "", FARO[0]))

    def test_un_nombre_solo_generico_no_engancha_con_nadie(self):
        # "Hospital" a secas no identifica ningun sitio.
        self.assertFalse(es_el_mismo("Hospital", FARO[0]))
        self.assertFalse(es_el_mismo("Centro de salud", ARROYO[0]))


class TestPiezas(unittest.TestCase):
    def test_normalizar_despliega_las_abreviaturas(self):
        self.assertIn("centro de salud", normalizar("C.S. Arroyo"))
        self.assertIn("hospital de alta resolucion", normalizar("CHARE Villamar"))
        self.assertIn("hospital de alta resolucion", normalizar("HARE Villamar"))

    def test_no_confunde_palabras_que_solo_se_parecen(self):
        # "share" y "hardware" no son siglas de nada.
        for palabra in ("share", "hardware", "hares"):
            with self.subTest(palabra=palabra):
                self.assertNotIn("alta resolucion", normalizar(palabra))
        self.assertIn("hospital universitario", normalizar("H.U. Virgen"))
        self.assertIn("hospital de alta resolucion", normalizar("HAR Villamar"))

    def test_clase(self):
        self.assertEqual(clase("HAR Villamar"), "hospital")
        self.assertEqual(clase("C.S. Arroyo Blanco"), "centro de salud")
        self.assertEqual(clase("Virgen del Faro"), "")

    def test_distintivas_ignora_parentesis_y_servicio(self):
        self.assertEqual(
            distintivas("Hospital Universitario Virgen del Faro (Vistamar)"),
            frozenset({"virgen", "faro"}),
        )
        self.assertEqual(
            distintivas("H.U. Virgen del Faro - Medicina Física y Rehabilitación"),
            frozenset({"virgen", "faro"}),
        )


if __name__ == "__main__":
    unittest.main()


class TestNombreCorto(unittest.TestCase):
    """Los nombres largos, abreviados para caber en una pastilla."""

    def test_los_tres_centros_reales(self):
        from app.centros import nombre_corto

        casos = {
            # Sin abreviar: "C.S." no se entendia (ver ABREVIATURAS).
            "Centro de Salud Arroyo Blanco-Villamar": "Centro de Salud Arroyo Blanco",
            "Hospital de Alta Resolución de Villamar": "HAR Villamar",
            "Hospital Universitario Virgen del Faro (Vistamar)":
                "H.U. Virgen del Faro",
        }
        for largo, corto in casos.items():
            with self.subTest(largo=largo):
                self.assertEqual(nombre_corto(largo), corto)

    def test_un_nombre_ya_corto_no_se_toca(self):
        from app.centros import nombre_corto

        self.assertEqual(nombre_corto("HAR Villamar"), "HAR Villamar")
        self.assertEqual(nombre_corto("Hospital Civil"), "Hospital Civil")

    def test_vacio(self):
        from app.centros import nombre_corto

        self.assertEqual(nombre_corto(""), "")


class TestAliasLocales(unittest.TestCase):
    """Nombres coloquiales que no se parecen al oficial.

    La tabla va vacia en el repositorio: los nombres de verdad son los de
    la provincia de cada cual y se ponen en `app/alias_locales.py`. Aqui se
    inventa una para probar el mecanismo.
    """

    OFICIAL = "Hospital Universitario Virgen del Faro (Vistamar)"

    def setUp(self):
        from app import centros

        self.centros = centros
        self.anterior = centros.ALIAS
        centros.ALIAS = (
            ("clinico", frozenset({"vistamar"}), frozenset({"virgen", "faro"})),
        )
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        self.centros.ALIAS = self.anterior

    def test_el_coloquial_lleva_al_hospital_de_verdad(self):
        for coloquial in (
            "Hospital Clínico Vistamar",
            "Hospital Clinico de Vistamar",
            "Clínico",
            "Hospital Clínico",
        ):
            with self.subTest(coloquial=coloquial):
                self.assertTrue(es_el_mismo(self.OFICIAL, coloquial))

    def test_otro_clinico_distinto_no_se_confunde(self):
        # El de Madrid, por ejemplo: "san carlos" no esta permitido como
        # acompanante, asi que el alias no se aplica.
        for otro in ("Hospital Clínico San Carlos", "Hospital Clínico de Valladolid"):
            with self.subTest(otro=otro):
                self.assertFalse(es_el_mismo(self.OFICIAL, otro))

    def test_no_arrastra_a_los_demas_hospitales(self):
        self.assertFalse(
            es_el_mismo("Hospital de Alta Resolución de Villamar", "Hospital Clínico Vistamar")
        )

    def test_sin_alias_configurados_no_pasa_nada(self):
        self.centros.ALIAS = ()

        self.assertFalse(es_el_mismo(self.OFICIAL, "Hospital Clínico Vistamar"))


if __name__ == "__main__":
    unittest.main()
