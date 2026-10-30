@echo off
rem Abre a interface local no navegador (Windows)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Rode primeiro o instalador: powershell -ExecutionPolicy Bypass -File instalar.ps1
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m editor interface
pause
