"""
Genera datos de entrenamiento para el meta-ensemble.

Usa:
  - FF++ val.csv: imágenes reales de face-swap (250 real + 250 fake)
  - Golden set (tests/golden_set): imágenes reales y GenAI reales

Salida: reports/full_eval_massive_{timestamp}.csv
        (formato compatible con train_meta_ensemble.py)

Uso:
  python scripts/generate_meta_training_data.py
  python scripts/generate_meta_training_data.py --n_ff 300
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ["TRANSFORMERS_CACHE"]              = str(ROOT / "models")
os.environ["HF_HOME"]                         = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(BACKEND)


REPORTS = ROOT / "reports"
FFPP_VAL = ROOT / "data" / "ff++_faces" / "val.csv"
GOLDEN   = ROOT / "tests" / "golden_set" / "manifest.json"


def load_models():
    print("Cargando modelos del ensemble (puede tomar 1-3 min)...")
    from app.models.deepfake_detector import _model_a, _model_b, _model_c, _model_d, _model_e
    for name, m in [("A-ViT", _model_a), ("B-SDXL", _model_b),
                    ("C-CLIP", _model_c), ("D-AIArt", _model_d), ("E-SigLIP", _model_e)]:
        try:
            m.load()
            status = "OK" if m._loaded else "FAIL"
        except Exception as e:
            status = f"ERR: {e}"
        print(f"  [{name}] {status}")
    return _model_a, _model_b, _model_c, _model_d, _model_e


def infer(img: Image.Image, models: tuple) -> dict | None:
    ma, mb, mc, md, me = models
    try:
        ra = ma.predict(img)
        rb = mb.predict(img)
        rc = mc.predict(img)
        rd = md.predict(img)
        re = me.predict(img)
        return {
            "face_deepfake_vit": ra["fake_probability"] if ra else None,
            "sdxl_detector":     rb["fake_probability"] if rb else None,
            "efficientnet_ffpp": rc["fake_probability"] if rc else None,
            "ai_art_detector":   rd["fake_probability"] if rd else None,
            "siglip_deepfake":   re["fake_probability"] if re else None,
        }
    except Exception as e:
        print(f"    [infer ERROR] {e}")
        return None


def load_ffpp_sample(n_per_class: int, seed: int = 42) -> list[tuple[Path, int]]:
    """Lee val.csv y samplea n_per_class imágenes por clase."""
    if not FFPP_VAL.exists():
        print(f"  [AVISO] FF++ val.csv no encontrado: {FFPP_VAL}")
        return []

    rng  = np.random.default_rng(seed)
    real_paths, fake_paths = [], []

    with open(FFPP_VAL) as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        p = Path(r["path"])
        lbl = int(r["label"])
        if p.exists():
            (fake_paths if lbl == 1 else real_paths).append(p)

    real_sample = rng.choice(real_paths, min(n_per_class, len(real_paths)), replace=False).tolist()
    fake_sample = rng.choice(fake_paths, min(n_per_class, len(fake_paths)), replace=False).tolist()

    result = [(p, 0) for p in real_sample] + [(p, 1) for p in fake_sample]
    rng.shuffle(result)
    print(f"  FF++: {len(real_sample)} real + {len(fake_sample)} fake = {len(result)} imágenes")
    return result


def load_golden_set() -> list[tuple[Path, int]]:
    """Carga imágenes del golden_set con label binario."""
    import json
    if not GOLDEN.exists():
        print("  [AVISO] Golden set manifest no encontrado")
        return []

    with open(GOLDEN) as f:
        manifest = json.load(f)

    result = []
    for item in manifest:
        p = ROOT / item["path"]
        if not p.exists():
            continue
        # label: 0=real, 1=fake/AI
        expected = item.get("expected_label", item.get("label"))
        if expected is None:
            cat = item.get("category", "")
            expected = 0 if cat == "real" else 1 if cat in ("ai_generated", "ia") else None
        if expected is not None:
            result.append((p, int(expected)))

    print(f"  Golden set: {sum(1 for _,l in result if l==0)} real + {sum(1 for _,l in result if l==1)} fake = {len(result)} imágenes")
    return result


def main(n_ff: int = 250) -> None:
    print("=" * 60)
    print("  Generando datos de entrenamiento para meta-ensemble")
    print("=" * 60)

    REPORTS.mkdir(parents=True, exist_ok=True)

    # Recopilar imágenes
    print("\nCargando conjuntos de imágenes...")
    samples = load_ffpp_sample(n_ff) + load_golden_set()
    print(f"  Total: {len(samples)} imágenes")

    if not samples:
        print("ERROR: Sin imágenes para procesar.")
        sys.exit(1)

    # Cargar modelos
    print()
    models = load_models()

    # Evaluar
    print(f"\nEvaluando {len(samples)} imágenes...")
    rows = []
    t0   = time.time()

    for i, (path, label) in enumerate(samples, 1):
        try:
            img    = Image.open(path).convert("RGB")
            scores = infer(img, models)
            if scores is None:
                continue
            scores["label"] = label
            scores["path"]  = str(path)
            rows.append(scores)

            if i % 50 == 0 or i == len(samples):
                elapsed = time.time() - t0
                eta     = elapsed / i * (len(samples) - i)
                n_real  = sum(1 for r in rows if r["label"] == 0)
                n_fake  = sum(1 for r in rows if r["label"] == 1)
                print(f"  [{i:4d}/{len(samples)}]  real={n_real}  fake={n_fake}  "
                      f"elapsed={elapsed:.0f}s  ETA={eta:.0f}s")
        except Exception as e:
            print(f"  [skip] {path.name}: {e}")

    if not rows:
        print("ERROR: No se generaron filas.")
        sys.exit(1)

    # Guardar CSV
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = REPORTS / f"full_eval_massive_{ts}.csv"
    cols     = ["face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
                "ai_art_detector", "siglip_deepfake", "label", "path"]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    n_real = sum(1 for r in rows if r["label"] == 0)
    n_fake = sum(1 for r in rows if r["label"] == 1)
    total_t = time.time() - t0

    print(f"\nGuardado: {out_path}")
    print(f"  {len(rows)} filas  ({n_real} real, {n_fake} fake)")
    print(f"  Tiempo total: {total_t:.0f}s")
    print(f"\nSiguiente paso:")
    print(f"  python scripts/train_meta_ensemble.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_ff", type=int, default=250,
                        help="Imágenes por clase de FF++ (default: 250)")
    args = parser.parse_args()
    main(args.n_ff)
