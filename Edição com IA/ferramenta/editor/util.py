"""Funções de apoio: caminhos, ffprobe, tempo, cores, execução do FFmpeg."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- caminhos

RAIZ = Path(__file__).resolve().parent.parent.parent  # pasta "Edição com IA"
PASTA_BRUTO = RAIZ / "1-Material bruto"
PASTA_IDENTIDADE = RAIZ / "2-Identidade visual e referências"
PASTA_PERFIS = PASTA_IDENTIDADE / "perfis"
PASTA_LOGOS = PASTA_IDENTIDADE / "logos"
PASTA_FONTES = PASTA_IDENTIDADE / "fontes"
PASTA_PROJETOS = RAIZ / "3-Projetos e intermediários"
PASTA_EXPORTADOS = RAIZ / "4-Vídeos exportados"
PASTA_INTERFACE = RAIZ / "ferramenta" / "interface"

EXTENSOES_VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".3gp"}


class ErroEdicao(Exception):
    """Erro com mensagem clara para o usuário."""


def garantir_pastas() -> None:
    for p in (PASTA_BRUTO, PASTA_PERFIS, PASTA_LOGOS, PASTA_FONTES, PASTA_PROJETOS, PASTA_EXPORTADOS):
        p.mkdir(parents=True, exist_ok=True)


def ffmpeg_bin(nome: str = "ffmpeg") -> str:
    caminho = shutil.which(nome)
    if not caminho:
        raise ErroEdicao(
            f"O programa '{nome}' não foi encontrado. Instale o FFmpeg e confira se ele está no PATH "
            f"(no terminal, '{nome} -version' precisa funcionar)."
        )
    return caminho


def nome_seguro(texto: str) -> str:
    texto = re.sub(r"[^\w\-]+", "-", texto.strip(), flags=re.UNICODE)
    texto = re.sub(r"-+", "-", texto).strip("-")
    return texto or "projeto"


# ---------------------------------------------------------------- arquivos

def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_json(caminho: Path) -> dict:
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def gravar_json(caminho: Path, dados: dict) -> None:
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


# ---------------------------------------------------------------- ffprobe

def info_video(caminho: Path) -> dict:
    """Retorna duração, dimensões, fps e presença de áudio/vídeo."""
    cmd = [
        ffmpeg_bin("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(caminho),
    ]
    # UTF-8 explícito: no Windows o padrão (cp1252) falha com acentos nos metadados e a saída chega vazia
    saida = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if saida.returncode != 0:
        raise ErroEdicao(f"Não consegui ler o arquivo '{caminho.name}': {(saida.stderr or '').strip()[:300]}")
    if not saida.stdout or not saida.stdout.strip():
        raise ErroEdicao(f"O ffprobe não devolveu informações sobre '{caminho.name}'. O arquivo pode estar incompleto ou ainda sendo gravado.")
    try:
        dados = json.loads(saida.stdout)
    except json.JSONDecodeError:
        raise ErroEdicao(f"Não consegui interpretar a resposta do ffprobe para '{caminho.name}'.")
    info = {"duracao": float(dados.get("format", {}).get("duration", 0) or 0),
            "largura": 0, "altura": 0, "fps": 30.0, "tem_video": False, "tem_audio": False,
            "rotacao": 0}
    for s in dados.get("streams", []):
        if s.get("codec_type") == "video" and not info["tem_video"]:
            info["tem_video"] = True
            info["largura"] = int(s.get("width", 0))
            info["altura"] = int(s.get("height", 0))
            num, _, den = (s.get("avg_frame_rate") or "30/1").partition("/")
            try:
                info["fps"] = round(float(num) / float(den or 1), 3) if float(den or 1) else 30.0
            except ValueError:
                info["fps"] = 30.0
            rot = 0
            for sd in s.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rot = int(sd["rotation"])
            rot = rot or int((s.get("tags") or {}).get("rotate", 0) or 0)
            info["rotacao"] = rot
            if rot % 180 != 0:
                info["largura"], info["altura"] = info["altura"], info["largura"]
            if not info["duracao"] and s.get("duration"):
                info["duracao"] = float(s["duration"])
        elif s.get("codec_type") == "audio":
            info["tem_audio"] = True
    return info


# ---------------------------------------------------------------- tempo

def formatar_tempo(segundos: float, com_ms: bool = True) -> str:
    segundos = max(0.0, float(segundos))
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    s = segundos % 60
    if com_ms:
        base = f"{m:02d}:{s:06.3f}"
    else:
        base = f"{m:02d}:{int(s):02d}"
    return f"{h:d}:{base}" if h else base


def tempo_srt(segundos: float) -> str:
    segundos = max(0.0, float(segundos))
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    s = int(segundos % 60)
    ms = int(round((segundos - int(segundos)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def tempo_ass(segundos: float) -> str:
    segundos = max(0.0, float(segundos))
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    s = segundos % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def ler_tempo(texto: str) -> float:
    """Aceita '12', '12.5', '1:05', '01:05.250', '0:01:05', '12s', '1m05s'."""
    t = str(texto).strip().lower().replace(",", ".")
    if not t:
        raise ErroEdicao("Tempo vazio.")
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", t)
    if m and any(m.groups()) and ":" not in t:
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
    partes = t.split(":")
    try:
        partes_f = [float(p) for p in partes]
    except ValueError:
        raise ErroEdicao(f"Não entendi o tempo '{texto}'. Use por exemplo 12, 1:05 ou 0:01:05.5")
    total = 0.0
    for p in partes_f:
        total = total * 60 + p
    return total


def ler_intervalo(texto: str) -> tuple[float, float]:
    """'00:12-00:18' ou '12-18' ou '12 a 18'."""
    t = str(texto).strip().replace(" a ", "-").replace("–", "-")
    if t.count("-") != 1:
        raise ErroEdicao(f"Intervalo inválido '{texto}'. Use o formato inicio-fim, por exemplo 00:12-00:18")
    a, b = t.split("-")
    ini, fim = ler_tempo(a), ler_tempo(b)
    if fim <= ini:
        raise ErroEdicao(f"Intervalo inválido '{texto}': o fim precisa ser maior que o início.")
    return ini, fim


# ---------------------------------------------------------------- cores

def hex_para_rgb(cor: str) -> tuple[int, int, int]:
    c = cor.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ErroEdicao(f"Cor inválida: '{cor}'. Use o formato #RRGGBB.")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def cor_ffmpeg(cor: str, alfa: float | None = None) -> str:
    r, g, b = hex_para_rgb(cor)
    base = f"0x{r:02X}{g:02X}{b:02X}"
    if alfa is not None:
        return f"{base}@{alfa}"
    return base


def cor_ass(cor: str, alfa: int = 0) -> str:
    """ASS usa &HAABBGGRR (alfa 0 = opaco, 255 = transparente)."""
    r, g, b = hex_para_rgb(cor)
    return f"&H{alfa:02X}{b:02X}{g:02X}{r:02X}"


# ---------------------------------------------------------------- execução

def escapar_filtro(caminho: str) -> str:
    """Escapa um caminho para uso dentro de filtros do FFmpeg (ass=, drawtext=...)."""
    c = str(caminho).replace("\\", "/")
    c = c.replace(":", "\\:").replace("'", "\\'").replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")
    return c


def executar(cmd: list[str], descricao: str = "comando") -> subprocess.CompletedProcess:
    saida = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if saida.returncode != 0:
        detalhe = (saida.stderr or saida.stdout or "").strip().splitlines()
        detalhe = "\n".join(detalhe[-8:])
        raise ErroEdicao(f"Falha ao executar {descricao}:\n{detalhe}")
    return saida


def executar_ffmpeg_com_progresso(args: list[str], duracao_esperada: float, ao_progredir=None,
                                  descricao: str = "FFmpeg", cwd: Path | None = None) -> None:
    """Roda o ffmpeg mostrando progresso real (lê -progress pipe:1)."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-y", "-nostdin", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats"] + args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", cwd=str(cwd) if cwd else None)
    ultimo = -1.0
    assert proc.stdout is not None
    for linha in proc.stdout:
        linha = linha.strip()
        if linha.startswith("out_time_us=") or linha.startswith("out_time_ms="):
            try:
                valor = int(linha.split("=", 1)[1])
            except ValueError:
                continue
            segundos = valor / 1_000_000
            if duracao_esperada > 0:
                frac = min(1.0, segundos / duracao_esperada)
            else:
                frac = 0.0
            if frac - ultimo >= 0.01 and ao_progredir:
                ao_progredir(frac, segundos)
                ultimo = frac
    proc.wait()
    erro = proc.stderr.read() if proc.stderr else ""
    if proc.returncode != 0:
        linhas = erro.strip().splitlines()[-10:]
        raise ErroEdicao(f"Falha na renderização ({descricao}):\n" + "\n".join(linhas))
    if ao_progredir:
        ao_progredir(1.0, duracao_esperada)


def imprimir(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except BrokenPipeError:  # saída fechada (ex.: "| head"): encerra em silêncio
        try:
            sys.stdout = open(os.devnull, "w")
        finally:
            sys.exit(0)


def barra_progresso(prefixo: str):
    """Retorna um callback que desenha progresso no terminal."""
    def _cb(frac: float, segundos: float = 0.0):
        largura = 30
        cheio = int(frac * largura)
        texto = f"\r{prefixo} [{'#' * cheio}{'.' * (largura - cheio)}] {frac * 100:5.1f}%"
        sys.stdout.write(texto)
        sys.stdout.flush()
        if frac >= 1.0:
            sys.stdout.write("\n")
    return _cb


# ---------------------------------------------------------------- pasta de saída (onde ficam os vídeos editados)

ARQUIVO_CONFIG = RAIZ / "configuracao.json"


def ler_configuracao() -> dict:
    try:
        return ler_json(ARQUIVO_CONFIG) if ARQUIVO_CONFIG.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def gravar_configuracao(novos: dict) -> None:
    atual = ler_configuracao()
    atual.update(novos)
    gravar_json(ARQUIVO_CONFIG, atual)


def validar_pasta_saida(texto: str, criar: bool = True) -> Path:
    """Valida uma pasta escolhida pelo usuário: existe (ou pode ser criada), é gravável e não é uma pasta proibida."""
    texto = (texto or "").strip().strip('"')
    if not texto:
        raise ErroEdicao("Informe o caminho da pasta de destino.")
    pasta = Path(os.path.expandvars(os.path.expanduser(texto)))
    if not pasta.is_absolute():
        raise ErroEdicao(f"Use o caminho completo da pasta (por exemplo C:\\Videos\\Prontos). Recebi: {texto}")
    try:
        pasta_resolvida = pasta.resolve()
        bruto = PASTA_BRUTO.resolve()
        if pasta_resolvida == bruto or bruto in pasta_resolvida.parents:
            raise ErroEdicao("Não salve os vídeos editados dentro de '1-Material bruto': essa pasta é reservada para os originais.")
    except OSError:
        pass
    if not pasta.exists():
        if not criar:
            raise ErroEdicao(f"A pasta não existe: {pasta}")
        try:
            pasta.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ErroEdicao(f"Não consegui criar a pasta '{pasta}': {e.strerror or e}. Escolha outra pasta ou confira se o disco existe.")
    if not pasta.is_dir():
        raise ErroEdicao(f"O caminho não é uma pasta: {pasta}")
    teste = pasta / f".teste-gravacao-{os.getpid()}.tmp"
    try:
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
    except OSError as e:
        raise ErroEdicao(f"Não consigo gravar na pasta '{pasta}' ({e.strerror or e}). Escolha uma pasta em que você tenha permissão, como Documentos ou Vídeos.")
    return pasta


def pasta_saida(dados: dict | None = None, estrito: bool = False) -> Path:
    """Pasta onde os vídeos editados são gravados: a do projeto, senão a padrão da configuração, senão '4-Vídeos exportados'.

    estrito=True (usado ao exportar): se houver uma pasta escolhida e ela não estiver disponível, falha com mensagem clara
    em vez de gravar em outro lugar sem avisar. estrito=False (listagens): cai para a próxima opção."""
    for origem in ((dados or {}).get("pasta_saida"), ler_configuracao().get("pasta_saida")):
        if origem:
            try:
                return validar_pasta_saida(origem)
            except ErroEdicao as e:
                if estrito:
                    raise ErroEdicao(f"A pasta de destino escolhida não está disponível: {e} "
                                     "Escolha outra pasta na seção 7 (ou remova a escolha para usar a pasta padrão).")
                continue
    PASTA_EXPORTADOS.mkdir(parents=True, exist_ok=True)
    return PASTA_EXPORTADOS


def escolher_pasta_janela(inicial: str | None = None, titulo: str = "Escolha a pasta para salvar os vídeos editados") -> str | None:
    """Abre a janela nativa de seleção de pasta (tkinter) num processo separado. Devolve o caminho, '' se cancelou."""
    codigo = (
        "import sys\n"
        "try:\n"
        "    import tkinter as tk\n"
        "    from tkinter import filedialog\n"
        "except Exception:\n"
        "    sys.exit(3)\n"
        "r = tk.Tk(); r.withdraw()\n"
        "try: r.attributes('-topmost', True)\n"
        "except Exception: pass\n"
        "p = filedialog.askdirectory(title=sys.argv[1], initialdir=sys.argv[2] or None, mustexist=False)\n"
        "sys.stdout.buffer.write((p or '').encode('utf-8'))\n"
    )
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([sys.executable, "-c", codigo, titulo, inicial or ""], capture_output=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        raise ErroEdicao("A janela de escolha de pasta ficou aberta por muito tempo e foi fechada. Tente de novo ou digite o caminho.")
    if r.returncode == 3:
        raise ErroEdicao("Este Python não tem o módulo de janelas (tkinter). Digite o caminho da pasta no campo ao lado.")
    if r.returncode != 0:
        raise ErroEdicao("Não consegui abrir a janela de escolha de pasta. Digite o caminho no campo ao lado.")
    return r.stdout.decode("utf-8", errors="replace").strip().replace("/", os.sep) if r.stdout else ""


def abrir_pasta_no_sistema(pasta: Path) -> None:
    """Abre a pasta no Explorador (Windows), Finder (macOS) ou gerenciador de arquivos (Linux)."""
    if sys.platform.startswith("win"):
        os.startfile(str(pasta))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(pasta)])
    else:
        subprocess.Popen(["xdg-open", str(pasta)])
