"""Perfis de estilo (fontes, cores, legendas, logo, títulos)."""
from __future__ import annotations

import copy
from pathlib import Path

from .util import PASTA_PERFIS, PASTA_LOGOS, PASTA_FONTES, ErroEdicao, ler_json, gravar_json

PERFIL_PADRAO = {
    "nome": "Pessoal",
    "tipo": "pessoal",
    "descricao": "Estilo neutro para vídeos pessoais.",
    "cores": {"primaria": "#111111", "destaque": "#FFD200", "texto": "#FFFFFF"},
    "fonte": {"familia": "Arial", "arquivo": None, "negrito": True},
    "legendas": {
        "posicao": "inferior",          # inferior | centro | superior
        "margem_vertical": 0.10,        # fração da altura
        "tamanho": 0.048,               # fração da altura
        "cor_texto": "#FFFFFF",
        "cor_contorno": "#000000",
        "espessura_contorno": 3,
        "cor_fundo": None,              # ex.: "#000000" para caixa atrás do texto
        "opacidade_fundo": 0.6,
        "max_caracteres_linha": 38,
        "max_linhas": 2,
        "max_duracao": 5.0,
        "modo": "frases",               # frases (2 linhas) | curtas (1 a 3 palavras no ritmo da fala)
        "max_palavras": 3,              # só no modo curtas
        "posicao_percentual": None,     # ex.: 0.62 = base do texto a 62% da altura (sobrepõe 'posicao')
        "italico": False,
        "sombra": 1,
        "sem_pontuacao": False,         # remove vírgulas e pontos finais (visual das referências)
    },
    "cartoes": {"fundo": "#FFFFFF", "texto": "#111111", "destaque": "#FFD200", "check": "#2E9E5B",
                "chip_fundo": "#111111", "chip_texto": "#FFFFFF"},
    "marca_dagua": {"texto": "", "posicao": "superior-direita"},
    "logo": {"arquivo": None, "posicao": "superior-direita", "largura": 0.14, "margem": 0.03},
    "titulo": {"fundo": "#111111", "cor": "#FFFFFF", "cor_subtitulo": "#FFD200", "duracao": 3.0},
    "encerramento": {"fundo": "#111111", "cor": "#FFFFFF", "texto": "", "duracao": 3.0, "mostrar_logo": True},
    "fundo_caber": "#000000",
}


def _mesclar(base: dict, extra: dict) -> dict:
    saida = copy.deepcopy(base)
    for chave, valor in (extra or {}).items():
        if isinstance(valor, dict) and isinstance(saida.get(chave), dict):
            saida[chave] = _mesclar(saida[chave], valor)
        else:
            saida[chave] = valor
    return saida


def criar_perfis_iniciais() -> None:
    PASTA_PERFIS.mkdir(parents=True, exist_ok=True)
    pessoal = PASTA_PERFIS / "pessoal.json"
    if not pessoal.exists():
        gravar_json(pessoal, PERFIL_PADRAO)
    consul = PASTA_PERFIS / "consul-sindico.json"
    if not consul.exists():
        gravar_json(consul, _mesclar(PERFIL_PADRAO, {
            "nome": "Consul Síndico",
            "tipo": "institucional",
            "descricao": "Identidade institucional Consul Síndico: azul-marinho, dourado e branco.",
            "cores": {"primaria": "#0A1A3C", "destaque": "#C2942B", "texto": "#FFFFFF"},
            "legendas": {"cor_texto": "#FFFFFF", "cor_contorno": "#0A1A3C", "espessura_contorno": 3,
                         "cor_fundo": "#0A1A3C", "opacidade_fundo": 0.55},
            "logo": {"arquivo": "consul-sindico.png", "posicao": "superior-direita", "largura": 0.14, "margem": 0.03},
            "titulo": {"fundo": "#0A1A3C", "cor": "#FFFFFF", "cor_subtitulo": "#C2942B", "duracao": 3.0},
            "encerramento": {"fundo": "#0A1A3C", "cor": "#C2942B", "texto": "Consul Síndico",
                             "duracao": 4.0, "mostrar_logo": True},
            "fundo_caber": "#0A1A3C",
            "cartoes": {"fundo": "#FFFFFF", "texto": "#0A1A3C", "destaque": "#C2942B", "check": "#2E9E5B",
                        "chip_fundo": "#0A1A3C", "chip_texto": "#FFFFFF"},
        }))
    reels = PASTA_PERFIS / "consul-sindico-reels.json"
    if not reels.exists():
        gravar_json(reels, _mesclar(PERFIL_PADRAO, {
            "nome": "Consul Síndico — Reels",
            "tipo": "institucional",
            "descricao": "Vertical, legendas curtas no ritmo da fala e cartões brancos com detalhes em dourado.",
            "cores": {"primaria": "#0A1A3C", "destaque": "#C2942B", "texto": "#FFFFFF"},
            "fonte": {"familia": "Arial", "arquivo": None, "negrito": True},
            "legendas": {"modo": "curtas", "max_palavras": 3, "posicao_percentual": 0.62, "tamanho": 0.034,
                         "italico": True, "sombra": 2, "sem_pontuacao": True, "cor_texto": "#FFFFFF",
                         "cor_contorno": "#000000", "espessura_contorno": 1, "cor_fundo": None},
            "logo": {"arquivo": "consul-sindico.png", "posicao": "superior-esquerda", "largura": 0.11, "margem": 0.03},
            "titulo": {"fundo": "#0A1A3C", "cor": "#FFFFFF", "cor_subtitulo": "#C2942B", "duracao": 2.0},
            "encerramento": {"fundo": "#0A1A3C", "cor": "#C2942B", "texto": "Consul Síndico", "duracao": 3.0, "mostrar_logo": True},
            "fundo_caber": "#0A1A3C",
            "cartoes": {"fundo": "#FFFFFF", "texto": "#0A1A3C", "destaque": "#C2942B", "check": "#2E9E5B",
                        "chip_fundo": "#0A1A3C", "chip_texto": "#FFFFFF"},
            "marca_dagua": {"texto": "@consulsindico", "posicao": "superior-direita"},
        }))


def listar_perfis() -> list[dict]:
    criar_perfis_iniciais()
    perfis = []
    for arq in sorted(PASTA_PERFIS.glob("*.json")):
        try:
            dados = ler_json(arq)
        except Exception:
            continue
        perfis.append({"id": arq.stem, "nome": dados.get("nome", arq.stem), "tipo": dados.get("tipo", "pessoal"),
                       "descricao": dados.get("descricao", "")})
    return perfis


def carregar_perfil(identificador: str) -> dict:
    criar_perfis_iniciais()
    arq = PASTA_PERFIS / f"{identificador}.json"
    if not arq.exists():
        disponiveis = ", ".join(p["id"] for p in listar_perfis())
        raise ErroEdicao(f"Perfil '{identificador}' não existe. Perfis disponíveis: {disponiveis}")
    perfil = _mesclar(PERFIL_PADRAO, ler_json(arq))
    perfil["id"] = identificador
    return perfil


def perfil_do_projeto(dados: dict) -> dict:
    """Perfil do projeto com os ajustes de legenda feitos no próprio projeto (modo, posição...)."""
    perfil = carregar_perfil(dados.get("perfil", "pessoal"))
    ajustes = {k: v for k, v in (dados.get("legendas") or {}).items() if k != "ativas" and v is not None}
    if ajustes:
        perfil["legendas"] = _mesclar(perfil["legendas"], ajustes)
    return perfil


def salvar_perfil(identificador: str, dados: dict) -> Path:
    criar_perfis_iniciais()
    arq = PASTA_PERFIS / f"{identificador}.json"
    existente = ler_json(arq) if arq.exists() else {}
    gravar_json(arq, _mesclar(existente, dados))
    return arq


def caminho_logo(perfil: dict, projeto: dict | None = None) -> Path | None:
    """Logo do projeto tem prioridade; depois a do perfil. Retorna None se não existir."""
    candidatos = []
    if projeto and projeto.get("logo", {}).get("arquivo"):
        candidatos.append(projeto["logo"]["arquivo"])
    if perfil.get("logo", {}).get("arquivo"):
        candidatos.append(perfil["logo"]["arquivo"])
    for c in candidatos:
        p = Path(c)
        if not p.is_absolute():
            p = PASTA_LOGOS / c
        if p.exists():
            return p
    return None


def caminho_fonte(perfil: dict) -> tuple[str, Path | None]:
    """Retorna (nome da família, arquivo .ttf se houver)."""
    fonte = perfil.get("fonte", {})
    arquivo = fonte.get("arquivo")
    if arquivo:
        p = Path(arquivo)
        if not p.is_absolute():
            p = PASTA_FONTES / arquivo
        if p.exists():
            return fonte.get("familia") or p.stem, p
    return fonte.get("familia") or "Arial", None


_FONTES_CANDIDATAS = {
    # (negrito, itálico): lista de caminhos possíveis (Windows, macOS, Linux)
    (True, False): ["C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
    (False, False): ["C:/Windows/Fonts/arial.ttf", "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
    (True, True): ["C:/Windows/Fonts/arialbi.ttf", "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    (False, True): ["C:/Windows/Fonts/ariali.ttf", "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


def arquivo_fonte(negrito: bool = True, italico: bool = False) -> Path | None:
    """Arquivo .ttf disponível no sistema para desenhar cartões e textos (ou fonte da pasta 'fontes')."""
    for arq in sorted(PASTA_FONTES.glob("*.ttf")) if PASTA_FONTES.exists() else []:
        nome = arq.stem.lower()
        if (("bold" in nome or "negrito" in nome) == negrito) and (("italic" in nome or "oblique" in nome) == italico):
            return arq
    for c in _FONTES_CANDIDATAS[(negrito, italico)] + _FONTES_CANDIDATAS[(True, False)]:
        if Path(c).exists():
            return Path(c)
    return None
