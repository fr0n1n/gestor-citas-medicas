"""Pruebas de la capa de IA que no necesitan hablar con ningun modelo.

Lo que se prueba aqui es lo que suele romperse de verdad al cambiar de
proveedor: en que formato se le manda el documento, como se traduce el
esquema JSON y que se entiende cuando la API contesta mal. La llamada en
si no se prueba: eso exige una clave y dinero, y esta documentado en
`docs/PROVEEDORES-IA.md` como se comprueba a mano.

Necesitan pydantic (lo arrastra `app.ia.esquema`), asi que se saltan solas
si no esta instalado.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from app.ia import entrada, gemini, red
    from app.ia.base import ErrorAnalisis, obtener_analizador
    HAY_PYDANTIC = True
except ImportError:  # pragma: no cover - depende del entorno
    HAY_PYDANTIC = False


@unittest.skipUnless(HAY_PYDANTIC, "hace falta pydantic")
class PrepararEntrada(unittest.TestCase):
    """Un documento, traducido a lo que cada API sabe recibir."""

    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.ruta = Path(self.carpeta.name)
        self.addCleanup(self.carpeta.cleanup)

    def test_una_llamada_apuntada_va_como_texto(self):
        fichero = self.ruta / "llamada.txt"
        fichero.write_text("Cita el 20 de octubre a las 10:15", encoding="utf-8")

        resultado = entrada.preparar(fichero, "text/plain")

        self.assertEqual(resultado.texto, "Cita el 20 de octubre a las 10:15")
        self.assertEqual(resultado.partes, [])
        self.assertIn("escrito", resultado.referencia)

    def test_un_texto_vacio_se_rechaza(self):
        fichero = self.ruta / "vacia.txt"
        fichero.write_text("   \n", encoding="utf-8")

        with self.assertRaises(ErrorAnalisis):
            entrada.preparar(fichero, "text/plain")

    def test_una_foto_va_como_imagen(self):
        fichero = self.ruta / "foto.png"
        fichero.write_bytes(_png_minimo())

        resultado = entrada.preparar(fichero, "image/png")

        self.assertIsNone(resultado.texto)
        self.assertEqual(len(resultado.partes), 1)
        self.assertTrue(resultado.partes[0].mime.startswith("image/"))
        self.assertTrue(resultado.partes[0].datos)

    def test_el_pdf_tal_cual_si_el_proveedor_lo_admite(self):
        fichero = self.ruta / "citacion.pdf"
        fichero.write_bytes(b"%PDF-1.4 esto no se abre, solo se reenvia")

        resultado = entrada.preparar(fichero, "application/pdf", admite_pdf=True)

        self.assertEqual(len(resultado.partes), 1)
        self.assertEqual(resultado.partes[0].mime, "application/pdf")

    def test_un_formato_que_nadie_sabe_abrir_lo_dice_con_su_nombre(self):
        fichero = self.ruta / "cosa.bin"
        fichero.write_bytes(b"\x00\x01\x02")

        with self.assertRaises(ErrorAnalisis) as fallo:
            entrada.preparar(fichero, "application/x-cosa")

        self.assertIn("claude-cli", str(fallo.exception))


@unittest.skipUnless(HAY_PYDANTIC, "hace falta pydantic")
class EsquemaParaGemini(unittest.TestCase):
    """Gemini rechaza con un 400 medio esquema de Pydantic."""

    def test_no_quedan_referencias_ni_palabras_prohibidas(self):
        from app.ia.base import esquema_json

        adaptado = gemini._esquema_para_gemini(esquema_json())
        texto = json.dumps(adaptado)

        for prohibida in ("$ref", "$defs", "anyOf", "additionalProperties"):
            self.assertNotIn(prohibida, texto, prohibida)

    def test_un_campo_opcional_se_queda_con_su_tipo(self):
        esquema = {
            "type": "object",
            "properties": {
                "fecha": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "El dia de la cita",
                }
            },
        }

        adaptado = gemini._esquema_para_gemini(esquema)

        campo = adaptado["properties"]["fecha"]
        self.assertEqual(campo["type"], "string")
        self.assertEqual(campo["description"], "El dia de la cita")

    def test_las_referencias_se_resuelven(self):
        esquema = {
            "$defs": {"Cita": {"type": "object", "properties": {"titulo": {"type": "string"}}}},
            "type": "object",
            "properties": {"cita": {"$ref": "#/$defs/Cita"}},
        }

        adaptado = gemini._esquema_para_gemini(esquema)

        self.assertEqual(
            adaptado["properties"]["cita"]["properties"]["titulo"]["type"], "string"
        )


@unittest.skipUnless(HAY_PYDANTIC, "hace falta pydantic")
class ErroresLegibles(unittest.TestCase):
    """Lo que la persona lee cuando la API contesta mal."""

    def test_se_saca_el_mensaje_del_json_de_error(self):
        cuerpo = json.dumps({"error": {"message": "La clave no es valida", "code": 401}})

        self.assertEqual(red._mensaje(cuerpo), "La clave no es valida")

    def test_si_no_es_json_se_devuelve_tal_cual(self):
        self.assertEqual(red._mensaje("502 Bad Gateway"), "502 Bad Gateway")


@unittest.skipUnless(HAY_PYDANTIC, "hace falta pydantic")
class ProveedorConfigurado(unittest.TestCase):
    """El nombre del `.env` tiene que llevar al proveedor que toca."""

    def test_cada_nombre_y_sus_alias(self):
        casos = {
            "claude-cli": "claude-cli",
            "cli": "claude-cli",
            "openai": "openai",
            "gpt": "openai",
            "gemini": "gemini",
            "google": "gemini",
            "ollama": "ollama",
            "anthropic": "anthropic",
            "ninguno": "ninguno",
        }
        for escrito, esperado in casos.items():
            with self.subTest(escrito=escrito):
                self.assertEqual(obtener_analizador(escrito).nombre, esperado)

    def test_un_nombre_inventado_lo_dice_con_la_lista(self):
        with self.assertRaises(ValueError) as fallo:
            obtener_analizador("deepseek")

        self.assertIn("gemini", str(fallo.exception))


def _png_minimo() -> bytes:
    """Un PNG de 1x1 valido, para no depender de ningun fichero."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


if __name__ == "__main__":
    unittest.main()
