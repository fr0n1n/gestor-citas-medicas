"""Pruebas de las piezas de seguridad.

Solo usan la biblioteca estandar:

    python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import unittest

from app.seguridad import (
    HOSTS_LOCALES,
    ControlIntentos,
    hash_password,
    hash_token,
    host_permitido,
    nombre_host,
    nuevo_token,
    origen_valido,
    problema_password,
    ruta_segura,
    verificar_password,
    verificar_sin_usuario,
)

PERMITIDOS = HOSTS_LOCALES | {"servidor.lan", "192.168.1.50", "medicos.tail1234.ts.net"}


class TestPasswords(unittest.TestCase):
    def test_la_correcta_verifica(self):
        h = hash_password("una frase bastante larga")
        self.assertTrue(verificar_password("una frase bastante larga", h))

    def test_la_incorrecta_no(self):
        h = hash_password("una frase bastante larga")
        self.assertFalse(verificar_password("una frase bastante largA", h))

    def test_mismo_password_distinto_hash(self):
        # La sal aleatoria impide ver que dos usuarios comparten contrasena.
        self.assertNotEqual(hash_password("repetida123"), hash_password("repetida123"))

    def test_no_guarda_el_password_en_claro(self):
        self.assertNotIn("secreto-visible", hash_password("secreto-visible"))

    def test_hash_corrupto_no_revienta(self):
        for roto in ("", "basura", "scrypt$1$2", "bcrypt$a$b$c$d$e", "scrypt$x$8$1$aa$bb"):
            with self.subTest(roto=roto):
                self.assertFalse(verificar_password("lo que sea", roto))

    def test_acentos_y_enes(self):
        h = hash_password("contraseña con ñ y tildé")
        self.assertTrue(verificar_password("contraseña con ñ y tildé", h))

    def test_sin_usuario_siempre_falla(self):
        self.assertFalse(verificar_sin_usuario("cualquier cosa"))


class TestPoliticaPassword(unittest.TestCase):
    def test_demasiado_corta(self):
        self.assertIsNotNone(problema_password("corta"))

    def test_igual_al_usuario(self):
        self.assertIsNotNone(problema_password("MariaLopez1", "marialopez1"))

    def test_repetitiva(self):
        self.assertIsNotNone(problema_password("aaaaaaaaaaaa"))

    def test_una_frase_larga_vale(self):
        self.assertIsNone(problema_password("el gato duerme en la silla", "Poseidon"))


class TestTokens(unittest.TestCase):
    def test_tokens_distintos_y_largos(self):
        a, b = nuevo_token(), nuevo_token()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 40)

    def test_hash_estable_y_distinto_del_token(self):
        t = nuevo_token()
        self.assertEqual(hash_token(t), hash_token(t))
        self.assertNotEqual(hash_token(t), t)


class TestRutaSegura(unittest.TestCase):
    def test_rutas_internas_pasan(self):
        for ruta in ("/", "/agenda", "/eventos/3?aviso=hola", "/calendario?anio=2026&mes=4"):
            with self.subTest(ruta=ruta):
                self.assertEqual(ruta_segura(ruta), ruta)

    def test_salidas_de_la_aplicacion_se_bloquean(self):
        for malo in (
            "https://web-falsa.example",
            "http://web-falsa.example/agenda",
            "//web-falsa.example",
            "/\\web-falsa.example",
            "\\\\web-falsa.example",
            "javascript:alert(1)",
            "agenda",
            "/agenda\r\nSet-Cookie: x=1",
            "",
            None,
        ):
            with self.subTest(malo=malo):
                self.assertEqual(ruta_segura(malo), "/")

    def test_valor_por_defecto_configurable(self):
        self.assertEqual(ruta_segura("https://x", "/tramites"), "/tramites")


class TestHosts(unittest.TestCase):
    def test_nombre_host(self):
        self.assertEqual(nombre_host("Servidor.LAN:8080"), "servidor.lan")
        self.assertEqual(nombre_host("192.168.1.50"), "192.168.1.50")
        self.assertEqual(nombre_host("[::1]:8080"), "::1")
        self.assertEqual(nombre_host("::1"), "::1")

    def test_permitidos(self):
        for host in ("localhost:8080", "127.0.0.1:8000", "servidor.lan:8080",
                     "192.168.1.50:8080", "medicos.tail1234.ts.net"):
            with self.subTest(host=host):
                self.assertTrue(host_permitido(host, PERMITIDOS))

    def test_dns_rebinding_bloqueado(self):
        for host in ("web-maliciosa.example", "servidor.lan.web-maliciosa.example", "", None):
            with self.subTest(host=host):
                self.assertFalse(host_permitido(host, PERMITIDOS))


class TestOrigen(unittest.TestCase):
    def test_get_siempre_pasa(self):
        self.assertTrue(origen_valido("GET", "https://web-maliciosa.example", None, "servidor.lan:8080", PERMITIDOS))

    def test_post_desde_la_propia_app(self):
        self.assertTrue(origen_valido("POST", "http://servidor.lan:8080", None, "servidor.lan:8080", PERMITIDOS))

    def test_post_desde_otra_web_se_rechaza(self):
        self.assertFalse(origen_valido("POST", "https://web-maliciosa.example", None, "servidor.lan:8080", PERMITIDOS))

    def test_post_con_referer_ajeno_se_rechaza(self):
        self.assertFalse(origen_valido("POST", None, "https://web-maliciosa.example/pagina", "servidor.lan:8080", PERMITIDOS))

    def test_origin_null_se_rechaza(self):
        self.assertFalse(origen_valido("POST", "null", None, "servidor.lan:8080", PERMITIDOS))

    def test_sin_origin_ni_referer_pasa(self):
        # curl o scripts: no son navegadores, no hay CSRF posible.
        self.assertTrue(origen_valido("POST", None, None, "servidor.lan:8080", PERMITIDOS))

    def test_detras_de_proxy_con_host_reescrito(self):
        # tailscale serve puede reenviar con Host: 127.0.0.1:8080.
        self.assertTrue(origen_valido("POST", "https://medicos.tail1234.ts.net", None, "127.0.0.1:8080", PERMITIDOS))

    def test_mismo_nombre_otro_puerto_de_la_lista_pasa(self):
        self.assertTrue(origen_valido("POST", "http://servidor.lan:9999", None, "servidor.lan:8080", PERMITIDOS))


class TestControlIntentos(unittest.TestCase):
    def setUp(self):
        self.ahora = 1000.0
        self.control = ControlIntentos(maximo=3, bloqueo_s=60, reloj=lambda: self.ahora)

    def test_bloquea_tras_el_maximo(self):
        for _ in range(2):
            self.control.fallo("ana")
        self.assertEqual(self.control.segundos_bloqueo("ana"), 0)
        self.control.fallo("ana")
        self.assertEqual(self.control.segundos_bloqueo("ana"), 60)

    def test_el_bloqueo_caduca(self):
        for _ in range(3):
            self.control.fallo("ana")
        self.ahora += 61
        self.assertEqual(self.control.segundos_bloqueo("ana"), 0)

    def test_no_distingue_mayusculas(self):
        for nombre in ("Ana", "ANA", " ana "):
            self.control.fallo(nombre)
        self.assertGreater(self.control.segundos_bloqueo("ana"), 0)

    def test_un_acierto_limpia_los_fallos(self):
        self.control.fallo("ana")
        self.control.fallo("ana")
        self.control.exito("ana")
        self.control.fallo("ana")
        self.assertEqual(self.control.segundos_bloqueo("ana"), 0)

    def test_fallos_antiguos_no_suman(self):
        self.control.fallo("ana")
        self.control.fallo("ana")
        self.ahora += 120
        self.control.fallo("ana")
        self.assertEqual(self.control.segundos_bloqueo("ana"), 0)

    def test_usuarios_independientes(self):
        for _ in range(3):
            self.control.fallo("ana")
        self.assertEqual(self.control.segundos_bloqueo("luis"), 0)


if __name__ == "__main__":
    unittest.main()
