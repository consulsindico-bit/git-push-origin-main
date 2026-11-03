@echo off
rem Renomeia um projeto. Coloque em "Edicao com IA\ferramenta" e clique duas vezes.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [X] Rode primeiro o instalar.bat nesta pasta.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m editor projetos
echo.
".venv\Scripts\python.exe" -X utf8 -m editor renomear
pause
