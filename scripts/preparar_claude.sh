#!/usr/bin/env bash
# Copia el claude ya instalado en esta maquina a vendor/, para que la imagen
# Docker lo use en vez de descargarlo (util con conexiones lentas).
#
#     ./scripts/preparar_claude.sh && docker compose build
#
# Solo copia el programa: nunca credenciales ni configuracion (~/.claude).
set -euo pipefail
cd "$(dirname "$0")/.."

origen="$(readlink -f "$(command -v claude)")" || {
    echo "No se encuentra 'claude' en esta maquina." >&2
    exit 1
}
if [ "$(uname -m)" != "x86_64" ] && [ "$(uname -m)" != "aarch64" ]; then
    echo "Arquitectura $(uname -m) no probada." >&2
fi

cp "$origen" vendor/claude
chmod 755 vendor/claude
echo "Copiado $origen -> vendor/claude ($(vendor/claude --version 2>/dev/null | head -1))"
