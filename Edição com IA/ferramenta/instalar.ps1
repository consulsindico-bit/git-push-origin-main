# Instalação no Windows. Abra o PowerShell nesta pasta e rode:  powershell -ExecutionPolicy Bypass -File instalar.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== Verificando o FFmpeg =="
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "FFmpeg não encontrado. Instale com um destes comandos e abra um novo PowerShell:"
    Write-Host "   winget install Gyan.FFmpeg"
    Write-Host "   (ou baixe em https://www.gyan.dev/ffmpeg/builds/ e adicione a pasta bin ao PATH)"
    exit 1
}
ffmpeg -version | Select-Object -First 1

Write-Host "== Verificando o Python =="
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host "Python não encontrado. Instale em https://www.python.org/downloads/ (marque 'Add python to PATH')."; exit 1 }
python --version

Write-Host "== Criando o ambiente virtual (.venv) e instalando dependências =="
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip | Out-Null
pip install -r requirements.txt

Write-Host "== Criando as pastas e os perfis iniciais =="
python -m editor pastas

Write-Host ""
Write-Host "Pronto. Para abrir a interface: clique duas vezes em iniciar-interface.bat"
Write-Host "Para usar pelo terminal:  .\.venv\Scripts\Activate.ps1  e depois  python -m editor --help"
Write-Host "Na primeira transcrição o modelo de voz (cerca de 480 MB para o 'small') é baixado automaticamente."
