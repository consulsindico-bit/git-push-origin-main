"""Detecção de silêncios (sugestões para revisão) e cortes a partir deles."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .projeto import adicionar_remocao, duracao_original, remocoes_mescladas
from .util import ErroEdicao, ffmpeg_bin

MARGEM_PADRAO = 0.15   # segundos mantidos de cada lado do silêncio, para o corte não ficar seco


def detectar_silencios(audio_ou_video: Path, duracao_minima: float = 0.7, limiar_db: float = -35.0) -> list[dict]:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(audio_ou_video), "-vn",
           "-af", f"silencedetect=n={limiar_db}dB:d={duracao_minima}", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ErroEdicao("Falha ao analisar silêncios:\n" + r.stderr.strip()[-400:])
    inicios = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", r.stderr)]
    fins = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", r.stderr)]
    silencios = []
    for n, ini in enumerate(inicios, start=1):
        fim = next((f for f in fins if f > ini), None)
        if fim is None:
            continue
        silencios.append({"id": n, "inicio": round(ini, 3), "fim": round(fim, 3), "duracao": round(fim - ini, 3)})
    return silencios


def sugerir(dados: dict, origem: Path, duracao_minima: float = 0.7, limiar_db: float = -35.0) -> list[dict]:
    silencios = detectar_silencios(origem, duracao_minima, limiar_db)
    ja_removidos = remocoes_mescladas(dados)
    for s in silencios:
        # conta como já removido se uma remoção cobre o miolo do silêncio (descontadas as margens)
        miolo_ini, miolo_fim = s["inicio"] + MARGEM_PADRAO + 0.02, s["fim"] - MARGEM_PADRAO - 0.02
        s["ja_removido"] = miolo_fim <= miolo_ini or any(a <= miolo_ini and miolo_fim <= b for a, b in ja_removidos)
        s["selecionado"] = not s["ja_removido"]
    dados["silencios_sugeridos"] = silencios
    dados["silencios_parametros"] = {"duracao_minima": duracao_minima, "limiar_db": limiar_db}
    return silencios


def aplicar(dados: dict, ids: list[int] | None = None, margem: float = MARGEM_PADRAO) -> list[dict]:
    sugeridos = dados.get("silencios_sugeridos") or []
    if not sugeridos:
        raise ErroEdicao("Ainda não há silêncios sugeridos. Rode primeiro a sugestão de silêncios.")
    escolhidos = [s for s in sugeridos if (ids is None and s.get("selecionado", True)) or (ids and s["id"] in ids)]
    dur = duracao_original(dados)
    aplicados = []
    for s in escolhidos:
        ini = s["inicio"] + (0 if s["inicio"] <= 0.05 else margem)
        fim = s["fim"] - (0 if s["fim"] >= dur - 0.05 else margem)
        if fim - ini < 0.25:
            continue
        if s.get("ja_removido"):
            continue
        item = adicionar_remocao(dados, ini, fim, "silencio", f"silêncio {s['id']} ({s['duracao']:.1f}s)")
        s["ja_removido"] = True
        aplicados.append(item)
    return aplicados


def desfazer(dados: dict) -> int:
    antes = len(dados["remocoes"])
    dados["remocoes"] = [r for r in dados["remocoes"] if r.get("motivo") != "silencio"]
    for s in dados.get("silencios_sugeridos") or []:
        s["ja_removido"] = False
    return antes - len(dados["remocoes"])
