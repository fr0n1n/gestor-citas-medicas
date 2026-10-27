"""Pruebas de las reglas sobre ficheros subidos."""

from __future__ import annotations

import unittest
from datetime import date

from app.archivos import (
    HEIC,
    JPEG,
    PDF,
    PNG,
    WEBP,
    detectar_tipo,
    nombre_libre,
    nombre_normalizado,
    nombre_original_seguro,
    slug,
)


class TestDetectarTipo(unittest.TestCase):
    def test_tipos_validos(self):
        casos = [
            (b"%PDF-1.7\n...", PDF),
            (b"\xff\xd8\xff\xe0\x00\x10JFIF", JPEG),
            (b"\x89PNG\r\n\x1a\n\x00\x00", PNG),
            (b"RIFF\x00\x00\x00\x00WEBPVP8 ", WEBP),
            (b"\x00\x00\x00\x18ftypheic\x00\x00", HEIC),
            (b"\x00\x00\x00\x18ftypmif1\x00\x00", HEIC),
        ]
        for cabecera, esperado in casos:
            with self.subTest(esperado=esperado.extension):
                self.assertEqual(detectar_tipo(cabecera), esperado)

    def test_se_rechaza_lo_que_no_es_documento(self):
        for malo in (
            b"MZ\x90\x00",  # ejecutable de Windows
            b"\x7fELF\x02",  # ejecutable de Linux
            b"<html><script>alert(1)</script>",
            b"<svg onload=alert(1)>",  # SVG puede llevar JavaScript
            b"PK\x03\x04",  # zip, docx...
            b"#!/bin/sh\n",
            b"",
            b" %PDF-1.7",  # la marca tiene que ir al principio
            b"\x00\x00\x00\x18ftypisom",  # video mp4
        ):
            with self.subTest(malo=malo[:12]):
                self.assertIsNone(detectar_tipo(malo))


class TestSlug(unittest.TestCase):
    def test_quita_tildes_y_espacios(self):
        self.assertEqual(slug("Traumatología"), "traumatologia")
        self.assertEqual(slug("Revisión de Digestivo"), "revision-de-digestivo")
        self.assertEqual(slug("Año Ñandú"), "ano-nandu")

    def test_sin_caracteres_peligrosos(self):
        self.assertEqual(slug("../../etc/passwd"), "etc-passwd")
        self.assertEqual(slug("a/b\\c:d*e?f"), "a-b-c-d-e-f")

    def test_vacios(self):
        self.assertEqual(slug(None), "")
        self.assertEqual(slug("  ---  "), "")

    def test_longitud_acotada(self):
        self.assertLessEqual(len(slug("x" * 500)), 40)


class TestNombreNormalizado(unittest.TestCase):
    def test_formato_acordado(self):
        self.assertEqual(
            nombre_normalizado(date(2026, 3, 2), ["Digestivo", "Citación"], "pdf"),
            "2026-03-02_digestivo_citacion.pdf",
        )

    def test_sin_fecha(self):
        self.assertEqual(
            nombre_normalizado(None, ["Dependencia"], "jpg"),
            "sin-fecha_dependencia.jpg",
        )

    def test_sin_partes(self):
        self.assertEqual(
            nombre_normalizado(date(2026, 1, 1), [None, ""], "png"),
            "2026-01-01_documento.png",
        )

    def test_no_repite_partes(self):
        self.assertEqual(
            nombre_normalizado(date(2026, 1, 1), ["Digestivo", "digestivo", "informe"], "pdf"),
            "2026-01-01_digestivo_informe.pdf",
        )


class TestNombreLibre(unittest.TestCase):
    def test_libre(self):
        self.assertEqual(nombre_libre("a.pdf", lambda n: False), "a.pdf")

    def test_ocupado(self):
        ocupados = {"a.pdf", "a-2.pdf"}
        self.assertEqual(nombre_libre("a.pdf", ocupados.__contains__), "a-3.pdf")


class TestNombreOriginal(unittest.TestCase):
    def test_se_queda_con_el_nombre_sin_ruta(self):
        self.assertEqual(nombre_original_seguro("../../etc/passwd"), "passwd")
        self.assertEqual(nombre_original_seguro("C:\\fotos\\receta.jpg"), "receta.jpg")

    def test_sin_caracteres_de_control(self):
        self.assertEqual(nombre_original_seguro("a\r\nb.pdf"), "ab.pdf")

    def test_vacio(self):
        self.assertEqual(nombre_original_seguro(None), "sin-nombre")
        self.assertEqual(nombre_original_seguro("/"), "sin-nombre")


if __name__ == "__main__":
    unittest.main()
