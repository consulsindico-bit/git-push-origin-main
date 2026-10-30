"""Interpretação local (sem internet) de pedidos simples em português.

Cobre os pedidos mais comuns: duração máxima, pausas/silêncios, legendas, formato, título,
encerramento, logo, volume, perfil e cortes por tempo. O que não for reconhecido é devolvido
como "não entendido", para ser decidido na conversa com o Claude.
"""
from __future__ import annotations

import re

from .projeto import adicionar_remocao
from .util import ErroEdicao, ler_tempo

_RE_DURACAO = re.compile(r"(?:até|ate|máximo|maximo|no máximo|no maximo|de)?\s*(\d+(?:[.,]\d+)?)\s*(segundos?|seg|s|minutos?|min)\b")
_RE_TITULO = re.compile(r"t[íi]tulo\s*[:\"“']?\s*[\"“']?([^\"”'\n.;]+)[\"”']?")
_RE_ENCERRAMENTO = re.compile(r"encerramento\s*[:\"“']\s*[\"“']?([^\"”'\n;]+)[\"”']?")
_RE_VOLUME = re.compile(r"(?:volume|voz)[^\d+-]*([+-]?\d+(?:[.,]\d+)?)\s*db")
_RE_CORTE = re.compile(r"(?:cort(?:e|ar)|remov(?:a|er)|tir(?:e|ar))\s+(?:o trecho\s+)?(?:de|entre)\s+([\d:.,]+)\s*(?:a|até|ate|e|-)\s+([\d:.,]+)")


def _normalizar(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())


def interpretar(dados: dict, pedido: str) -> dict:
    """Aplica ao projeto o que for reconhecido e devolve um relatório."""
    original = pedido.strip()
    t = _normalizar(original)
    entendido: list[str] = []
    acoes: list[str] = []          # ações que a interface/CLI executam depois (ex.: sugerir silêncios)
    nao_entendido: list[str] = []
    frases = [f.strip() for f in re.split(r"[.;\n]| e (?=\w)|, ", original) if f.strip()]
    cobertas: set[str] = set()

    def marcar(frase_chave: str):
        for f in frases:
            if frase_chave in _normalizar(f):
                cobertas.add(f)

    # Duração máxima
    m = _RE_DURACAO.search(t)
    if m and re.search(r"\b(até|ate|máximo|maximo|segundos?|minutos?)\b", t):
        valor = float(m.group(1).replace(",", "."))
        if m.group(2).startswith("min"):
            valor *= 60
        dados["duracao_alvo"] = valor
        entendido.append(f"duração máxima de {valor:.0f} segundos")
        acoes.append("verificar_duracao")
        for f in frases:
            if _RE_DURACAO.search(_normalizar(f)):
                cobertas.add(f)

    # Pausas / silêncios
    if re.search(r"(pausas?|sil[êe]ncios?)", t):
        if re.search(r"(mant(er|enha)|deixe|sem (retirar|remover|tirar)) (as )?(pausas?|sil[êe]ncios?)", t):
            entendido.append("manter as pausas (sem remoção de silêncios)")
        else:
            entendido.append("remover pausas longas (vou sugerir os silêncios para você revisar antes de aplicar)")
            acoes.append("sugerir_silencios")
        marcar("pausa"); marcar("silêncio"); marcar("silencio")

    # Legendas
    if re.search(r"legendas?", t):
        if re.search(r"(sem|tire|tirar|remova|remover|desativ)\w*\s+(as\s+)?legendas?", t):
            dados.setdefault("legendas", {})["ativas"] = False
            entendido.append("legendas desativadas")
        else:
            dados.setdefault("legendas", {})["ativas"] = True
            entendido.append("legendas ativadas (sincronizadas com a transcrição)")
            if not dados.get("transcricao"):
                acoes.append("transcrever")
        marcar("legenda")

    # Formato
    formato = None
    if re.search(r"(vertical|9:16|9x16|reels|tiktok|shorts|stories|story)", t):
        formato = "9:16"
    elif re.search(r"(quadrad|1:1|1x1|feed)", t):
        formato = "1:1"
    elif re.search(r"(horizontal|16:9|16x9|youtube|widescreen)", t):
        formato = "16:9"
    if formato:
        dados["formato"] = formato
        entendido.append(f"formato {formato}")
        for chave in ("vertical", "9:16", "9x16", "reels", "tiktok", "shorts", "stories", "quadrad", "1:1", "1x1",
                      "horizontal", "16:9", "16x9", "youtube"):
            marcar(chave)

    # Título
    m = _RE_TITULO.search(original if "ítulo" in original or "itulo" in original else "")
    if m:
        texto = m.group(1).strip().strip("\"'“”")
        if texto and not re.fullmatch(r"(e|com|sem)", texto):
            dados.setdefault("titulo", {})["texto"] = texto
            entendido.append(f"título: “{texto}”")
        marcar("título"); marcar("titulo")
    elif re.search(r"sem t[íi]tulo", t):
        dados.setdefault("titulo", {})["texto"] = ""
        entendido.append("sem título")
        marcar("título"); marcar("titulo")

    # Encerramento
    if "encerramento" in t:
        enc = dados.setdefault("encerramento", {})
        if re.search(r"sem encerramento", t):
            enc["ativo"] = False
            entendido.append("sem encerramento")
        else:
            enc["ativo"] = True
            m = _RE_ENCERRAMENTO.search(original)
            if m:
                enc["texto"] = m.group(1).strip()
                entendido.append(f"encerramento com o texto “{enc['texto']}”")
            else:
                entendido.append("encerramento ativado (texto do perfil)")
        marcar("encerramento")

    # Logo
    if re.search(r"\blogo(marca|tipo)?\b", t):
        lg = dados.setdefault("logo", {})
        if re.search(r"sem (a )?logo", t):
            lg["ativo"] = False
            entendido.append("sem logo")
        else:
            lg["ativo"] = True
            entendido.append("logo ativada (arquivo do perfil ou do projeto)")
        marcar("logo")

    # Volume
    m = _RE_VOLUME.search(t)
    if m:
        ganho = float(m.group(1).replace(",", "."))
        dados.setdefault("audio", {})["ganho_db"] = ganho
        entendido.append(f"ganho de voz {ganho:+.1f} dB")
        marcar("volume"); marcar("voz")
    elif re.search(r"(aument\w+|mais alt\w+|sub\w+) (o )?(volume|a voz|voz)", t):
        dados.setdefault("audio", {})["ganho_db"] = float(dados.get("audio", {}).get("ganho_db", 0)) + 3.0
        entendido.append("volume da voz +3 dB")
        marcar("volume"); marcar("voz")
    elif re.search(r"(diminu\w+|mais baix\w+|abaix\w+|reduz\w+) (o )?(volume|a voz|voz)", t):
        dados.setdefault("audio", {})["ganho_db"] = float(dados.get("audio", {}).get("ganho_db", 0)) - 3.0
        entendido.append("volume da voz -3 dB")
        marcar("volume"); marcar("voz")
    elif re.search(r"normaliz\w+", t):
        dados.setdefault("audio", {})["normalizar"] = True
        entendido.append("normalização do áudio ativada")
        marcar("normaliz")

    # Perfil
    if re.search(r"consul", t):
        dados["perfil"] = "consul-sindico"
        entendido.append("perfil Consul Síndico (institucional)")
        marcar("consul")
    elif re.search(r"\bpessoal\b", t):
        dados["perfil"] = "pessoal"
        entendido.append("perfil pessoal")
        marcar("pessoal")

    # Cortes por tempo
    for m in _RE_CORTE.finditer(t):
        try:
            ini, fim = ler_tempo(m.group(1)), ler_tempo(m.group(2))
            adicionar_remocao(dados, ini, fim, "manual", "pedido por descrição")
            entendido.append(f"remover o trecho de {m.group(1)} a {m.group(2)}")
        except ErroEdicao as e:
            nao_entendido.append(f"corte '{m.group(0)}': {e}")
        for f in frases:
            if m.group(0) in _normalizar(f):
                cobertas.add(f)

    # Pedidos que exigem julgamento (feitos na conversa)
    if re.search(r"(ideia principal|mais importante|resum\w+|essencial|melhores partes)", t):
        acoes.append("propor_cortes")
        entendido.append("manter a ideia principal: isso exige escolher trechos; vou propor os cortes na conversa antes de renderizar")
        marcar("ideia principal"); marcar("importante"); marcar("resum"); marcar("essencial")

    for f in frases:
        if f not in cobertas and not any(f in c for c in cobertas):
            nao_entendido.append(f)
    return {"pedido": original, "entendido": entendido, "acoes": sorted(set(acoes)), "nao_entendido": nao_entendido}
