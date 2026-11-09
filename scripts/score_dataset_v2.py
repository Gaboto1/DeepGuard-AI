"""
Puntua un dataset multi-fuente con los 6 modelos del ensemble + la compuerta
de tipo de contenido (CLIP zero-shot foto vs arte).

A diferencia del dataset anterior (donde TODO lo real venia de ff++_faces y
TODO lo IA de real_world_training — confundiendo "clase" con "fuente"), aqui
cada clase se alimenta de multiples fuentes independientes:

    real (0): coco/val2017          fotografia natural diversa
              ff++_faces/real       fotogramas de video comprimido (rostros)
    IA   (1): diffusiondb           arte generado por Stable Diffusion
              ai_sdturbo            imagenes IA genericas
              ai_sdturbo_sports     imagenes IA fotorrealistas (deporte)
              ff++_faces/fake       deepfakes faciales

La columna `source` permite evaluacion leave-one-source-out, unica forma
honesta de medir generalizacion con estos datos.

Salida: reports/dataset_v2_scores.csv
"""
import argparse
import csv
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "models"))
os.environ.setdefault("HF_HOME", str(ROOT / "models"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(str(BACKEND))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# (nombre_fuente, ruta_relativa, label, n_objetivo)
#
# Nueve fuentes equilibradas: 20.000 reales y 20.000 sinteticas. El tamano se
# elige por coste — aqui corren los seis detectores sobre GPU, a diferencia de
# los embeddings CLIP, que son mucho mas rapidos y usan un conjunto mayor.
PLAN = [
    # ── real (30.000) ──
    ("coco_train",     "data/v3/real/coco_train",                   0, 12000),
    ("celeba",         "data/v3/real/celeba",                       0,  7000),
    ("coco",           "data/coco/val2017",                         0,  4000),
    ("ff_real",        "data/ff++_faces/real",                      0,  7000),
    # ── sintetica (30.000) ──
    ("elsa_multigen",  "data/v3/ai/elsa_multigen",                  1, 14000),
    ("midjourney",     "data/v3/ai/midjourney",                     1,  4000),
    ("diffusiondb",    "data/diffusiondb",                          1,  6000),
    ("ff_fake",        "data/ff++_faces/fake",                      1,  5000),
    ("sdturbo_sports", "data/real_world_training/ai_sdturbo_sports", 1,  1000),
]

OUT = ROOT / "reports" / "dataset_v2_scores.csv"

COLUMNS = [
    "source", "label", "path",
    "face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
    "ai_art_detector", "siglip_deepfake", "ai_human_detector",
    "artwork_probability",
]


def collect(base: Path, n: int, seed: int = 42) -> list[Path]:
    """Muestreo reproducible sin cargar toda la lista en memoria si es enorme."""
    files: list[Path] = []
    for p in sorted(base.rglob("*")):
        if p.suffix.lower() in EXTS:
            files.append(p)
    rnd = random.Random(seed)
    rnd.shuffle(files)
    return files[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0, help="0 = plan completo")
    args = ap.parse_args()

    print("=" * 70)
    print("  Scoring dataset v2 — multi-fuente, des-confundido")
    print("=" * 70)

    # ── recolecta rutas ──────────────────────────────────────────────────────
    items: list[tuple[str, int, Path]] = []
    for name, rel, label, n in PLAN:
        base = ROOT / rel
        if not base.exists():
            print(f"  [!] {name}: {base} no existe — omitido")
            continue
        if args.limit:
            n = min(n, args.limit)
        got = collect(base, n)
        items.extend((name, label, p) for p in got)
        print(f"  {name:16s} label={label}  {len(got):5d} imagenes")

    random.Random(7).shuffle(items)
    total = len(items)
    n_real = sum(1 for _, l, _ in items if l == 0)
    print(f"\n  TOTAL: {total}  (real={n_real}  IA={total - n_real})\n")

    # ── carga modelos ────────────────────────────────────────────────────────
    print("Cargando modelos del ensemble...")
    from app.models.deepfake_detector import (
        _model_a, _model_b, _model_c, _model_d, _model_e, _model_f,
    )
    for m in (_model_a, _model_b, _model_c, _model_d, _model_e, _model_f):
        m.load()

    from app.models.content_type_gate import ContentTypeGate
    gate = ContentTypeGate.get_instance()
    gate.load()
    print("Modelos listos.\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    written = 0

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()

        for i in range(0, total, args.batch):
            chunk = items[i:i + args.batch]
            imgs, meta = [], []
            for src, label, path in chunk:
                try:
                    imgs.append(Image.open(path).convert("RGB"))
                    meta.append((src, label, path))
                except Exception:
                    continue
            if not imgs:
                continue

            ra = _model_a.predict_batch(imgs)
            rb = _model_b.predict_batch(imgs)
            rc = _model_c.predict_batch(imgs)
            rd = _model_d.predict_batch(imgs)
            re_ = _model_e.predict_batch(imgs)
            rf = _model_f.predict_batch(imgs)
            art = gate.artwork_probability_batch(imgs)

            def g(res, j):
                return round(res[j]["fake_probability"], 6) if res[j] else ""

            for j, (src, label, path) in enumerate(meta):
                w.writerow({
                    "source": src, "label": label, "path": str(path),
                    "face_deepfake_vit": g(ra, j),
                    "sdxl_detector":     g(rb, j),
                    "efficientnet_ffpp": g(rc, j),
                    "ai_art_detector":   g(rd, j),
                    "siglip_deepfake":   g(re_, j),
                    "ai_human_detector": g(rf, j),
                    "artwork_probability": round(art[j], 6),
                })
                written += 1

            for im in imgs:
                im.close()

            if (i // args.batch) % 20 == 0 or i + args.batch >= total:
                el = time.time() - t0
                done = min(i + args.batch, total)
                eta = el / max(done, 1) * (total - done)
                print(f"  [{done}/{total}] {el/60:.1f}min  ETA {eta/60:.1f}min", flush=True)
                fh.flush()

    print(f"\nListo: {written} filas -> {OUT}")
    print(f"Tiempo total: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
