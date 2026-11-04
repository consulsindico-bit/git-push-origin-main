"""Cortes inteligentes: sugere remover vícios de fala e repetições, sempre com revisão antes de aplicar."""
from __future__ import annotations

import re
import unicodedata

from .projeto import adicionar_remocao

VICIOS = {"é", "eh", "hum", "hmm", "ahn", "ah", "uh", "né", "tipo", "assim", "então", "aí", "ok", "tá", "ta", "bom", "olha", "veja", "entendeu"}
# Palavras que só contam como vício quando aparecem sozinhas entre pausas (curtas) ou repetidas
VICIOS_FORTES = {"e", "eh", "hum", "hmm", "ahn", "ah", "uh", "ne"}   # comparados sem acento
MARGEM = 0.05


def _norm(p: str) -> str:
    p = unicodedata.normalize("NFKD", p.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", p)


def sugerir(dados: dict) -> list[dict]:
    """Devolve sugestões [{id, inicio, fim, motivo, texto, fala}] a partir das palavras da transcrição."""
    transcricao = dados.get("transcricao")
    if not transcricao:
        return []
    sugestoes = []
    n = 0
    for seg in transcricao["segmentos"]:
        palavras = [w for w in (seg.get("palavras") or []) if w.get("p")]
        for i, w in enumerate(palavras):
            chave = _norm(w["p"])
            dur = float(w["fim"]) - float(w["inicio"])
            # 1) vício forte isolado (é..., hum, né) com alguma folga em volta
            if chave in VICIOS_FORTES:
                antes = palavras[i - 1] if i > 0 else None
                depois = palavras[i + 1] if i + 1 < len(palavras) else None
                folga = (float(w["inicio"]) - float(antes["fim"]) if antes else 0.3) + (float(depois["inicio"]) - float(w["fim"]) if depois else 0.3)
                if dur >= 0.4 or (dur >= 0.2 and folga >= 0.2):
                    n += 1
                    sugestoes.append({"id": n, "inicio": round(float(w["inicio"]) - MARGEM, 3), "fim": round(float(w["fim"]) + MARGEM, 3),
                                      "motivo": "vício de fala", "texto": w["p"], "fala": seg["id"]})
                    continue
            # 2) palavra repetida em sequência ("o o síndico", "que que")
            if i + 1 < len(palavras) and chave and chave == _norm(palavras[i + 1]["p"]):
                n += 1
                sugestoes.append({"id": n, "inicio": round(float(w["inicio"]) - MARGEM, 3), "fim": round(float(palavras[i + 1]["inicio"]) - 0.02, 3),
                                  "motivo": "palavra repetida", "texto": f"{w['p']} {palavras[i + 1]['p']}", "fala": seg["id"]})
        # 3) frase repetida (segmento igual ao anterior)
    anterior = None
    for seg in transcricao["segmentos"]:
        chave = _norm(seg["texto"])
        if anterior and chave and chave == _norm(anterior["texto"]) and len(chave) > 12:
            n += 1
            sugestoes.append({"id": n, "inicio": round(float(anterior["inicio"]), 3), "fim": round(float(anterior["fim"]), 3),
                              "motivo": "frase repetida (primeira ocorrência)", "texto": anterior["texto"][:60], "fala": anterior["id"]})
        anterior = seg
    sugestoes.sort(key=lambda s: s["inicio"])
    for k, s in enumerate(sugestoes, start=1):
        s["id"] = k
    dados["vicios_sugeridos"] = sugestoes
    return sugestoes


def aplicar(dados: dict, ids: list[int] | None = None) -> list[dict]:
    sugeridos = dados.get("vicios_sugeridos") or sugerir(dados)
    escolhidos = [s for s in sugeridos if ids is None or s["id"] in ids]
    aplicados = []
    for s in escolhidos:
        if s["fim"] - s["inicio"] < 0.08:
            continue
        item = adicionar_remocao(dados, s["inicio"], s["fim"], "vicio", f"{s['motivo']}: {s['texto']}")
        aplicados.append(item)
    dados["vicios_sugeridos"] = [s for s in sugeridos if s not in escolhidos]
    return aplicados


def desfazer(dados: dict) -> int:
    antes = len(dados.get("remocoes", []))
    dados["remocoes"] = [r for r in dados.get("remocoes", []) if r.get("motivo") != "vicio"]
    return antes - len(dados["remocoes"])
