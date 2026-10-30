#!/usr/bin/env bash
# Abre a interface local no navegador (macOS / Linux)
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Rode primeiro: bash instalar.sh"; exit 1; }
. .venv/bin/activate
python -m editor interface
