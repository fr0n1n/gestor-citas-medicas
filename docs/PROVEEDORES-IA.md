# Qué modelo lee los documentos

La aplicación nunca guarda nada por su cuenta: el modelo **propone** y una
persona confirma. Aun así, elegir proveedor es una decisión con tres caras —
quién ve tus documentos, cuánto cuesta y cuánto acierta— y por eso se cambia
con una línea del `.env`:

```bash
MEDICOS_IA_PROVEEDOR=claude-cli   # claude-cli | anthropic | openai | gemini | ollama | ninguno
```

## La tabla corta

| Proveedor | Qué necesita | Dónde van tus documentos | Cuesta | Lee |
|---|---|---|---|---|
| `claude-cli` | `CLAUDE_CODE_OAUTH_TOKEN` | Anthropic | Tu suscripción de Claude | Texto, fotos y PDF |
| `anthropic` | `ANTHROPIC_API_KEY` | Anthropic | Por uso | Texto, fotos y PDF |
| `openai` | `OPENAI_API_KEY` | OpenAI | Por uso | Texto y fotos; los PDF se mandan dibujados |
| `gemini` | `GEMINI_API_KEY` | Google | Plan gratuito con límites, luego por uso | Texto, fotos y PDF |
| `ollama` | Ollama con un modelo de visión | **A ningún sitio: se queda en tu máquina** | Nada | Texto y fotos; los PDF se mandan dibujados |
| `ninguno` | — | — | — | Nada: todo se escribe a mano |

Ninguno necesita instalar librerías: se habla con las APIs por HTTP con la
biblioteca estándar de Python.

## Cómo se le pasa el documento a cada uno

`app/ia/entrada.py` traduce cada documento a lo que el proveedor sabe recibir:

- **Lo apuntado de una llamada** (`.txt`) va como texto dentro de la petición.
- **Una foto** se encoge a 1600 px de ancho y se endereza con la orientación
  de los metadatos. Una foto de móvil de 8 MB se queda en unos cientos de KB,
  que es lo que cambia la factura.
- **Un PDF** va tal cual a quien lo entiende (Anthropic, Gemini). A los demás
  se les mandan sus páginas dibujadas en JPEG, como máximo 8, con `pdftoppm`
  (paquete `poppler-utils`, ya incluido en la imagen de Docker).
- **HEIC y formatos raros**: se intentan convertir a JPEG con Pillow. Si no se
  puede, el error lo dice y sugiere `claude-cli`, que los lee todos.

## Configurar cada uno

### claude-cli (el de por defecto)

Usa el binario `claude` con tu suscripción, sin pago por uso. Se ejecuta
encerrado: `--restricted --tools Read --permission-mode dontAsk
--strict-mcp-config`, en una carpeta temporal que solo contiene una copia del
documento. Un papel con instrucciones escondidas no puede hacer nada más que
estropear su propia propuesta.

```bash
claude setup-token          # en cualquier ordenador con Claude Code
# y el token va al .env como CLAUDE_CODE_OAUTH_TOKEN
```

### openai

```bash
MEDICOS_IA_PROVEEDOR=openai
OPENAI_API_KEY=sk-...
# MEDICOS_IA_MODELO=gpt-4o      # por defecto
```

Se pide salida estructurada con el mismo esquema JSON que usan los demás.

### gemini

```bash
MEDICOS_IA_PROVEEDOR=gemini
GEMINI_API_KEY=...             # también vale GOOGLE_API_KEY
# MEDICOS_IA_MODELO=gemini-2.5-flash   # por defecto
```

El esquema de Pydantic se adapta antes de mandarlo: Gemini rechaza con un 400
las referencias (`$ref`, `$defs`) y palabras como `anyOf` o
`additionalProperties`, así que se resuelven y se podan.

### ollama (en tu máquina, sin que salga nada)

```bash
ollama pull llama3.2-vision
MEDICOS_IA_PROVEEDOR=ollama
MEDICOS_OLLAMA_URL=http://localhost:11434
MEDICOS_IA_MODELO=llama3.2-vision
```

Si la aplicación va en Docker y Ollama en el anfitrión, la URL no es
`localhost`: usa la IP de la máquina o `http://host.docker.internal:11434`.

Acierta bastante menos que los modelos grandes. La pantalla de revisión deja
de ser una formalidad: hay que leerla entera.

## Comprobar que funciona, sin gastar de más

```bash
# ¿Está disponible el proveedor configurado? No consume nada.
docker compose exec medicos python scripts/probar_ia.py

# Analiza un documento de verdad y enseña lo que ha entendido,
# sin guardar nada en la base de datos.
docker compose exec medicos python scripts/probar_ia.py --fichero /data/documentos/entrada/x.pdf

# También con una llamada apuntada en un .txt.
docker compose exec medicos python scripts/probar_ia.py --fichero /tmp/llamada.txt
```

Las pruebas automáticas (`python -m unittest discover -s tests`) cubren lo que
suele romperse al cambiar de proveedor: en qué formato sale el documento, cómo
se traduce el esquema y qué mensaje se lee cuando la API contesta mal. La
llamada real no se prueba sola, porque exige una clave y dinero.

## Escribir otro proveedor

Un proveedor es una clase con dos métodos (`app/ia/base.py`):

```python
class MiProveedor:
    nombre = "mi-proveedor"

    def disponible(self) -> tuple[bool, str]:
        """(si se puede usar, explicación para la persona)."""

    def analizar(self, archivo: Path, mime: str, contexto: ContextoAnalisis) -> DocumentoExtraido:
        """Lee el documento y propone qué hacer con él."""
```

Lo demás está hecho: `entrada.preparar()` deja el documento en texto o
imágenes, `red.pedir_json()` hace la llamada y traduce los errores, y
`base.json_del_texto()` saca el JSON aunque venga envuelto en ```` ``` ````.
Se registra en `obtener_analizador()` y se añade a la tabla de arriba.

## Lo que conviene tener claro

Al analizar, el documento **sale de tu servidor** hacia el proveedor elegido,
salvo con `ollama`. Son documentos médicos de una persona concreta. Si para un
papel en particular prefieres que no salga, archívalo a mano: sin pulsar
"Analizar" no se envía nada, y con `MEDICOS_IA_PROVEEDOR=ninguno` la aplicación
funciona entera escribiendo las citas a mano.
