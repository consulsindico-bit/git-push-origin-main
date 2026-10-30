# ============================================================================
#  Instalador para Windows 10/11 — Edição com IA
#  Como rodar: clique duas vezes em instalar.bat  (ou, no PowerShell, nesta pasta:
#              powershell -ExecutionPolicy Bypass -File .\instalar.ps1)
#  O script verifica cada requisito, orienta o que faltar, cria o ambiente
#  virtual, instala as dependências, confirma o FFmpeg e roda um teste final.
# ============================================================================
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -LiteralPath $PSScriptRoot

$falhas = @()
function Titulo($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }
function Ok($t)     { Write-Host "  [OK] $t" -ForegroundColor Green }
function Aviso($t)  { Write-Host "  [!] $t" -ForegroundColor Yellow }
function Erro($t)   { Write-Host "  [X] $t" -ForegroundColor Red }
function Pausar()   { if ($Host.Name -like "*ConsoleHost*") { Write-Host ""; Read-Host "Pressione Enter para fechar" | Out-Null } }
function AtualizarPath() {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function TemWinget() { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }
function Perguntar($texto) {
    $r = Read-Host "$texto (S/N)"
    return ($r -match '^[sSyY]')
}

Write-Host "Pasta da ferramenta: $PSScriptRoot"
if ($PSScriptRoot -match '[^\x00-\x7F]' -or $PSScriptRoot -match ' ') {
    Ok "O caminho tem espaços/acentos; isso é esperado e tratado (todas as chamadas usam o caminho entre aspas)."
}
if ($PSScriptRoot -like "*\OneDrive\*") {
    Aviso "A pasta está dentro do OneDrive. Funciona, mas vídeos grandes serão sincronizados; se preferir, mova para C:\Edição com IA."
}

# ----------------------------------------------------------------- 1. Python
Titulo "1/6 Python (3.11 a 3.14, 64 bits)"
$python = $null
$candidatos = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in "3.13", "3.12", "3.14", "3.11") {
        try { $saida = & py "-$v" -c "import sys,struct;print(sys.version.split()[0], struct.calcsize('P')*8)" 2>$null; if ($LASTEXITCODE -eq 0 -and $saida) { $candidatos += ,@("py -$v", $saida) } } catch {}
    }
}
foreach ($exe in "python", "python3") {
    $cmd = Get-Command $exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
        try { $saida = & $exe -c "import sys,struct;print(sys.version.split()[0], struct.calcsize('P')*8)" 2>$null; if ($LASTEXITCODE -eq 0 -and $saida) { $candidatos += ,@($exe, $saida) } } catch {}
    }
}
foreach ($c in $candidatos) {
    $versao, $bits = $c[1].Split(" ")
    $partes = $versao.Split("."); $maior = [int]$partes[0]; $menor = [int]$partes[1]
    if ($maior -eq 3 -and $menor -ge 11 -and $menor -le 14 -and $bits -eq "64") { $python = $c[0]; Ok "Python $versao (64 bits) encontrado via '$($c[0])'"; break }
    else { Aviso "Python $versao ($bits bits) via '$($c[0])' não serve (precisa 3.11-3.14, 64 bits)." }
}
if (-not $python) {
    Erro "Python 3.11-3.14 (64 bits) não encontrado."
    Write-Host "  Instale pela Microsoft Store ou por https://www.python.org/downloads/windows/ (marque 'Add python.exe to PATH')."
    if (TemWinget) {
        if (Perguntar "  Quer que eu instale agora com o winget (Python 3.12)?") {
            winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements
            AtualizarPath
            Write-Host "  Python instalado. FECHE esta janela e rode o instalador de novo." -ForegroundColor Yellow
        }
    }
    Pausar; exit 1
}
$pyArgs = $python.Split(" ")
$pyExe = $pyArgs[0]
$pyExtra = @(); if ($pyArgs.Length -gt 1) { $pyExtra = $pyArgs[1..($pyArgs.Length-1)] }
function RodarPython { param([string[]]$lista) & $pyExe @pyExtra @lista }

# ----------------------------------------------------------------- 2. FFmpeg
Titulo "2/6 FFmpeg e FFprobe"
AtualizarPath
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
if (-not $ffmpeg -or -not $ffprobe) {
    Erro "FFmpeg/FFprobe não encontrados no PATH."
    Write-Host "  Opção A (recomendada): no PowerShell, rode  winget install --id Gyan.FFmpeg -e"
    Write-Host "  Opção B: baixe 'ffmpeg-release-essentials.zip' em https://www.gyan.dev/ffmpeg/builds/,"
    Write-Host "           extraia em C:\ffmpeg e adicione C:\ffmpeg\bin ao PATH (Configurações > Sistema > Sobre > Configurações avançadas > Variáveis de ambiente)."
    if (TemWinget) {
        if (Perguntar "  Quer que eu instale agora com o winget?") {
            winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements
            AtualizarPath
            $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
            $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
        }
    }
    if (-not $ffmpeg -or -not $ffprobe) {
        Erro "FFmpeg ainda não está acessível. Instale, FECHE esta janela, abra de novo e rode o instalador outra vez."
        Pausar; exit 1
    }
}
$versaoFF = (& ffmpeg -version 2>&1 | Select-Object -First 1)
Ok "$versaoFF"
$filtros = (& ffmpeg -hide_banner -filters 2>&1) -join "`n"
if ($filtros -notmatch "\bass\b" -or $filtros -notmatch "drawtext") {
    Erro "Este FFmpeg não tem os filtros 'ass'/'drawtext' (legendas e textos). Instale a versão da gyan.dev (winget Gyan.FFmpeg)."
    Pausar; exit 1
}
Ok "Filtros de legendas (ass) e texto (drawtext) presentes"

# ----------------------------------------------------------------- 3. Git (opcional)
Titulo "3/6 Git (opcional: só para atualizar a ferramenta pelo GitHub)"
if (Get-Command git -ErrorAction SilentlyContinue) { Ok ((& git --version) -join "") } else { Aviso "Git não instalado. Não é necessário para usar a ferramenta. Se quiser: winget install --id Git.Git -e" }

# ----------------------------------------------------------------- 4. Ambiente virtual
Titulo "4/6 Ambiente virtual (.venv)"
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    RodarPython @("-m", "venv", ".venv")
    if ($LASTEXITCODE -ne 0) { Erro "Não consegui criar o ambiente virtual."; Pausar; exit 1 }
    Ok "Ambiente virtual criado"
} else { Ok "Ambiente virtual já existe" }
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# ----------------------------------------------------------------- 5. Dependências
Titulo "5/6 Dependências Python (versões fixadas em requirements.txt)"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Erro "A instalação das dependências falhou. Verifique a conexão com a internet e rode de novo."
    Write-Host "  Se o erro mencionar 'No matching distribution' para ctranslate2/onnxruntime, sua versão do Python não é suportada: instale o Python 3.12."
    Pausar; exit 1
}
Ok "Dependências instaladas"

# ----------------------------------------------------------------- 6. Teste final
Titulo "6/6 Teste final (pastas, perfis, FFmpeg a partir do Python, renderização de 2 s com legenda)"
& $venvPy -m editor pastas | Out-Null
& $venvPy -m editor autoteste
if ($LASTEXITCODE -ne 0) { Erro "O teste final falhou (veja as mensagens acima)."; Pausar; exit 1 }

Write-Host ""
Write-Host "INSTALAÇÃO CONCLUÍDA." -ForegroundColor Green
Write-Host "  Para abrir a interface: clique duas vezes em iniciar-interface.bat"
Write-Host "  Na primeira transcrição, o modelo de voz 'small' (~480 MB) é baixado uma única vez."
Pausar
exit 0
