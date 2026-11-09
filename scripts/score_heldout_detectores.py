"""
Mide cada detector por separado sobre el conjunto RETENIDO.

Por que hace falta, y por que la Tabla 4 del informe estaba sesgada
------------------------------------------------------------------
La tabla de AUC por detector se calculaba sobre reports/dataset_v2_scores.csv,
y ahi un detector no juega el mismo partido que los otros cinco:

    C  probe CLIP ViT-L/14     se ENTRENA con embeddings de estas mismas
                               fuentes (scripts/extract_clip_embeddings.py
                               usa coco_train, celeba, elsa, midjourney...).
                               Su AUC en ese CSV es DENTRO DE MUESTRA.
    A, B, D, E, F              son modelos preentrenados de terceros que
                               nunca vieron estas imagenes. Su AUC ahi es
                               fuera de muestra.

Comparar 0,9997 (C, dentro de muestra) contra 0,49-0,87 (el resto, fuera de
muestra) y concluir que C es el mejor detector es un artefacto del montaje, no
un resultado. Y sostiene al reves el argumento de la defensa: con C en 0,9997 y
el conjunto completo en 0,9995, parece que el ensemble no aporta nada.

Aqui los seis se miden sobre data/heldout/, que ningun plan de entrenamiento
toca. Es el unico terreno donde los seis AUC son comparables entre si.

Salida: reports/heldout_detectores.json
"""
import json
import os
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

HELDOUT = ROOT / "data" / "heldout"
OUT = ROOT / "reports" / "heldout_detectores.json"
# Las filas individuales, no solo los agregados: sin ellas no se puede
# reevaluar un conjunto de features distinto sin volver a pasar la GPU
# sobre las 2.000 imagenes del retenido.
OUT_FILAS = ROOT / "reports" / "heldout_detectores.csv"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}

DETECTORES = {
    "face_deepfake_vit": "A  Deep-Fake-Detector-v2 (ViT)",
    "sdxl_detector":     "B  sdxl-detector (Swin)",
    "efficientnet_ffpp": "C  probe CLIP ViT-L/14",
    "ai_art_detector":   "D  detector de arte IA",
    "siglip_deepfake":   "E  Deepfake-Detect-Siglip2",
    "ai_human_detector": "F  umm-maybe AI-image-detector",
}


def recoger(base: Path, n: int, seed: int = 13) -> list[Path]:
    import random
    files = sorted(p for p in base.rglob("*") if p.suffix.lower() in EXTS)
    random.Random(seed).shuffle(files)
    return files[:n]


def auc(y, p):
    from sklearn.metrics import roc_auc_score
    y, p = np.asarray(y), np.asarray(p, dtype=float)
    ok = ~np.isnan(p)
    y, p = y[ok], p[ok]
    if len(np.unique(y)) < 2 or len(y) < 20:
        return None
    return round(float(roc_auc_score(y, p)), 4)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500, help="imagenes por fuente")
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args()

    if not HELDOUT.exists():
        print(f"ERROR: falta {HELDOUT}. Ejecuta scripts/download_heldout.py")
        return 1

    items: list[tuple[str, int, Path]] = []
    for clase_dir in sorted(HELDOUT.iterdir()):
        if not clase_dir.is_dir():
            continue
        label = 0 if clase_dir.name == "real" else 1
        for fuente_dir in sorted(clase_dir.iterdir()):
            if not fuente_dir.is_dir():
                continue
            got = recoger(fuente_dir, args.n)
            items.extend((fuente_dir.name, label, p) for p in got)
            print(f"  {fuente_dir.name:12s} label={label}  {len(got):5d}")
    if not items:
        print("ERROR: conjunto retenido vacio")
        return 1
    total = len(items)
    print(f"\n  TOTAL: {total}\n")

    print("Cargando los seis detectores...")
    from app.models.deepfake_detector import (
        _model_a, _model_b, _model_c, _model_d, _model_e, _model_f)
    modelos = [_model_a, _model_b, _model_c, _model_d, _model_e, _model_f]
    for m in modelos:
        m.load()
    faltan = [n for n, m in zip("ABCDEF", modelos)
              if not getattr(m, "_loaded", False)]
    if faltan:
        print(f"ABORTA: detectores {faltan} sin cargar; el AUC seria basura.")
        return 1
    print("Seis detectores listos.\n")

    filas = []
    t0 = time.time()
    for i in range(0, total, args.batch):
        chunk = items[i:i + args.batch]
        imgs, meta = [], []
        for src, label, path in chunk:
            try:
                imgs.append(Image.open(path).convert("RGB"))
                meta.append((src, label))
            except Exception:
                continue
        if not imgs:
            continue
        res = [m.predict_batch(imgs) for m in modelos]

        for j, (src, label) in enumerate(meta):
            fila = {"source": src, "label": label}
            for col, r in zip(DETECTORES, res):
                v = r[j]["fake_probability"] if r[j] else None
                fila[col] = float("nan") if v is None else round(float(v), 6)
            filas.append(fila)
        for im in imgs:
            im.close()

        if (i // args.batch) % 20 == 0 or i + args.batch >= total:
            el = time.time() - t0
            done = min(i + args.batch, total)
            print(f"  [{done}/{total}] {el/60:.1f}min  "
                  f"ETA {el/max(done,1)*(total-done)/60:.1f}min", flush=True)

    y = [f["label"] for f in filas]
    reales = {f["source"] for f in filas if f["label"] == 0}
    ia = {f["source"] for f in filas if f["label"] == 1}

    rep = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "n": len(filas),
        "fuentes_real": sorted(reales),
        "fuentes_ia": sorted(ia),
        "nota": ("AUC de cada detector sobre fuentes ausentes de todo plan de "
                 "entrenamiento. A diferencia de la tabla calculada sobre "
                 "dataset_v2_scores.csv, aqui los seis estan fuera de muestra "
                 "y son comparables entre si."),
        "detectores": {},
    }

    print("\n=== AUC POR DETECTOR — CONJUNTO RETENIDO (fuera de muestra) ===")
    print(f"{'detector':34s} {'AUC':>7s} {'media real':>11s} {'media IA':>9s}")
    for col, etiqueta in DETECTORES.items():
        p = np.array([f[col] for f in filas], dtype=float)
        a = auc(y, p)
        yy = np.array(y)
        mr = float(np.nanmean(p[yy == 0])) if (yy == 0).any() else None
        mi = float(np.nanmean(p[yy == 1])) if (yy == 1).any() else None
        por_fuente = {}
        for src in sorted(reales | ia):
            sub = np.array([f[col] for f in filas if f["source"] == src],
                           dtype=float)
            por_fuente[src] = round(float(np.nanmean(sub)), 4)
        rep["detectores"][col] = {
            "etiqueta": etiqueta, "auc_heldout": a,
            "media_real": round(mr, 4) if mr is not None else None,
            "media_ia": round(mi, 4) if mi is not None else None,
            "media_por_fuente": por_fuente,
        }
        print(f"{etiqueta:34s} {str(a):>7s} "
              f"{(f'{mr:.4f}' if mr is not None else '-'):>11s} "
              f"{(f'{mi:.4f}' if mi is not None else '-'):>9s}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\n-> {OUT}")
    import pandas as pd
    pd.DataFrame(filas).to_csv(OUT_FILAS, index=False)
    print(f"-> {OUT_FILAS}  ({len(filas)} filas)")
    print(f"Tiempo total: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
