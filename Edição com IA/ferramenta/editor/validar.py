"""Validação antes da prévia/exportação: texto cortado, área segura, sobreposições, legenda coberta,
texto longo demais, contraste fraco e elementos duplicados. Cada problema cita o elemento e o instante."""
from __future__ import annotations

from pathlib import Path

from .cartoes import planejar_sobreposicoes
from .estilos import perfil_do_projeto
from .legendas import construir_legendas, tamanho_fonte
from .projeto import dimensoes_formato, mapear_intervalo
from .util import ErroEdicao, hex_para_rgb

# Área segura (fração do quadro) por formato: fora dela, botões e textos das redes podem cobrir o conteúdo
AREA_SEGURA = {
    "9:16": {"esq": 0.05, "dir": 0.12, "topo": 0.10, "base": 0.20},   # Reels/TikTok/Shorts: ícones à direita (metade de baixo), legenda e barra embaixo
    "1:1": {"esq": 0.04, "dir": 0.04, "topo": 0.06, "base": 0.10},
    "16:9": {"esq": 0.04, "dir": 0.04, "topo": 0.06, "base": 0.12},
}
MAX_LINHAS = {"titulo": 4, "pergunta": 3, "check": 3, "alerta": 3, "texto": 4, "topico": 4, "palavra": 2, "resumo": 10}


def _luminancia(cor: str) -> float:
    def canal(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hex_para_rgb(cor)
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(cor1: str, cor2: str) -> float:
    l1, l2 = _luminancia(cor1), _luminancia(cor2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _bbox(arquivo: str, x: int, y: int) -> tuple[int, int, int, int] | None:
    from PIL import Image
    with Image.open(arquivo) as im:
        alfa = im.convert("RGBA").split()[3]
        bb = alfa.getbbox()
    if not bb:
        return None
    return bb[0] + x, bb[1] + y, bb[2] + x, bb[3] + y


def _intersecao(a, b) -> int:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def _linhas_do_png(arquivo: str) -> int:
    """Estimativa de linhas de texto: conta faixas horizontais com conteúdo separadas por vazio dentro da caixa."""
    from PIL import Image
    import numpy as np
    with Image.open(arquivo) as im:
        a = np.array(im.convert("RGBA"))
    if a.size == 0:
        return 0
    # pixels "de texto": alfa alto e cor bem diferente da cor de fundo dominante da caixa
    alfa = a[:, :, 3] > 200
    if not alfa.any():
        return 0
    rgb = a[:, :, :3].astype(int)
    fundo = np.median(rgb[alfa], axis=0)
    texto = alfa & (np.abs(rgb - fundo).sum(axis=2) > 120)
    linhas = texto.any(axis=1)
    n, dentro = 0, False
    for v in linhas:
        if v and not dentro:
            n += 1
        dentro = bool(v)
    return n


def validar(pasta: Path, dados: dict, formato: str | None = None) -> dict:
    perfil = perfil_do_projeto(dados)
    formato = formato or dados.get("formato", "16:9")
    L, A = dimensoes_formato(formato)
    seguro = AREA_SEGURA.get(formato, AREA_SEGURA["16:9"])
    sx0, sx1 = int(L * seguro["esq"]), int(L * (1 - seguro["dir"]))
    sy0, sy1 = int(A * seguro["topo"]), int(A * (1 - seguro["base"]))
    problemas: list[dict] = []

    ja = set()

    def add(nivel, elemento, instante, mensagem):
        chave = (str(elemento), mensagem)
        if chave in ja:
            return
        ja.add(chave)
        problemas.append({"nivel": nivel, "elemento": elemento, "instante": round(float(instante or 0), 2), "mensagem": mensagem})

    trabalho = pasta / "trabalho"
    sobre = planejar_sobreposicoes(dados, perfil, L, A, trabalho)
    por_id = {c["id"]: c for c in dados.get("cartoes", [])}
    caixas = []
    for sp in sobre:
        if sp.get("kind") == "tela" or sp.get("kind") == "video":
            if sp.get("kind") == "video":
                caixas.append((sp["id"], sp["tipo"], (sp["x"], sp["y"], sp["x"] + sp["w"], sp["y"] + sp["h"]), sp["inicio"], sp["fim"]))
            continue
        bb = _bbox(sp["arquivo"], sp["x"], sp["y"])
        if not bb:
            continue
        ident, tipo = sp["id"], sp["tipo"]
        orig = por_id.get(ident, {})
        instante = orig.get("inicio", sp["inicio"])
        if tipo in ("marca_dagua",):
            continue
        # 1) cortado na borda do quadro
        if bb[0] <= 0 or bb[2] >= L or bb[1] <= 0 or bb[3] >= A:
            add("erro", ident, instante, f"{tipo} está cortado na borda do quadro {formato}. Reduza o tamanho ou encurte o texto.")
        # 2) fora da área segura das redes
        elif bb[0] < sx0 or (bb[2] > sx1 and bb[3] > A * 0.45) or bb[1] < sy0 or bb[3] > sy1:
            # a coluna de ícones das redes fica na metade de baixo, à direita
            lados = []
            if bb[1] < sy0: lados.append("topo")
            if bb[3] > sy1: lados.append("base")
            if bb[0] < sx0: lados.append("esquerda")
            if bb[2] > sx1 and bb[3] > A * 0.45: lados.append("direita")
            add("aviso", ident, instante, f"{tipo} invade a área onde as redes colocam botões e textos ({', '.join(lados)}). "
                                           "Arraste no Palco para dentro da área tracejada.")
        # 3) texto longo demais
        if tipo in MAX_LINHAS:
            n = _linhas_do_png(sp["arquivo"])
            if n > MAX_LINHAS[tipo]:
                add("aviso", ident, instante, f"{tipo} ficou com {n} linhas; encurte o texto (máximo recomendado: {MAX_LINHAS[tipo]}).")
        caixas.append((ident, tipo, bb, sp["inicio"], sp["fim"]))

    # 4) sobreposição entre elementos no mesmo instante
    vistos = set()
    for i, (id1, t1, b1, i1, f1) in enumerate(caixas):
        for id2, t2, b2, i2, f2 in caixas[i + 1:]:
            if id1 == id2 or (id1, id2) in vistos:
                continue
            if f1 is None or f2 is None or min(f1, f2) - max(i1, i2) < 0.4:
                continue
            inter = _intersecao(b1, b2)
            menor = min((b1[2] - b1[0]) * (b1[3] - b1[1]), (b2[2] - b2[0]) * (b2[3] - b2[1])) or 1
            if inter / menor > 0.25:
                vistos.add((id1, id2))
                add("aviso", id1, por_id.get(id1, {}).get("inicio", i1),
                    f"{t1} {id1} cobre {t2} {id2} entre {max(i1, i2):.1f}s e {min(f1, f2):.1f}s do vídeo editado. Mude a posição ou o tempo de um deles.")

    # 5) elementos cobrindo a legenda
    if dados.get("legendas", {}).get("ativas", True) and dados.get("transcricao"):
        cfg = perfil["legendas"]
        tam = tamanho_fonte(perfil, L, A)
        pct = cfg.get("posicao_percentual")
        if pct is None:
            pct = {"inferior": 1 - float(cfg.get("margem_vertical", 0.10)), "centro": 0.5, "superior": float(cfg.get("margem_vertical", 0.10)) + 0.06}.get(cfg.get("posicao", "inferior"), 0.9)
        faixa = (int(L * 0.06), int(A * pct) - int(tam * 2.4), int(L * 0.94), int(A * pct))
        legendas = construir_legendas(dados, perfil, L, A)
        for ident, tipo, bb, i1, f1 in caixas:
            if tipo in ("assinatura",) or f1 is None:
                continue
            if _intersecao(bb, faixa) > 0.15 * (faixa[2] - faixa[0]) * (faixa[3] - faixa[1]):
                if any(l["inicio"] < f1 and l["fim"] > i1 for l in legendas):
                    add("aviso", ident, por_id.get(ident, {}).get("inicio", i1), f"{tipo} {ident} cobre a faixa da legenda. Mova o elemento ou a legenda no Palco.")
        if faixa[3] > sy1:
            add("aviso", "legenda", 0, "A legenda está na área que as redes cobrem com botões e descrição. Suba a legenda no Palco (ou ajuste a altura na seção 5).")

    # 6) contraste
    cfg_c = perfil.get("cartoes", {})
    for c in dados.get("cartoes", []):
        if not c.get("ativo", True):
            continue
        fundo = c.get("cor_fundo") or (perfil["cores"]["primaria"] if c["tipo"] == "tela" else cfg_c.get("fundo", "#FFFFFF"))
        texto = c.get("cor_texto") or ("#FFFFFF" if c["tipo"] == "tela" else cfg_c.get("texto", "#111111"))
        try:
            if c["tipo"] not in ("imagem", "video", "emoji", "icone", "palavra") and contraste(fundo, texto) < 3.0:
                add("aviso", c["id"], c["inicio"], f"{c['tipo']} {c['id']}: contraste fraco entre texto e fundo ({contraste(fundo, texto):.1f}:1; o mínimo confortável é 3:1).")
        except ErroEdicao:
            pass

    # 7) duplicados
    vistos_dup = {}
    for c in dados.get("cartoes", []):
        if not c.get("ativo", True):
            continue
        chave = (c["tipo"], (c.get("texto") or "").strip().lower(), ",".join(c.get("itens") or []), round(float(c["inicio"]), 0))
        if chave in vistos_dup:
            add("aviso", c["id"], c["inicio"], f"{c['tipo']} {c['id']} repete o elemento {vistos_dup[chave]} no mesmo instante. Remova um deles (ou use 'Reiniciar elementos').")
        else:
            vistos_dup[chave] = c["id"]

    # 8) elementos em trechos removidos
    for c in dados.get("cartoes", []):
        if c.get("ativo", True) and mapear_intervalo(dados, float(c["inicio"]), float(c["fim"])) is None:
            add("aviso", c["id"], c["inicio"], f"{c['tipo']} {c['id']} está num trecho removido e não vai aparecer.")

    problemas.sort(key=lambda p: (0 if p["nivel"] == "erro" else 1, p["instante"]))
    return {"formato": formato, "erros": sum(1 for p in problemas if p["nivel"] == "erro"),
            "avisos": sum(1 for p in problemas if p["nivel"] == "aviso"), "problemas": problemas,
            "area_segura": seguro}
