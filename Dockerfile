# Imagen unica, sin build de Node: la interfaz se sirve desde el propio
# servidor de Python y no hay nada que compilar.
FROM python:3.12-slim

# Incluir el CLI de Claude, que analiza los documentos con tu suscripcion
# (MEDICOS_IA_PROVEEDOR=claude-cli). Se autentica con un token en el .env
# (CLAUDE_CODE_OAUTH_TOKEN, ver README): no hace falta montar ~/.claude.
ARG CON_CLAUDE_CLI=true

# El usuario del contenedor debe tener el mismo UID que el del host, o los
# ficheros del volumen de datos acabaran perteneciendo a root.
ARG UID=1000
ARG GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDICOS_DATA_DIR=/data

WORKDIR /app

# CLI de Claude. Dos formas:
#  - Si hay una copia en vendor/claude (scripts/preparar_claude.sh la pone
#    ahi desde el claude ya instalado en la maquina), se usa esa. Evita
#    descargar ~220 MB: el instalador oficial se rinde a los 10 minutos
#    y con una conexion lenta no le da tiempo.
#  - Si no, se descarga con el instalador oficial.
# En ambos casos queda en /usr/local/bin y no se deja nada mas: ni curl ni
# credenciales.
# La carpeta vendor/ se monta solo durante este paso: el binario no queda
# guardado dos veces en la imagen (una en la copia y otra en su sitio).
RUN --mount=type=bind,source=vendor,target=/tmp/vendor \
    if [ "$CON_CLAUDE_CLI" = "true" ]; then \
        if [ -f /tmp/vendor/claude ]; then \
            cp /tmp/vendor/claude /usr/local/bin/claude; \
        else \
            apt-get update && \
            apt-get install -y --no-install-recommends curl ca-certificates && \
            curl -fsSL https://claude.ai/install.sh | bash && \
            cp -L /root/.local/bin/claude /usr/local/bin/claude && \
            rm -rf /root/.local /root/.claude /root/.claude.json /root/.cache && \
            apt-get purge -y curl && apt-get autoremove -y && \
            apt-get clean && rm -rf /var/lib/apt/lists/*; \
        fi && \
        chmod 755 /usr/local/bin/claude; \
    fi

# poppler-utils trae pdftoppm, que dibuja las paginas de un PDF como
# imagenes. Es lo que permite ver una miniatura y una vista previa de los
# documentos sin incrustar el PDF: incrustarlo obligaria a abrir la politica
# de seguridad y ademas en el movil se ve mal. Son unos 20 MB.
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Las dependencias se copian e instalan antes que el codigo para que un
# cambio en la aplicacion no invalide esta capa de la cache.
#
# Versiones EXACTAS a proposito. Con rangos abiertos, cada reconstruccion se
# traia lo ultimo que hubiera salido y la aplicacion podia dejar de funcionar
# sin haber tocado una linea de codigo: paso el 2026-09-23 con sqlmodel 0.0.46,
# que devuelve las fechas con zona horaria y rompio el control de sesiones.
# Para subir cualquiera de estas versiones: cambiarla aqui a mano, reconstruir
# y probar. Nunca automaticamente.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "fastapi==0.141.1" \
        "uvicorn[standard]==0.53.0" \
        "sqlmodel==0.0.46" \
        "jinja2==3.1.6" \
        "python-multipart==0.0.32" \
        "pydantic==2.13.5" \
        "pydantic-settings==2.15.0" \
        "pillow==11.3.0"

COPY app ./app
COPY scripts ./scripts

RUN groupadd -g "$GID" medicos 2>/dev/null || true && \
    useradd -u "$UID" -g "$GID" -m -s /bin/bash medicos 2>/dev/null || true && \
    mkdir -p /data && chown -R "$UID:$GID" /data /app

USER $UID:$GID

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/salud')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
