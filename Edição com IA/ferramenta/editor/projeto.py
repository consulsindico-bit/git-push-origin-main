"""Projeto reutilizável: um arquivo projeto.json com todas as decisões de edição."""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from .util import (PASTA_BRUTO, PASTA_PROJETOS, EXTENSOES_VIDEO, ErroEdicao, garantir_pastas,
                   gravar_json, info_video, ler_json, nome_seguro, sha256_arquivo)

VERSAO_PROJETO = 2

FORMATOS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


def projeto_novo(nome: str, origem: Path, info: dict, perfil: str) -> dict:
    return {
        "versao": VERSAO_PROJETO,
        "nome": nome,
        "criado_em": dt.datetime.now().isoformat(timespec="seconds"),
        "origem": {
            "arquivo": origem.name,                  # cópia preservada em 1-Material bruto
            "caminho": str(origem),
            "sha256": sha256_arquivo(origem),
            "info": info,
        },
        "perfil": perfil,
        "transcricao": None,                         # {"modelo":..., "idioma":"pt", "segmentos":[...]}
        "remocoes": [],                              # [{"id":1,"inicio":..,"fim":..,"motivo":"manual"}]
        "silencios_sugeridos": [],                   # [{"id":1,"inicio":..,"fim":..,"duracao":..}]
        "audio": {"ganho_db": 0.0, "melhorar_voz": True, "normalizar": True},
        "formato": "16:9",
        "enquadramento": {"modo": "cortar", "centro_x": 0.5, "centro_y": 0.5},
        "titulo": {"texto": "", "subtitulo": "", "duracao": None},
        "encerramento": {"texto": "", "duracao": None, "ativo": False},
        "logo": {"arquivo": None, "posicao": None, "largura": None, "ativo": True},
        "legendas": {"ativas": True},
        "cartoes": [],                               # ver cartoes.py
        "zooms": [],                                 # [{"id","inicio","fim","fator","tipo":"suave"|"corte"}]
        "marca_dagua": {"texto": "", "posicao": None, "ativo": False},
        "assinatura": {"nome": "", "handle": "", "inicio": 0, "fim": 0, "ativo": False},
        "duracao_alvo": None,
        "historico": [],
        "exportacoes": [],
    }


# ---------------------------------------------------------------- localizar / carregar

def pasta_projeto(identificador: str | Path) -> Path:
    p = Path(identificador)
    if p.is_dir() and (p / "projeto.json").exists():
        return p
    if p.name == "projeto.json" and p.exists():
        return p.parent
    candidato = PASTA_PROJETOS / str(identificador)
    if (candidato / "projeto.json").exists():
        return candidato
    candidato = PASTA_PROJETOS / nome_seguro(str(identificador))
    if (candidato / "projeto.json").exists():
        return candidato
    existentes = listar_projetos()
    nomes = ", ".join(e["id"] for e in existentes) or "(nenhum)"
    raise ErroEdicao(f"Projeto '{identificador}' não encontrado. Projetos existentes: {nomes}")


def listar_projetos() -> list[dict]:
    garantir_pastas()
    saida = []
    for pasta in sorted(PASTA_PROJETOS.iterdir()):
        arq = pasta / "projeto.json"
        if arq.exists():
            try:
                d = ler_json(arq)
            except Exception:
                continue
            saida.append({"id": pasta.name, "nome": d.get("nome", pasta.name),
                          "origem": d.get("origem", {}).get("arquivo"),
                          "duracao": d.get("origem", {}).get("info", {}).get("duracao", 0),
                          "transcrito": bool(d.get("transcricao")),
                          "perfil": d.get("perfil"), "criado_em": d.get("criado_em")})
    return saida


def carregar(identificador: str | Path) -> tuple[Path, dict]:
    pasta = pasta_projeto(identificador)
    dados = ler_json(pasta / "projeto.json")
    versao = int(dados.get("versao", 1) or 1)
    if versao < VERSAO_PROJETO:
        # Cópia de segurança antes de qualquer alteração por uma versão nova da ferramenta
        backup = pasta / f"projeto.backup-v{versao}.json"
        if not backup.exists():
            shutil.copy2(pasta / "projeto.json", backup)
        dados.setdefault("cartoes", [])
        dados.setdefault("zooms", [])
        dados.setdefault("marca_dagua", {"texto": "", "posicao": None, "ativo": False})
        dados.setdefault("assinatura", {"nome": "", "handle": "", "inicio": 0, "fim": 0, "ativo": False})
        dados["versao"] = VERSAO_PROJETO
        gravar_json(pasta / "projeto.json", dados)
    return pasta, dados


def salvar(pasta: Path, dados: dict, acao: str | None = None) -> None:
    if acao:
        dados.setdefault("historico", []).append(
            {"quando": dt.datetime.now().isoformat(timespec="seconds"), "acao": acao})
        dados["historico"] = dados["historico"][-200:]
    gravar_json(pasta / "projeto.json", dados)


def caminho_origem(dados: dict) -> Path:
    p = Path(dados["origem"]["caminho"])
    if p.exists():
        return p
    alternativo = PASTA_BRUTO / dados["origem"]["arquivo"]
    if alternativo.exists():
        return alternativo
    raise ErroEdicao(f"O vídeo original '{dados['origem']['arquivo']}' não está mais em '1-Material bruto'. "
                     f"Coloque-o de volta nessa pasta para continuar.")


# ---------------------------------------------------------------- importar

def importar(arquivo: str | Path, nome: str | None = None, perfil: str = "pessoal") -> tuple[Path, dict]:
    """Copia o vídeo para 1-Material bruto (sem alterar o original) e cria o projeto."""
    garantir_pastas()
    origem = Path(arquivo).expanduser()
    if not origem.exists():
        raise ErroEdicao(f"Arquivo não encontrado: {origem}")
    if origem.suffix.lower() not in EXTENSOES_VIDEO:
        raise ErroEdicao(f"Extensão '{origem.suffix}' não reconhecida como vídeo. "
                         f"Formatos aceitos: {', '.join(sorted(EXTENSOES_VIDEO))}")
    info = info_video(origem)
    if not info["tem_video"]:
        raise ErroEdicao("O arquivo não tem faixa de vídeo.")
    if not info["tem_audio"]:
        raise ErroEdicao("O arquivo não tem faixa de áudio; a transcrição e os cortes por fala não funcionariam.")

    nome = nome or origem.stem
    identificador = nome_seguro(nome)
    pasta = PASTA_PROJETOS / identificador
    if (pasta / "projeto.json").exists():
        raise ErroEdicao(f"Já existe um projeto chamado '{identificador}'. Use --nome para escolher outro nome.")

    # Copia para o material bruto, sem sobrescrever
    destino = PASTA_BRUTO / origem.name
    try:
        mesmo_arquivo = destino.exists() and destino.samefile(origem)
    except OSError:
        mesmo_arquivo = False
    if destino.exists() and not mesmo_arquivo:
        if sha256_arquivo(destino) != sha256_arquivo(origem):
            base, ext = origem.stem, origem.suffix
            n = 2
            while (PASTA_BRUTO / f"{base}-{n}{ext}").exists():
                n += 1
            destino = PASTA_BRUTO / f"{base}-{n}{ext}"
            shutil.copy2(origem, destino)
    elif not destino.exists():
        shutil.copy2(origem, destino)

    pasta.mkdir(parents=True, exist_ok=True)
    dados = projeto_novo(nome, destino, info, perfil)
    salvar(pasta, dados, acao=f"importado de {origem}")
    return pasta, dados


# ---------------------------------------------------------------- linha do tempo

def duracao_original(dados: dict) -> float:
    return float(dados["origem"]["info"]["duracao"])


def remocoes_mescladas(dados: dict) -> list[tuple[float, float]]:
    dur = duracao_original(dados)
    itens = sorted(((max(0.0, float(r["inicio"])), min(dur, float(r["fim"]))) for r in dados.get("remocoes", [])),
                   key=lambda x: x[0])
    mescla: list[list[float]] = []
    for ini, fim in itens:
        if fim <= ini:
            continue
        if mescla and ini <= mescla[-1][1]:
            mescla[-1][1] = max(mescla[-1][1], fim)
        else:
            mescla.append([ini, fim])
    return [(a, b) for a, b in mescla]


def trechos_mantidos(dados: dict) -> list[tuple[float, float]]:
    """Complemento das remoções dentro de [0, duração]."""
    dur = duracao_original(dados)
    mantidos = []
    cursor = 0.0
    for ini, fim in remocoes_mescladas(dados):
        if ini - cursor > 0.04:
            mantidos.append((cursor, ini))
        cursor = max(cursor, fim)
    if dur - cursor > 0.04:
        mantidos.append((cursor, dur))
    return mantidos


def duracao_editada(dados: dict) -> float:
    return sum(b - a for a, b in trechos_mantidos(dados))


def mapear_tempo(dados: dict, t: float) -> float | None:
    """Converte um instante do vídeo original para o instante no vídeo cortado.
    Retorna None se o instante foi removido."""
    acumulado = 0.0
    for ini, fim in trechos_mantidos(dados):
        if ini <= t <= fim:
            return acumulado + (t - ini)
        acumulado += fim - ini
    return None


def mapear_intervalo(dados: dict, ini: float, fim: float) -> tuple[float, float] | None:
    """Mapeia um intervalo para a linha do tempo cortada, encolhendo pelo que foi removido."""
    acumulado = 0.0
    novo_ini = None
    novo_fim = None
    for a, b in trechos_mantidos(dados):
        lo, hi = max(a, ini), min(b, fim)
        if hi > lo:
            if novo_ini is None:
                novo_ini = acumulado + (lo - a)
            novo_fim = acumulado + (hi - a)
        acumulado += b - a
    if novo_ini is None or novo_fim is None or novo_fim - novo_ini < 0.05:
        return None
    return novo_ini, novo_fim


def proximo_id(lista: list[dict]) -> int:
    return (max((int(x.get("id", 0)) for x in lista), default=0) + 1)


def adicionar_remocao(dados: dict, inicio: float, fim: float, motivo: str, rotulo: str = "") -> dict:
    dur = duracao_original(dados)
    inicio, fim = max(0.0, inicio), min(dur, fim)
    if fim <= inicio:
        raise ErroEdicao(f"Trecho inválido ({inicio:.2f}-{fim:.2f}).")
    item = {"id": proximo_id(dados["remocoes"]), "inicio": round(inicio, 3), "fim": round(fim, 3),
            "motivo": motivo, "rotulo": rotulo}
    dados["remocoes"].append(item)
    return item


def dimensoes_formato(formato: str) -> tuple[int, int]:
    if formato not in FORMATOS:
        raise ErroEdicao(f"Formato '{formato}' inválido. Use 16:9, 9:16 ou 1:1.")
    return FORMATOS[formato]


def adicionar_zoom(dados: dict, inicio: float, fim: float, fator: float | None = None, tipo: str = "suave") -> dict:
    dur = duracao_original(dados)
    inicio, fim = max(0.0, float(inicio)), min(dur, float(fim))
    if fim <= inicio:
        raise ErroEdicao("O zoom precisa de fim maior que início.")
    if tipo not in ("suave", "corte"):
        raise ErroEdicao("Tipo de zoom inválido: use 'suave' (aproxima aos poucos) ou 'corte' (aproximação imediata).")
    lista = dados.setdefault("zooms", [])
    item = {"id": proximo_id(lista), "inicio": round(inicio, 3), "fim": round(fim, 3),
            "fator": float(fator) if fator else None, "tipo": tipo, "ativo": True}
    lista.append(item)
    return item


def zooms_automaticos(dados: dict, fator: float | None = None, minimo: float = 1.5) -> list[dict]:
    """Cortes rápidos: alterna quadro aberto e aproximado a cada fala (estilo das referências).
    Falas mais curtas que `minimo` segundos são agrupadas com a seguinte."""
    transcricao = dados.get("transcricao")
    if not transcricao:
        raise ErroEdicao("Transcreva primeiro para gerar os cortes automáticos.")
    dados["zooms"] = [z for z in dados.get("zooms", []) if not z.get("automatico")]
    aproximar = False
    criados = []
    ini_grupo = None
    for seg in transcricao["segmentos"]:
        if mapear_intervalo(dados, seg["inicio"], seg["fim"]) is None:
            continue
        if ini_grupo is None:
            ini_grupo = float(seg["inicio"])
        if float(seg["fim"]) - ini_grupo < minimo:
            continue
        if aproximar:
            item = adicionar_zoom(dados, ini_grupo, float(seg["fim"]), fator, "corte")
            item["automatico"] = True
            criados.append(item)
        aproximar = not aproximar
        ini_grupo = None
    return criados
