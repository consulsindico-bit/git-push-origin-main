#!/usr/bin/env bash
# Instalação no macOS ou Linux. Rode uma vez:  bash instalar.sh
set -e
cd "$(dirname "$0")"

echo "== Verificando o FFmpeg =="
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg não encontrado."
  if [[ "$OSTYPE" == darwin* ]]; then
    echo "No macOS, instale com o Homebrew:  brew install ffmpeg"
  else
    echo "No Ubuntu/Debian:  sudo apt install ffmpeg      No Fedora:  sudo dnf install ffmpeg"
  fi
  exit 1
fi
ffmpeg -version | head -1

echo "== Verificando o Python =="
PY=python3
command -v $PY >/dev/null 2>&1 || { echo "Python 3 não encontrado. Instale em https://www.python.org/downloads/"; exit 1; }
$PY --version

echo "== Criando o ambiente virtual (.venv) e instalando dependências =="
[ -d .venv ] || $PY -m venv .venv
. .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "== Criando as pastas e os perfis iniciais =="
python -m editor pastas

echo
echo "Pronto. Para abrir a interface:   bash iniciar-interface.sh"
echo "Para usar pelo terminal:          source .venv/bin/activate && python -m editor --help"
echo "Na primeira transcrição o modelo de voz (cerca de 480 MB para o 'small') é baixado automaticamente."
