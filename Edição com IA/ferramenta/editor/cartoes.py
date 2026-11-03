"""Cartões na tela (título, check, alerta, chips, texto), marca d'água e faixa de assinatura.

Cada cartão vira uma imagem PNG com transparência (desenhada com Pillow) que o FFmpeg
sobrepõe ao vídeo no intervalo escolhido. Tempos ficam no projeto na linha do tempo ORIGINAL;
na renderização são convertidos para a linha do tempo cortada.
"""
from __future__ import annotations

from pathlib import Path

from .estilos import arquivo_fonte
from .projeto import mapear_intervalo, proximo_id
from .util import ErroEdicao, hex_para_rgb

TIPOS = {"titulo": "Título no topo (linhas em caixas)", "check": "Confirmação ✓", "alerta": "Alerta ⓘ",
         "chips": "Palavras-chave em pílulas", "texto": "Caixa de texto simples"}
POSICOES = {"superior": 0.11, "centro": 0.50, "inferior": 0.74}   # superior = borda de cima; demais = centro


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        return Image, ImageDraw, ImageFont
    except ImportError:
        raise ErroEdicao("A biblioteca 'Pillow' não está instalada (necessária para os cartões). "
                         "Rode o instalador de novo ou: pip install pillow")


def _rgba(cor: str, alfa: float = 1.0) -> tuple[int, int, int, int]:
    r, g, b = hex_para_rgb(cor)
    return r, g, b, int(round(255 * alfa))


def _fonte(tamanho: int, negrito: bool = True, italico: bool = False):
    _, _, ImageFont = _pil()
    caminho = arquivo_fonte(negrito=negrito, italico=italico)
    try:
        return ImageFont.truetype(str(caminho), tamanho) if caminho else ImageFont.load_default(size=tamanho)
    except OSError:
        return ImageFont.load_default(size=tamanho)


def _medir(draw, texto: str, fonte) -> tuple[int, int]:
    l, t, r, b = draw.textbbox((0, 0), texto, font=fonte)
    return r - l, b - t


def _quebrar(draw, texto: str, fonte, largura_max: int) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = (atual + " " + palavra).strip()
        if _medir(draw, teste, fonte)[0] <= largura_max or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    # Equilibra: evita última linha com uma palavra só quando dá para dividir melhor
    if len(linhas) >= 2 and len(linhas[-1]) < len(linhas[-2]) * 0.45:
        palavras = texto.split()
        alvo = len(linhas)
        melhor, melhor_var = linhas, None
        for corte in range(1, len(palavras)):
            a, b = " ".join(palavras[:corte]), " ".join(palavras[corte:])
            if alvo == 2 and _medir(draw, a, fonte)[0] <= largura_max and _medir(draw, b, fonte)[0] <= largura_max:
                var = abs(len(a) - len(b))
                if melhor_var is None or var < melhor_var:
                    melhor, melhor_var = [a, b], var
        linhas = melhor
    return linhas


def _desenhar_check(draw, x: int, y: int, tam: int, cor):
    esp = max(3, tam // 7)
    draw.line([(x + tam * 0.1, y + tam * 0.55), (x + tam * 0.4, y + tam * 0.85), (x + tam * 0.92, y + tam * 0.15)],
              fill=cor, width=esp, joint="curve")


def _desenhar_info(draw, x: int, y: int, tam: int, cor, fonte):
    esp = max(3, tam // 9)
    draw.ellipse([x, y, x + tam, y + tam], outline=cor, width=esp)
    w, h = _medir(draw, "i", fonte)
    draw.text((x + tam / 2 - w / 2, y + tam / 2 - h / 2 - tam * 0.12), "i", font=fonte, fill=cor)


# ---------------------------------------------------------------- desenho dos cartões

def desenhar_cartao(cartao: dict, perfil: dict, largura: int, altura: int, destino: Path) -> dict:
    """Desenha o cartão em PNG e devolve {arquivo, x, y, w, h} em pixels da saída."""
    Image, ImageDraw, _ = _pil()
    cfg = perfil.get("cartoes", {})
    cores = perfil["cores"]
    fundo = cfg.get("fundo", "#FFFFFF")
    cor_texto = cfg.get("texto", cores["primaria"])
    cor_destaque = cfg.get("destaque", cores["destaque"])
    base = min(largura, altura)
    tipo = cartao.get("tipo", "texto")
    texto = (cartao.get("texto") or "").strip()
    if tipo != "chips" and not texto:
        raise ErroEdicao("O cartão precisa de um texto.")
    largura_max = int(largura * 0.86)
    raio = int(base * 0.018)
    pad_x, pad_y = int(base * 0.03), int(base * 0.018)

    if tipo == "titulo":
        tam = int(base * 0.052)
        fonte = _fonte(tam, negrito=True)
        medidor = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        linhas = _quebrar(medidor, texto, fonte, largura_max - 2 * pad_x)
        destaque = (cartao.get("destaque") or "").strip()
        alt_linha = _medir(medidor, "Ág", fonte)[1] + 2 * pad_y
        espaco = int(base * 0.012)
        total_h = len(linhas) * (alt_linha + espaco) + (alt_linha + espaco if destaque else 0)
        img = Image.new("RGBA", (largura, total_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        y = 0
        for linha in linhas:
            w = _medir(draw, linha, fonte)[0] + 2 * pad_x
            x = (largura - w) // 2
            draw.rounded_rectangle([x, y, x + w, y + alt_linha], radius=raio, fill=_rgba(fundo, 0.96))
            draw.text((x + pad_x, y + pad_y - tam * 0.08), linha, font=fonte, fill=_rgba(cor_texto))
            y += alt_linha + espaco
        if destaque:
            fonte_d = _fonte(int(tam * 0.9), negrito=True)
            w = _medir(draw, destaque, fonte_d)[0] + 2 * pad_x
            x = (largura - w) // 2
            draw.rounded_rectangle([x, y, x + w, y + alt_linha], radius=raio, fill=_rgba(cor_destaque, 0.98))
            draw.text((x + pad_x, y + pad_y), destaque, font=fonte_d, fill=_rgba("#FFFFFF"))
        img.save(destino)
        return {"arquivo": str(destino), "w": largura, "h": total_h}

    if tipo == "chips":
        itens = [i.strip() for i in (cartao.get("itens") or texto.split(",")) if i.strip()]
        if not itens:
            raise ErroEdicao("O cartão de palavras-chave precisa de itens separados por vírgula.")
        tam = int(base * 0.034)
        fonte = _fonte(tam, negrito=True)
        medidor = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        alt = _medir(medidor, "ÁG", fonte)[1] + 2 * pad_y
        gap = int(base * 0.015)
        larguras = [_medir(medidor, i.upper(), fonte)[0] + 2 * pad_x for i in itens]
        total_w = sum(larguras) + gap * (len(itens) - 1)
        escala = min(1.0, largura_max / total_w)
        if escala < 1.0:
            fonte = _fonte(max(12, int(tam * escala)), negrito=True)
            larguras = [_medir(medidor, i.upper(), fonte)[0] + 2 * pad_x for i in itens]
            total_w = sum(larguras) + gap * (len(itens) - 1)
        img = Image.new("RGBA", (largura, alt), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x = (largura - total_w) // 2
        quantos = cartao.get("_visiveis", len(itens))
        for n, (item, w) in enumerate(zip(itens, larguras)):
            if n < quantos:
                draw.rounded_rectangle([x, 0, x + w, alt], radius=alt // 2, fill=_rgba(cfg.get("chip_fundo", cores["primaria"]), 0.9))
                draw.text((x + pad_x, pad_y - tam * 0.1), item.upper(), font=fonte, fill=_rgba(cfg.get("chip_texto", "#FFFFFF")))
            x += w + gap
        img.save(destino)
        return {"arquivo": str(destino), "w": largura, "h": alt}

    # check / alerta / texto
    tam = int(base * 0.042)
    fonte = _fonte(tam, negrito=True)
    medidor = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    icone = int(tam * 1.0) if tipo in ("check", "alerta") else 0
    linhas = _quebrar(medidor, texto, fonte, largura_max - 2 * pad_x - (icone + pad_x if icone else 0))
    alt_texto = _medir(medidor, "Ág", fonte)[1]
    h = len(linhas) * int(alt_texto * 1.25) + 2 * pad_y
    w_texto = max(_medir(medidor, l, fonte)[0] for l in linhas)
    w = w_texto + 2 * pad_x + (icone + pad_x if icone else 0)
    img = Image.new("RGBA", (largura, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x0 = (largura - w) // 2
    draw.rounded_rectangle([x0, 0, x0 + w, h], radius=raio, fill=_rgba(fundo, 0.96))
    x_txt = x0 + pad_x
    if tipo == "check":
        _desenhar_check(draw, x_txt, (h - icone) // 2, icone, _rgba(cfg.get("check", "#2E9E5B")))
        x_txt += icone + pad_x
    elif tipo == "alerta":
        _desenhar_info(draw, x_txt, (h - icone) // 2, icone, _rgba(cor_destaque), _fonte(int(icone * 0.75), negrito=True))
        x_txt += icone + pad_x
    y = pad_y - tam * 0.1
    for linha in linhas:
        draw.text((x_txt, y), linha, font=fonte, fill=_rgba(cor_texto))
        y += int(alt_texto * 1.25)
    img.save(destino)
    return {"arquivo": str(destino), "w": largura, "h": h}


def desenhar_marca_dagua(texto: str, perfil: dict, largura: int, altura: int, destino: Path) -> dict:
    Image, ImageDraw, _ = _pil()
    base = min(largura, altura)
    tam = int(base * 0.03)
    fonte = _fonte(tam, negrito=False)
    medidor = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    w, h = _medir(medidor, texto, fonte)
    img = Image.new("RGBA", (w + 8, h + 10), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((5, 4), texto, font=fonte, fill=(0, 0, 0, 110))
    draw.text((4, 3), texto, font=fonte, fill=(255, 255, 255, 215))
    img.save(destino)
    return {"arquivo": str(destino), "w": w + 8, "h": h + 10}


def desenhar_assinatura(nome: str, handle: str, perfil: dict, largura: int, altura: int, destino: Path) -> dict:
    Image, ImageDraw, _ = _pil()
    cfg = perfil.get("cartoes", {})
    cores = perfil["cores"]
    base = min(largura, altura)
    tam = int(base * 0.042)
    fonte = _fonte(tam, negrito=True)
    fonte_h = _fonte(int(tam * 0.72), negrito=False)
    medidor = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    pad = int(base * 0.025)
    w1, h1 = _medir(medidor, nome, fonte)
    w2, h2 = _medir(medidor, handle, fonte_h) if handle else (0, 0)
    w = max(w1, w2) + 2 * pad
    h = h1 + (h2 + int(tam * 0.25) if handle else 0) + 2 * pad
    img = Image.new("RGBA", (largura, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x0 = (largura - w) // 2
    draw.rounded_rectangle([x0, 0, x0 + w, h], radius=int(base * 0.018), fill=_rgba(cfg.get("fundo", "#FFFFFF"), 0.96))
    draw.text((x0 + pad, pad - tam * 0.1), nome, font=fonte, fill=_rgba(cfg.get("texto", cores["primaria"])))
    if handle:
        draw.text((x0 + pad, pad + h1 + int(tam * 0.25) - tam * 0.1), handle, font=fonte_h, fill=_rgba(cores["destaque"]))
    img.save(destino)
    return {"arquivo": str(destino), "w": largura, "h": h}


# ---------------------------------------------------------------- projeto

def adicionar(dados: dict, tipo: str, texto: str, inicio: float | None, fim: float | None,
              fala: int | None = None, posicao: str | None = None, destaque: str = "",
              itens: list[str] | None = None, y: float | None = None) -> dict:
    if tipo not in TIPOS:
        raise ErroEdicao(f"Tipo de cartão '{tipo}' inválido. Opções: {', '.join(TIPOS)}")
    if fala is not None:
        seg = next((s for s in (dados.get("transcricao") or {}).get("segmentos", []) if s["id"] == int(fala)), None)
        if seg is None:
            raise ErroEdicao(f"A fala [{fala}] não existe na transcrição.")
        inicio = float(seg["inicio"]) if inicio is None else inicio
        fim = float(seg["fim"]) if fim is None else fim
    if inicio is None or fim is None or fim <= inicio:
        raise ErroEdicao("Informe início e fim (ou a fala em que o cartão aparece).")
    posicao = posicao or ("superior" if tipo in ("titulo", "chips") else "inferior")
    if posicao not in POSICOES:
        raise ErroEdicao(f"Posição '{posicao}' inválida. Use: {', '.join(POSICOES)}")
    lista = dados.setdefault("cartoes", [])
    item = {"id": proximo_id(lista), "tipo": tipo, "texto": texto.strip(), "inicio": round(float(inicio), 3),
            "fim": round(float(fim), 3), "fala": fala, "posicao": posicao, "destaque": destaque.strip(),
            "itens": itens or None, "y": y}
    lista.append(item)
    return item


def remover(dados: dict, ident: int) -> bool:
    antes = len(dados.get("cartoes", []))
    dados["cartoes"] = [c for c in dados.get("cartoes", []) if c["id"] != ident]
    return len(dados["cartoes"]) < antes


def _y(altura: int, frac: float, h: int, topo: bool) -> int:
    y = int(altura * frac) if topo else int(altura * frac - h / 2)
    return max(int(altura * 0.02), min(y, altura - h - int(altura * 0.02)))


def planejar_sobreposicoes(dados: dict, perfil: dict, largura: int, altura: int, pasta: Path) -> list[dict]:
    """Desenha todos os PNGs e devolve [{arquivo, x, y, inicio, fim}] já na linha do tempo cortada."""
    saida = []
    pasta.mkdir(parents=True, exist_ok=True)
    for antigo in pasta.glob("cartao-*.png"):
        antigo.unlink()
    for c in dados.get("cartoes", []) or []:
        novo = mapear_intervalo(dados, float(c["inicio"]), float(c["fim"]))
        if novo is None:
            continue  # cartão caiu inteiro num trecho removido
        frac_y = float(c["y"]) if c.get("y") is not None else POSICOES.get(c.get("posicao", "inferior"), 0.74)
        topo = c.get("posicao") == "superior" and c.get("y") is None
        if c["tipo"] == "chips":
            itens = [i.strip() for i in (c.get("itens") or (c.get("texto") or "").split(",")) if i.strip()]
            passo = min(0.5, (novo[1] - novo[0]) / max(1, len(itens)) * 0.5)
            for n in range(1, len(itens) + 1):
                info = desenhar_cartao(dict(c, _visiveis=n, itens=itens), perfil, largura, altura, pasta / f"cartao-{c['id']}-{n}.png")
                ini = novo[0] + (n - 1) * passo
                fim = novo[1] if n == len(itens) else novo[0] + n * passo
                saida.append({"arquivo": info["arquivo"], "x": 0, "y": _y(altura, frac_y, info["h"], topo), "inicio": ini, "fim": fim})
            continue
        info = desenhar_cartao(c, perfil, largura, altura, pasta / f"cartao-{c['id']}.png")
        saida.append({"arquivo": info["arquivo"], "x": 0, "y": _y(altura, frac_y, info["h"], topo), "inicio": novo[0], "fim": novo[1]})

    md = dados.get("marca_dagua") or {}
    texto_md = md.get("texto") or perfil.get("marca_dagua", {}).get("texto")
    if md.get("ativo", bool(texto_md)) and texto_md:
        info = desenhar_marca_dagua(texto_md, perfil, largura, altura, pasta / "cartao-marca-dagua.png")
        margem = int(min(largura, altura) * 0.035)
        pos = md.get("posicao") or perfil.get("marca_dagua", {}).get("posicao", "superior-direita")
        x = largura - info["w"] - margem if "direita" in pos else margem
        y = margem if "superior" in pos else altura - info["h"] - margem
        # se a logo ocupa o mesmo canto, a marca d'água vai para o canto oposto na mesma altura
        logo_pos = (dados.get("logo") or {}).get("posicao") or perfil.get("logo", {}).get("posicao", "superior-direita")
        if pos == logo_pos and (dados.get("logo") or {}).get("ativo", True):
            x = margem if "direita" in pos else largura - info["w"] - margem
        saida.append({"arquivo": info["arquivo"], "x": x, "y": y, "inicio": 0.0, "fim": None})

    ass = dados.get("assinatura") or {}
    if ass.get("ativo") and ass.get("nome"):
        novo = mapear_intervalo(dados, float(ass.get("inicio", 0)), float(ass.get("fim", 0)))
        if novo:
            info = desenhar_assinatura(ass["nome"], ass.get("handle", ""), perfil, largura, altura, pasta / "cartao-assinatura.png")
            saida.append({"arquivo": info["arquivo"], "x": 0, "y": int(altura * 0.80 - info["h"] / 2), "inicio": novo[0], "fim": novo[1]})
    return saida
