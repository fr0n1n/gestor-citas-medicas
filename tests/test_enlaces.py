"""Pruebas de los enlaces dentro del texto libre."""

from __future__ import annotations

import unittest

from app.enlaces import enlazar, mapa_de, sin_urls, urls_de

# Tal como lo escribio la persona al dar de alta la resonancia.
REAL = (
    "Av. de Andalucía, 27, Cruz de Humilladero, 00000 Vistamar "
    "(enlace: https://maps.app.goo.gl/B58DGdDdhpw1EWQ36?g_st=aw)"
)


class TestUrlsDe(unittest.TestCase):
    def test_encuentra_la_direccion_sin_el_parentesis(self):
        self.assertEqual(
            urls_de(REAL), ["https://maps.app.goo.gl/B58DGdDdhpw1EWQ36?g_st=aw"]
        )

    def test_varias(self):
        self.assertEqual(
            urls_de("ver https://a.es/x y tambien http://b.es."),
            ["https://a.es/x", "http://b.es"],
        )

    def test_sin_ninguna(self):
        self.assertEqual(urls_de("Planta 2, consulta 12"), [])
        self.assertEqual(urls_de(None), [])


class TestSinUrls(unittest.TestCase):
    def test_deja_solo_la_direccion_postal(self):
        self.assertEqual(
            sin_urls(REAL), "Av. de Andalucía, 27, Cruz de Humilladero, 00000 Vistamar"
        )

    def test_texto_sin_enlaces_no_se_toca(self):
        self.assertEqual(sin_urls("Planta 2, consulta 12"), "Planta 2, consulta 12")

    def test_solo_un_enlace(self):
        self.assertEqual(sin_urls("https://maps.app.goo.gl/abc"), "")


class TestEnlazar(unittest.TestCase):
    def test_la_direccion_queda_pulsable(self):
        html = str(enlazar(REAL))
        self.assertIn('href="https://maps.app.goo.gl/B58DGdDdhpw1EWQ36?g_st=aw"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        # El parentesis de cierre se queda fuera del enlace.
        self.assertTrue(html.rstrip().endswith(")"))

    def test_escapa_antes_de_enlazar(self):
        html = str(enlazar("<script>alert(1)</script> http://a.b"))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_no_enlaza_esquemas_peligrosos(self):
        for malo in ("javascript:alert(1)", "data:text/html,<b>", "file:///etc/passwd"):
            with self.subTest(malo=malo):
                self.assertNotIn("<a ", str(enlazar(malo)))


class TestMapaDe(unittest.TestCase):
    def test_construye_la_busqueda(self):
        enlace = mapa_de("Av. de Cibeles, 6, 29630 Villamar")
        self.assertTrue(enlace.startswith("https://www.google.com/maps/search/"))
        self.assertIn("Cibeles", enlace)

    def test_ignora_la_url_que_venga_dentro(self):
        # No debe meter la direccion de internet dentro de la busqueda.
        self.assertNotIn("goo.gl", mapa_de(REAL))

    def test_sin_direccion(self):
        self.assertIsNone(mapa_de(None))
        self.assertIsNone(mapa_de("   "))


if __name__ == "__main__":
    unittest.main()


class TestNombreDeMapa(unittest.TestCase):
    """El nombre del sitio, leido del propio enlace y sin preguntar a nadie."""

    LARGO = (
        "https://www.google.com/maps/place/Centro+de+Diagn%C3%B3stico+Scanner,"
        "+Av.+de+Andaluc%C3%ADa,+27,+Cruz+de+Humilladero,+00000+M%C3%A1laga/"
        "data=!4m2!3m1!1s0xd72f775ef467ac5"
    )

    def test_saca_el_nombre_del_sitio(self):
        from app.enlaces import nombre_de_mapa

        self.assertEqual(nombre_de_mapa(self.LARGO), "Centro de Diagnóstico Scanner")

    def test_dentro_de_una_frase(self):
        from app.enlaces import nombre_de_mapa

        self.assertEqual(
            nombre_de_mapa(f"La prueba es aquí ({self.LARGO})"),
            "Centro de Diagnóstico Scanner",
        )

    def test_un_enlace_corto_no_lleva_el_nombre(self):
        from app.enlaces import nombre_de_mapa

        self.assertIsNone(nombre_de_mapa(REAL))

    def test_sin_enlaces(self):
        from app.enlaces import nombre_de_mapa

        self.assertIsNone(nombre_de_mapa("Planta 2, consulta 12"))
        self.assertIsNone(nombre_de_mapa(None))
