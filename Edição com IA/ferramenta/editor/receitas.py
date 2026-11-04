"""Receitas por tipo de vídeo: combos salvos de estilo, elementos, posições e configurações,
reaplicáveis em projetos novos (aviso, regra, depoimento, institucional...).

Uma receita guarda: perfil, formato, enquadramento (modo), legendas (modo, altura, destaques), áudio,
marca d'água, assinatura (com tempos relativos ao fim), título/encerramento, zoom automático e os elementos
como "esqueleto" (tipo, posição, animação, tamanho, texto e tempos relativos: início do vídeo, fim do vídeo
ou fala de número N).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import cartoes as mod_cartoes
from .util import PASTA_IDENTIDADE, ErroEdicao, gravar_json, ler_json, nome_seguro

PASTA_RECEITAS = PASTA_IDENTIDADE / "receitas"


def listar() -> list[dict]:
    PASTA_RECEITAS.mkdir(parents=True, exist_ok=True)
    saida = []
    for arq in sorted(PASTA_RECEITAS.glob("*.json")):
        try:
            d = ler_json(arq)
        except Exception:  # noqa: BLE001
            continue
        saida.append({"id": arq.stem, "nome": d.get("nome", arq.stem), "descricao": d.get("descricao", ""),
                      "elementos": len(d.get("elementos") or []), "perfil": d.get("perfil"), "criada_em": d.get("criada_em")})
    return saida


def _relativo(dados: dict, t: float) -> dict:
    """Expressa um instante de forma reaproveitável: relativo ao início, ao fim ou a uma fala."""
    dur = float(dados["origem"]["info"]["duracao"])
    if t <= 8.0:
        return {"ancora": "inicio", "desloc": round(t, 2)}
    if dur - t <= 8.0:
        return {"ancora": "fim", "desloc": round(dur - t, 2)}
    for seg in (dados.get("transcricao") or {}).get("segmentos", []):
        if float(seg["inicio"]) - 0.3 <= t <= float(seg["fim"]):
            return {"ancora": "fala", "fala": seg["id"], "desloc": round(t - float(seg["inicio"]), 2)}
    return {"ancora": "fracao", "fracao": round(t / dur, 3)}


def _absoluto(dados: dict, rel: dict, duracao_video: float) -> float:
    a = rel.get("ancora")
    if a == "inicio":
        return float(rel.get("desloc", 0))
    if a == "fim":
        return max(0.0, duracao_video - float(rel.get("desloc", 0)))
    if a == "fala":
        segs = (dados.get("transcricao") or {}).get("segmentos", [])
        seg = next((s for s in segs if s["id"] == rel.get("fala")), None)
        if seg is None and segs:
            seg = segs[min(len(segs) - 1, max(0, int(rel.get("fala", 1)) - 1))]
        return (float(seg["inicio"]) if seg else 0.0) + float(rel.get("desloc", 0))
    return float(rel.get("fracao", 0)) * duracao_video


def salvar(dados: dict, nome: str, descricao: str = "", incluir_textos: bool = True) -> Path:
    if not nome.strip():
        raise ErroEdicao("Dê um nome à receita (ex.: aviso-condominio, regra, depoimento).")
    PASTA_RECEITAS.mkdir(parents=True, exist_ok=True)
    dur = float(dados["origem"]["info"]["duracao"])
    elementos = []
    for c in dados.get("cartoes", []):
        if not c.get("ativo", True):
            continue
        e = {k: c.get(k) for k in ("tipo", "posicao", "y", "x", "animacao", "tamanho", "subtipo", "limite", "numero", "destaque", "descricao")}
        e["texto"] = c.get("texto") if incluir_textos else ""
        e["itens"] = c.get("itens") if incluir_textos else None
        e["imagem"], e["video"] = c.get("imagem"), c.get("video")
        e["inicio"] = _relativo(dados, float(c["inicio"]))
        e["duracao"] = round(float(c["fim"]) - float(c["inicio"]), 2)
        elementos.append(e)
    ass = dict(dados.get("assinatura") or {})
    if ass.get("ativo"):
        ass["inicio_rel"] = _relativo(dados, float(ass.get("inicio", 0)))
        ass["duracao"] = round(float(ass.get("fim", 0)) - float(ass.get("inicio", 0)), 2)
    receita = {
        "nome": nome.strip(), "descricao": descricao.strip(), "criada_em": dt.datetime.now().isoformat(timespec="seconds"),
        "perfil": dados.get("perfil"), "formato": dados.get("formato"), "enquadramento_modo": (dados.get("enquadramento") or {}).get("modo", "cortar"),
        "legendas": {k: v for k, v in (dados.get("legendas") or {}).items() if k in ("ativas", "modo", "posicao_percentual", "destaques")},
        "audio": dados.get("audio"), "marca_dagua": dados.get("marca_dagua"), "assinatura": ass,
        "titulo": dados.get("titulo"), "encerramento": dados.get("encerramento"), "logo": dados.get("logo"),
        "zoom_automatico": any(z.get("automatico") for z in dados.get("zooms") or []),
        "elementos": elementos,
    }
    arq = PASTA_RECEITAS / f"{nome_seguro(nome)}.json"
    gravar_json(arq, receita)
    return arq


def aplicar(dados: dict, identificador: str, substituir_elementos: bool = True) -> dict:
    arq = PASTA_RECEITAS / f"{nome_seguro(identificador)}.json"
    if not arq.exists():
        arq = PASTA_RECEITAS / f"{identificador}.json"
    if not arq.exists():
        raise ErroEdicao(f"Receita '{identificador}' não encontrada. Receitas: {', '.join(r['id'] for r in listar()) or '(nenhuma)'}")
    r = ler_json(arq)
    dur = float(dados["origem"]["info"]["duracao"])
    for chave in ("perfil", "formato"):
        if r.get(chave):
            dados[chave] = r[chave]
    dados.setdefault("enquadramento", {})["modo"] = r.get("enquadramento_modo", "cortar")
    dados.setdefault("legendas", {}).update(r.get("legendas") or {})
    for chave in ("audio", "marca_dagua", "titulo", "encerramento", "logo"):
        if r.get(chave):
            dados[chave] = dict(r[chave])
    ass = dict(r.get("assinatura") or {})
    if ass.get("ativo") and ass.get("inicio_rel"):
        ini = _absoluto(dados, ass["inicio_rel"], dur)
        ass["inicio"], ass["fim"] = round(ini, 2), round(min(dur, ini + float(ass.get("duracao", 4))), 2)
        ass.pop("inicio_rel", None); ass.pop("duracao", None)
    dados["assinatura"] = ass
    if substituir_elementos:
        dados["cartoes"] = []
    criados, pulados = 0, 0
    for e in r.get("elementos") or []:
        ini = _absoluto(dados, e["inicio"], dur)
        fim = min(dur, ini + float(e.get("duracao", 3)))
        if fim - ini < 0.3:
            pulados += 1
            continue
        texto = e.get("texto") or ""
        if e["tipo"] in ("titulo", "pergunta", "check", "alerta", "texto", "topico", "palavra", "emoji") and not texto:
            texto = {"titulo": "TÍTULO AQUI", "pergunta": "PERGUNTA AQUI?", "check": "Texto aqui", "alerta": "Texto aqui", "texto": "Texto aqui",
                     "topico": "Tópico aqui", "palavra": "PALAVRA", "emoji": "💡"}[e["tipo"]]
        try:
            mod_cartoes.adicionar(dados, e["tipo"], texto, ini, fim, posicao=e.get("posicao"), destaque=e.get("destaque") or "",
                                  itens=e.get("itens"), y=e.get("y"), numero=e.get("numero"), descricao=e.get("descricao") or "",
                                  imagem=e.get("imagem"), animacao=e.get("animacao"), tamanho=e.get("tamanho"), subtipo=e.get("subtipo"),
                                  limite=e.get("limite"), video=e.get("video"), permitir_duplicado=True)
            if e.get("x"):
                dados["cartoes"][-1]["x"] = e["x"]
            criados += 1
        except ErroEdicao:
            pulados += 1
    if r.get("zoom_automatico") and dados.get("transcricao"):
        from .projeto import zooms_automaticos
        try:
            zooms_automaticos(dados)
        except ErroEdicao:
            pass
    return {"receita": r["nome"], "elementos_criados": criados, "pulados": pulados}


def remover(identificador: str) -> bool:
    arq = PASTA_RECEITAS / f"{nome_seguro(identificador)}.json"
    if arq.exists():
        arq.unlink()
        return True
    return False
