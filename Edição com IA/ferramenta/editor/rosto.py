"""Detecção de rosto (OpenCV, local) para enquadrar automaticamente e para o zoom seguir a pessoa."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .util import ErroEdicao, ffmpeg_bin

LARGURA_ANALISE = 480


def _cv2():
    try:
        import cv2
    except ImportError:
        raise ErroEdicao("A biblioteca 'opencv-python-headless' não está instalada (necessária para detectar o rosto). "
                         "Rode o instalador de novo (instalar.bat) ou: pip install opencv-python-headless==4.14.0.94")
    return cv2


def detectar(video: Path, duracao: float, passo: float = 1.0, ao_progredir=None) -> dict:
    """Amostra um quadro a cada `passo` segundos e devolve as posições do rosto (frações 0..1).

    Resultado: {"centro_x", "centro_y", "largura" (fração da largura do quadro), "amostras": [{"t", "x", "y", "w"}], "quadros_com_rosto", "quadros"}
    """
    cv2 = _cv2()
    cascata = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascata.empty():
        raise ErroEdicao("Não encontrei o modelo de rosto do OpenCV (haarcascade_frontalface_default.xml).")
    amostras = []
    total = 0
    with tempfile.TemporaryDirectory(prefix="rosto-") as tmp:
        padrao = Path(tmp) / "q-%05d.jpg"
        cmd = [ffmpeg_bin(), "-hide_banner", "-y", "-loglevel", "error", "-i", str(video),
               "-vf", f"fps=1/{passo},scale={LARGURA_ANALISE}:-2", "-q:v", "4", str(padrao)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise ErroEdicao("Falha ao extrair quadros para a detecção de rosto:\n" + r.stderr.strip()[-300:])
        quadros = sorted(Path(tmp).glob("q-*.jpg"))
        total = len(quadros)
        for n, q in enumerate(quadros):
            img = cv2.imread(str(q))
            if img is None:
                continue
            h, w = img.shape[:2]
            cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            cinza = cv2.equalizeHist(cinza)
            rostos = cascata.detectMultiScale(cinza, scaleFactor=1.1, minNeighbors=5, minSize=(int(w * 0.08), int(w * 0.08)))
            if len(rostos):
                x, y, rw, rh = max(rostos, key=lambda r: r[2] * r[3])   # o maior rosto
                amostras.append({"t": round(n * passo, 2), "x": round((x + rw / 2) / w, 4), "y": round((y + rh / 2) / h, 4),
                                 "w": round(rw / w, 4)})
            if ao_progredir and total:
                ao_progredir((n + 1) / total, f"analisando quadro {n + 1}/{total}")
    if not amostras:
        return {"centro_x": None, "centro_y": None, "largura": None, "amostras": [], "quadros_com_rosto": 0, "quadros": total}
    xs = sorted(a["x"] for a in amostras)
    ys = sorted(a["y"] for a in amostras)
    ws = sorted(a["w"] for a in amostras)
    mediana = lambda v: v[len(v) // 2]  # noqa: E731
    return {"centro_x": round(mediana(xs), 3), "centro_y": round(mediana(ys), 3), "largura": round(mediana(ws), 3),
            "amostras": amostras, "quadros_com_rosto": len(amostras), "quadros": total}


def centro_em(rosto: dict | None, t: float) -> tuple[float, float] | None:
    """Posição do rosto no instante t (amostra mais próxima), ou None."""
    if not rosto or not rosto.get("amostras"):
        return None
    a = min(rosto["amostras"], key=lambda s: abs(s["t"] - t))
    if abs(a["t"] - t) > 3.0:
        return rosto["centro_x"], rosto["centro_y"]
    return a["x"], a["y"]


def enquadramento_sugerido(rosto: dict, info: dict, formato: str) -> dict:
    """Centro do recorte para o formato: o rosto fica no terço superior, com folga."""
    from .projeto import dimensoes_formato
    L, A = dimensoes_formato(formato)
    lo, ao = int(info["largura"]), int(info["altura"])
    alvo = L / A
    cx = float(rosto["centro_x"])
    cy = float(rosto["centro_y"])
    # Altura do recorte em fração do quadro original
    if lo / ao > alvo:
        ch = 1.0
        cw = (ao * alvo) / lo
    else:
        cw = 1.0
        ch = (lo / alvo) / ao
    # Queremos o rosto a ~38% da altura do recorte
    centro_y = cy + (0.5 - 0.38) * ch
    centro_x = cx
    centro_x = min(max(centro_x, cw / 2), 1 - cw / 2) if cw < 1 else 0.5
    centro_y = min(max(centro_y, ch / 2), 1 - ch / 2) if ch < 1 else 0.5
    return {"modo": "cortar", "centro_x": round(centro_x, 3), "centro_y": round(centro_y, 3)}


def posicao_no_recorte(rosto: dict | None, info: dict, enquadramento: dict, largura: int, altura: int) -> tuple[float, float] | None:
    """Converte o centro do rosto (fração do quadro original) para fração do quadro de saída."""
    if not rosto or rosto.get("centro_x") is None:
        return None
    lo, ao = int(info["largura"]), int(info["altura"])
    alvo = largura / altura
    if (enquadramento or {}).get("modo", "cortar") != "cortar":
        return float(rosto["centro_x"]), float(rosto["centro_y"])
    if lo / ao > alvo:
        ch, cw = 1.0, (ao * alvo) / lo
    else:
        cw, ch = 1.0, (lo / alvo) / ao
    x0 = min(max(float(enquadramento.get("centro_x", 0.5)) - cw / 2, 0), 1 - cw)
    y0 = min(max(float(enquadramento.get("centro_y", 0.5)) - ch / 2, 0), 1 - ch)
    fx = (float(rosto["centro_x"]) - x0) / cw
    fy = (float(rosto["centro_y"]) - y0) / ch
    return min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0)
