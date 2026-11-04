"""Interface local (navegador) em português. Servidor HTTP simples, só na sua máquina (127.0.0.1)."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from . import cartoes as mod_cartoes
from . import descrever, estilos, legendas as mod_legendas, projeto as mod_projeto, render, silencios as mod_silencios
from . import transcricao as mod_transcricao, verificar as mod_verificar
from .util import (PASTA_BRUTO, PASTA_EXPORTADOS, PASTA_INTERFACE, PASTA_LOGOS, RAIZ, EXTENSOES_VIDEO, ErroEdicao,
                   garantir_pastas, nome_seguro)

# ---------------------------------------------------------------- dependências

def verificar_dependencias() -> list[str]:
    """Lista problemas de dependência em linguagem clara (vazia = tudo certo)."""
    import shutil
    problemas = []
    for nome in ("ffmpeg", "ffprobe"):
        if not shutil.which(nome):
            problemas.append(f"O programa '{nome}' não foi encontrado. Instale o FFmpeg (Windows: winget install --id Gyan.FFmpeg -e) "
                             "e abra a interface de novo.")
    try:
        import faster_whisper  # noqa: F401
    except Exception:  # noqa: BLE001
        problemas.append("O pacote 'faster-whisper' não está instalado: a transcrição e as legendas não vão funcionar. "
                         "Rode o instalador (instalar.bat) de novo.")
    return problemas


# ---------------------------------------------------------------- estado

_trava = threading.Lock()
_trava_desenho = threading.Lock()   # desenho de elementos (palco/prévia) um de cada vez: evita PNG lido pela metade
_estado = {
    "projeto_atual": None,          # id da pasta do projeto
    "tarefa": {"ativa": False, "nome": "", "progresso": 0.0, "mensagem": "", "erro": None, "resultado": None},
}


def _tarefa_atualizar(**campos):
    with _trava:
        _estado["tarefa"].update(campos)


def _iniciar_tarefa(nome: str, funcao):
    with _trava:
        if _estado["tarefa"]["ativa"]:
            raise ErroEdicao(f"Já existe uma tarefa em andamento ({_estado['tarefa']['nome']}). Aguarde terminar.")
        _estado["tarefa"] = {"ativa": True, "nome": nome, "progresso": 0.0, "mensagem": "iniciando...", "erro": None, "resultado": None}

    def executar():
        try:
            resultado = funcao()
            _tarefa_atualizar(ativa=False, progresso=1.0, mensagem="concluído", resultado=resultado)
        except ErroEdicao as e:
            _tarefa_atualizar(ativa=False, erro=str(e), mensagem="falhou")
        except Exception as e:  # noqa: BLE001
            _tarefa_atualizar(ativa=False, erro=f"Erro inesperado: {e}\n{traceback.format_exc()[-800:]}", mensagem="falhou")

    threading.Thread(target=executar, daemon=True).start()


def _progresso(frac: float, mensagem=None):
    campos = {"progresso": round(float(frac), 4)}
    if isinstance(mensagem, str):
        campos["mensagem"] = mensagem
    elif isinstance(mensagem, (int, float)):
        campos["mensagem"] = f"{mensagem:.1f}s renderizados"
    _tarefa_atualizar(**campos)


def _projeto_atual() -> tuple[Path, dict]:
    ident = _estado["projeto_atual"]
    if not ident:
        raise ErroEdicao("Nenhum projeto selecionado. Importe um vídeo ou escolha um projeto.")
    return mod_projeto.carregar(ident)


def _dados_projeto_para_tela(pasta: Path, dados: dict) -> dict:
    perfil = estilos.perfil_do_projeto(dados)
    saida = dict(dados)
    saida["id"] = pasta.name
    saida["pasta"] = str(pasta)
    saida["duracao_editada"] = round(mod_projeto.duracao_editada(dados), 3)
    saida["trechos_mantidos"] = mod_projeto.trechos_mantidos(dados)
    saida["logo_em_uso"] = str(estilos.caminho_logo(perfil, dados) or "")
    saida["perfil_dados"] = perfil
    saida["tipos_cartao"] = mod_cartoes.TIPOS
    saida["animacoes"] = mod_cartoes.ANIMACOES
    saida["subtipos_tela"] = mod_cartoes.SUBTIPOS_TELA
    for d in (mod_cartoes.PASTA_VIDEOS_APOIO, mod_cartoes.PASTA_ICONES):
        d.mkdir(parents=True, exist_ok=True)
    saida["videos_apoio"] = [p.name for p in sorted(mod_cartoes.PASTA_VIDEOS_APOIO.iterdir()) if p.suffix.lower() in EXTENSOES_VIDEO]
    saida["icones"] = [p.name for p in sorted(mod_cartoes.PASTA_ICONES.iterdir()) if p.suffix.lower() in (".png", ".webp")]
    for c in saida.get("cartoes") or []:
        c["removido"] = mod_projeto.mapear_intervalo(dados, c["inicio"], c["fim"]) is None
    for z in saida.get("zooms") or []:
        z["removido"] = mod_projeto.mapear_intervalo(dados, z["inicio"], z["fim"]) is None
    mod_cartoes.PASTA_IMAGENS.mkdir(parents=True, exist_ok=True)
    saida["imagens"] = [p.name for p in sorted(mod_cartoes.PASTA_IMAGENS.iterdir()) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    if dados.get("transcricao"):
        for seg in saida["transcricao"]["segmentos"]:
            seg["texto_marcado"] = mod_transcricao.texto_com_marcas(seg)
            seg["mantido"] = mod_projeto.mapear_intervalo(dados, seg["inicio"], seg["fim"]) is not None
        try:
            saida["legendas_previa"] = mod_legendas.construir_legendas(dados, perfil)
        except ErroEdicao:
            saida["legendas_previa"] = []
    previas = sorted((pasta / "trabalho").glob("previa-*.mp4")) if (pasta / "trabalho").exists() else []
    saida["previas"] = [str(p) for p in previas]
    saida["origem_caminho"] = str(mod_projeto.caminho_origem(dados)) if Path(dados["origem"]["caminho"]).exists() else ""
    return saida


# ---------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    server_version = "EdicaoComIA/0.1"

    def log_message(self, fmt, *args):  # silencia o log padrão
        pass

    # --- utilidades
    def _json(self, dados, codigo: int = 200):
        corpo = json.dumps(dados, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _erro(self, mensagem: str, codigo: int = 400):
        self._json({"erro": mensagem}, codigo)

    def _ler_json(self) -> dict:
        tamanho = int(self.headers.get("Content-Length") or 0)
        if not tamanho:
            return {}
        try:
            return json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except json.JSONDecodeError:
            raise ErroEdicao("Pedido inválido (JSON malformado).")

    def _arquivo(self, caminho: Path):
        """Serve um arquivo dentro da pasta principal, com suporte a Range (necessário para o <video>)."""
        try:
            caminho = caminho.resolve()
            caminho.relative_to(RAIZ.resolve())
        except (ValueError, OSError):
            return self._erro("Acesso negado fora da pasta do projeto.", 403)
        if not caminho.is_file():
            return self._erro("Arquivo não encontrado.", 404)
        tamanho = caminho.stat().st_size
        tipo = mimetypes.guess_type(str(caminho))[0] or "application/octet-stream"
        inicio, fim = 0, tamanho - 1
        faixa = self.headers.get("Range")
        parcial = False
        if faixa:
            m = re.match(r"bytes=(\d*)-(\d*)", faixa)
            if m:
                if m.group(1):
                    inicio = int(m.group(1))
                    if m.group(2):
                        fim = min(int(m.group(2)), tamanho - 1)
                elif m.group(2):
                    inicio = max(0, tamanho - int(m.group(2)))
                parcial = True
        if inicio > fim or inicio >= tamanho:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{tamanho}")
            self.end_headers()
            return
        self.send_response(206 if parcial else 200)
        self.send_header("Content-Type", tipo)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - inicio + 1))
        self.send_header("Cache-Control", "no-store")
        if parcial:
            self.send_header("Content-Range", f"bytes {inicio}-{fim}/{tamanho}")
        self.end_headers()
        with open(caminho, "rb") as f:
            f.seek(inicio)
            restante = fim - inicio + 1
            while restante > 0:
                bloco = f.read(min(1024 * 512, restante))
                if not bloco:
                    break
                try:
                    self.wfile.write(bloco)
                except (BrokenPipeError, ConnectionResetError):
                    return
                restante -= len(bloco)

    # --- GET
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        try:
            if url.path in ("/", "/index.html"):
                return self._arquivo(PASTA_INTERFACE / "index.html")
            if url.path == "/arquivo":
                return self._arquivo(Path(q.get("caminho", [""])[0]))
            if url.path == "/api/estado":
                return self._json(self._estado_completo())
            if url.path == "/api/tarefa":
                with _trava:
                    return self._json(dict(_estado["tarefa"]))
            if url.path == "/api/exportados":
                itens = sorted(PASTA_EXPORTADOS.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
                return self._json([{"arquivo": str(p), "nome": p.name, "srt": str(p.with_suffix(".srt")) if p.with_suffix(".srt").exists() else None,
                                    "tamanho_mb": round(p.stat().st_size / 1e6, 2)} for p in itens])
            if url.path == "/api/logos":
                return self._json([p.name for p in sorted(PASTA_LOGOS.iterdir()) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")])
            if url.path == "/api/material":
                return self._json([p.name for p in sorted(PASTA_BRUTO.iterdir()) if p.suffix.lower() in EXTENSOES_VIDEO])
            return self._erro("Rota não encontrada.", 404)
        except ErroEdicao as e:
            return self._erro(str(e))
        except Exception as e:  # noqa: BLE001
            return self._erro(f"Erro inesperado: {e}", 500)

    def _estado_completo(self) -> dict:
        saida = {"projetos": mod_projeto.listar_projetos(), "perfis": estilos.listar_perfis(),
                 "dependencias": verificar_dependencias(), "versao": __version__, "codigo": str(Path(__file__).resolve().parent), "projeto": None, "pastas": {"raiz": str(RAIZ), "bruto": str(PASTA_BRUTO), "logos": str(PASTA_LOGOS),
                                             "exportados": str(PASTA_EXPORTADOS)}}
        with _trava:
            saida["tarefa"] = dict(_estado["tarefa"])
            ident = _estado["projeto_atual"]
        if ident:
            try:
                pasta, dados = mod_projeto.carregar(ident)
                saida["projeto"] = _dados_projeto_para_tela(pasta, dados)
            except ErroEdicao as e:
                saida["aviso"] = str(e)
                _estado["projeto_atual"] = None
        return saida

    # --- POST
    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        try:
            rota = url.path
            if rota == "/api/importar/upload":
                return self._importar_upload(q)
            if rota == "/api/logo/upload":
                return self._logo_upload(q)
            if rota == "/api/imagem/upload":
                return self._imagem_upload(q)
            if rota == "/api/video_apoio/upload":
                return self._video_apoio_upload(q)
            corpo = self._ler_json()
            fn = getattr(self, "rota_" + rota.replace("/api/", "").replace("/", "_"), None)
            if not fn:
                return self._erro("Rota não encontrada.", 404)
            return fn(corpo)
        except ErroEdicao as e:
            return self._erro(str(e))
        except Exception as e:  # noqa: BLE001
            return self._erro(f"Erro inesperado: {e}\n{traceback.format_exc()[-600:]}", 500)

    def _importar_upload(self, q):
        nome = Path(q.get("nome", ["video.mp4"])[0]).name
        if Path(nome).suffix.lower() not in EXTENSOES_VIDEO:
            raise ErroEdicao(f"Extensão não aceita: {Path(nome).suffix}")
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho <= 0:
            raise ErroEdicao("Arquivo vazio.")
        garantir_pastas()
        destino = PASTA_BRUTO / nome
        n = 2
        while destino.exists():
            destino = PASTA_BRUTO / f"{Path(nome).stem}-{n}{Path(nome).suffix}"
            n += 1
        restante = tamanho
        with open(destino, "wb") as f:
            while restante > 0:
                bloco = self.rfile.read(min(1024 * 1024, restante))
                if not bloco:
                    break
                f.write(bloco)
                restante -= len(bloco)
        perfil = q.get("perfil", ["pessoal"])[0]
        nome_projeto = q.get("nome_projeto", [""])[0] or destino.stem
        pasta, dados = mod_projeto.importar(destino, nome=nome_projeto, perfil=perfil)
        _estado["projeto_atual"] = pasta.name
        return self._json({"ok": True, "projeto": pasta.name, "arquivo": str(destino)})

    def _logo_upload(self, q):
        nome = Path(q.get("nome", ["logo.png"])[0]).name
        if Path(nome).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ErroEdicao("A logo precisa ser PNG (de preferência com fundo transparente), JPG ou WEBP.")
        tamanho = int(self.headers.get("Content-Length") or 0)
        PASTA_LOGOS.mkdir(parents=True, exist_ok=True)
        destino = PASTA_LOGOS / nome
        with open(destino, "wb") as f:
            f.write(self.rfile.read(tamanho))
        pasta, dados = _projeto_atual()
        dados.setdefault("logo", {})["arquivo"] = nome
        dados["logo"]["ativo"] = True
        mod_projeto.salvar(pasta, dados, acao=f"logo enviada: {nome}")
        return self._json({"ok": True, "arquivo": str(destino)})

    def _imagem_upload(self, q):
        nome = Path(q.get("nome", ["imagem.png"])[0]).name
        if Path(nome).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ErroEdicao("Envie imagens PNG, JPG ou WEBP.")
        tamanho = int(self.headers.get("Content-Length") or 0)
        mod_cartoes.PASTA_IMAGENS.mkdir(parents=True, exist_ok=True)
        destino = mod_cartoes.PASTA_IMAGENS / nome
        with open(destino, "wb") as f:
            f.write(self.rfile.read(tamanho))
        return self._json({"ok": True, "arquivo": nome})

    def _video_apoio_upload(self, q):
        nome = Path(q.get("nome", ["clipe.mp4"])[0]).name
        if Path(nome).suffix.lower() not in EXTENSOES_VIDEO:
            raise ErroEdicao("Envie um vídeo (mp4, mov, mkv, webm...).")
        tamanho = int(self.headers.get("Content-Length") or 0)
        mod_cartoes.PASTA_VIDEOS_APOIO.mkdir(parents=True, exist_ok=True)
        destino = mod_cartoes.PASTA_VIDEOS_APOIO / nome
        restante = tamanho
        with open(destino, "wb") as f:
            while restante > 0:
                bloco = self.rfile.read(min(1024 * 1024, restante))
                if not bloco:
                    break
                f.write(bloco)
                restante -= len(bloco)
        return self._json({"ok": True, "arquivo": nome})

    # --- rotas JSON
    def rota_projeto_selecionar(self, c):
        pasta, _ = mod_projeto.carregar(c["id"])
        _estado["projeto_atual"] = pasta.name
        return self._json({"ok": True})

    def rota_importar_caminho(self, c):
        caminho = c.get("caminho", "").strip()
        if not caminho:
            raise ErroEdicao("Informe o caminho do vídeo.")
        p = Path(caminho)
        if not p.is_absolute() and (PASTA_BRUTO / caminho).exists():
            p = PASTA_BRUTO / caminho
        pasta, dados = mod_projeto.importar(p, nome=c.get("nome") or None, perfil=c.get("perfil") or "pessoal")
        _estado["projeto_atual"] = pasta.name
        return self._json({"ok": True, "projeto": pasta.name})

    def rota_transcrever(self, c):
        pasta, dados = _projeto_atual()
        modelo = c.get("modelo") or mod_transcricao.MODELO_PADRAO

        def trabalho():
            origem = mod_projeto.caminho_origem(dados)
            _progresso(0.0, "extraindo áudio")
            audio = mod_transcricao.extrair_audio(origem, pasta / "trabalho" / "audio-16k.wav")
            resultado = mod_transcricao.transcrever(audio, dados["origem"]["info"]["duracao"], modelo=modelo, ao_progredir=_progresso)
            dados["transcricao"] = resultado
            mod_projeto.salvar(pasta, dados, acao=f"transcrito com modelo {modelo} (interface)")
            (pasta / "transcricao-revisao.txt").write_text(mod_transcricao.texto_revisao(resultado), encoding="utf-8")
            incertos = mod_transcricao.segmentos_incertos(resultado)
            return {"trechos": len(resultado["segmentos"]), "incertos": [s["id"] for s in incertos]}
        _iniciar_tarefa("Transcrição", trabalho)
        return self._json({"ok": True})

    def rota_transcricao_corrigir(self, c):
        pasta, dados = _projeto_atual()
        if not dados.get("transcricao"):
            raise ErroEdicao("Transcreva primeiro.")
        n = 0
        for item in c.get("segmentos", []):
            seg = next((s for s in dados["transcricao"]["segmentos"] if s["id"] == int(item["id"])), None)
            if seg is None:
                continue
            novo = (item.get("texto") or "").replace(mod_transcricao.MARCA_INCERTA, "").strip()
            if novo != seg["texto"] or not seg.get("revisado"):
                seg["texto"] = novo
                seg["revisado"] = True
                seg["incerto"] = False
                n += 1
        mod_projeto.salvar(pasta, dados, acao=f"transcrição revisada na interface ({n} trechos)")
        (pasta / "transcricao-revisao.txt").write_text(mod_transcricao.texto_revisao(dados["transcricao"]), encoding="utf-8")
        return self._json({"ok": True, "alterados": n})

    def rota_silencios_sugerir(self, c):
        pasta, dados = _projeto_atual()
        lista = mod_silencios.sugerir(dados, mod_projeto.caminho_origem(dados),
                                     duracao_minima=float(c.get("min") or 0.7), limiar_db=float(c.get("limiar") or -35))
        mod_projeto.salvar(pasta, dados, acao="silêncios sugeridos (interface)")
        return self._json({"ok": True, "silencios": lista})

    def rota_silencios_aplicar(self, c):
        pasta, dados = _projeto_atual()
        ids = [int(i) for i in c.get("ids", [])] or None
        aplicados = mod_silencios.aplicar(dados, ids)
        mod_projeto.salvar(pasta, dados, acao=f"silêncios aplicados (interface): {len(aplicados)}")
        return self._json({"ok": True, "aplicados": len(aplicados), "duracao_editada": mod_projeto.duracao_editada(dados)})

    def rota_silencios_desfazer(self, c):
        pasta, dados = _projeto_atual()
        n = mod_silencios.desfazer(dados)
        mod_projeto.salvar(pasta, dados, acao="remoções de silêncio desfeitas (interface)")
        return self._json({"ok": True, "desfeitas": n})

    def rota_cortes_adicionar(self, c):
        pasta, dados = _projeto_atual()
        adicionados = []
        if "inicio" in c and "fim" in c:
            adicionados.append(mod_projeto.adicionar_remocao(dados, float(c["inicio"]), float(c["fim"]), "manual", c.get("rotulo", "por tempo")))
        for ident in c.get("falas", []):
            seg = next((s for s in (dados.get("transcricao") or {}).get("segmentos", []) if s["id"] == int(ident)), None)
            if seg is None:
                raise ErroEdicao(f"Fala [{ident}] não existe.")
            adicionados.append(mod_projeto.adicionar_remocao(dados, seg["inicio"], seg["fim"], "transcricao", f"fala {ident}: {seg['texto'][:40]}"))
        mod_projeto.salvar(pasta, dados, acao=f"cortes adicionados (interface): {len(adicionados)}")
        return self._json({"ok": True, "adicionados": adicionados, "duracao_editada": mod_projeto.duracao_editada(dados)})

    def rota_cortes_remover(self, c):
        pasta, dados = _projeto_atual()
        if c.get("todos"):
            dados["remocoes"] = []
            for s in dados.get("silencios_sugeridos") or []:
                s["ja_removido"] = False
        else:
            ids = {int(i) for i in c.get("ids", [])}
            dados["remocoes"] = [r for r in dados["remocoes"] if r["id"] not in ids]
        mod_projeto.salvar(pasta, dados, acao="cortes desfeitos (interface)")
        return self._json({"ok": True, "duracao_editada": mod_projeto.duracao_editada(dados)})

    def rota_configurar(self, c):
        pasta, dados = _projeto_atual()
        if "perfil" in c:
            estilos.carregar_perfil(c["perfil"])
            dados["perfil"] = c["perfil"]
        if "formato" in c:
            mod_projeto.dimensoes_formato(c["formato"])
            dados["formato"] = c["formato"]
        for chave in ("enquadramento", "titulo", "encerramento", "logo", "audio", "legendas", "marca_dagua", "assinatura"):
            if chave in c and isinstance(c[chave], dict):
                dados.setdefault(chave, {}).update(c[chave])
        if "duracao_alvo" in c:
            dados["duracao_alvo"] = float(c["duracao_alvo"]) if c["duracao_alvo"] else None
        mod_projeto.salvar(pasta, dados, acao="configuração alterada na interface")
        return self._json({"ok": True})

    def rota_cartoes_adicionar(self, c):
        pasta, dados = _projeto_atual()
        itens = [i.strip() for i in (c.get("itens") or "").split(",") if i.strip()] or None
        fala = int(c["fala"]) if c.get("fala") not in (None, "") else None
        num = lambda k: float(c[k]) if c.get(k) not in (None, "") else None  # noqa: E731
        item = mod_cartoes.adicionar(dados, c.get("tipo", "texto"), c.get("texto", ""), num("inicio"), num("fim"),
                                     fala=fala, posicao=c.get("posicao") or None, destaque=c.get("destaque", ""), itens=itens,
                                     numero=c.get("numero") or None, descricao=c.get("descricao", ""), imagem=c.get("imagem") or None,
                                     palavra_ancora=(c.get("palavra") or "").strip() or None, duracao=num("duracao"),
                                     animacao=c.get("animacao") or None, tamanho=num("tamanho"),
                                     subtipo=c.get("subtipo") or None, limite=num("limite"), video=c.get("video") or None,
                                     video_inicio=num("video_inicio"))
        mod_projeto.salvar(pasta, dados, acao=f"elemento {item['id']} adicionado (interface)")
        return self._json({"ok": True, "cartao": item})

    def rota_cartoes_atualizar(self, c):
        pasta, dados = _projeto_atual()
        campos = {k: c.get(k) for k in ("texto", "destaque", "posicao", "numero", "descricao", "animacao", "ativo", "cor_fundo", "cor_texto", "subtipo", "video", "imagem")}
        for k in ("inicio", "fim", "y", "x", "tamanho", "limite", "video_inicio", "janela_y", "janela"):
            if c.get(k) not in (None, ""):
                campos[k] = float(c[k])
        if c.get("itens"):
            campos["itens"] = [i.strip() for i in c["itens"].split(",") if i.strip()]
        item = mod_cartoes.atualizar(dados, int(c["id"]), **campos)
        mod_projeto.salvar(pasta, dados, acao=f"elemento {c['id']} editado (interface)")
        return self._json({"ok": True, "cartao": item})

    def rota_zoom_adicionar(self, c):
        pasta, dados = _projeto_atual()
        ini, fim = c.get("inicio"), c.get("fim")
        if c.get("fala") not in (None, ""):
            seg = next((s for s in (dados.get("transcricao") or {}).get("segmentos", []) if s["id"] == int(c["fala"])), None)
            if seg is None:
                raise ErroEdicao(f"A fala [{c['fala']}] não existe.")
            ini, fim = (ini if ini not in (None, "") else seg["inicio"]), (fim if fim not in (None, "") else seg["fim"])
        if ini in (None, "") or fim in (None, ""):
            raise ErroEdicao("Informe início e fim, ou a fala.")
        item = mod_projeto.adicionar_zoom(dados, float(ini), float(fim), float(c["fator"]) if c.get("fator") else None, c.get("tipo") or "suave")
        mod_projeto.salvar(pasta, dados, acao=f"zoom {item['id']} adicionado (interface)")
        return self._json({"ok": True, "zoom": item})

    def rota_zoom_automatico(self, c):
        pasta, dados = _projeto_atual()
        criados = mod_projeto.zooms_automaticos(dados, float(c["fator"]) if c.get("fator") else None, minimo=float(c.get("minimo") or 1.5))
        mod_projeto.salvar(pasta, dados, acao=f"cortes rápidos automáticos (interface): {len(criados)}")
        return self._json({"ok": True, "criados": len(criados)})

    def rota_rosto(self, c):
        """Detecta o rosto em segundo plano; com 'enquadrar' ajusta o recorte do formato atual."""
        from . import rosto as mod_rosto
        pasta, dados = _projeto_atual()
        enquadrar = bool(c.get("enquadrar"))

        def trabalho():
            origem = mod_projeto.caminho_origem(dados)
            r = mod_rosto.detectar(origem, dados["origem"]["info"]["duracao"], ao_progredir=_progresso)
            dados["rosto"] = r
            if enquadrar and r["centro_x"] is not None:
                dados["enquadramento"] = mod_rosto.enquadramento_sugerido(r, dados["origem"]["info"], dados.get("formato", "16:9"))
            mod_projeto.salvar(pasta, dados, acao="rosto detectado (interface)")
            return {"quadros": r["quadros"], "com_rosto": r["quadros_com_rosto"], "centro_x": r["centro_x"], "centro_y": r["centro_y"],
                    "enquadramento": dados.get("enquadramento")}
        _iniciar_tarefa("Detecção de rosto", trabalho)
        return self._json({"ok": True})

    def rota_zoom_remover(self, c):
        pasta, dados = _projeto_atual()
        dados["zooms"] = [z for z in dados.get("zooms", []) if z["id"] != int(c["id"])]
        mod_projeto.salvar(pasta, dados, acao=f"zoom {c['id']} removido (interface)")
        return self._json({"ok": True})

    def rota_sugerir(self, c):
        """Sugestões (tópicos e destaques) sem aplicar; a interface pede confirmação."""
        import io, contextlib
        from . import cli as mod_cli
        pasta, dados = _projeto_atual()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            class A: pass
            a = A(); a.projeto = pasta.name; a.aplicar = bool(c.get("aplicar"))
            mod_cli.cmd_sugerir(a)
        return self._json({"ok": True, "texto": buf.getvalue()})

    def rota_cartoes_remover(self, c):
        pasta, dados = _projeto_atual()
        mod_cartoes.remover(dados, int(c["id"]))
        mod_projeto.salvar(pasta, dados, acao=f"cartão {c['id']} removido (interface)")
        return self._json({"ok": True})

    def rota_palco(self, c):
        pasta, dados = _projeto_atual()
        with _trava_desenho:
            return self._json(render.palco(pasta, dados, float(c.get("tempo") or 0.0), formato=c.get("formato") or None))

    def rota_cartoes_previa(self, c):
        pasta, dados = _projeto_atual()
        with _trava_desenho:
            return self._json(render.quadro_cartao(pasta, dados, int(c["id"]), formato=c.get("formato") or None))

    def rota_descrever(self, c):
        pasta, dados = _projeto_atual()
        r = descrever.interpretar(dados, c.get("pedido", ""))
        if "sugerir_silencios" in r["acoes"]:
            r["silencios"] = mod_silencios.sugerir(dados, mod_projeto.caminho_origem(dados))
        if "verificar_duracao" in r["acoes"] and dados.get("duracao_alvo"):
            r["duracao_editada"] = mod_projeto.duracao_editada(dados)
            r["duracao_alvo"] = dados["duracao_alvo"]
        mod_projeto.salvar(pasta, dados, acao=f"descrição (interface): {r['pedido'][:80]}")
        return self._json(r)

    def rota_enquadramento(self, c):
        pasta, dados = _projeto_atual()
        r = render.quadro(pasta, dados, tempo=float(c.get("tempo") or 1.0), formato=c.get("formato"))
        return self._json(r)

    def rota_previsualizar(self, c):
        pasta, dados = _projeto_atual()
        formato = c.get("formato") or dados.get("formato")

        def trabalho():
            r = render.renderizar(pasta, dados, formato=formato, qualidade="previa", ao_progredir=_progresso)
            mod_projeto.salvar(pasta, dados)
            r["conferencia"] = render.verificar_saida(Path(r["arquivo"]))
            return r
        _iniciar_tarefa("Prévia", trabalho)
        return self._json({"ok": True})

    def rota_exportar(self, c):
        pasta, dados = _projeto_atual()
        formatos = c.get("formatos") or [dados.get("formato", "16:9")]
        nome = c.get("nome") or None

        def trabalho():
            saidas = []
            for i, f in enumerate(formatos):
                def prog(frac, msg=None, i=i):
                    _progresso((i + frac) / len(formatos), f"exportando {f}: {frac * 100:.0f}%")
                r = render.renderizar(pasta, dados, formato=f, qualidade="final", nome_saida=nome, ao_progredir=prog)
                mod_projeto.salvar(pasta, dados, acao=f"exportado (interface) {r['arquivo']}")
                r["conferencia"] = render.verificar_saida(Path(r["arquivo"]))
                saidas.append(r)
            return {"exportacoes": saidas}
        _iniciar_tarefa("Exportação", trabalho)
        return self._json({"ok": True})

    def rota_verificar(self, c):
        pasta, dados = _projeto_atual()
        return self._json(mod_verificar.verificar_projeto(pasta, dados))


# ---------------------------------------------------------------- iniciar

def iniciar(porta: int = 8765, abrir: bool = True) -> None:
    garantir_pastas()
    estilos.criar_perfis_iniciais()
    if not (PASTA_INTERFACE / "index.html").exists():
        raise ErroEdicao(f"Arquivo da interface não encontrado: {PASTA_INTERFACE / 'index.html'}")
    projetos = mod_projeto.listar_projetos()
    if projetos:
        _estado["projeto_atual"] = projetos[-1]["id"]
    for problema in verificar_dependencias():
        print(f"[!] {problema}", flush=True)
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    except OSError as e:
        raise ErroEdicao(f"Não consegui abrir a porta {porta} ({e}). Talvez a interface já esteja aberta em outra janela; "
                         f"feche-a ou use: python -m editor interface --porta {porta + 1}")
    servidor.daemon_threads = True
    endereco = f"http://127.0.0.1:{porta}/"
    print(f"Edição com IA versão {__version__} — código em: {Path(__file__).resolve().parent}", flush=True)
    print(f"Interface aberta em {endereco}  (só nesta máquina; Ctrl+C para fechar)", flush=True)
    if abrir:
        try:
            webbrowser.open(endereco)
        except Exception:  # noqa: BLE001
            pass
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nInterface encerrada.")
    finally:
        servidor.server_close()
