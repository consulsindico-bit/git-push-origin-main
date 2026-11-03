@echo off
rem Gera folhas de quadros dos videos em "2-Identidade visual e referencias\referencias" para enviar na conversa.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [X] Rode primeiro o instalar.bat nesta pasta.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m editor referencias
pause
