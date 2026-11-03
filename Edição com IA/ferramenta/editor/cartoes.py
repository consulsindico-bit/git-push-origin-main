"""Elementos visuais sobre o vídeo: cartões (título, pergunta, check, alerta, chips, texto, tópico numerado,
palavra-chave grande, resumo), imagens de apoio, marca d'água e identificação do apresentador.

Cada elemento vira um PNG com transparência (Pillow) que o FFmpeg sobrepõe no intervalo escolhido,
com animação de entrada/saída opcional. Tempos ficam no projeto na linha do tempo ORIGINAL e são
convertidos para a linha do tempo cortada na renderização.
"""
from __future__ import annotations

import re
from pathlib import Path

from .estilos import arquivo_fonte
from .projeto import mapear_intervalo, proximo_id
from .util import PASTA_IDENTIDADE, ErroEdicao, hex_para_rgb

TIPOS = {
    "titulo": "Título no topo (linhas em caixas, com destaque)",
    "pergunta": "Pergunta principal (caixa única no topo)",
    "check": "Confirmação ✓",
    "alerta": "Alerta ⓘ",
    "chips": "Etiquetas de conceitos (pílulas no topo)",
    "texto": "Caixa de texto simples",
    "topico": "Tópico numerado (número, nome e descrição)",
    "palavra": "Palavra-chave grande",
    "resumo": "Resumo com itens numerados",
    "imagem": "Imagem de apoio (captura, foto, ilustração)",
}
POSICOES = {"superior": 0.11, "centro": 0.50, "inferior": 0.70}   # superior = borda de cima; demais = centro
ANIMACOES = {"nenhuma": "sem animação", "fade": "aparece e some suavemente", "subir": "sobe e aparece"}
PASTA_IMAGENS = PASTA_IDENTIDADE / "imagens"


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter  # noqa: F401
        return Image, ImageDraw, ImageFont, ImageFilter
    except ImportError:
        raise ErroEdicao("A biblioteca 'Pillow' não está instalada (necessária para os cartões). "
                         "Rode o instalador de novo (instalar.bat) ou: pip install pillow")


def _rgba(cor: str, alfa: float = 1.0) -> tuple[int, int, int, int]:
    r, g, b = hex_para_rgb(cor)
    return r, g, b, int(round(255 * alfa))


def _fonte(perfil: dict, papel: str, tamanho: int, negrito: bool = True, italico: bool = False):
    """papel: 'titulos' ou 'textos' (famílias do perfil, ex.: Montserrat / Open Sans)."""
    _, _, ImageFont, _ = _pil()
    familia = (perfil.get("fontes") or {}).get(papel)
    caminho = arquivo_fonte(negrito=negrito, italico=italico, familia=familia)
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
    # Equilibra 2 linhas: evita última linha com uma palavra só
    if len(linhas) == 2 and len(linhas[-1]) < len(linhas[-2]) * 0.45:
        palavras = texto.split()
        melhor, melhor_var = linhas, None
        for corte in range(1, len(palavras)):
            a, b = " ".join(palavras[:corte]), " ".join(palavras[corte:])
            if _medir(draw, a, fonte)[0] <= largura_max and _medir(draw, b, fonte)[0] <= largura_max:
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


def _sombra(img, Image, ImageFilter, deslocamento: int, raio: int):
    """Acrescenta uma sombra suave atrás de uma imagem RGBA."""
    borda = raio * 3
    base = Image.new("RGBA", (img.width + 2 * borda, img.height + 2 * borda), (0, 0, 0, 0))
    alfa = img.split()[3]
    sombra = Image.new("RGBA", img.size, (0, 0, 0, 120))
    sombra.putalpha(alfa.point(lambda a: int(a * 0.5)))
    base.alpha_composite(sombra, (borda + deslocamento, borda + deslocamento))
    base = base.filter(ImageFilter.GaussianBlur(raio))
    base.alpha_composite(img, (borda, borda))
    return base, borda


# ---------------------------------------------------------------- desenho

def desenhar_cartao(cartao: dict, perfil: dict, largura: int, altura: int, destino: Path) -> dict:
    """Desenha o elemento em PNG (largura total do quadro) e devolve {arquivo, w, h}."""
    Image, ImageDraw, _, ImageFilter = _pil()
    cfg = perfil.get("cartoes", {})
    cores = perfil["cores"]
    fundo = cartao.get("cor_fundo") or cfg.get("fundo", "#FFFFFF")
    cor_texto = cartao.get("cor_texto") or cfg.get("texto", cores["primaria"])
    cor_destaque = cartao.get("cor_destaque") or cfg.get("destaque", cores["destaque"])
    escala = float(cartao.get("tamanho") or 1.0)
    base = min(largura, altura) * escala
    tipo = cartao.get("tipo", "texto")
    texto = (cartao.get("texto") or "").strip()
    if tipo not in ("chips", "imagem", "resumo") and not texto:
        raise ErroEdicao("O cartão precisa de um texto.")
    largura_max = int(largura * 0.86)
    raio = int(base * 0.018)
    pad_x, pad_y = int(base * 0.03), int(base * 0.018)
    medidor = ImageDraw.Draw(Image.new("RGBA", (10, 10)))

    if tipo in ("titulo", "pergunta"):
        tam = int(base * (0.052 if tipo == "titulo" else 0.044))
        fonte = _fonte(perfil, "titulos", tam, negrito=True)
        linhas = _quebrar(medidor, texto, fonte, largura_max - 2 * pad_x)
        destaque = (cartao.get("destaque") or "").strip()
        alt_linha = _medir(medidor, "Ág", fonte)[1] + 2 * pad_y
        espaco = int(base * 0.012)
        if tipo == "pergunta":
            # caixa única com todas as linhas
            h = len(linhas) * int(alt_linha * 0.92) + pad_y
            w = max(_medir(medidor, l, fonte)[0] for l in linhas) + 2 * pad_x
            img = Image.new("RGBA", (largura, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            x = (largura - w) // 2
            draw.rounded_rectangle([x, 0, x + w, h], radius=raio, fill=_rgba(fundo, 0.96))
            y = pad_y * 0.5
            for linha in linhas:
                lw = _medir(draw, linha, fonte)[0]
                draw.text((x + (w - lw) / 2, y), linha, font=fonte, fill=_rgba(cor_texto))
                y += int(alt_linha * 0.92)
            img.save(destino)
            return {"arquivo": str(destino), "w": largura, "h": h}
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
            fonte_d = _fonte(perfil, "titulos", int(tam * 0.9), negrito=True)
            w = _medir(draw, destaque, fonte_d)[0] + 2 * pad_x
            x = (largura - w) // 2
            draw.rounded_rectangle([x, y, x + w, y + alt_linha], radius=raio, fill=_rgba(cor_destaque, 0.98))
            draw.text((x + pad_x, y + pad_y), destaque, font=fonte_d, fill=_rgba("#FFFFFF"))
        img.save(destino)
        return {"arquivo": str(destino), "w": largura, "h": total_h}

    if tipo == "chips":
        itens = [i.strip() for i in (cartao.get("itens") or texto.split(",")) if i.strip()]
        if not itens:
            raise ErroEdicao("As etiquetas precisam de itens separados por vírgula.")
        tam = int(base * 0.034)
        fonte = _fonte(perfil, "titulos", tam, negrito=True)
        alt = _medir(medidor, "ÁG", fonte)[1] + 2 * pad_y
        gap = int(base * 0.015)
        larguras = [_medir(medidor, i.upper(), fonte)[0] + 2 * pad_x for i in itens]
        total_w = sum(larguras) + gap * (len(itens) - 1)
        if total_w > largura_max:
            fonte = _fonte(perfil, "titulos", max(12, int(tam * largura_max / total_w)), negrito=True)
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

    if tipo == "topico":
        numero = str(cartao.get("numero") or "").strip()
        descricao = (cartao.get("descricao") or "").strip()
        tam = int(base * 0.046)
        tam_desc = int(base * 0.03)
        fonte = _fonte(perfil, "titulos", tam, negrito=True)
        fonte_desc = _fonte(perfil, "textos", tam_desc, negrito=False)
        fonte_num = _fonte(perfil, "titulos", int(tam * 1.1), negrito=True)
        badge = int(tam * 1.5) if numero else 0
        largura_txt = largura_max - 2 * pad_x - (badge + pad_x if badge else 0)
        linhas = _quebrar(medidor, texto, fonte, largura_txt)
        linhas_desc = _quebrar(medidor, descricao, fonte_desc, largura_txt) if descricao else []
        alt_t = int(_medir(medidor, "Ág", fonte)[1] * 1.2)
        alt_d = int(_medir(medidor, "Ág", fonte_desc)[1] * 1.3)
        h = 2 * pad_y + len(linhas) * alt_t + (int(tam * 0.2) + len(linhas_desc) * alt_d if linhas_desc else 0)
        h = max(h, badge + 2 * pad_y)
        w_txt = max([_medir(medidor, l, fonte)[0] for l in linhas] + [_medir(medidor, l, fonte_desc)[0] for l in linhas_desc])
        w = w_txt + 2 * pad_x + (badge + pad_x if badge else 0)
        img = Image.new("RGBA", (largura, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x0 = (largura - w) // 2
        draw.rounded_rectangle([x0, 0, x0 + w, h], radius=raio, fill=_rgba(fundo, 0.96))
        x_txt = x0 + pad_x
        if badge:
            by = (h - badge) // 2
            draw.rounded_rectangle([x_txt, by, x_txt + badge, by + badge], radius=int(badge * 0.25), fill=_rgba(cor_destaque))
            nw, nh = _medir(draw, numero, fonte_num)
            draw.text((x_txt + (badge - nw) / 2, by + (badge - nh) / 2 - tam * 0.12), numero, font=fonte_num, fill=_rgba("#FFFFFF"))
            x_txt += badge + pad_x
        y = pad_y - tam * 0.1
        for linha in linhas:
            draw.text((x_txt, y), linha, font=fonte, fill=_rgba(cor_texto))
            y += alt_t
        if linhas_desc:
            y += int(tam * 0.2)
            for linha in linhas_desc:
                draw.text((x_txt, y), linha, font=fonte_desc, fill=_rgba(cor_texto, 0.85))
                y += alt_d
        img.save(destino)
        return {"arquivo": str(destino), "w": largura, "h": h}

    if tipo == "palavra":
        tam = int(base * 0.11)
        fonte = _fonte(perfil, "titulos", tam, negrito=True)
        linhas = _quebrar(medidor, texto, fonte, largura_max)
        def cabe():
            return len(linhas) <= 2 and all(_medir(medidor, l.upper(), fonte)[0] + int(tam * 0.2) <= largura_max for l in linhas)
        while not cabe() and tam > 30:
            tam = int(tam * 0.88)
            fonte = _fonte(perfil, "titulos", tam, negrito=True)
            linhas = _quebrar(medidor, texto.upper(), fonte, largura_max)
        contorno = max(3, int(tam * 0.08))
        alt = int(_medir(medidor, "Ág", fonte)[1] * 1.15)
        h = len(linhas) * alt + 2 * contorno + int(tam * 0.3)
        img = Image.new("RGBA", (largura, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cor_p = cartao.get("cor_texto") or cfg.get("palavra_cor", "#FFFFFF")
        cor_c = cfg.get("palavra_contorno", cores["primaria"])
        y = contorno + int(tam * 0.05)
        for linha in linhas:
            lw = _medir(draw, linha, fonte)[0]
            draw.text(((largura - lw) / 2, y), linha.upper(), font=fonte, fill=_rgba(cor_p),
                      stroke_width=contorno, stroke_fill=_rgba(cor_c))
            y += alt
        img, _ = _sombra(img, Image, ImageFilter, int(tam * 0.06), max(2, int(tam * 0.05)))
        img.save(destino)
        return {"arquivo": str(destino), "w": img.width, "h": img.height}

    if tipo == "resumo":
        itens = [i.strip() for i in (cartao.get("itens") or []) if i.strip()]
        if not itens:
            raise ErroEdicao("O resumo precisa de itens.")
        tam_t = int(base * 0.046)
        tam_i = int(base * 0.034)
        fonte_t = _fonte(perfil, "titulos", tam_t, negrito=True)
        fonte_i = _fonte(perfil, "textos", tam_i, negrito=False)
        fonte_n = _fonte(perfil, "titulos", tam_i, negrito=True)
        w = int(largura * 0.88)
        largura_txt = w - 2 * pad_x - int(tam_i * 1.6)
        alt_i = int(_medir(medidor, "Ág", fonte_i)[1] * 1.35)
        blocos = [_quebrar(medidor, it, fonte_i, largura_txt) for it in itens]
        h = 2 * pad_y + (int(_medir(medidor, "Ág", fonte_t)[1] * 1.4) if texto else 0) + sum(len(b) * alt_i for b in blocos) + int(tam_i * 0.5) * len(itens)
        img = Image.new("RGBA", (largura, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x0 = (largura - w) // 2
        draw.rounded_rectangle([x0, 0, x0 + w, h], radius=raio, fill=_rgba(fundo, 0.96))
        y = pad_y
        if texto:
            draw.text((x0 + pad_x, y - tam_t * 0.1), texto, font=fonte_t, fill=_rgba(cor_texto))
            y += int(_medir(medidor, "Ág", fonte_t)[1] * 1.4)
            draw.line([(x0 + pad_x, y - int(tam_t * 0.15)), (x0 + w - pad_x, y - int(tam_t * 0.15))], fill=_rgba(cor_destaque), width=3)
        for n, linhas in enumerate(blocos, start=1):
            draw.text((x0 + pad_x, y - tam_i * 0.1), f"{n}.", font=fonte_n, fill=_rgba(cor_destaque))
            for linha in linhas:
                draw.text((x0 + pad_x + int(tam_i * 1.6), y - tam_i * 0.1), linha, font=fonte_i, fill=_rgba(cor_texto))
                y += alt_i
            y += int(tam_i * 0.5)
        img.save(destino)
        return {"arquivo": str(destino), "w": largura, "h": h}

    if tipo == "imagem":
        caminho = _caminho_imagem(cartao.get("imagem"))
        src = Image.open(caminho).convert("RGBA")
        alvo_w = int(largura * float(cartao.get("tamanho") or 0.8))
        fator = alvo_w / src.width
        src = src.resize((alvo_w, max(1, int(src.height * fator))), Image.LANCZOS)
        if src.height > altura * 0.7:
            fator = altura * 0.7 / src.height
            src = src.resize((max(1, int(src.width * fator)), int(altura * 0.7)), Image.LANCZOS)
        r = int(min(src.size) * 0.05)
        mascara = Image.new("L", src.size, 0)
        ImageDraw.Draw(mascara).rounded_rectangle([0, 0, src.width - 1, src.height - 1], radius=r, fill=255)
        src.putalpha(Image.fromarray(__import__("numpy").minimum(__import__("numpy").array(src.split()[3]), __import__("numpy").array(mascara))))
        if cartao.get("borda", True):
            moldura = Image.new("RGBA", (src.width + 8, src.height + 8), (0, 0, 0, 0))
            ImageDraw.Draw(moldura).rounded_rectangle([0, 0, moldura.width - 1, moldura.height - 1], radius=r + 4, fill=_rgba(fundo))
            moldura.alpha_composite(src, (4, 4))
            src = moldura
        src, _ = _sombra(src, Image, ImageFilter, int(base * 0.008), max(3, int(base * 0.012)))
        img = Image.new("RGBA", (largura, src.height), (0, 0, 0, 0))
        img.alpha_composite(src, ((largura - src.width) // 2, 0))
        img.save(destino)
        return {"arquivo": str(destino), "w": largura, "h": img.height}

    # check / alerta / texto
    tam = int(base * 0.042)
    fonte = _fonte(perfil, "titulos", tam, negrito=True)
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
        _desenhar_info(draw, x_txt, (h - icone) // 2, icone, _rgba(cor_destaque), _fonte(perfil, "titulos", int(icone * 0.75), negrito=True))
        x_txt += icone + pad_x
    y = pad_y - tam * 0.1
    for linha in linhas:
        draw.text((x_txt, y), linha, font=fonte, fill=_rgba(cor_texto))
        y += int(alt_texto * 1.25)
    img.save(destino)
    return {"arquivo": str(destino), "w": largura, "h": h}


def _caminho_imagem(nome: str | None) -> Path:
    if not nome:
        raise ErroEdicao("O cartão de imagem precisa do nome do arquivo (coloque a imagem em "
                         f"'{PASTA_IMAGENS}' ou informe o caminho completo).")
    p = Path(nome)
    candidatos = [p] if p.is_absolute() else [PASTA_IMAGENS / nome, Path(nome)]
    for c in candidatos:
        if c.exists():
            return c
    raise ErroEdicao(f"Imagem não encontrada: {nome}. Coloque-a em '{PASTA_IMAGENS}'.")


def desenhar_marca_dagua(texto: str, perfil: dict, largura: int, altura: int, destino: Path) -> dict:
    Image, ImageDraw, _, _ = _pil()
    base = min(largura, altura)
    tam = int(base * 0.03)
    fonte = _fonte(perfil, "textos", tam, negrito=False)
    medidor = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    w, h = _medir(medidor, texto, fonte)
    img = Image.new("RGBA", (w + 8, h + 10), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((5, 4), texto, font=fonte, fill=(0, 0, 0, 110))
    draw.text((4, 3), texto, font=fonte, fill=(255, 255, 255, 215))
    img.save(destino)
    return {"arquivo": str(destino), "w": w + 8, "h": h + 10}


def desenhar_assinatura(nome: str, handle: str, perfil: dict, largura: int, altura: int, destino: Path,
                        cargo: str = "") -> dict:
    """Identificação do apresentador: nome em destaque, cargo/empresa e @ abaixo."""
    Image, ImageDraw, _, _ = _pil()
    cfg = perfil.get("cartoes", {})
    cores = perfil["cores"]
    base = min(largura, altura)
    tam = int(base * 0.042)
    fonte = _fonte(perfil, "titulos", tam, negrito=True)
    fonte_h = _fonte(perfil, "textos", int(tam * 0.72), negrito=False)
    medidor = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    pad = int(base * 0.025)
    linhas_sec = [l for l in (cargo, handle) if l]
    w1, h1 = _medir(medidor, nome, fonte)
    ws = [_medir(medidor, l, fonte_h)[0] for l in linhas_sec]
    h2 = _medir(medidor, "Ág", fonte_h)[1]
    w = max([w1] + ws) + 2 * pad + int(tam * 0.4)
    h = h1 + len(linhas_sec) * int(h2 * 1.25) + (int(tam * 0.25) if linhas_sec else 0) + 2 * pad
    img = Image.new("RGBA", (largura, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x0 = (largura - w) // 2
    draw.rounded_rectangle([x0, 0, x0 + w, h], radius=int(base * 0.018), fill=_rgba(cfg.get("fundo", "#FFFFFF"), 0.96))
    draw.rectangle([x0, int(h * 0.2), x0 + int(tam * 0.18), int(h * 0.8)], fill=_rgba(cores["destaque"]))
    x_txt = x0 + pad + int(tam * 0.2)
    draw.text((x_txt, pad - tam * 0.1), nome, font=fonte, fill=_rgba(cfg.get("texto", cores["primaria"])))
    y = pad + h1 + int(tam * 0.25)
    for n, linha in enumerate(linhas_sec):
        cor = cores["destaque"] if linha == handle else cfg.get("texto", cores["primaria"])
        draw.text((x_txt, y - tam * 0.1), linha, font=fonte_h, fill=_rgba(cor, 0.9))
        y += int(h2 * 1.25)
    img.save(destino)
    return {"arquivo": str(destino), "w": largura, "h": h}


# ---------------------------------------------------------------- projeto

def _chave(p: str) -> str:
    """Normaliza para comparar palavras: minúsculas, sem acentos e sem pontuação."""
    import unicodedata
    sem_acento = unicodedata.normalize("NFKD", p.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sem_acento)


def ancorar_palavra(dados: dict, palavra: str, fala: int | None = None) -> tuple[float, float, int]:
    """Encontra o instante em que a palavra é dita (na fala indicada ou na primeira ocorrência)."""
    transcricao = dados.get("transcricao")
    if not transcricao:
        raise ErroEdicao("Transcreva primeiro para ancorar elementos em palavras.")
    alvo = _chave(palavra)
    for seg in transcricao["segmentos"]:
        if fala is not None and seg["id"] != int(fala):
            continue
        for w in seg.get("palavras") or []:
            if _chave(w["p"]) == alvo:
                return float(w["inicio"]), float(seg["fim"]), seg["id"]
        # texto corrigido pode não bater com as palavras originais: usa o tempo da fala
        if alvo in [_chave(t) for t in seg["texto"].split()]:
            return float(seg["inicio"]), float(seg["fim"]), seg["id"]
    raise ErroEdicao(f"Não encontrei a palavra '{palavra}' na transcrição" + (f" (fala {fala})." if fala else "."))


def adicionar(dados: dict, tipo: str, texto: str = "", inicio: float | None = None, fim: float | None = None,
              fala: int | None = None, posicao: str | None = None, destaque: str = "",
              itens: list[str] | None = None, y: float | None = None, numero: str | int | None = None,
              descricao: str = "", imagem: str | None = None, palavra_ancora: str | None = None,
              duracao: float | None = None, animacao: str | None = None, tamanho: float | None = None) -> dict:
    if tipo not in TIPOS:
        raise ErroEdicao(f"Tipo de elemento '{tipo}' inválido. Opções: {', '.join(TIPOS)}")
    if palavra_ancora:
        ini_p, fim_seg, fala = ancorar_palavra(dados, palavra_ancora, fala)
        inicio = ini_p if inicio is None else inicio
        fim = (inicio + duracao) if duracao else (fim if fim is not None else max(fim_seg, inicio + 1.5))
    elif fala is not None:
        seg = next((s for s in (dados.get("transcricao") or {}).get("segmentos", []) if s["id"] == int(fala)), None)
        if seg is None:
            raise ErroEdicao(f"A fala [{fala}] não existe na transcrição.")
        inicio = float(seg["inicio"]) if inicio is None else inicio
        fim = (inicio + duracao) if duracao else (float(seg["fim"]) if fim is None else fim)
    elif inicio is not None and duracao and fim is None:
        fim = inicio + duracao
    if inicio is None or fim is None or fim <= inicio:
        raise ErroEdicao("Informe início e fim (ou a fala/palavra em que o elemento aparece).")
    if tipo == "imagem":
        _caminho_imagem(imagem)
    padrao_pos = {"titulo": "superior", "pergunta": "superior", "chips": "superior", "palavra": "centro",
                  "resumo": "centro", "imagem": "centro", "topico": "centro"}
    posicao = posicao or padrao_pos.get(tipo, "inferior")
    if posicao not in POSICOES:
        raise ErroEdicao(f"Posição '{posicao}' inválida. Use: {', '.join(POSICOES)}")
    if tipo == "palavra" and y is None and posicao == "centro":
        y = 0.38  # acima do centro, para não cobrir tópicos nem legendas
    animacao = animacao or ("fade" if tipo != "palavra" else "subir")
    if animacao not in ANIMACOES:
        raise ErroEdicao(f"Animação '{animacao}' inválida. Use: {', '.join(ANIMACOES)}")
    lista = dados.setdefault("cartoes", [])
    item = {"id": proximo_id(lista), "tipo": tipo, "texto": texto.strip(), "inicio": round(float(inicio), 3),
            "fim": round(float(fim), 3), "fala": fala, "posicao": posicao, "destaque": destaque.strip(),
            "itens": itens or None, "y": y, "numero": numero, "descricao": descricao.strip(), "imagem": imagem,
            "palavra_ancora": palavra_ancora, "animacao": animacao, "tamanho": tamanho, "ativo": True}
    lista.append(item)
    return item


def atualizar(dados: dict, ident: int, **campos) -> dict:
    for c in dados.get("cartoes", []):
        if c["id"] == int(ident):
            for k, v in campos.items():
                if v is not None:
                    c[k] = v
            return c
    raise ErroEdicao(f"Elemento [{ident}] não existe.")


def remover(dados: dict, ident: int) -> bool:
    antes = len(dados.get("cartoes", []))
    dados["cartoes"] = [c for c in dados.get("cartoes", []) if c["id"] != ident]
    return len(dados["cartoes"]) < antes


def _y(altura: int, frac: float, h: int, topo: bool) -> int:
    y = int(altura * frac) if topo else int(altura * frac - h / 2)
    return max(int(altura * 0.02), min(y, altura - h - int(altura * 0.02)))


def planejar_sobreposicoes(dados: dict, perfil: dict, largura: int, altura: int, pasta: Path) -> list[dict]:
    """Desenha os PNGs e devolve [{arquivo, x, y, inicio, fim, animacao, id, tipo}] na linha do tempo cortada."""
    saida = []
    pasta.mkdir(parents=True, exist_ok=True)
    for antigo in pasta.glob("cartao-*.png"):
        antigo.unlink()
    for c in dados.get("cartoes", []) or []:
        if not c.get("ativo", True):
            continue
        novo = mapear_intervalo(dados, float(c["inicio"]), float(c["fim"]))
        if novo is None:
            continue  # elemento caiu inteiro num trecho removido
        frac_y = float(c["y"]) if c.get("y") is not None else POSICOES.get(c.get("posicao", "inferior"), 0.74)
        topo = c.get("posicao") == "superior" and c.get("y") is None
        anim = c.get("animacao", "fade")
        if c["tipo"] == "chips":
            itens = [i.strip() for i in (c.get("itens") or (c.get("texto") or "").split(",")) if i.strip()]
            passo = min(0.5, (novo[1] - novo[0]) / max(1, len(itens)) * 0.5)
            for n in range(1, len(itens) + 1):
                info = desenhar_cartao(dict(c, _visiveis=n, itens=itens), perfil, largura, altura, pasta / f"cartao-{c['id']}-{n}.png")
                ini = novo[0] + (n - 1) * passo
                fim = novo[1] if n == len(itens) else novo[0] + n * passo
                saida.append({"arquivo": info["arquivo"], "x": 0, "y": _y(altura, frac_y, info["h"], topo), "inicio": ini, "fim": fim,
                              "animacao": "nenhuma" if n > 1 else anim, "id": c["id"], "tipo": c["tipo"]})
            continue
        info = desenhar_cartao(c, perfil, largura, altura, pasta / f"cartao-{c['id']}.png")
        saida.append({"arquivo": info["arquivo"], "x": 0, "y": _y(altura, frac_y, info["h"], topo), "inicio": novo[0], "fim": novo[1],
                      "animacao": anim, "id": c["id"], "tipo": c["tipo"]})

    md = dados.get("marca_dagua") or {}
    texto_md = md.get("texto") or perfil.get("marca_dagua", {}).get("texto")
    if md.get("ativo", bool(texto_md)) and texto_md:
        info = desenhar_marca_dagua(texto_md, perfil, largura, altura, pasta / "cartao-marca-dagua.png")
        margem = int(min(largura, altura) * 0.035)
        pos = md.get("posicao") or perfil.get("marca_dagua", {}).get("posicao", "superior-direita")
        x = largura - info["w"] - margem if "direita" in pos else margem
        y = margem if "superior" in pos else altura - info["h"] - margem
        logo_pos = (dados.get("logo") or {}).get("posicao") or perfil.get("logo", {}).get("posicao", "superior-direita")
        if pos == logo_pos and (dados.get("logo") or {}).get("ativo", True):
            x = margem if "direita" in pos else largura - info["w"] - margem
        saida.append({"arquivo": info["arquivo"], "x": x, "y": y, "inicio": 0.0, "fim": None, "animacao": "nenhuma",
                      "id": "marca", "tipo": "marca_dagua"})

    ass = dados.get("assinatura") or {}
    if ass.get("ativo") and ass.get("nome"):
        novo = mapear_intervalo(dados, float(ass.get("inicio", 0)), float(ass.get("fim", 0)))
        if novo:
            info = desenhar_assinatura(ass["nome"], ass.get("handle", ""), perfil, largura, altura,
                                       pasta / "cartao-assinatura.png", cargo=ass.get("cargo", ""))
            frac = float(ass.get("y") or 0.90)
            saida.append({"arquivo": info["arquivo"], "x": 0, "y": _y(altura, frac, info["h"], False), "inicio": novo[0],
                          "fim": novo[1], "animacao": ass.get("animacao", "subir"), "id": "assinatura", "tipo": "assinatura"})
    return saida
