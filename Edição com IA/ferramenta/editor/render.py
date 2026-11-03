"""Renderização com FFmpeg: cortes, áudio, formato, título, logo, encerramento e legendas."""
from __future__ import annotations

import datetime as dt
import shutil
import textwrap
from pathlib import Path

from .estilos import caminho_fonte, caminho_logo, carregar_perfil, perfil_do_projeto
from .cartoes import planejar_sobreposicoes
from .legendas import construir_legendas, escrever_ass, escrever_srt
from .projeto import caminho_origem, dimensoes_formato, duracao_editada, trechos_mantidos
from .util import (PASTA_EXPORTADOS, PASTA_FONTES, ErroEdicao, cor_ffmpeg, escapar_filtro,
                   executar, executar_ffmpeg_com_progresso, ffmpeg_bin, info_video, nome_seguro)

FPS_SAIDA = 30
TAXA_AUDIO = 48000


def _fonte_drawtext(perfil: dict) -> str:
    _familia, arquivo = caminho_fonte(perfil)
    if arquivo:
        return f"fontfile='{escapar_filtro(str(arquivo))}'"
    candidatos = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
    ]
    for c in candidatos:
        if Path(c).exists():
            return f"fontfile='{escapar_filtro(c)}'"
    return "font='Sans'"


def _plano(dados: dict, perfil: dict, formato: str, qualidade: str) -> dict:
    """Decisões concretas desta renderização (também devolvidas ao usuário como resumo)."""
    largura, altura = dimensoes_formato(formato)
    if qualidade == "previa":
        fator = 480 / max(largura, altura)
        largura, altura = int(largura * fator) // 2 * 2, int(altura * fator) // 2 * 2
    titulo = dados.get("titulo") or {}
    encerramento = dados.get("encerramento") or {}
    cfg_t = perfil["titulo"]
    cfg_e = perfil["encerramento"]
    dur_titulo = float(titulo.get("duracao") or cfg_t.get("duracao", 3.0)) if titulo.get("texto") else 0.0
    texto_enc = encerramento.get("texto") or (cfg_e.get("texto") if encerramento.get("ativo") else "")
    logo = caminho_logo(perfil, dados) if dados.get("logo", {}).get("ativo", True) else None
    enc_ativo = bool(encerramento.get("ativo")) and (bool(texto_enc) or (logo and cfg_e.get("mostrar_logo", True)))
    dur_enc = float(encerramento.get("duracao") or cfg_e.get("duracao", 3.0)) if enc_ativo else 0.0
    return {
        "formato": formato, "largura": largura, "altura": altura, "qualidade": qualidade,
        "trechos": trechos_mantidos(dados), "duracao_conteudo": duracao_editada(dados),
        "titulo": titulo.get("texto", ""), "subtitulo": titulo.get("subtitulo", ""), "duracao_titulo": dur_titulo,
        "encerramento": texto_enc if enc_ativo else "", "duracao_encerramento": dur_enc, "encerramento_ativo": enc_ativo,
        "logo": str(logo) if logo else None,
        "legendas": bool(dados.get("legendas", {}).get("ativas", True)) and bool(dados.get("transcricao")),
        "audio": dados.get("audio", {}),
        "enquadramento": dados.get("enquadramento", {"modo": "cortar", "centro_x": 0.5, "centro_y": 0.5}),
    }


def _filtro_enquadramento(info: dict, plano: dict, perfil: dict) -> str:
    """Converte o vídeo original para o tamanho de saída (cortando ou encaixando)."""
    L, A = plano["largura"], plano["altura"]
    lo, ao = int(info["largura"]), int(info["altura"])
    enq = plano["enquadramento"]
    modo = enq.get("modo", "cortar")
    if modo == "caber":
        fundo = cor_ffmpeg(perfil.get("fundo_caber", "#000000"))
        return (f"scale={L}:{A}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={L}:{A}:(ow-iw)/2:(oh-ih)/2:color={fundo},setsar=1")
    # cortar: recorta a maior área possível com a proporção de saída, centrada em centro_x/centro_y
    alvo = L / A
    if lo / ao > alvo:
        ch = ao
        cw = int(ao * alvo) // 2 * 2
    else:
        cw = lo
        ch = int(lo / alvo) // 2 * 2
    cx = float(enq.get("centro_x", 0.5))
    cy = float(enq.get("centro_y", 0.5))
    x = int(min(max(0, cx * lo - cw / 2), lo - cw))
    y = int(min(max(0, cy * ao - ch / 2), ao - ch))
    return f"crop={cw}:{ch}:{x}:{y},scale={L}:{A}:flags=lanczos,setsar=1"


def _filtro_zoom(dados: dict, perfil: dict, plano: dict) -> str | None:
    """Aproximações suaves (zoompan) nos intervalos pedidos, já na linha do tempo cortada."""
    from .projeto import mapear_intervalo
    cfg = perfil.get("zoom", {})
    fator_padrao = float(cfg.get("fator", 1.12))
    entrada = max(0.1, float(cfg.get("entrada", 0.5)))
    trechos = []
    for z in dados.get("zooms", []) or []:
        if not z.get("ativo", True):
            continue
        novo = mapear_intervalo(dados, float(z["inicio"]), float(z["fim"]))
        if novo:
            trechos.append((novo[0], novo[1], float(z.get("fator") or fator_padrao), z.get("tipo", "suave")))
    if not trechos:
        return None
    expr = "1"
    for ini, fim, fator, tipo in reversed(trechos):
        if tipo == "corte":
            valor = f"{fator:.4f}"
        else:
            e = min(entrada, (fim - ini) / 2)
            valor = f"(1+{fator - 1:.4f}*min(1\\,(it-{ini:.3f})/{e:.3f}))"
        expr = f"if(between(it\\,{ini:.3f}\\,{fim:.3f})\\,{valor}\\,{expr})"
    L, A = plano["largura"], plano["altura"]
    return (f"zoompan=z='{expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={L}x{A}:fps={FPS_SAIDA}")


def _filtro_audio(plano: dict) -> str:
    cfg = plano["audio"] or {}
    partes = []
    ganho = float(cfg.get("ganho_db", 0) or 0)
    if cfg.get("melhorar_voz", True):
        partes.append("highpass=f=80")
        partes.append("acompressor=threshold=-20dB:ratio=3:attack=5:release=120:makeup=2")
    if abs(ganho) > 0.01:
        partes.append(f"volume={ganho}dB")
    if cfg.get("normalizar", True):
        partes.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    partes.append(f"aformat=sample_fmts=fltp:sample_rates={TAXA_AUDIO}:channel_layouts=stereo")
    return ",".join(partes)


def _linhas_centralizadas(pasta: Path, prefixo: str, texto: str, largura_car: int, fonte: str, tam: int,
                          cor: str, y_base: str) -> str:
    """Um drawtext por linha, cada uma centralizada. y_base é a expressão do topo do bloco."""
    linhas = []
    for par in texto.split("\n"):
        linhas.extend(textwrap.wrap(par, width=largura_car, break_long_words=False) or [""])
    passo = int(tam * 1.3)
    filtros = []
    for i, linha in enumerate(linhas):
        arq = pasta / f"{prefixo}_{i}.txt"
        arq.write_text(linha, encoding="utf-8")
        filtros.append(f"drawtext={fonte}:textfile='{escapar_filtro(arq.name)}':fontsize={tam}:fontcolor={cor}:"
                       f"x=(w-text_w)/2:y={y_base}+{i * passo}")
    return ",".join(filtros), len(linhas) * passo


def _cartao(pasta: Path, perfil: dict, plano: dict, tipo: str, indice_logo: int | None) -> tuple[str, str, str]:
    """Gera o trecho de filtro de um cartão (título ou encerramento). Retorna (filtro, rótulo_v, rótulo_a)."""
    L, A = plano["largura"], plano["altura"]
    fonte = _fonte_drawtext(perfil)
    if tipo == "titulo":
        cfg = perfil["titulo"]
        dur = plano["duracao_titulo"]
        fundo = cor_ffmpeg(cfg.get("fundo", "#111111"))
        tam = int(min(A * 0.065, L * 0.075))
        tam_sub = int(tam * 0.55)
        f_tit, alt_tit = _linhas_centralizadas(pasta, "cartao_titulo", plano["titulo"], max(10, int(0.86 * L / (tam * 0.62))),
                                               fonte, tam, cor_ffmpeg(cfg.get("cor", "#FFFFFF")), "(h/2-ALT)")
        f_tit = f_tit.replace("(h/2-ALT)", f"(h/2-{alt_tit + int(A * 0.03)})")
        filtro = (f"color=c={fundo}:s={L}x{A}:r={FPS_SAIDA}:d={dur:.3f},"
                  f"drawbox=x=0:y={int(A*0.5)-2}:w={L}:h=4:color={cor_ffmpeg(perfil['cores']['destaque'])}:t=fill,"
                  + f_tit)
        if plano["subtitulo"]:
            f_sub, _ = _linhas_centralizadas(pasta, "cartao_subtitulo", plano["subtitulo"], max(12, int(0.86 * L / (tam_sub * 0.62))),
                                             fonte, tam_sub, cor_ffmpeg(cfg.get("cor_subtitulo", "#FFD200")), f"(h/2+{int(A*0.03)})")
            filtro += "," + f_sub
        filtro += ",format=yuv420p"
        rot_v = "[tit_v]"
        filtro = f"{filtro}{rot_v};anullsrc=r={TAXA_AUDIO}:cl=stereo,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS[tit_a]"
        return filtro, rot_v, "[tit_a]"
    cfg = perfil["encerramento"]
    dur = plano["duracao_encerramento"]
    fundo = cor_ffmpeg(cfg.get("fundo", "#111111"))
    tam = int(min(A * 0.05, L * 0.06))
    filtro = f"color=c={fundo}:s={L}x{A}:r={FPS_SAIDA}:d={dur:.3f}"
    com_logo = indice_logo is not None and cfg.get("mostrar_logo", True)
    if com_logo:
        filtro += "[enc_fundo];"
        lw = int(L * 0.4)
        filtro += (f"[{indice_logo}:v]scale={lw}:-1:flags=lanczos[enc_logo];"
                   f"[enc_fundo][enc_logo]overlay=x=(W-w)/2:y=(H/2-h-{int(A*0.02)}):format=auto")
    if plano["encerramento"]:
        f_enc, alt_enc = _linhas_centralizadas(pasta, "cartao_encerramento", plano["encerramento"], max(12, int(0.86 * L / (tam * 0.62))),
                                               fonte, tam, cor_ffmpeg(cfg.get("cor", "#FFFFFF")),
                                               f"(h/2+{int(A*0.04)})" if com_logo else "(h/2-ALT)")
        f_enc = f_enc.replace("(h/2-ALT)", f"(h/2-{alt_enc // 2})")
        filtro += "," + f_enc
    filtro += ",format=yuv420p[enc_v]"
    filtro += f";anullsrc=r={TAXA_AUDIO}:cl=stereo,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS[enc_a]"
    return filtro, "[enc_v]", "[enc_a]"


def renderizar(pasta: Path, dados: dict, formato: str | None = None, qualidade: str = "final",
               nome_saida: str | None = None, ao_progredir=None) -> dict:
    """Gera o vídeo (prévia ou final) e, na exportação final, o SRT ao lado. Retorna um resumo."""
    perfil = perfil_do_projeto(dados)
    formato = formato or dados.get("formato", "16:9")
    origem = caminho_origem(dados)
    info = dados["origem"]["info"]
    plano = _plano(dados, perfil, formato, qualidade)
    if not plano["trechos"]:
        raise ErroEdicao("Todos os trechos foram removidos; não há conteúdo para renderizar.")

    trabalho = pasta / "trabalho"
    trabalho.mkdir(exist_ok=True)
    for antigo in trabalho.glob("cartao_*.txt"):
        antigo.unlink()

    # Legendas (na linha do tempo cortada, deslocadas pelo título)
    legendas = construir_legendas(dados, perfil, plano["largura"], plano["altura"]) if plano["legendas"] else []
    arq_ass = None
    if legendas:
        arq_ass = escrever_ass(legendas, trabalho / "legendas.ass", perfil, plano["largura"], plano["altura"])

    entradas = ["-i", str(origem)]
    indice_logo = None
    if plano["logo"]:
        entradas += ["-i", plano["logo"]]
        indice_logo = 1
    # Cartões, marca d'água e assinatura (PNGs desenhados agora, na resolução de saída)
    sobreposicoes = planejar_sobreposicoes(dados, perfil, plano["largura"], plano["altura"], trabalho)
    indices_sobre = []
    n_entradas = 1 + (1 if indice_logo is not None else 0)
    for sp in sobreposicoes:
        animado = sp.get("animacao", "nenhuma") != "nenhuma" and sp["fim"] is not None
        if animado:
            dur = max(0.2, sp["fim"] - sp["inicio"])
            entradas += ["-loop", "1", "-framerate", str(FPS_SAIDA), "-t", f"{dur:.3f}", "-i", sp["arquivo"]]
        else:
            entradas += ["-i", sp["arquivo"]]
        indices_sobre.append(n_entradas)
        n_entradas += 1

    # --- Filtro principal: cortes + concat
    fc = []
    rotulos = []
    for n, (ini, fim) in enumerate(plano["trechos"]):
        fc.append(f"[0:v]trim=start={ini:.3f}:end={fim:.3f},setpts=PTS-STARTPTS[v{n}]")
        fc.append(f"[0:a]atrim=start={ini:.3f}:end={fim:.3f},asetpts=PTS-STARTPTS[a{n}]")
        rotulos.append(f"[v{n}][a{n}]")
    n_trechos = len(plano["trechos"])
    if n_trechos == 1:
        fc.append("[v0]null[vc];[a0]anull[ac]")
    else:
        fc.append("".join(rotulos) + f"concat=n={n_trechos}:v=1:a=1[vc][ac]")

    # --- Vídeo: enquadramento, fps, legendas, logo
    cadeia_v = [_filtro_enquadramento(info, plano, perfil), f"fps={FPS_SAIDA}"]
    zoom = _filtro_zoom(dados, perfil, plano)
    if zoom:
        cadeia_v.append(zoom)
    cadeia_v.append("format=yuv420p")
    if arq_ass:
        tem_fontes = PASTA_FONTES.exists() and any(f.suffix.lower() in (".ttf", ".otf") for f in PASTA_FONTES.iterdir())
        fontsdir = f":fontsdir='{escapar_filtro(str(PASTA_FONTES))}'" if tem_fontes else ""
        cadeia_v.append(f"ass='{escapar_filtro(arq_ass.name)}'{fontsdir}")
    fc.append("[vc]" + ",".join(cadeia_v) + "[vp]")
    if indice_logo is not None:
        cfg_logo = perfil["logo"]
        # proporcional à área do quadro, para ficar parecida em todos os formatos
        base = (plano["largura"] * plano["altura"]) ** 0.5
        largura_logo = int(base * float(dados.get("logo", {}).get("largura") or cfg_logo.get("largura", 0.14)))
        margem = int(plano["largura"] * float(cfg_logo.get("margem", 0.03)))
        posicao = dados.get("logo", {}).get("posicao") or cfg_logo.get("posicao", "superior-direita")
        pos = {"superior-direita": f"x=W-w-{margem}:y={margem}", "superior-esquerda": f"x={margem}:y={margem}",
               "inferior-direita": f"x=W-w-{margem}:y=H-h-{margem}", "inferior-esquerda": f"x={margem}:y=H-h-{margem}"}
        if posicao not in pos:
            raise ErroEdicao(f"Posição de logo '{posicao}' inválida. Use: {', '.join(pos)}")
        fc.append(f"[{indice_logo}:v]scale={largura_logo}:-1:flags=lanczos[logo]")
        fc.append(f"[vp][logo]overlay={pos[posicao]}:format=auto[vmain]")
    else:
        fc.append("[vp]null[vmain]")
    atual_v = "[vmain]"
    for n, (sp, idx) in enumerate(zip(sobreposicoes, indices_sobre)):
        anim = sp.get("animacao", "nenhuma")
        if sp["fim"] is None or anim == "nenhuma":
            ativo = f":enable='between(t,{sp['inicio']:.3f},{sp['fim']:.3f})'" if sp["fim"] is not None else ""
            fc.append(f"{atual_v}[{idx}:v]overlay=x={sp['x']}:y={sp['y']}:format=auto{ativo}[vs{n}]")
        else:
            dur = max(0.2, sp["fim"] - sp["inicio"])
            t_anim = min(0.35, dur / 3)
            fc.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d={t_anim:.3f}:alpha=1,"
                      f"fade=t=out:st={dur - t_anim:.3f}:d={t_anim:.3f}:alpha=1,setpts=PTS+{sp['inicio']:.3f}/TB[ov{n}]")
            if anim == "subir":
                desloc = int(plano["altura"] * 0.03)
                y_expr = f"'{sp['y']}+{desloc}*max(0\\,1-(t-{sp['inicio']:.3f})/{t_anim:.3f})'"
            else:
                y_expr = str(sp["y"])
            fc.append(f"{atual_v}[ov{n}]overlay=x={sp['x']}:y={y_expr}:format=auto:eof_action=pass:eval=frame[vs{n}]")
        atual_v = f"[vs{n}]"
    if atual_v != "[vmain]":
        fc.append(f"{atual_v}null[vmain2]")
        fc[-1] = fc[-1]  # mantém legível
    else:
        fc.append("[vmain]null[vmain2]")
    fc.append(f"[ac]{_filtro_audio(plano)}[amain]")

    # --- Cartões
    sequencia = []
    if plano["duracao_titulo"] > 0:
        f, rv, ra = _cartao(trabalho, perfil, plano, "titulo", indice_logo)
        fc.append(f)
        sequencia.append((rv, ra))
    sequencia.append(("[vmain2]", "[amain]"))
    if plano["encerramento_ativo"]:
        f, rv, ra = _cartao(trabalho, perfil, plano, "encerramento", indice_logo)
        fc.append(f)
        sequencia.append((rv, ra))
    if len(sequencia) == 1:
        fc.append("[vmain2]null[vout];[amain]anull[aout]")
    else:
        fc.append("".join(rv + ra for rv, ra in sequencia) + f"concat=n={len(sequencia)}:v=1:a=1[vout][aout]")

    filtro_completo = ";".join(fc)
    (trabalho / "filtro.txt").write_text(filtro_completo, encoding="utf-8")

    # --- Saída
    duracao_total = plano["duracao_conteudo"] + plano["duracao_titulo"] + plano["duracao_encerramento"]
    sufixo = formato.replace(":", "x")
    if qualidade == "previa":
        saida = trabalho / f"previa-{sufixo}.mp4"
        codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k"]
    else:
        PASTA_EXPORTADOS.mkdir(parents=True, exist_ok=True)
        base = nome_seguro(nome_saida or dados["nome"])
        saida = PASTA_EXPORTADOS / f"{base}-{sufixo}.mp4"
        n = 2
        while saida.exists():
            saida = PASTA_EXPORTADOS / f"{base}-{sufixo}-{n}.mp4"
            n += 1
        codec = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    # O grafo de filtros vai direto como argumento (funciona em qualquer versão do FFmpeg;
    # a opção -filter_complex_script foi removida nas versões 8+). O filtro.txt fica só para consulta.
    args = entradas + ["-filter_complex", filtro_completo,
                       "-map", "[vout]", "-map", "[aout]", "-r", str(FPS_SAIDA)] + codec + [str(saida)]
    executar_ffmpeg_com_progresso(args, duracao_total, ao_progredir, descricao=qualidade, cwd=trabalho)

    resultado = {"arquivo": str(saida), "formato": formato, "qualidade": qualidade, "duracao_prevista": round(duracao_total, 3),
                 "legendas": len(legendas), "trechos": len(plano["trechos"]), "logo": bool(plano["logo"]),
                 "titulo": bool(plano["duracao_titulo"]), "encerramento": plano["encerramento_ativo"],
                 "cartoes": len(sobreposicoes)}
    if qualidade == "final":
        srt = saida.with_suffix(".srt")
        if legendas:
            escrever_srt(legendas, srt, deslocamento=plano["duracao_titulo"])
            resultado["srt"] = str(srt)
        resultado["quando"] = dt.datetime.now().isoformat(timespec="seconds")
        dados.setdefault("exportacoes", []).append(resultado)
    return resultado


def quadro(pasta: Path, dados: dict, tempo: float, formato: str | None = None) -> dict:
    """Gera duas imagens: o quadro original com a área de corte marcada e o resultado enquadrado."""
    perfil = perfil_do_projeto(dados)
    formato = formato or dados.get("formato", "16:9")
    origem = caminho_origem(dados)
    info = dados["origem"]["info"]
    plano = _plano(dados, perfil, formato, "final")
    trabalho = pasta / "trabalho"
    trabalho.mkdir(exist_ok=True)
    original = trabalho / "quadro-original.jpg"
    enquadrado = trabalho / f"quadro-{formato.replace(':', 'x')}.jpg"
    filtro = _filtro_enquadramento(info, plano, perfil)
    executar([ffmpeg_bin(), "-hide_banner", "-y", "-loglevel", "error", "-ss", f"{tempo:.3f}", "-i", str(origem),
              "-frames:v", "1", "-vf", filtro + ",scale=-2:540", str(enquadrado)], "geração do quadro enquadrado")
    # Quadro original com a área marcada
    marcacao = ""
    if plano["enquadramento"].get("modo", "cortar") == "cortar":
        partes = filtro.split(",")[0]  # crop=cw:ch:x:y
        cw, ch, x, y = partes.replace("crop=", "").split(":")
        cor = cor_ffmpeg(perfil["cores"]["destaque"])
        marcacao = f"drawbox=x={x}:y={y}:w={cw}:h={ch}:color={cor}:t=6,"
    executar([ffmpeg_bin(), "-hide_banner", "-y", "-loglevel", "error", "-ss", f"{tempo:.3f}", "-i", str(origem),
              "-frames:v", "1", "-vf", marcacao + "scale=-2:540", str(original)], "geração do quadro original")
    return {"original": str(original), "enquadrado": str(enquadrado), "tempo": tempo, "formato": formato,
            "enquadramento": plano["enquadramento"]}


def quadro_cartao(pasta: Path, dados: dict, ident: int, formato: str | None = None) -> dict:
    """Imagem de conferência: quadro do vídeo no início do cartão, já enquadrado, com o cartão e a marca d'água por cima."""
    from PIL import Image
    from .cartoes import planejar_sobreposicoes
    from .projeto import mapear_intervalo
    cartao = next((c for c in dados.get("cartoes", []) if c["id"] == int(ident)), None)
    if cartao is None:
        raise ErroEdicao(f"Cartão [{ident}] não existe.")
    perfil = perfil_do_projeto(dados)
    formato = formato or dados.get("formato", "16:9")
    plano = _plano(dados, perfil, formato, "final")
    trabalho = pasta / "trabalho"
    trabalho.mkdir(exist_ok=True)
    origem = caminho_origem(dados)
    tempo = float(cartao["inicio"]) + min(0.5, (float(cartao["fim"]) - float(cartao["inicio"])) / 2)
    base = trabalho / f"quadro-cartao-{ident}-base.png"
    executar([ffmpeg_bin(), "-hide_banner", "-y", "-loglevel", "error", "-ss", f"{tempo:.3f}", "-i", str(origem), "-frames:v", "1",
              "-vf", _filtro_enquadramento(dados["origem"]["info"], plano, perfil), str(base)], "quadro do cartão")
    img = Image.open(base).convert("RGBA")
    novo = mapear_intervalo(dados, float(cartao["inicio"]), float(cartao["fim"]))
    t_edit = (novo[0] + min(0.5, (novo[1] - novo[0]) / 2)) if novo else None
    for sp in planejar_sobreposicoes(dados, perfil, plano["largura"], plano["altura"], trabalho):
        visivel = sp["fim"] is None or (t_edit is not None and sp["inicio"] <= t_edit <= sp["fim"])
        if visivel:
            camada = Image.open(sp["arquivo"]).convert("RGBA")
            img.alpha_composite(camada, (int(sp["x"]), int(sp["y"])))
    saida = trabalho / f"quadro-cartao-{ident}.jpg"
    img.convert("RGB").save(saida, quality=88)
    base.unlink(missing_ok=True)
    return {"arquivo": str(saida), "tempo": tempo, "removido": novo is None}


def verificar_saida(arquivo: Path) -> dict:
    """Confere se o arquivo exportado abre e contém vídeo e áudio."""
    p = Path(arquivo)
    if not p.exists() or p.stat().st_size == 0:
        return {"ok": False, "erro": "arquivo não existe ou está vazio"}
    try:
        info = info_video(p)
    except ErroEdicao as e:
        return {"ok": False, "erro": str(e)}
    ok = info["tem_video"] and info["tem_audio"] and info["duracao"] > 0
    return {"ok": ok, "duracao": round(info["duracao"], 3), "largura": info["largura"], "altura": info["altura"],
            "tem_video": info["tem_video"], "tem_audio": info["tem_audio"], "tamanho_mb": round(p.stat().st_size / 1e6, 2)}


def limpar_trabalho(pasta: Path) -> None:
    t = pasta / "trabalho"
    if t.exists():
        shutil.rmtree(t)
