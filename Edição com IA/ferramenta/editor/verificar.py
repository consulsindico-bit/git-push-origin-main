"""Comprovação de funcionamento: originais preservados, exportação íntegra, cortes e legendas coerentes."""
from __future__ import annotations

from pathlib import Path

from .legendas import construir_legendas
from .estilos import perfil_do_projeto
from .projeto import caminho_origem, duracao_editada
from .render import verificar_saida
from .util import sha256_arquivo


def verificar_projeto(pasta: Path, dados: dict) -> dict:
    relatorio = {"ok": True, "itens": []}

    def item(nome: str, ok: bool, detalhe: str = ""):
        relatorio["itens"].append({"nome": nome, "ok": ok, "detalhe": detalhe})
        if not ok:
            relatorio["ok"] = False

    # 1) Original preservado
    try:
        origem = caminho_origem(dados)
        atual = sha256_arquivo(origem)
        igual = atual == dados["origem"]["sha256"]
        item("Original preservado (hash SHA-256 idêntico ao da importação)", igual,
             origem.name if igual else f"{origem.name}: o arquivo mudou desde a importação!")
    except Exception as e:  # noqa: BLE001
        item("Original preservado", False, str(e))

    # 2) Exportações abrem e têm imagem + áudio; duração bate com os cortes
    exportacoes = dados.get("exportacoes") or []
    if not exportacoes:
        item("Exportação", False, "nenhuma exportação registrada ainda")
    for exp in exportacoes[-5:]:
        arquivo = Path(exp["arquivo"])
        chk = verificar_saida(arquivo)
        if not chk.get("ok"):
            item(f"Exportado abre e tem vídeo+áudio: {arquivo.name}", False, chk.get("erro", "faltam faixas"))
            continue
        item(f"Exportado abre e tem vídeo+áudio: {arquivo.name}", True,
             f"{chk['largura']}x{chk['altura']}, {chk['duracao']:.2f}s, {chk['tamanho_mb']} MB")
        prevista = float(exp.get("duracao_prevista", 0))
        diff = abs(chk["duracao"] - prevista)
        item(f"Duração corresponde aos cortes: {arquivo.name}", diff <= 0.25,
             f"prevista {prevista:.2f}s, obtida {chk['duracao']:.2f}s (diferença {diff:.2f}s)")
        srt = exp.get("srt")
        if srt:
            item(f"Legendas SRT ao lado do vídeo: {Path(srt).name}", Path(srt).exists(), "")

    # 3) Legendas dentro da duração editada e sem sobreposição
    if dados.get("transcricao"):
        perfil = perfil_do_projeto(dados)
        legendas = construir_legendas(dados, perfil)
        dur = duracao_editada(dados)
        fora = [l for l in legendas if l["fim"] > dur + 0.05 or l["inicio"] < -0.01]
        sobrep = [i for i in range(len(legendas) - 1) if legendas[i]["fim"] > legendas[i + 1]["inicio"] + 0.01]
        item("Legendas dentro da linha do tempo cortada", not fora, f"{len(legendas)} legendas, duração editada {dur:.2f}s")
        item("Legendas sem sobreposição", not sobrep, "")
        incertos = [s["id"] for s in dados["transcricao"]["segmentos"] if s.get("incerto") and not s.get("revisado")]
        item("Trechos incertos revisados", not incertos,
             "todos revisados" if not incertos else f"ainda sem revisão: {incertos}")
    else:
        item("Transcrição", False, "ainda não transcrito")
    return relatorio
