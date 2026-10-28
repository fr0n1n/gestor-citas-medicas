# Médicos

Aplicación local para organizar las citas, pruebas y trámites médicos de un
familiar al que se acompaña.

Nace de un problema concreto: cuando alguien de tu familia entra en el
circuito médico, no hay *una* agenda. Hay citas confirmadas, citas pedidas
esperando que llamen, citas que ni siquiera se han pedido, analíticas que
deben hacerse quince días antes de una consulta, informes en papel repartidos
por varios cajones y un expediente de dependencia a medias. Un calendario
normal no sirve, porque **la mitad de las cosas importantes todavía no tienen
fecha**.

Todo se guarda en tu propio equipo o servidor. Sin nube de terceros y sin
telemetría.

---

## Lo que hace

- **Citas sin fecha como ciudadanas de primera.** Una cita puede estar
  `por solicitar`, `esperando llamada`, `confirmada`, `realizada`, `aplazada`
  o `cancelada`. Las que esperan llamada se cuentan por días y se marcan
  cuando toca reclamar.
- **Requisitos previos con antelación.** "Analítica 15 días antes" se guarda
  como antelación, no como fecha: si la cita se mueve, la fecha límite se
  recalcula sola. Si la cita aún no tiene día, el requisito queda visible
  como pendiente de fecha en vez de desaparecer.
- **Pantalla de inicio que solo enseña lo que hay que hacer hoy**: requisitos
  que vencen, citas por pedir, citas que llevan demasiado esperando y
  consultas ya pasadas sin cerrar, por tramos (hoy, mañana, esta semana, la
  siguiente...).
- **La tarjeta de una cita es donde se trabaja**, no un resumen con enlace a
  otra pantalla: a la vista quedan el área, el centro, qué es, cuándo, dónde,
  el estado y la ambulancia; dentro se despliegan los preparativos, se marcan,
  se corrigen y se añaden, y "Ver la cita" abre el resto **en lectura**, con un
  botón de editar al lado. Se guarda y se vuelve a la lista.
- **Te han llamado para dar una cita**: se pega lo que te acaban de decir en
  "Apuntar llamada" y el modelo propone la cita con sus requisitos y sus
  teléfonos. Cuando llaman del hospital no hay papel que escanear.
- **Línea de tiempo, calendario mensual e historial** con lo que dijo el
  médico en cada consulta.
- **Trámites administrativos** (dependencia, incapacidad, ayudas) divididos
  en pasos con sus plazos.
- **Exportación a `.ics`** para que las citas aparezcan en el móvil de quien
  acompañe al paciente.
- **Varios pacientes** en la misma instalación.

- **Documentos**: sube fotos o PDF desde el móvil; Claude los lee y propone a
  qué cita o trámite pertenecen y qué hay que hacer. Tú confirmas.

---

## Arrancar

Necesitas Docker. Los datos se quedan en `./data`.

```bash
git clone <este-repo> Medicos
cd Medicos
cp .env.example .env          # opcional: ajusta zona horaria y umbrales
docker compose up -d --build
```

Crea tu usuario (te pedirá la contraseña, mínimo 10 caracteres):

```bash
docker compose exec medicos python scripts/usuario.py crear TU_NOMBRE
```

Abre <http://localhost:8080> y entra.

Por defecto el contenedor solo escucha en el propio equipo. Para usarlo desde
otros equipos o el móvil, ver [Instalar en un servidor](#instalar-en-un-servidor).

### Usuarios

No hay página de registro: en un servidor accesible desde la red, cualquiera
de la red podría darse de alta. Se gestionan desde la consola:

```bash
docker compose exec medicos python scripts/usuario.py crear NOMBRE
docker compose exec medicos python scripts/usuario.py password NOMBRE   # cierra sus sesiones
docker compose exec medicos python scripts/usuario.py listar
docker compose exec medicos python scripts/usuario.py borrar NOMBRE
docker compose exec medicos python scripts/usuario.py cerrar-sesiones   # ¿perdiste el móvil?
```

La sesión dura 30 días y se prolonga con el uso, así que en el móvil casi
nunca hace falta volver a entrar.

### Datos de ejemplo

Para ver cómo se comporta antes de meter datos reales:

```bash
docker compose exec medicos python scripts/demo.py
```

Crea un paciente ficticio con el caso completo: una cita con analítica
previa, una prueba esperando llamada desde hace dos meses, una cita sin
pedir, una consulta pasada sin cerrar y un expediente de dependencia a
medias. Se niega a ejecutarse si ya hay datos.

### Sin Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

---

## Instalar en un servidor

Pensado para un servidor siempre encendido, con Docker y con **nginx**
delante poniendo el dominio y el certificado HTTPS
(por ejemplo `https://medicos.tudominio.com`).

```bash
git clone <este-repo> Medicos && cd Medicos
cp .env.example .env
chmod 600 .env
mkdir -p data && chmod 700 data
```

En el `.env`, como mínimo:

```ini
# El nombre con el que se abre la app. Cualquier otro se rechaza
# (protección contra DNS rebinding): sin esta línea, verás "Acceso rechazado".
MEDICOS_HOSTS_PERMITIDOS=medicos.tudominio.com

# Solo nginx, en el mismo servidor, habla con el contenedor.
MEDICOS_IP_ESCUCHA=127.0.0.1

# Para analizar documentos con Claude (ver más abajo).
CLAUDE_CODE_OAUTH_TOKEN=...
```

Arranca y crea tu usuario:

```bash
docker compose up -d --build
docker compose exec medicos python scripts/usuario.py crear TU_NOMBRE
```

### Actualizar el servidor desde otra máquina

Si copias el proyecto con `rsync --delete`, **excluye la carpeta de datos**, o
la borrará (no existe en el origen):

```bash
rsync -az --delete --exclude '.git/' --exclude 'data/' --exclude 'datos/' \
      --exclude '.env' ./ usuario@servidor:/ruta/del/proyecto/
```

Y si la carpeta de datos la crea Docker en vez de ti, quedará como `root` y la
app no podrá escribir: `chown -R 1000:1000` sobre ella lo arregla.

### nginx

Hay una configuración lista en
[`despliegue/nginx-medicos.conf`](despliegue/nginx-medicos.conf). Lo que no
puede faltar:

- **`client_max_body_size 210m;`**: nginx corta por defecto las peticiones de
  más de 1 MB, y una sola foto de móvil ya las supera. Sin esto, subir
  documentos falla con un *413* que viene de nginx, no de la app.
- **`proxy_set_header Host $host;`**: la app tiene que ver el nombre original.
- **`proxy_set_header X-Forwarded-Proto $scheme;`**: así la cookie de sesión
  solo viaja por HTTPS.

Si nginx está en **otra máquina** o dentro de Docker (por ejemplo Nginx Proxy
Manager), no llegará a `127.0.0.1`: usa `MEDICOS_IP_ESCUCHA=0.0.0.0`. En ese
caso la app también queda accesible por `http://IP:8080` en tu red local, sin
certificado; el login la sigue protegiendo, pero no abras nunca ese puerto en
el router. Docker se salta el cortafuegos del sistema (`ufw`).

Si además pasas el dominio por el proxy de **Cloudflare**, su plan gratuito
limita cada petición a 100 MB: sube como mucho unas pocas fotos a la vez.

---

## Seguridad

Son datos de salud, así que la aplicación se ha endurecido pensando en que
viva en un servidor accesible desde la red:

- **Usuario y contraseña** en todas las páginas. Contraseñas con `scrypt`,
  sesiones guardadas como hash (una copia de la base no sirve para entrar),
  bloqueo de 15 minutos tras 5 intentos fallidos y cookies `HttpOnly` y
  `SameSite`, además de `Secure` cuando se entra por HTTPS.
- **Solo responde a los nombres configurados**, lo que impide que una web
  maliciosa lea los datos mediante *DNS rebinding*.
- **Solo acepta formularios enviados desde la propia app** (protección CSRF):
  otra web abierta en tu navegador no puede modificar ni borrar nada.
- **Cabeceras estrictas**: CSP sin JavaScript en línea, prohibido meterla en
  un iframe y nada en la caché del navegador.
- **Contenedor endurecido**: usuario sin privilegios, sistema de ficheros de
  solo lectura, sin capacidades del kernel, `no-new-privileges` y límites de
  memoria y procesos.

Las piezas de seguridad están en `app/seguridad.py`, sin dependencias
externas y con sus propios tests.

### Cómo abrirla desde fuera de casa

La contraseña de la app es la **última** barrera, no debería ser la única:
son datos de salud. Pon otra capa delante. De más a menos recomendable:

**1. Solo por VPN (Tailscale o WireGuard).** Nadie fuera de tu red privada
llega ni a ver la página. Con [Tailscale](https://tailscale.com), en el
servidor:

```bash
sudo tailscale up                                   # une el servidor a tu red de Tailscale
sudo tailscale serve --bg http://127.0.0.1:8080     # la publica con HTTPS SOLO dentro de esa red
```

```ini
# .env: el nombre que te da Tailscale (lo ves con `tailscale status`)
MEDICOS_HOSTS_PERMITIDOS=servidor.tu-red.ts.net
```

**2. Túnel de Cloudflare con Cloudflare Access.** Sin abrir puertos en el
router, y Cloudflare pide un código enviado a un correo autorizado *antes*
de dejarte llegar al login de la app:

```bash
cloudflared tunnel login
cloudflared tunnel create medicos
cloudflared tunnel route dns medicos citas.tudominio.com
```

```yaml
# ~/.cloudflared/config.yml
tunnel: medicos
credentials-file: /home/TU_USUARIO/.cloudflared/<id-del-tunel>.json
ingress:
  - hostname: citas.tudominio.com
    service: http://127.0.0.1:8080
  - service: http_status:404
```

Después, en el panel de Cloudflare: *Zero Trust → Access → Applications →
Self-hosted*, con el dominio `citas.tudominio.com` y una política
*Allow* con *Emails* = solo los correos de quien deba entrar (método
*One-time PIN*). Sin esa política, el túnel solo oculta tu IP: la app
quedaría abierta a todo internet.

**3. Tu propio proxy con HTTPS (nginx + Let's Encrypt).** Abre el puerto
443 del router hacia nginx (ver [nginx](#nginx)). Es la opción más expuesta:
añade el límite de intentos de login por IP que trae comentado
[`despliegue/nginx-medicos.conf`](despliegue/nginx-medicos.conf) y, si
puedes, una autenticación previa en el proxy.

**Nunca:**
- abrir en el router el puerto del contenedor (`8080`) directamente;
- entrar por HTTP sin cifrar desde fuera de casa;
- cambiar `MEDICOS_IP_ESCUCHA` a `0.0.0.0` si el proxy está en la misma
  máquina: con `127.0.0.1` solo el proxy habla con el contenedor.

**Además:**
- reconstruye la imagen de vez en cuando (`docker compose up -d --build`),
  aunque no cambie el código: así se actualizan las librerías del sistema
  que leen PDF e imágenes. El CI pasa `pip-audit` sobre las versiones del
  `Dockerfile`;
- cifra las copias de seguridad de `datos/` si salen del servidor;
- usa contraseñas largas (frases): la app exige 10 caracteres como mínimo.

---

## Copias de seguridad

Todo lo que importa está en `./data`:

```
data/
├── medicos.db       # la base de datos entera (SQLite)
└── documentos/      # los ficheros escaneados
```

Copiar esa carpeta es hacer una copia de seguridad completa. Restaurarla en
otro ordenador es copiarla de vuelta. No hay nada más.

---

## Documentos, llamadas y el modelo que los lee

Desde la web (también desde el móvil) se suben fotos o PDF de citaciones,
informes, volantes o resoluciones, y se apunta lo que te dicen por teléfono.
Todo entra por **Citas**, que es donde estás cuando llega, o desde la ficha de
una cita o de un trámite para que quede asociado a ella.

Lo que se sube cae en una **bandeja de pendientes**. Desde ahí:

- **✨ Analizar**: el modelo lee el documento (sin OCR: entiende la foto o el
  PDF directamente) y prepara una propuesta: qué cita o trámite es,
  fechas, preparativos, y si corresponde a una cita que ya existía. Por
  ejemplo: *"esta es la citación de la ecografía que estaba esperando
  llamada: confírmala para el 6/10 a las 9:40"*.
- **Tú revisas y confirmas** con un clic. Puedes corregir fechas, cambiar a
  qué cita se asocia o desmarcar lo que no quieras. Nada entra en la agenda
  sin esa confirmación: una fecha mal leída es una cita perdida.
- **O lo archivas a mano**, sin Claude.

Al confirmar, el documento se renombra como
`AAAA-MM-DD_tema_tipo.pdf` (fecha del propio documento) y pasa al archivo.

El análisis se hace **en el servidor, en segundo plano**: se puede cerrar la
web o perder la conexión y la propuesta queda guardada. Si el servidor se
reinicia a mitad, el documento vuelve a la cola solo.

### Conectar Claude (una vez)

La app usa **tu suscripción de Claude** a través del CLI de Claude Code, que
ya va dentro de la imagen. Solo necesita un token:

```bash
claude setup-token          # en cualquier equipo con Claude Code instalado
```

Pega el resultado en el `.env` del servidor y reinicia:

```ini
CLAUDE_CODE_OAUTH_TOKEN=...
```

```bash
docker compose up -d
docker compose exec medicos python scripts/probar_ia.py   # comprueba que funciona
```

El Claude que analiza documentos está **encerrado**: solo puede leer el
fichero que se le pasa (sin comandos, sin internet, sin tu configuración ni
tu historial). Un documento con instrucciones escondidas no puede hacer más
que estropear su propia propuesta, que siempre revisa una persona.

### Otros modelos: GPT, Gemini o uno local

No hace falta Claude. `MEDICOS_IA_PROVEEDOR` en el `.env` admite:

| Proveedor | Qué necesita | Dónde van tus documentos | Cuesta |
|---|---|---|---|
| `claude-cli` | `CLAUDE_CODE_OAUTH_TOKEN` | Anthropic | **Por defecto.** Tu suscripción de Claude |
| `anthropic` | `ANTHROPIC_API_KEY` | Anthropic | Por uso |
| `openai` | `OPENAI_API_KEY` | OpenAI | Por uso |
| `gemini` | `GEMINI_API_KEY` | Google | Plan gratuito con límites |
| `ollama` | Ollama con un modelo de visión | **A ningún sitio: tu máquina** | Nada |
| `ninguno` | — | — | Sin análisis: todo a mano |

Ninguno obliga a instalar librerías. Los detalles —qué formatos lee cada uno,
cómo se le manda un PDF, cómo comprobarlo sin gastar y cómo escribir otro—
están en **[docs/PROVEEDORES-IA.md](docs/PROVEEDORES-IA.md)**.

### Privacidad

Al analizar, el documento **sale de tu servidor** hacia el proveedor elegido,
salvo con `ollama`. Si prefieres que un papel concreto no salga, archívalo a
mano: sin pulsar "Analizar" no se envía nada, y con
`MEDICOS_IA_PROVEEDOR=ninguno` la aplicación funciona entera a mano.

---

## Cómo está hecho

Python + FastAPI + SQLite, con las páginas renderizadas en el servidor
(Jinja2). **Sin React, sin Tailwind, sin CDN**: la interfaz no carga nada de
internet, así que la aplicación funciona con el ordenador desconectado.

```
app/
├── logica.py      # Reglas del dominio: fechas límite, días de espera,
│                  # transiciones de estado, rejilla del calendario.
│                  # Sin dependencias externas y con tests.
├── ics.py         # Generación de .ics (RFC 5545), también sin dependencias
├── modelos.py     # Tablas (SQLModel)
├── consultas.py   # Las consultas que alimentan cada pantalla
├── rutas/         # Controladores HTTP
├── ia/            # El modelo que lee documentos, intercambiable:
│   ├── base.py    #   prompt, esquema y cuál se usa
│   ├── entrada.py #   el documento traducido a texto o imágenes
│   ├── red.py     #   las llamadas HTTP y sus errores, en castellano
│   └── *.py       #   claude_cli, anthropic, openai, gemini, ollama
├── cola.py        # Análisis en segundo plano (sobrevive a cierres)
├── propuestas.py  # De la propuesta de la IA a citas y trámites
├── plantillas/    # HTML
└── estatico/      # Una hoja de estilos, escrita a mano
```

Lo delicado vive en módulos que no importan FastAPI ni la base de datos
(`logica.py`, `ics.py`, `areas.py`, `centros.py`, `enlaces.py`, `seguridad.py`,
`archivos.py`). Así se pueden probar sin instalar nada:

```bash
python3 -m unittest discover -s tests -t .      # 197 pruebas
```

Las que necesitan las dependencias de la aplicación (las de la capa de IA) se
saltan solas si no están instaladas, así que ese comando funciona en cualquier
máquina con Python.

---

## El modelo de datos, en una frase

`Evento` es una cita, prueba o revisión, **y su fecha puede ser nula**. Esa
decisión es la que sostiene el resto: la pestaña de solicitudes, los requisitos
que todavía no pueden calcular su fecha límite, y el aviso de reclamar. Un
calendario que exige fechas no habría servido.

---

## Licencia

MIT. Si te resulta útil para tu propia situación, cógelo y adáptalo.
