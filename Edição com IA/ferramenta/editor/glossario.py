"""Glossário de legendas: termos do setor corrigidos de forma consistente na transcrição.

Arquivo: 2-Identidade visual e referências/glossario.txt, uma regra por linha:
    forma errada 1 | forma errada 2 => forma certa
Linhas começando com # são comentários. A comparação ignora maiúsculas e acentos.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .util import PASTA_IDENTIDADE

ARQUIVO = PASTA_IDENTIDADE / "glossario.txt"

GLOSSARIO_INICIAL = """# Glossário de legendas — uma regra por linha: formas erradas (separadas por |) => forma certa
# A ferramenta aplica estas trocas na transcrição (sem diferenciar maiúsculas e acentos).
cindico | cíndico | sindico => síndico
sindica | cíndica => síndica
condominal | condominio => condominial
cota condominal => cota condominial
inadimplencia => inadimplência
inadimplente | inadimplentes => inadimplente
assembleia geral ordinaria | assembleia geral ordinária => Assembleia Geral Ordinária
ago => AGO
age => AGE
conselho fiscal => conselho fiscal
balançete | balancete => balancete
consul sindico | consul cíndico | cônsul síndico | consul síndico => Consul Síndico
fundo de reserva => fundo de reserva
taxa condominal => taxa condominial
convencao => convenção
regimento interno => regimento interno
"""


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip()


def garantir_arquivo() -> Path:
    PASTA_IDENTIDADE.mkdir(parents=True, exist_ok=True)
    if not ARQUIVO.exists():
        ARQUIVO.write_text(GLOSSARIO_INICIAL, encoding="utf-8")
    return ARQUIVO


def carregar() -> list[tuple[list[str], str]]:
    garantir_arquivo()
    regras = []
    for linha in ARQUIVO.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=>" not in linha:
            continue
        errados, certo = linha.split("=>", 1)
        formas = [_norm(e) for e in errados.split("|") if e.strip()]
        certo = certo.strip()
        if formas and certo:
            regras.append((formas, certo))
    return regras


def texto_glossario() -> str:
    return garantir_arquivo().read_text(encoding="utf-8")


def gravar_texto(conteudo: str) -> int:
    garantir_arquivo().write_text(conteudo, encoding="utf-8")
    return len(carregar())


def aplicar_texto(texto: str, regras: list[tuple[list[str], str]] | None = None) -> tuple[str, int]:
    """Aplica as regras ao texto; devolve (novo_texto, quantidade de trocas). Preserva maiúscula inicial da frase."""
    regras = carregar() if regras is None else regras
    # frases mais longas primeiro, para "consul sindico" vencer "sindico"
    regras = sorted(regras, key=lambda r: -max(len(f) for f in r[0]))
    trocas = 0
    for formas, certo in regras:
        for forma in sorted(formas, key=len, reverse=True):
            # casa palavras inteiras, ignorando acentos: compara por versão normalizada
            padrao = r"(?<![\wÀ-ÿ])" + r"\s+".join(re.escape(p) for p in forma.split(" ")) + r"(?![\wÀ-ÿ])"
            def trocar(m):
                nonlocal trocas
                original = m.group(0)
                if original == certo or (original[1:] == certo[1:] and original[0].lower() == certo[0].lower() and original[0].isupper()):
                    return original
                trocas += 1
                novo = certo
                if original[0].isupper() and not certo[0].isupper():
                    novo = certo[0].upper() + certo[1:]
                return novo
            # procura no texto normalizado, mas substitui no texto original com um mapa de posições
            texto = _substituir_sem_acento(texto, padrao, trocar)
    return texto, trocas


def _substituir_sem_acento(texto: str, padrao: str, func) -> str:
    """Aplica um regex sobre a versão sem acentos do texto, substituindo nos trechos equivalentes do original."""
    # Mapeia cada caractere original para um sem acento (NFKD pode gerar 2 símbolos; usamos só o primeiro)
    simples = "".join((unicodedata.normalize("NFKD", ch)[0] if unicodedata.normalize("NFKD", ch) else ch) for ch in texto)
    saida, pos = [], 0
    for m in re.finditer(padrao, simples, flags=re.IGNORECASE):
        saida.append(texto[pos:m.start()])
        classe = type("M", (), {})()
        trecho = texto[m.start():m.end()]
        saida.append(func(type("Match", (), {"group": lambda self, _i=0, t=trecho: t})()))
        pos = m.end()
    saida.append(texto[pos:])
    return "".join(saida)


def aplicar_transcricao(transcricao: dict) -> int:
    """Aplica o glossário a todos os trechos; devolve o total de trocas. Não marca como 'revisado'."""
    regras = carregar()
    total = 0
    for seg in transcricao.get("segmentos", []):
        novo, n = aplicar_texto(seg["texto"], regras)
        if n:
            seg["texto"] = novo
            seg["glossario"] = True
            total += n
    return total
