"""Transcrição local em português brasileiro com marcações de tempo (faster-whisper)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .util import ErroEdicao, ffmpeg_bin, formatar_tempo, ler_tempo

MODELOS = ["tiny", "base", "small", "medium", "large-v3"]
MODELO_PADRAO = "small"

# Limiares de incerteza (conservadores: melhor sinalizar demais do que inventar)
LOGPROB_MINIMO = -0.7
NO_SPEECH_MAXIMO = 0.6
PROB_PALAVRA_MINIMA = 0.45
COMPRESSAO_MAXIMA = 2.4

MARCA_INCERTA = "[?]"


def extrair_audio(video: Path, destino: Path) -> Path:
    """Extrai o áudio em WAV mono 16 kHz (formato ideal para o Whisper)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin(), "-hide_banner", "-y", "-loglevel", "error", "-i", str(video),
           "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destino)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise ErroEdicao("Não consegui extrair o áudio do vídeo:\n" + r.stderr.strip()[-400:])
    return destino


def _carregar_wav(caminho: Path):
    """Lê o WAV mono 16 kHz como array float32 (evita depender do PyAV)."""
    import wave
    import numpy as np
    with wave.open(str(caminho), "rb") as w:
        if w.getnchannels() != 1 or w.getframerate() != 16000 or w.getsampwidth() != 2:
            raise ErroEdicao("Áudio intermediário fora do esperado (precisa ser mono, 16 kHz, 16 bits).")
        dados = w.readframes(w.getnframes())
    return np.frombuffer(dados, dtype=np.int16).astype(np.float32) / 32768.0


def transcrever(audio: Path, duracao: float, modelo: str = MODELO_PADRAO,
                ao_progredir=None, dispositivo: str = "cpu") -> dict:
    """Transcreve o áudio e devolve segmentos com palavras, tempos e marcações de incerteza."""
    if modelo not in MODELOS:
        raise ErroEdicao(f"Modelo '{modelo}' inválido. Opções: {', '.join(MODELOS)}")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ErroEdicao("O pacote 'faster-whisper' não está instalado. "
                         "Rode o instalador (instalar.sh / instalar.ps1) ou 'pip install faster-whisper'.")

    if ao_progredir:
        ao_progredir(0.0, f"carregando modelo '{modelo}' (na primeira vez ele é baixado)")
    tipo_computo = "int8" if dispositivo == "cpu" else "float16"
    whisper = WhisperModel(modelo, device=dispositivo, compute_type=tipo_computo)

    segmentos_iter, info = whisper.transcribe(
        _carregar_wav(audio),
        language="pt",
        task="transcribe",
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 200},
        condition_on_previous_text=False,      # reduz "invenção" de texto repetido
        hallucination_silence_threshold=2.0,   # descarta texto gerado sobre silêncio longo
        initial_prompt="Transcrição em português do Brasil, com pontuação.",
    )

    segmentos = []
    for n, seg in enumerate(segmentos_iter, start=1):
        texto = (seg.text or "").strip()
        if not texto:
            continue
        palavras = []
        for w in (seg.words or []):
            palavras.append({"p": w.word.strip(), "inicio": round(float(w.start), 3),
                             "fim": round(float(w.end), 3), "prob": round(float(w.probability), 3)})
        motivos = []
        if seg.avg_logprob < LOGPROB_MINIMO:
            motivos.append("confiança baixa no trecho")
        if seg.no_speech_prob > NO_SPEECH_MAXIMO:
            motivos.append("pode não haver fala aqui")
        if seg.compression_ratio > COMPRESSAO_MAXIMA:
            motivos.append("texto repetitivo (possível invenção)")
        palavras_incertas = [w["p"] for w in palavras if w["prob"] < PROB_PALAVRA_MINIMA]
        if palavras_incertas:
            motivos.append("palavras incertas: " + ", ".join(palavras_incertas[:6]))
        confianca = round(min(1.0, max(0.0, 1.0 + seg.avg_logprob)), 2)
        segmentos.append({
            "id": n,
            "inicio": round(float(seg.start), 3),
            "fim": round(float(seg.end), 3),
            "texto": texto,
            "texto_original": texto,
            "confianca": confianca,
            "incerto": bool(motivos),
            "motivo_incerteza": "; ".join(motivos),
            "palavras": palavras,
            "revisado": False,
        })
        if ao_progredir and duracao > 0:
            ao_progredir(min(0.99, float(seg.end) / duracao), f"transcrevendo ({formatar_tempo(seg.end, False)})")
    if ao_progredir:
        ao_progredir(1.0, "transcrição concluída")
    return {"modelo": modelo, "idioma": info.language, "probabilidade_idioma": round(float(info.language_probability), 2),
            "segmentos": segmentos}


# ---------------------------------------------------------------- revisão

def texto_com_marcas(seg: dict) -> str:
    """Texto do segmento com [?] após palavras incertas (só quando ainda não foi revisado)."""
    if seg.get("revisado") or seg.get("texto") != seg.get("texto_original"):
        return seg["texto"]
    palavras = seg.get("palavras") or []
    if not palavras:
        return seg["texto"]
    partes = []
    for w in palavras:
        p = w["p"]
        if w.get("prob", 1.0) < PROB_PALAVRA_MINIMA:
            p = f"{p}{MARCA_INCERTA}"
        partes.append(p)
    return " ".join(partes)


def texto_revisao(transcricao: dict) -> str:
    linhas = [
        "# Transcrição para revisão. Edite apenas o texto depois da barra | .",
        "# Não altere os números entre colchetes nem os tempos.",
        f"# Palavras seguidas de {MARCA_INCERTA} são incertas. Linhas com ⚠ precisam de conferência.",
        "# Para deixar um trecho sem legenda, apague o texto depois da barra (o áudio continua).",
        "",
    ]
    for seg in transcricao["segmentos"]:
        aviso = " ⚠" if seg.get("incerto") and not seg.get("revisado") else ""
        linhas.append(f"[{seg['id']}] {formatar_tempo(seg['inicio'])} --> {formatar_tempo(seg['fim'])}{aviso} | "
                      f"{texto_com_marcas(seg)}")
    return "\n".join(linhas) + "\n"


_RE_LINHA = re.compile(r"^\[(\d+)\]\s*([\d:.,]+)\s*-->\s*([\d:.,]+)\s*⚠?\s*\|\s?(.*)$")


def aplicar_texto_revisado(transcricao: dict, conteudo: str) -> int:
    """Lê o texto editado pelo usuário e atualiza os segmentos. Retorna quantos mudaram."""
    por_id = {s["id"]: s for s in transcricao["segmentos"]}
    alterados = 0
    for linha in conteudo.splitlines():
        linha = linha.rstrip()
        if not linha or linha.startswith("#"):
            continue
        m = _RE_LINHA.match(linha)
        if not m:
            raise ErroEdicao(f"Linha fora do padrão esperado: '{linha[:60]}'. "
                             f"Mantenha o formato [n] inicio --> fim | texto.")
        ident = int(m.group(1))
        if ident not in por_id:
            raise ErroEdicao(f"O trecho [{ident}] não existe na transcrição.")
        novo = m.group(4).strip().replace(MARCA_INCERTA, "").strip()
        seg = por_id[ident]
        novo_ini, novo_fim = ler_tempo(m.group(2)), ler_tempo(m.group(3))
        if abs(novo_ini - seg["inicio"]) > 0.01 or abs(novo_fim - seg["fim"]) > 0.01:
            seg["inicio"], seg["fim"] = round(novo_ini, 3), round(novo_fim, 3)
            alterados += 1
        if novo != seg["texto"] or not seg.get("revisado"):
            if novo != seg["texto"]:
                alterados += 1
            seg["texto"] = novo
            seg["revisado"] = True
            seg["incerto"] = False
    return alterados


def corrigir_segmento(transcricao: dict, ident: int, texto: str) -> dict:
    for seg in transcricao["segmentos"]:
        if seg["id"] == ident:
            seg["texto"] = texto.strip()
            seg["revisado"] = True
            seg["incerto"] = False
            return seg
    raise ErroEdicao(f"O trecho [{ident}] não existe na transcrição.")


def segmentos_incertos(transcricao: dict) -> list[dict]:
    return [s for s in transcricao["segmentos"] if s.get("incerto") and not s.get("revisado")]
