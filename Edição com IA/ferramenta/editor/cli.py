"""Linha de comando em português: python -m editor <comando> ..."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import descrever, estilos, legendas as mod_legendas, projeto as mod_projeto, render, silencios as mod_silencios
from . import transcricao as mod_transcricao, verificar as mod_verificar
from .util import (PASTA_BRUTO, PASTA_EXPORTADOS, PASTA_LOGOS, PASTA_PERFIS, PASTA_PROJETOS, RAIZ, EXTENSOES_VIDEO, ErroEdicao, escapar_filtro,
                   barra_progresso, formatar_tempo, garantir_pastas, imprimir, ler_intervalo, ler_tempo, nome_seguro)


def _ids(texto: str) -> list[int]:
    saida: list[int] = []
    for parte in texto.split(","):
        parte = parte.strip()
        if not parte:
            continue
        if "-" in parte:
            a, b = parte.split("-", 1)
            saida.extend(range(int(a), int(b) + 1))
        else:
            saida.append(int(parte))
    return saida


def _carregar(args) -> tuple[Path, dict]:
    return mod_projeto.carregar(args.projeto)


def _resumo(pasta: Path, dados: dict) -> None:
    info = dados["origem"]["info"]
    imprimir(f"Projeto: {dados['nome']}   (pasta: {pasta.name})")
    imprimir(f"Original: {dados['origem']['arquivo']}  {info['largura']}x{info['altura']}  {formatar_tempo(info['duracao'], False)}")
    imprimir(f"Perfil: {dados.get('perfil')}   Formato: {dados.get('formato')}   "
             f"Legendas: {'sim' if dados.get('legendas', {}).get('ativas', True) else 'não'}")
    imprimir(f"Transcrição: {'sim (' + str(len(dados['transcricao']['segmentos'])) + ' trechos)' if dados.get('transcricao') else 'ainda não'}")
    imprimir(f"Remoções: {len(dados.get('remocoes', []))}   Duração editada: {formatar_tempo(mod_projeto.duracao_editada(dados), False)}")
    t = dados.get("titulo", {})
    if t.get("texto"):
        imprimir(f"Título: {t['texto']}" + (f" / {t['subtitulo']}" if t.get("subtitulo") else ""))
    e = dados.get("encerramento", {})
    if e.get("ativo"):
        imprimir(f"Encerramento: ativo" + (f" ({e['texto']})" if e.get("texto") else ""))
    if dados.get("duracao_alvo"):
        imprimir(f"Duração alvo: {dados['duracao_alvo']:.0f}s")


# ---------------------------------------------------------------- comandos

def cmd_importar(args):
    pasta, dados = mod_projeto.importar(args.arquivo, nome=args.nome, perfil=args.perfil)
    imprimir(f"Importado. Cópia preservada em: {dados['origem']['caminho']}")
    imprimir(f"Projeto criado em: {pasta / 'projeto.json'}")
    _resumo(pasta, dados)


def cmd_projetos(args):
    lista = mod_projeto.listar_projetos()
    if not lista:
        imprimir("Nenhum projeto ainda. Use: python -m editor importar <video.mp4>")
    for p in lista:
        imprimir(f"- {p['id']}: {p['origem']} ({formatar_tempo(p['duracao'], False)}) "
                 f"{'transcrito' if p['transcrito'] else 'sem transcrição'}, perfil {p['perfil']}")


def cmd_info(args):
    pasta, dados = _carregar(args)
    _resumo(pasta, dados)


def cmd_transcrever(args):
    pasta, dados = _carregar(args)
    origem = mod_projeto.caminho_origem(dados)
    trabalho = pasta / "trabalho"
    audio = mod_transcricao.extrair_audio(origem, trabalho / "audio-16k.wav")
    barra = barra_progresso("Transcrevendo")

    def progresso(frac, msg):
        barra(frac)
    resultado = mod_transcricao.transcrever(audio, dados["origem"]["info"]["duracao"], modelo=args.modelo, ao_progredir=progresso)
    dados["transcricao"] = resultado
    mod_projeto.salvar(pasta, dados, acao=f"transcrito com modelo {args.modelo}")
    revisao = pasta / "transcricao-revisao.txt"
    revisao.write_text(mod_transcricao.texto_revisao(resultado), encoding="utf-8")
    incertos = mod_transcricao.segmentos_incertos(resultado)
    imprimir(f"{len(resultado['segmentos'])} trechos transcritos. Arquivo para revisão: {revisao}")
    if incertos:
        imprimir(f"⚠ {len(incertos)} trecho(s) incerto(s) precisam de conferência: {[s['id'] for s in incertos]}")
    else:
        imprimir("Nenhum trecho marcado como incerto.")


def cmd_transcricao(args):
    pasta, dados = _carregar(args)
    if not dados.get("transcricao"):
        raise ErroEdicao("Este projeto ainda não foi transcrito. Rode: python -m editor transcrever <projeto>")
    texto = mod_transcricao.texto_revisao(dados["transcricao"])
    if args.exportar:
        Path(args.exportar).write_text(texto, encoding="utf-8")
        imprimir(f"Transcrição gravada em {args.exportar}")
    else:
        imprimir(texto)


def cmd_corrigir(args):
    pasta, dados = _carregar(args)
    if not dados.get("transcricao"):
        raise ErroEdicao("Este projeto ainda não foi transcrito.")
    if args.arquivo:
        conteudo = Path(args.arquivo).read_text(encoding="utf-8")
        n = mod_transcricao.aplicar_texto_revisado(dados["transcricao"], conteudo)
        mod_projeto.salvar(pasta, dados, acao=f"transcrição revisada a partir de {args.arquivo}")
        imprimir(f"Revisão aplicada: {n} alteração(ões).")
    elif args.id is not None and args.texto is not None:
        seg = mod_transcricao.corrigir_segmento(dados["transcricao"], args.id, args.texto)
        mod_projeto.salvar(pasta, dados, acao=f"trecho {args.id} corrigido")
        imprimir(f"[{seg['id']}] {formatar_tempo(seg['inicio'])} --> {formatar_tempo(seg['fim'])} | {seg['texto']}")
    else:
        raise ErroEdicao("Informe --arquivo <revisado.txt> ou --id N --texto \"novo texto\".")
    (pasta / "transcricao-revisao.txt").write_text(mod_transcricao.texto_revisao(dados["transcricao"]), encoding="utf-8")


def cmd_silencios(args):
    pasta, dados = _carregar(args)
    if args.desfazer:
        n = mod_silencios.desfazer(dados)
        mod_projeto.salvar(pasta, dados, acao="remoções de silêncio desfeitas")
        imprimir(f"{n} remoção(ões) de silêncio desfeita(s).")
        return
    if args.aplicar:
        ids = _ids(args.ids) if args.ids else None
        aplicados = mod_silencios.aplicar(dados, ids, margem=args.margem)
        mod_projeto.salvar(pasta, dados, acao=f"silêncios aplicados: {[a['rotulo'] for a in aplicados]}")
        imprimir(f"{len(aplicados)} silêncio(s) removido(s). Duração editada: {formatar_tempo(mod_projeto.duracao_editada(dados), False)}")
        return
    origem = mod_projeto.caminho_origem(dados)
    lista = mod_silencios.sugerir(dados, origem, duracao_minima=args.min, limiar_db=args.limiar)
    mod_projeto.salvar(pasta, dados, acao="silêncios sugeridos")
    if not lista:
        imprimir("Nenhum silêncio encontrado com esses parâmetros.")
        return
    imprimir(f"{len(lista)} silêncio(s) sugerido(s) (mínimo {args.min}s, limiar {args.limiar} dB). Revise e aplique com --aplicar [--ids 1,3]:")
    for s in lista:
        marca = " (já removido)" if s["ja_removido"] else ""
        imprimir(f"  [{s['id']}] {formatar_tempo(s['inicio'])} --> {formatar_tempo(s['fim'])}  {s['duracao']:.2f}s{marca}")
    total = sum(s["duracao"] for s in lista if not s["ja_removido"])
    imprimir(f"Total que seria removido (descontando margens): ~{max(0, total - 0.3 * len(lista)):.1f}s")


def cmd_cortar(args):
    pasta, dados = _carregar(args)
    acoes = []
    if args.remover:
        for trecho in args.remover:
            ini, fim = ler_intervalo(trecho)
            item = mod_projeto.adicionar_remocao(dados, ini, fim, "manual", "por tempo")
            acoes.append(f"removido {formatar_tempo(ini)}-{formatar_tempo(fim)} (id {item['id']})")
    if args.remover_falas:
        if not dados.get("transcricao"):
            raise ErroEdicao("Para cortar por falas, transcreva primeiro.")
        por_id = {s["id"]: s for s in dados["transcricao"]["segmentos"]}
        for ident in _ids(args.remover_falas):
            if ident not in por_id:
                raise ErroEdicao(f"O trecho de fala [{ident}] não existe.")
            s = por_id[ident]
            item = mod_projeto.adicionar_remocao(dados, s["inicio"], s["fim"], "transcricao", f"fala {ident}: {s['texto'][:40]}")
            acoes.append(f"removida a fala [{ident}] (id {item['id']})")
    if args.manter_apenas:
        dur = mod_projeto.duracao_original(dados)
        manter = sorted(ler_intervalo(t) for t in args.manter_apenas)
        cursor = 0.0
        for ini, fim in manter:
            if ini - cursor > 0.05:
                mod_projeto.adicionar_remocao(dados, cursor, ini, "manual", "fora do trecho mantido")
            cursor = max(cursor, fim)
        if dur - cursor > 0.05:
            mod_projeto.adicionar_remocao(dados, cursor, dur, "manual", "fora do trecho mantido")
        acoes.append("mantidos apenas: " + ", ".join(f"{formatar_tempo(a)}-{formatar_tempo(b)}" for a, b in manter))
    if not acoes:
        raise ErroEdicao("Informe --remover inicio-fim, --remover-falas 3,5-7 ou --manter-apenas inicio-fim.")
    mod_projeto.salvar(pasta, dados, acao="; ".join(acoes))
    for a in acoes:
        imprimir(a)
    imprimir(f"Duração editada: {formatar_tempo(mod_projeto.duracao_editada(dados), False)}")


def cmd_cortes(args):
    pasta, dados = _carregar(args)
    if args.limpar:
        dados["remocoes"] = []
        for s in dados.get("silencios_sugeridos") or []:
            s["ja_removido"] = False
        mod_projeto.salvar(pasta, dados, acao="todas as remoções apagadas")
        imprimir("Todas as remoções foram apagadas (o original nunca é alterado).")
        return
    if args.desfazer:
        antes = len(dados["remocoes"])
        dados["remocoes"] = [r for r in dados["remocoes"] if r["id"] not in _ids(args.desfazer)]
        mod_projeto.salvar(pasta, dados, acao=f"remoções desfeitas: {args.desfazer}")
        imprimir(f"{antes - len(dados['remocoes'])} remoção(ões) desfeita(s).")
    if not dados["remocoes"]:
        imprimir("Nenhuma remoção. O vídeo será exportado inteiro.")
    for r in dados["remocoes"]:
        imprimir(f"  [{r['id']}] {formatar_tempo(r['inicio'])} --> {formatar_tempo(r['fim'])}  {r['motivo']}  {r.get('rotulo', '')}")
    imprimir("Trechos mantidos: " + ", ".join(f"{formatar_tempo(a, False)}-{formatar_tempo(b, False)}" for a, b in mod_projeto.trechos_mantidos(dados)))
    imprimir(f"Duração editada: {formatar_tempo(mod_projeto.duracao_editada(dados), False)}")


def cmd_plano(args):
    pasta, dados = _carregar(args)
    _resumo(pasta, dados)
    if dados.get("transcricao"):
        imprimir("\nFalas (id, tempo original, situação, texto):")
        for s in dados["transcricao"]["segmentos"]:
            novo = mod_projeto.mapear_intervalo(dados, s["inicio"], s["fim"])
            situacao = "mantida" if novo else "REMOVIDA"
            aviso = " ⚠" if s.get("incerto") and not s.get("revisado") else ""
            imprimir(f"  [{s['id']}] {formatar_tempo(s['inicio'], False)}-{formatar_tempo(s['fim'], False)} "
                     f"({s['fim'] - s['inicio']:.1f}s) {situacao}{aviso}: {s['texto']}")
    if dados.get("duracao_alvo"):
        dur = mod_projeto.duracao_editada(dados)
        alvo = float(dados["duracao_alvo"])
        if dur > alvo:
            imprimir(f"\n⚠ A duração editada ({dur:.1f}s) ainda passa do alvo ({alvo:.0f}s): faltam cortar {dur - alvo:.1f}s.")
        else:
            imprimir(f"\nDuração editada ({dur:.1f}s) dentro do alvo ({alvo:.0f}s).")


def cmd_audio(args):
    pasta, dados = _carregar(args)
    cfg = dados.setdefault("audio", {})
    if args.ganho is not None:
        cfg["ganho_db"] = float(args.ganho)
    if args.melhorar_voz:
        cfg["melhorar_voz"] = args.melhorar_voz == "sim"
    if args.normalizar:
        cfg["normalizar"] = args.normalizar == "sim"
    mod_projeto.salvar(pasta, dados, acao=f"áudio: {cfg}")
    imprimir(f"Áudio: ganho {cfg.get('ganho_db', 0):+.1f} dB, melhorar voz {'sim' if cfg.get('melhorar_voz', True) else 'não'}, "
             f"normalizar {'sim' if cfg.get('normalizar', True) else 'não'}")


def cmd_texto(args):
    pasta, dados = _carregar(args)
    t = dados.setdefault("titulo", {})
    e = dados.setdefault("encerramento", {})
    if args.titulo is not None:
        t["texto"] = args.titulo
    if args.subtitulo is not None:
        t["subtitulo"] = args.subtitulo
    if args.duracao_titulo is not None:
        t["duracao"] = float(args.duracao_titulo)
    if args.encerramento is not None:
        e["texto"] = args.encerramento
        e["ativo"] = True
    if args.sem_encerramento:
        e["ativo"] = False
    if args.com_encerramento:
        e["ativo"] = True
    if args.duracao_encerramento is not None:
        e["duracao"] = float(args.duracao_encerramento)
    mod_projeto.salvar(pasta, dados, acao="título/encerramento atualizados")
    imprimir(f"Título: {t.get('texto') or '(nenhum)'}" + (f" / {t['subtitulo']}" if t.get("subtitulo") else ""))
    imprimir(f"Encerramento: {'ativo' if e.get('ativo') else 'desativado'}" + (f" ({e['texto']})" if e.get("texto") else ""))


def cmd_logo(args):
    pasta, dados = _carregar(args)
    lg = dados.setdefault("logo", {})
    if args.arquivo:
        p = Path(args.arquivo)
        if not p.exists() and not (PASTA_LOGOS / args.arquivo).exists():
            raise ErroEdicao(f"Logo não encontrada: {args.arquivo}. Coloque o PNG em '{PASTA_LOGOS}'.")
        lg["arquivo"] = str(p) if p.exists() else args.arquivo
        lg["ativo"] = True
    if args.posicao:
        lg["posicao"] = args.posicao
    if args.largura is not None:
        lg["largura"] = float(args.largura)
    if args.desativar:
        lg["ativo"] = False
    if args.ativar:
        lg["ativo"] = True
    mod_projeto.salvar(pasta, dados, acao=f"logo: {lg}")
    perfil = estilos.carregar_perfil(dados.get("perfil", "pessoal"))
    caminho = estilos.caminho_logo(perfil, dados)
    imprimir(f"Logo em uso: {caminho if (caminho and lg.get('ativo', True)) else '(nenhuma)'}")
    if lg.get("ativo", True) and not caminho:
        imprimir(f"⚠ Nenhum arquivo de logo encontrado. Coloque a logo oficial (PNG com fundo transparente) em: {PASTA_LOGOS}")


def cmd_formato(args):
    pasta, dados = _carregar(args)
    mod_projeto.dimensoes_formato(args.formato)
    dados["formato"] = args.formato
    enq = dados.setdefault("enquadramento", {"modo": "cortar", "centro_x": 0.5, "centro_y": 0.5})
    if args.modo:
        enq["modo"] = args.modo
    if args.centro_x is not None:
        enq["centro_x"] = min(1.0, max(0.0, float(args.centro_x)))
    if args.centro_y is not None:
        enq["centro_y"] = min(1.0, max(0.0, float(args.centro_y)))
    mod_projeto.salvar(pasta, dados, acao=f"formato {args.formato} {enq}")
    imprimir(f"Formato {args.formato}, modo '{enq['modo']}', centro ({enq['centro_x']:.2f}, {enq['centro_y']:.2f}).")
    imprimir("Para conferir o enquadramento: python -m editor enquadramento <projeto> --tempo 5")


def cmd_enquadramento(args):
    pasta, dados = _carregar(args)
    r = render.quadro(pasta, dados, tempo=ler_tempo(args.tempo), formato=args.formato)
    imprimir(f"Quadro original com a área marcada: {r['original']}")
    imprimir(f"Resultado enquadrado ({r['formato']}): {r['enquadrado']}")


def cmd_legendas(args):
    pasta, dados = _carregar(args)
    cfg = dados.setdefault("legendas", {})
    if args.ativar:
        cfg["ativas"] = True
    if args.desativar:
        cfg["ativas"] = False
    mod_projeto.salvar(pasta, dados)
    if not dados.get("transcricao"):
        raise ErroEdicao("Transcreva primeiro para gerar legendas.")
    perfil = estilos.carregar_perfil(dados.get("perfil", "pessoal"))
    lista = mod_legendas.construir_legendas(dados, perfil)
    saida = pasta / "legendas-previa.srt"
    mod_legendas.escrever_srt(lista, saida)
    imprimir(f"{len(lista)} legendas (já com os cortes aplicados) gravadas em {saida}")
    imprimir(f"Legendas no vídeo: {'ativadas' if cfg.get('ativas', True) else 'desativadas'}")
    if args.mostrar:
        for n, l in enumerate(lista, 1):
            imprimir(f"  {n}. {formatar_tempo(l['inicio'])} --> {formatar_tempo(l['fim'])}  {l['texto'].replace(chr(10), ' / ')}")


def cmd_perfil(args):
    pasta, dados = _carregar(args)
    estilos.carregar_perfil(args.perfil)
    dados["perfil"] = args.perfil
    mod_projeto.salvar(pasta, dados, acao=f"perfil {args.perfil}")
    imprimir(f"Perfil do projeto: {args.perfil}")


def cmd_perfis(args):
    for p in estilos.listar_perfis():
        imprimir(f"- {p['id']} ({p['tipo']}): {p['nome']} — {p['descricao']}")
    imprimir(f"Os perfis ficam em: {PASTA_PERFIS}")


def cmd_descrever(args):
    pasta, dados = _carregar(args)
    r = descrever.interpretar(dados, " ".join(args.pedido))
    mod_projeto.salvar(pasta, dados, acao=f"descrição: {r['pedido'][:80]}")
    imprimir("Entendi:")
    for e in r["entendido"]:
        imprimir(f"  ✓ {e}")
    if r["nao_entendido"]:
        imprimir("Não entendi (peça na conversa com o Claude ou use os comandos):")
        for e in r["nao_entendido"]:
            imprimir(f"  ? {e}")
    for acao in r["acoes"]:
        if acao == "sugerir_silencios":
            origem = mod_projeto.caminho_origem(dados)
            lista = mod_silencios.sugerir(dados, origem)
            if args.aplicar and lista:
                mod_silencios.aplicar(dados)
                imprimir(f"  → {len(lista)} silêncio(s) removido(s) automaticamente (--aplicar).")
            else:
                imprimir(f"  → {len(lista)} silêncio(s) sugerido(s). Revise com: python -m editor silencios {pasta.name}  e aplique com --aplicar")
            mod_projeto.salvar(pasta, dados)
        elif acao == "transcrever":
            imprimir("  → Para legendas é preciso transcrever: python -m editor transcrever " + pasta.name)
        elif acao == "verificar_duracao":
            dur = mod_projeto.duracao_editada(dados)
            alvo = float(dados["duracao_alvo"])
            if dur > alvo:
                imprimir(f"  → Duração atual {dur:.1f}s > alvo {alvo:.0f}s. Faltam cortar {dur - alvo:.1f}s; veja 'plano' e escolha as falas a remover.")
            else:
                imprimir(f"  → Duração atual {dur:.1f}s já está dentro do alvo.")
        elif acao == "propor_cortes":
            imprimir("  → Escolher o que é 'ideia principal' exige leitura da transcrição: use 'plano' e decida (ou peça ao Claude) quais falas remover.")


def cmd_previsualizar(args):
    pasta, dados = _carregar(args)
    r = render.renderizar(pasta, dados, formato=args.formato, qualidade="previa", ao_progredir=barra_progresso("Prévia"))
    mod_projeto.salvar(pasta, dados)
    imprimir(f"Prévia (baixa resolução) em: {r['arquivo']}")
    chk = render.verificar_saida(Path(r["arquivo"]))
    imprimir(f"Conferido: {'ok' if chk.get('ok') else 'PROBLEMA'} {chk}")


def cmd_exportar(args):
    pasta, dados = _carregar(args)
    formatos = args.formato or [dados.get("formato", "16:9")]
    for f in formatos:
        r = render.renderizar(pasta, dados, formato=f, qualidade="final", nome_saida=args.nome,
                              ao_progredir=barra_progresso(f"Exportando {f}"))
        mod_projeto.salvar(pasta, dados, acao=f"exportado {r['arquivo']}")
        chk = render.verificar_saida(Path(r["arquivo"]))
        imprimir(f"Vídeo final: {r['arquivo']}")
        if r.get("srt"):
            imprimir(f"Legendas SRT: {r['srt']}")
        imprimir(f"Conferido: {'ok' if chk.get('ok') else 'PROBLEMA'} — {chk.get('largura')}x{chk.get('altura')}, "
                 f"{chk.get('duracao')}s, vídeo {'sim' if chk.get('tem_video') else 'NÃO'}, áudio {'sim' if chk.get('tem_audio') else 'NÃO'}")


def cmd_verificar(args):
    pasta, dados = _carregar(args)
    rel = mod_verificar.verificar_projeto(pasta, dados)
    for it in rel["itens"]:
        imprimir(f"  {'✓' if it['ok'] else '✗'} {it['nome']}" + (f" — {it['detalhe']}" if it["detalhe"] else ""))
    imprimir("Resultado geral: " + ("TUDO OK" if rel["ok"] else "HÁ PENDÊNCIAS"))
    if not rel["ok"]:
        sys.exit(1)


def cmd_interface(args):
    from . import servidor
    servidor.iniciar(porta=args.porta, abrir=not args.nao_abrir)


def cmd_autoteste(args):
    """Confere FFmpeg, dependências e renderiza 2 s com legenda, sem mexer nos projetos do usuário."""
    import subprocess
    import tempfile
    from .util import ffmpeg_bin, info_video, escapar_filtro
    from .legendas import escrever_ass
    falhas = []
    imprimir(f"Pasta principal: {RAIZ}")
    for nome in ("ffmpeg", "ffprobe"):
        try:
            caminho = ffmpeg_bin(nome)
            versao = subprocess.run([caminho, "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.splitlines()[0]
            imprimir(f"  [OK] {nome}: {versao}")
        except ErroEdicao as e:
            falhas.append(str(e)); imprimir(f"  [X] {e}")
    try:
        import faster_whisper, ctranslate2, numpy  # noqa: F401
        imprimir(f"  [OK] faster-whisper {faster_whisper.__version__}, ctranslate2 {ctranslate2.__version__}, numpy {numpy.__version__}")
    except Exception as e:  # noqa: BLE001
        falhas.append(f"dependência Python ausente: {e}"); imprimir(f"  [X] dependência Python ausente: {e}")
    if falhas:
        imprimir("Teste final: FALHOU"); sys.exit(1)
    # Renderização curta com legenda, em pasta temporária (com espaço e acento no nome, de propósito)
    with tempfile.TemporaryDirectory(prefix="edição com ia ") as tmp:
        pasta = Path(tmp)
        perfil = estilos.carregar_perfil("consul-sindico")
        escrever_ass([{"inicio": 0.2, "fim": 1.8, "texto": "Teste de legenda\ncom acentuação: ção, ê, ã"}], pasta / "legendas.ass", perfil, 640, 360)
        saida = pasta / "teste.mp4"
        cmd = [ffmpeg_bin(), "-hide_banner", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x0A1A3C:s=640x360:r=30:d=2",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
               "-filter_complex", "[0:v]ass=legendas.ass,format=yuv420p[v];[1:a]anull[a]", "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest", str(saida)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(pasta))
        if r.returncode != 0:
            imprimir("  [X] Falha ao renderizar o vídeo de teste:\n" + r.stderr.strip()[-600:])
            imprimir("Teste final: FALHOU"); sys.exit(1)
        info = info_video(saida)
        ok = info["tem_video"] and info["tem_audio"] and 1.5 < info["duracao"] < 2.5
        imprimir(f"  [{'OK' if ok else 'X'}] Vídeo de 2 s renderizado com legenda e áudio ({info['largura']}x{info['altura']}, {info['duracao']:.2f}s), em pasta com espaço e acento")
        if not ok:
            imprimir("Teste final: FALHOU"); sys.exit(1)
    imprimir("Teste final: OK")


def cmd_referencias(args):
    """Para cada vídeo de referência, gera uma folha com 12 quadros e um resumo (para enviar na conversa)."""
    import subprocess
    from .util import PASTA_IDENTIDADE, ffmpeg_bin, info_video
    pasta = PASTA_IDENTIDADE / "referencias"
    pasta.mkdir(parents=True, exist_ok=True)
    videos = sorted(v for v in pasta.iterdir() if v.suffix.lower() in EXTENSOES_VIDEO)
    if not videos:
        imprimir(f"Nenhum vídeo em: {pasta}")
        return
    linhas = ["# Resumo dos vídeos de referência", ""]
    for v in videos:
        info = info_video(v)
        n = 12
        passo = max(info["duracao"] / n, 0.1)
        saida = pasta / f"{v.stem}-quadros.jpg"
        cmd = [ffmpeg_bin(), "-hide_banner", "-y", "-loglevel", "error", "-i", str(v),
               "-vf", f"drawtext=fontfile='{escapar_filtro(_fonte_arquivo())}':text='%{{pts\\:hms}}':fontsize=44:fontcolor=white:box=1:boxcolor=black@0.5:x=16:y=16,fps=1/{passo:.4f},scale=480:-2,tile=4x3",
               "-frames:v", "1", str(saida)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            imprimir(f"  [X] {v.name}: {r.stderr.strip()[-300:]}")
            continue
        formato = "vertical 9:16" if info["altura"] > info["largura"] else ("quadrado 1:1" if info["altura"] == info["largura"] else "horizontal 16:9")
        linha = f"- {v.name}: {formatar_tempo(info['duracao'], False)}, {info['largura']}x{info['altura']} ({formato}), {info['fps']:.0f} fps"
        linhas.append(linha)
        imprimir(f"  [OK] {linha} -> {saida.name}")
    (pasta / "referencias-resumo.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    imprimir(f"Folhas de quadros e resumo gravados em: {pasta}")
    imprimir("Envie na conversa os arquivos *-quadros.jpg e o referencias-resumo.txt (são pequenos).")


def _fonte_arquivo() -> str:
    from .render import _fonte_drawtext
    from .estilos import carregar_perfil
    f = _fonte_drawtext(carregar_perfil("pessoal"))
    return f.split("'")[1].replace("\\:", ":") if "fontfile" in f else ""


def cmd_pastas(args):
    garantir_pastas()
    estilos.criar_perfis_iniciais()
    imprimir(f"Pasta principal: {RAIZ}")
    imprimir(f"  Material bruto:         {PASTA_BRUTO}")
    imprimir(f"  Identidade/perfis:      {PASTA_PERFIS}")
    imprimir(f"  Logos:                  {PASTA_LOGOS}")
    imprimir(f"  Projetos:               {PASTA_PROJETOS}")
    imprimir(f"  Vídeos exportados:      {PASTA_EXPORTADOS}")


# ---------------------------------------------------------------- parser

def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m editor", description="Edição de vídeo com IA (local, em português).")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("pastas", help="cria/mostra a estrutura de pastas"); s.set_defaults(fn=cmd_pastas)
    s = sub.add_parser("referencias", help="gera folhas de quadros dos vídeos em 2-Identidade visual e referências/referencias"); s.set_defaults(fn=cmd_referencias)
    s = sub.add_parser("autoteste", help="confere FFmpeg e dependências e renderiza um clipe de 2 s"); s.set_defaults(fn=cmd_autoteste)

    s = sub.add_parser("importar", help="copia o vídeo para o material bruto e cria um projeto")
    s.add_argument("arquivo"); s.add_argument("--nome"); s.add_argument("--perfil", default="pessoal"); s.set_defaults(fn=cmd_importar)

    s = sub.add_parser("projetos", help="lista os projetos"); s.set_defaults(fn=cmd_projetos)
    s = sub.add_parser("info", help="resumo do projeto"); s.add_argument("projeto"); s.set_defaults(fn=cmd_info)

    s = sub.add_parser("transcrever", help="transcreve em pt-BR com tempos (local, Whisper)")
    s.add_argument("projeto"); s.add_argument("--modelo", default=mod_transcricao.MODELO_PADRAO, choices=mod_transcricao.MODELOS)
    s.set_defaults(fn=cmd_transcrever)

    s = sub.add_parser("transcricao", help="mostra a transcrição com marcas de incerteza")
    s.add_argument("projeto"); s.add_argument("--exportar", help="grava em um arquivo .txt para revisar"); s.set_defaults(fn=cmd_transcricao)

    s = sub.add_parser("corrigir", help="aplica correções na transcrição")
    s.add_argument("projeto"); s.add_argument("--arquivo", help="txt revisado (formato do comando transcricao)")
    s.add_argument("--id", type=int); s.add_argument("--texto"); s.set_defaults(fn=cmd_corrigir)

    s = sub.add_parser("silencios", help="sugere silêncios; com --aplicar remove os escolhidos")
    s.add_argument("projeto"); s.add_argument("--min", type=float, default=0.7, help="duração mínima do silêncio (s)")
    s.add_argument("--limiar", type=float, default=-35.0, help="limiar em dB"); s.add_argument("--aplicar", action="store_true")
    s.add_argument("--ids", help="ex.: 1,3,5-7"); s.add_argument("--margem", type=float, default=mod_silencios.MARGEM_PADRAO)
    s.add_argument("--desfazer", action="store_true"); s.set_defaults(fn=cmd_silencios)

    s = sub.add_parser("cortar", help="remove trechos por tempo ou por falas da transcrição")
    s.add_argument("projeto"); s.add_argument("--remover", nargs="*", help="ex.: 00:12-00:18 01:05-01:10")
    s.add_argument("--remover-falas", help="ids das falas, ex.: 3,5-7"); s.add_argument("--manter-apenas", nargs="*", help="ex.: 00:05-00:50")
    s.set_defaults(fn=cmd_cortar)

    s = sub.add_parser("cortes", help="lista/desfaz remoções")
    s.add_argument("projeto"); s.add_argument("--desfazer", help="ids, ex.: 2,3"); s.add_argument("--limpar", action="store_true"); s.set_defaults(fn=cmd_cortes)

    s = sub.add_parser("plano", help="mostra falas, o que foi removido e a duração prevista"); s.add_argument("projeto"); s.set_defaults(fn=cmd_plano)

    s = sub.add_parser("audio", help="volume da voz e melhorias")
    s.add_argument("projeto"); s.add_argument("--ganho", type=float, help="dB, ex.: 3 ou -2")
    s.add_argument("--melhorar-voz", choices=["sim", "nao"]); s.add_argument("--normalizar", choices=["sim", "nao"]); s.set_defaults(fn=cmd_audio)

    s = sub.add_parser("texto", help="título e encerramento")
    s.add_argument("projeto"); s.add_argument("--titulo"); s.add_argument("--subtitulo"); s.add_argument("--duracao-titulo", type=float)
    s.add_argument("--encerramento"); s.add_argument("--com-encerramento", action="store_true"); s.add_argument("--sem-encerramento", action="store_true")
    s.add_argument("--duracao-encerramento", type=float); s.set_defaults(fn=cmd_texto)

    s = sub.add_parser("logo", help="logo no vídeo")
    s.add_argument("projeto"); s.add_argument("--arquivo"); s.add_argument("--posicao", choices=["superior-direita", "superior-esquerda", "inferior-direita", "inferior-esquerda"])
    s.add_argument("--largura", type=float, help="fração da largura do vídeo, ex.: 0.14"); s.add_argument("--ativar", action="store_true"); s.add_argument("--desativar", action="store_true")
    s.set_defaults(fn=cmd_logo)

    s = sub.add_parser("formato", help="16:9, 9:16 ou 1:1 e enquadramento")
    s.add_argument("projeto"); s.add_argument("formato", choices=list(mod_projeto.FORMATOS)); s.add_argument("--modo", choices=["cortar", "caber"])
    s.add_argument("--centro-x", type=float, help="0 = esquerda, 0.5 = centro, 1 = direita"); s.add_argument("--centro-y", type=float); s.set_defaults(fn=cmd_formato)

    s = sub.add_parser("enquadramento", help="gera imagens para revisar o enquadramento")
    s.add_argument("projeto"); s.add_argument("--tempo", default="5"); s.add_argument("--formato", choices=list(mod_projeto.FORMATOS)); s.set_defaults(fn=cmd_enquadramento)

    s = sub.add_parser("legendas", help="gera o SRT de prévia (com cortes aplicados) e liga/desliga legendas")
    s.add_argument("projeto"); s.add_argument("--ativar", action="store_true"); s.add_argument("--desativar", action="store_true"); s.add_argument("--mostrar", action="store_true")
    s.set_defaults(fn=cmd_legendas)

    s = sub.add_parser("perfil", help="define o perfil de estilo do projeto"); s.add_argument("projeto"); s.add_argument("perfil"); s.set_defaults(fn=cmd_perfil)
    s = sub.add_parser("perfis", help="lista os perfis de estilo"); s.set_defaults(fn=cmd_perfis)

    s = sub.add_parser("descrever", help="interpreta um pedido em português, ex.: \"até 60 segundos, sem pausas, com legendas\"")
    s.add_argument("projeto"); s.add_argument("pedido", nargs="+"); s.add_argument("--aplicar", action="store_true", help="aplica silêncios sem revisão")
    s.set_defaults(fn=cmd_descrever)

    s = sub.add_parser("previsualizar", help="gera uma prévia rápida em baixa resolução")
    s.add_argument("projeto"); s.add_argument("--formato", choices=list(mod_projeto.FORMATOS)); s.set_defaults(fn=cmd_previsualizar)

    s = sub.add_parser("exportar", help="exporta o vídeo final (MP4 com legendas embutidas + SRT)")
    s.add_argument("projeto"); s.add_argument("--formato", nargs="*", choices=list(mod_projeto.FORMATOS)); s.add_argument("--nome"); s.set_defaults(fn=cmd_exportar)

    s = sub.add_parser("verificar", help="confere original preservado, exportação íntegra, cortes e legendas"); s.add_argument("projeto"); s.set_defaults(fn=cmd_verificar)

    s = sub.add_parser("interface", help="abre a interface local no navegador")
    s.add_argument("--porta", type=int, default=8765); s.add_argument("--nao-abrir", action="store_true"); s.set_defaults(fn=cmd_interface)
    return p


def main(argv=None) -> int:
    garantir_pastas()
    estilos.criar_perfis_iniciais()
    parser = construir_parser()
    args = parser.parse_args(argv)
    try:
        args.fn(args)
    except ErroEdicao as e:
        imprimir(f"\nERRO: {e}")
        return 1
    except KeyboardInterrupt:
        imprimir("\nInterrompido.")
        return 130
    return 0
