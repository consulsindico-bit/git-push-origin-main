@echo off
rem Instalador para Windows: clique duas vezes neste arquivo.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
