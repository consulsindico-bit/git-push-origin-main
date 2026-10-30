@echo off
rem Abre a interface local no navegador (Windows). Clique duas vezes neste arquivo.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [X] O ambiente ainda nao foi instalado. Rode primeiro o instalar.bat nesta pasta.
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [X] FFmpeg nao encontrado no PATH. Instale com:  winget install --id Gyan.FFmpeg -e
  echo     Depois feche esta janela, abra de novo e tente outra vez.
  pause
  exit /b 1
)
echo Abrindo a interface em http://127.0.0.1:8765/  (feche esta janela para encerrar)
".venv\Scripts\python.exe" -m editor interface
if errorlevel 1 pause
