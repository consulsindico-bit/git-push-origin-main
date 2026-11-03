"""Geração de legendas sincronizadas (SRT e ASS) a partir da transcrição e dos cortes."""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

from .estilos import caminho_fonte
from .projeto import mapear_intervalo
from .util import cor_ass, tempo_ass, tempo_srt

PONTUACAO_FIM = re.compile(r"[.!?…]$")
PONTUACAO_PAUSA = re.compile(r"[,;:]$")
DURACAO_MINIMA = 0.8
INTERVALO_QUEBRA = 0.9   # pausa entre palavras que força nova legenda


def _chave(p: str) -> str:
    return re.sub(r"[^\wáéíóúâêôãõç]", "", p.lower())


def _palavras_do_segmento(seg: dict) -> list[dict]:
    """Palavras com tempo. Se o texto foi corrigido, alinha as palavras novas às originais
    (as iguais mantêm o tempo real; as trocadas/inseridas recebem o tempo das vizinhas)."""
    texto = (seg.get("texto") or "").strip()
    if not texto:
        return []
    novas = texto.split()
    originais = [w for w in (seg.get("palavras") or []) if w.get("p")]
    ini, fim = float(seg["inicio"]), float(seg["fim"])
    if not originais:
        return _distribuir(novas, ini, fim)
    if seg.get("texto") == seg.get("texto_original") and len(originais) == len(novas):
        return [{"p": w["p"], "inicio": w["inicio"], "fim": w["fim"]} for w in originais]

    import difflib
    sm = difflib.SequenceMatcher(a=[_chave(w["p"]) for w in originais], b=[_chave(p) for p in novas], autojunk=False)
    saida: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                o = originais[i1 + k]
                saida.append({"p": novas[j1 + k], "inicio": o["inicio"], "fim": o["fim"]})
        elif tag == "replace":
            saida.extend(_distribuir(novas[j1:j2], originais[i1]["inicio"], originais[i2 - 1]["fim"]))
        elif tag == "insert":
            a = originais[i1 - 1]["fim"] if i1 > 0 else ini
            b = originais[i1]["inicio"] if i1 < len(originais) else fim
            if b - a < 0.15 * (j2 - j1):
                # sem espaço: encosta nas vizinhas, encurtando um pouco a anterior
                if saida:
                    a = max(saida[-1]["inicio"] + 0.1, saida[-1]["fim"] - 0.25 * (j2 - j1))
                    saida[-1]["fim"] = a
                b = max(b, a + 0.25 * (j2 - j1))
            saida.extend(_distribuir(novas[j1:j2], a, b))
        # "delete": palavra original sem correspondente -> some
    return saida


def _distribuir(palavras: list[str], ini: float, fim: float) -> list[dict]:
    total = sum(len(p) + 1 for p in palavras)
    saida, cursor = [], ini
    for p in palavras:
        dur = (fim - ini) * (len(p) + 1) / total if total else 0
        saida.append({"p": p, "inicio": round(cursor, 3), "fim": round(cursor + dur, 3)})
        cursor += dur
    return saida


def _cabe(texto: str, max_car: int, max_linhas: int) -> bool:
    return len(textwrap.wrap(texto, width=max_car, break_long_words=False, break_on_hyphens=False)) <= max_linhas


def _quebrar_linhas(texto: str, max_car: int, max_linhas: int) -> str:
    largura = max_car
    linhas = textwrap.wrap(texto, width=largura, break_long_words=False, break_on_hyphens=False)
    while len(linhas) > max_linhas and largura < len(texto):
        largura += 2  # alarga a linha em vez de perder palavras
        linhas = textwrap.wrap(texto, width=largura, break_long_words=False, break_on_hyphens=False)
    # Equilibra duas linhas (evita primeira linha muito maior que a segunda)
    if len(linhas) == 2 and len(linhas[0]) > len(linhas[1]) * 1.8:
        palavras = texto.split()
        melhor = linhas
        for i in range(1, len(palavras)):
            a, b = " ".join(palavras[:i]), " ".join(palavras[i:])
            if len(a) <= largura and len(b) <= largura and abs(len(a) - len(b)) < abs(len(melhor[0]) - len(melhor[1])):
                melhor = [a, b]
        linhas = melhor
    return "\n".join(linhas)


def tamanho_fonte(perfil: dict, largura: int, altura: int) -> int:
    """Tamanho da fonte das legendas: proporcional à altura, mas limitado pela largura."""
    cfg = perfil["legendas"]
    return max(18, int(min(altura * float(cfg.get("tamanho", 0.048)), largura * 0.062)))


def max_caracteres(perfil: dict, largura: int | None, altura: int | None) -> int:
    cfg = perfil["legendas"]
    max_car = int(cfg.get("max_caracteres_linha", 38))
    if largura and altura:
        tam = tamanho_fonte(perfil, largura, altura)
        max_car = min(max_car, int(0.88 * largura / (tam * 0.55)))
    return max(12, max_car)


def construir_legendas(dados: dict, perfil: dict, largura: int | None = None, altura: int | None = None) -> list[dict]:
    """Devolve legendas já na linha do tempo cortada: [{inicio, fim, texto}]."""
    transcricao = dados.get("transcricao")
    if not transcricao:
        return []
    cfg = perfil["legendas"]
    if largura is None or altura is None:
        from .projeto import dimensoes_formato
        largura, altura = dimensoes_formato(dados.get("formato", "16:9"))
    max_car = max_caracteres(perfil, largura, altura)
    max_linhas = int(cfg.get("max_linhas", 2))
    max_dur = float(cfg.get("max_duracao", 5.0))
    limite_car = max_car * max_linhas

    # 1) Palavras na linha do tempo editada
    palavras: list[dict] = []
    for seg in transcricao["segmentos"]:
        for w in _palavras_do_segmento(seg):
            novo = mapear_intervalo(dados, w["inicio"], w["fim"])
            if novo is None:
                # palavra removida pelo corte (ou curta demais): tenta manter se o ponto central sobreviveu
                continue
            palavras.append({"p": w["p"], "inicio": novo[0], "fim": novo[1], "seg": seg["id"]})

    if cfg.get("modo") == "curtas":
        return _agrupar_curtas(palavras, int(cfg.get("max_palavras", 3)), bool(cfg.get("sem_pontuacao", False)))

    # 2) Agrupa em legendas
    legendas: list[dict] = []
    atual: list[dict] = []

    def fechar():
        if atual:
            texto = " ".join(w["p"] for w in atual)
            legendas.append({"inicio": atual[0]["inicio"], "fim": atual[-1]["fim"], "texto": texto,
                             "segmentos": sorted({w["seg"] for w in atual})})
            atual.clear()

    for w in palavras:
        if atual:
            texto_atual = " ".join(x["p"] for x in atual)
            tamanho_novo = len(texto_atual) + 1 + len(w["p"])
            nao_cabe = not _cabe(texto_atual + " " + w["p"], max_car, max_linhas)
            pausa = w["inicio"] - atual[-1]["fim"]
            duracao = w["fim"] - atual[0]["inicio"]
            termina_frase = bool(PONTUACAO_FIM.search(atual[-1]["p"]))
            termina_pausa = bool(PONTUACAO_PAUSA.search(atual[-1]["p"]))
            if (nao_cabe or pausa > INTERVALO_QUEBRA or duracao > max_dur
                    or w["seg"] != atual[-1]["seg"] and termina_frase
                    or (termina_frase and len(texto_atual) > limite_car * 0.5)
                    or (termina_pausa and tamanho_novo > limite_car * 0.8)):
                fechar()
        atual.append(w)
    fechar()

    # 3) Ajusta durações mínimas e sobreposições, quebra em linhas
    for i, leg in enumerate(legendas):
        if leg["fim"] - leg["inicio"] < DURACAO_MINIMA:
            leg["fim"] = leg["inicio"] + DURACAO_MINIMA
        if i + 1 < len(legendas) and leg["fim"] > legendas[i + 1]["inicio"] - 0.05:
            leg["fim"] = max(leg["inicio"] + 0.3, legendas[i + 1]["inicio"] - 0.05)
        leg["texto"] = _quebrar_linhas(leg["texto"], max_car, max_linhas)
        leg["inicio"], leg["fim"] = round(leg["inicio"], 3), round(leg["fim"], 3)
    return legendas


def _limpar_pontuacao(texto: str) -> str:
    return re.sub(r"[.,;:!?…]+(\s|$)", r"\1", texto).strip()


def _agrupar_curtas(palavras: list[dict], max_palavras: int, sem_pontuacao: bool) -> list[dict]:
    """Grupos de 1 a max_palavras palavras, no ritmo da fala (estilo das referências)."""
    legendas: list[dict] = []
    atual: list[dict] = []

    def fechar():
        if atual:
            texto = " ".join(w["p"] for w in atual)
            if sem_pontuacao:
                texto = _limpar_pontuacao(texto)
            if texto:
                legendas.append({"inicio": atual[0]["inicio"], "fim": atual[-1]["fim"], "texto": texto,
                                 "segmentos": sorted({w["seg"] for w in atual})})
            atual.clear()

    for w in palavras:
        if atual:
            pausa = w["inicio"] - atual[-1]["fim"]
            fim_frase = bool(PONTUACAO_FIM.search(atual[-1]["p"])) or bool(PONTUACAO_PAUSA.search(atual[-1]["p"]))
            if len(atual) >= max_palavras or pausa > 0.45 or fim_frase or (w["fim"] - atual[0]["inicio"]) > 2.2:
                fechar()
        atual.append(w)
    fechar()
    for i, leg in enumerate(legendas):
        minimo = 0.45
        if leg["fim"] - leg["inicio"] < minimo:
            leg["fim"] = leg["inicio"] + minimo
        if i + 1 < len(legendas) and leg["fim"] > legendas[i + 1]["inicio"] - 0.02:
            leg["fim"] = max(leg["inicio"] + 0.2, legendas[i + 1]["inicio"] - 0.02)
        leg["inicio"], leg["fim"] = round(leg["inicio"], 3), round(leg["fim"], 3)
    return legendas


# ---------------------------------------------------------------- escrita

def escrever_srt(legendas: list[dict], caminho: Path, deslocamento: float = 0.0) -> Path:
    linhas = []
    for n, leg in enumerate(legendas, start=1):
        linhas.append(str(n))
        linhas.append(f"{tempo_srt(leg['inicio'] + deslocamento)} --> {tempo_srt(leg['fim'] + deslocamento)}")
        linhas.append(leg["texto"])
        linhas.append("")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho


def escrever_ass(legendas: list[dict], caminho: Path, perfil: dict, largura: int, altura: int,
                 deslocamento: float = 0.0) -> Path:
    cfg = perfil["legendas"]
    familia, _arquivo = caminho_fonte(perfil)
    tamanho = tamanho_fonte(perfil, largura, altura)
    margem_v = int(altura * float(cfg.get("margem_vertical", 0.10)))
    margem_h = int(largura * 0.06)
    alinhamento = {"inferior": 2, "centro": 5, "superior": 8}.get(cfg.get("posicao", "inferior"), 2)
    if cfg.get("posicao_percentual") is not None:
        # base do texto a X% da altura, medida do topo (ex.: 0.62 = abaixo do rosto num vídeo vertical)
        alinhamento = 2
        margem_v = int(altura * (1.0 - float(cfg["posicao_percentual"])))
    negrito = -1 if perfil.get("fonte", {}).get("negrito", True) else 0
    italico = -1 if cfg.get("italico") else 0
    cor_texto = cor_ass(cfg.get("cor_texto", "#FFFFFF"))
    if cfg.get("cor_fundo"):
        estilo_borda = 3
        alfa = int(round(255 * (1 - float(cfg.get("opacidade_fundo", 0.6)))))
        cor_borda = cor_ass(cfg["cor_fundo"], alfa)
        cor_sombra = cor_ass(cfg["cor_fundo"], alfa)
        contorno = max(2, int(tamanho * 0.18))
        sombra = 0
    else:
        estilo_borda = 1
        cor_borda = cor_ass(cfg.get("cor_contorno", "#000000"))
        cor_sombra = cor_ass("#000000", 128)
        contorno = int(cfg.get("espessura_contorno", 3))
        sombra = int(cfg.get("sombra", 1))
    cabecalho = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {largura}
PlayResY: {altura}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Padrao,{familia},{tamanho},{cor_texto},{cor_texto},{cor_borda},{cor_sombra},{negrito},{italico},0,0,100,100,0,0,{estilo_borda},{contorno},{sombra},{alinhamento},{margem_h},{margem_h},{margem_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    eventos = []
    for leg in legendas:
        texto = leg["texto"].replace("\n", "\\N")
        eventos.append(f"Dialogue: 0,{tempo_ass(leg['inicio'] + deslocamento)},{tempo_ass(leg['fim'] + deslocamento)},"
                       f"Padrao,,0,0,0,,{texto}")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(cabecalho + "\n".join(eventos) + "\n", encoding="utf-8-sig")
    return caminho
