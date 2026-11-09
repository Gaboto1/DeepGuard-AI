"""
Cruza compuerta de contenido y deteccion de rostro sobre el material relevante.

La pregunta que responde
------------------------
Subir el peso del track facial de 0.60 a 0.80 llevo la deteccion de deepfake
facial de 11,7 % a 94,0 % sobre ff++, pero empeoro el retenido: las imagenes
de IA erroneamente declaradas autenticas pasaron de 4,9 % a 12,6 %, y 29
imagenes de FLUX se movieron de "Inconclusive" a "Low Evidence".

La causa probable es de dominio. El cabezal facial se entrena SOLO con ff++,
es decir con intercambio de rostro sobre fotografia: nunca vio un rostro
enteramente sintetico. FLUX y DALL-E 3 estan llenos de retratos generados, y
ante ellos el cabezal opina fuera de su dominio. Darle mas peso amplifica ese
error.

Si eso es asi, la compuerta de tipo de contenido deberia separar los dos casos:
ff++ es fotografia y los retratos de FLUX deberian caer del lado de obra
grafica. En ese caso el peso facial alto puede condicionarse a que la compuerta
diga fotografia, que es el dominio en que el cabezal fue entrenado, sin tocar
el entrenamiento.

Este script mide esa separacion antes de cambiar nada: no vale condicionar una
regla a una compuerta sin saber si la compuerta distingue los casos.

Salida: reports/diagnostico_compuerta_rostro.json
"""
import argparse
import json
import os
import random
import sys
import time

from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "models"))
os.environ.setdefault("HF_HOME", str(ROOT / "models"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(str(BACKEND))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
OUT = ROOT / "reports" / "diagnostico_compuerta_rostro.json"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Las cuatro fuentes retenidas mas las dos de ff++, que son los dos extremos
# del problema: rostro real, intercambio de rostro y rostro sintetico.
GRUPOS = [
    ("lfw",      "real retenido",        ROOT / "data/heldout/real/lfw"),
    ("imagenet", "real retenido",        ROOT / "data/heldout/real/imagenet"),
    ("flux",     "IA retenido",          ROOT / "data/heldout/ai/flux"),
    ("dalle3",   "IA retenido",          ROOT / "data/heldout/ai/dalle3"),
    ("ff_real",  "real entrenamiento",   ROOT / "data/ff++_faces/real"),
    ("ff_fake",  "deepfake entrenam.",   ROOT / "data/ff++_faces/fake"),
]


def recoger(base: Path, n: int, seed: int = 13) -> list[Path]:
    files = sorted(p for p in base.rglob("*") if p.suffix.lower() in EXTS)
    random.Random(seed).shuffle(files)
    return files[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="imagenes por fuente")
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args()

    print("Cargando compuerta de contenido y detector de rostro...")
    from app.models.content_type_gate import ContentTypeGate, ARTWORK_THRESHOLD
    from app.models.face_detector import FaceDetector
    gate = ContentTypeGate.get_instance()
    gate.load()
    fd = FaceDetector.get_instance()
    fd.load()
    print(f"Listo. Umbral de obra grafica = {ARTWORK_THRESHOLD}\n")

    rep = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "umbral_obra_grafica": ARTWORK_THRESHOLD,
        "n_por_fuente": args.n,
        "fuentes": {},
    }

    cab = (f"{'fuente':10s} {'naturaleza':20s} {'n':>4s} {'p_obra':>7s} "
           f"{'%obra':>7s} {'%rostro':>8s} {'%obra Y rostro':>15s}")
    print(cab)
    print("-" * len(cab))

    t0 = time.time()
    for nombre, naturaleza, base in GRUPOS:
        if not base.exists():
            print(f"{nombre:10s} [!] falta {base}")
            continue
        rutas = recoger(base, args.n)
        probs, rostros = [], []
        for i in range(0, len(rutas), args.batch):
            imgs, ok = [], []
            for r in rutas[i:i + args.batch]:
                try:
                    imgs.append(Image.open(r).convert("RGB"))
                    ok.append(r)
                except Exception:
                    continue
            if not imgs:
                continue
            probs.extend(gate.artwork_probability_batch(imgs))
            for im in imgs:
                try:
                    caras = fd.detect_faces(im)
                    rostros.append(1 if caras else 0)
                except Exception:
                    rostros.append(0)
                im.close()

        p = np.array(probs, dtype=float)
        r = np.array(rostros, dtype=int)
        n = min(len(p), len(r))
        p, r = p[:n], r[:n]
        es_obra = p >= ARTWORK_THRESHOLD
        rep["fuentes"][nombre] = {
            "naturaleza": naturaleza,
            "n": int(n),
            "prob_obra_media": round(float(p.mean()), 4),
            "pct_obra_grafica": round(100 * float(es_obra.mean()), 2),
            "pct_con_rostro": round(100 * float((r == 1).mean()), 2),
            "pct_obra_y_rostro": round(
                100 * float((es_obra & (r == 1)).mean()), 2),
        }
        v = rep["fuentes"][nombre]
        print(f"{nombre:10s} {naturaleza:20s} {n:4d} {p.mean():7.4f} "
              f"{v['pct_obra_grafica']:6.2f}% {v['pct_con_rostro']:7.2f}% "
              f"{v['pct_obra_y_rostro']:14.2f}%")

    print(f"\nTiempo: {(time.time()-t0)/60:.1f} min")

    f = rep["fuentes"]
    if {"ff_fake", "flux"} <= set(f):
        print("\n=== LECTURA ===")
        print(f"  ff++ fake (intercambio de rostro):  "
              f"{f['ff_fake']['pct_obra_grafica']:.1f} % clasificado obra gráfica")
        print(f"  FLUX (rostro sintetico):            "
              f"{f['flux']['pct_obra_grafica']:.1f} % clasificado obra gráfica")
        sep = f["flux"]["pct_obra_grafica"] - f["ff_fake"]["pct_obra_grafica"]
        print(f"\n  Separacion: {sep:+.1f} puntos.")
        if sep > 40:
            print("  La compuerta SI distingue los dos casos. Condicionar el")
            print("  peso facial alto a 'fotografia' es viable y atacaria el")
            print("  error de dominio sin tocar el entrenamiento.")
        else:
            print("  La compuerta NO separa lo suficiente. Condicionar el peso")
            print("  a la compuerta no arreglaria el error de dominio: haria")
            print("  falta entrenar el cabezal facial con rostros sinteticos")
            print("  como clase positiva, no solo con intercambio de rostro.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
