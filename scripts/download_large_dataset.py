"""
Descarga conjuntos grandes de imágenes reales y generadas por IA para mejorar
el meta-ensemble. Presupuesto objetivo: 30 GB en data/.

REALES (etiqueta=0):
  - COCO 2017 val  :   5 000 imágenes diversas  (~  788 MB, siempre)
  - COCO 2017 train: 118 000 imágenes diversas  (~ 18.0 GB, --coco_train)

IA (etiqueta=1):
  - DiffusionDB 2M : N × 1 000 imgs SD1.x      (~ 30 MB/parte, --n_diffusiondb N)
  - SD-Turbo local : data/real_world_training/ai_sdturbo/ (ya generadas)

Uso rápido (solo COCO val + 50 partes DiffusionDB ≈ 2.3 GB):
  python scripts/download_large_dataset.py

Uso completo (COCO train + 100 partes DiffusionDB ≈ 21 GB):
  python scripts/download_large_dataset.py --coco_train --n_diffusiondb 100
"""
import argparse
import csv
import io
import os
import sys
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
from PIL import Image

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
DATA    = ROOT / "data"
REPORTS = ROOT / "reports"

sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TRANSFORMERS_CACHE",              str(ROOT / "models"))
os.environ.setdefault("HF_HOME",                         str(ROOT / "models"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.chdir(BACKEND)

FEATURE_COLS = [
    "face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
    "ai_art_detector", "siglip_deepfake",
]

# ─── Progreso de descarga ─────────────────────────────────────────────────────

def _dl_progress(block_num: int, block_size: int, total_size: int) -> None:
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb  = downloaded / 1_048_576
        tot = total_size  / 1_048_576
        print(f"\r  {pct:3d}%  {mb:.1f}/{tot:.1f} MB", end="", flush=True)


def download_file(url: str, dest: Path, desc: str = "") -> Path:
    """Descarga url → dest con barra de progreso. Si ya existe, retorna sin descargar."""
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"  ✓ {desc or dest.name} ya existe ({dest.stat().st_size/1_048_576:.1f} MB)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n  Descargando {desc or dest.name}…")
    try:
        urllib.request.urlretrieve(url, str(dest), _dl_progress)
        print()
    except Exception as e:
        print(f"\n  ERROR descargando {url}: {e}")
        if dest.exists():
            dest.unlink()
        raise
    return dest


# ─── COCO ─────────────────────────────────────────────────────────────────────

COCO_VAL_URL   = "http://images.cocodataset.org/zips/val2017.zip"
COCO_TRAIN_URL = "http://images.cocodataset.org/zips/train2017.zip"


def download_coco(split: str = "val") -> list[Path]:
    """Descarga COCO 2017 val (788 MB) o train (18 GB) y extrae imágenes."""
    url      = COCO_VAL_URL if split == "val" else COCO_TRAIN_URL
    zip_path = DATA / "coco" / f"{split}2017.zip"
    img_dir  = DATA / "coco" / f"{split}2017"

    if img_dir.exists() and any(img_dir.glob("*.jpg")):
        imgs = sorted(img_dir.glob("*.jpg"))
        print(f"  ✓ COCO {split}: {len(imgs)} imágenes ya extraídas")
        return imgs

    print(f"\n[COCO 2017 {split}]")
    download_file(url, zip_path, f"COCO {split}2017")

    print(f"  Extrayendo {zip_path.name}…")
    img_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.namelist() if m.endswith(".jpg")]
        for i, m in enumerate(members, 1):
            if i % 10_000 == 0:
                print(f"  [{i}/{len(members)}] extraídas…")
            data = z.read(m)
            (img_dir / Path(m).name).write_bytes(data)
    zip_path.unlink()   # libera espacio
    imgs = sorted(img_dir.glob("*.jpg"))
    print(f"  Extraídas: {len(imgs)} imágenes → {img_dir}")
    return imgs


# ─── DiffusionDB ──────────────────────────────────────────────────────────────

# URL directa a los ZIPs de DiffusionDB 2M en HuggingFace (sin scripts)
DIFFDB_BASE = (
    "https://huggingface.co/datasets/poloclub/diffusiondb"
    "/resolve/main/images/{part}.zip"
)
DIFFDB_DIR  = DATA / "diffusiondb"


def download_diffusiondb_part(part_idx: int) -> list[Path]:
    """Descarga una parte de DiffusionDB (~30 MB, 1000 imágenes) y extrae."""
    part_name = f"part-{part_idx:06d}"
    img_dir   = DIFFDB_DIR / part_name
    if img_dir.exists() and len(list(img_dir.glob("*.png"))) >= 900:
        return sorted(img_dir.glob("*.png"))

    url      = DIFFDB_BASE.format(part=part_name)
    zip_path = DIFFDB_DIR / f"{part_name}.zip"

    try:
        download_file(url, zip_path, f"DiffusionDB {part_name}")
    except Exception as e:
        print(f"  [skip] parte {part_idx} inaccesible: {e}")
        return []

    img_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            for m in z.namelist():
                if m.endswith(".png") or m.endswith(".jpg") or m.endswith(".webp"):
                    data = z.read(m)
                    (img_dir / Path(m).name).write_bytes(data)
        zip_path.unlink()
    except Exception as e:
        print(f"  [skip] error extrayendo {part_name}: {e}")
        if zip_path.exists():
            zip_path.unlink()
        return []

    imgs = sorted(img_dir.glob("*.png")) + sorted(img_dir.glob("*.jpg"))
    print(f"  {part_name}: {len(imgs)} imágenes extraídas")
    return imgs


# ─── SD-Turbo existentes ──────────────────────────────────────────────────────

def load_existing_sdturbo() -> list[Path]:
    sdturbo_dir = DATA / "real_world_training" / "ai_sdturbo"
    imgs = sorted(sdturbo_dir.glob("sdturbo_*.jpg"))
    if imgs:
        print(f"  SD-Turbo existentes: {len(imgs)} imágenes")
    return imgs


# ─── Modelos ──────────────────────────────────────────────────────────────────

def load_models():
    print("Cargando modelos del ensemble…")
    from app.models.deepfake_detector import _model_a, _model_b, _model_c, _model_d, _model_e
    for tag, m in [("A-ViT",  _model_a), ("B-SDXL", _model_b),
                   ("C-CLIP", _model_c), ("D-AIArt", _model_d), ("E-SigLIP", _model_e)]:
        try:
            m.load()
            print(f"  [{tag}] {'OK' if m._loaded else 'FAIL'}")
        except Exception as e:
            print(f"  [{tag}] ERR: {e}")
    return _model_a, _model_b, _model_c, _model_d, _model_e


def infer(img: Image.Image, models: tuple) -> dict | None:
    ma, mb, mc, md, me = models
    try:
        ra, rb, rc, rd, re = (m.predict(img) for m in (ma, mb, mc, md, me))
        return {
            "face_deepfake_vit": ra["fake_probability"] if ra else None,
            "sdxl_detector":     rb["fake_probability"] if rb else None,
            "efficientnet_ffpp": rc["fake_probability"] if rc else None,
            "ai_art_detector":   rd["fake_probability"] if rd else None,
            "siglip_deepfake":   re["fake_probability"] if re else None,
        }
    except Exception as e:
        print(f"\n    [infer ERR] {e}")
        return None


# ─── Evaluación ───────────────────────────────────────────────────────────────

def evaluate_batch(
    real_paths: list[Path],
    ai_paths:   list[Path],
    models:     tuple,
    batch_label: str = "",
) -> list[dict]:
    all_items = [(p, 0) for p in real_paths] + [(p, 1) for p in ai_paths]
    rng = np.random.default_rng(42)
    rng.shuffle(all_items)   # type: ignore

    rows, skipped = [], 0
    t0 = time.time()
    n  = len(all_items)
    print(f"\nEvaluando {n} imágenes ({len(real_paths)} real, {len(ai_paths)} IA)…")

    for i, (path, label) in enumerate(all_items, 1):
        try:
            img    = Image.open(path).convert("RGB")
            scores = infer(img, models)
            if scores is None:
                skipped += 1
                continue
            scores["label"] = label
            scores["path"]  = str(path)
            rows.append(scores)
        except Exception as e:
            skipped += 1
            if skipped <= 5:
                print(f"\n  [skip] {Path(path).name}: {e}")
            continue

        if i % 500 == 0 or i == n:
            elapsed = time.time() - t0
            eta     = elapsed / i * (n - i)
            nr = sum(1 for r in rows if r["label"] == 0)
            nf = sum(1 for r in rows if r["label"] == 1)
            suffix = f" — {batch_label}" if batch_label else ""
            print(
                f"  [{i:5d}/{n}] real={nr} IA={nf} "
                f"elapsed={elapsed/60:.1f}min ETA={eta/60:.1f}min{suffix}"
            )

    print(f"  Completado: {len(rows)} filas válidas, {skipped} saltadas")
    return rows


def save_csv(rows: list[dict], suffix: str = "") -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag      = f"_{suffix}" if suffix else ""
    out_path = REPORTS / f"full_eval_massive_{ts}{tag}.csv"
    cols     = FEATURE_COLS + ["label", "path"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    nr = sum(1 for r in rows if r["label"] == 0)
    nf = sum(1 for r in rows if r["label"] == 1)
    print(f"\n  CSV guardado: {out_path}")
    print(f"  {len(rows)} filas ({nr} real, {nf} IA)")
    return out_path


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(
    coco_train:      bool = False,
    n_diffusiondb:   int  = 50,
    max_coco_real:   int  = 0,    # 0 = sin límite
    skip_eval:       bool = False,
) -> None:
    t_start = time.time()
    print("=" * 65)
    print("  DeepScan — Descarga masiva de datos de entrenamiento")
    print(f"  COCO val ✓ | COCO train {'✓' if coco_train else '✗'}")
    print(f"  DiffusionDB: {n_diffusiondb} partes (~{n_diffusiondb*1000:,} imágenes)")
    print("=" * 65)

    # ── 1. Reales: COCO val ───────────────────────────────────────────────────
    print("\n[1] COCO 2017 val (5 000 imágenes diversas, ~788 MB)…")
    coco_val = download_coco("val")

    # ── 2. Reales: COCO train (opcional) ──────────────────────────────────────
    coco_train_imgs: list[Path] = []
    if coco_train:
        print("\n[2] COCO 2017 train (118 000 imágenes, ~18 GB)…")
        coco_train_imgs = download_coco("train")

    all_real: list[Path] = coco_val + coco_train_imgs
    if max_coco_real and len(all_real) > max_coco_real:
        rng = np.random.default_rng(7)
        idx = rng.choice(len(all_real), max_coco_real, replace=False)
        all_real = [all_real[i] for i in sorted(idx)]
    print(f"\n  Total imágenes REALES: {len(all_real):,}")

    # ── 3. IA: DiffusionDB ────────────────────────────────────────────────────
    print(f"\n[3] DiffusionDB 2M — {n_diffusiondb} partes…")
    all_ai: list[Path] = []
    for part_idx in range(1, n_diffusiondb + 1):
        imgs = download_diffusiondb_part(part_idx)
        all_ai.extend(imgs)
        if part_idx % 10 == 0:
            print(f"  [{part_idx}/{n_diffusiondb}] IA acumuladas: {len(all_ai):,}")

    # ── 4. IA: SD-Turbo existentes (complementario) ───────────────────────────
    sdturbo = load_existing_sdturbo()
    all_ai.extend(sdturbo)
    print(f"  Total imágenes IA: {len(all_ai):,}")

    if skip_eval:
        print("\n--skip_eval: solo descarga completada.")
        return

    if not all_real or not all_ai:
        print("\nERROR: no hay suficientes imágenes para evaluar.")
        sys.exit(1)

    # ── 5. Cargar modelos y evaluar ───────────────────────────────────────────
    print(f"\n[4] Cargando modelos del ensemble…")
    models = load_models()

    # Mezcla equilibrada para el CSV: hasta 15k de cada clase por lote
    # (el train_meta_ensemble.py combina todos los CSVs)
    CHUNK = 15_000
    all_real_shuf = list(all_real)
    all_ai_shuf   = list(all_ai)
    np.random.default_rng(99).shuffle(all_real_shuf)  # type: ignore
    np.random.default_rng(99).shuffle(all_ai_shuf)    # type: ignore

    chunk_idx = 0
    csv_files = []
    for r_start in range(0, len(all_real_shuf), CHUNK):
        a_start = chunk_idx * CHUNK
        real_chunk = all_real_shuf[r_start : r_start + CHUNK]
        ai_chunk   = all_ai_shuf[a_start   : a_start + CHUNK]
        if not real_chunk or not ai_chunk:
            break
        label = f"chunk{chunk_idx+1}"
        rows  = evaluate_batch(real_chunk, ai_chunk, models, batch_label=label)
        if rows:
            csv_files.append(save_csv(rows, suffix=label))
        chunk_idx += 1

    total_time = (time.time() - t_start) / 60
    print(f"\n{'='*65}")
    print(f"  ¡Listo! {len(csv_files)} CSV(s) guardados en reports/")
    print(f"  Tiempo total: {total_time:.1f} min")
    print(f"\n  Siguiente paso:")
    print(f"  python scripts/train_meta_ensemble.py")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Descarga masiva para meta-ensemble")
    parser.add_argument(
        "--coco_train", action="store_true",
        help="Descarga COCO train 2017 (~18 GB, 118 000 imágenes reales)"
    )
    parser.add_argument(
        "--n_diffusiondb", type=int, default=50,
        help="Partes de DiffusionDB a descargar (1 parte = ~1000 imgs AI, ~30 MB) [default: 50]"
    )
    parser.add_argument(
        "--max_coco_real", type=int, default=0,
        help="Límite de imágenes COCO a usar (0 = sin límite)"
    )
    parser.add_argument(
        "--skip_eval", action="store_true",
        help="Solo descarga imágenes, no evalúa (útil para descargar primero)"
    )
    args = parser.parse_args()
    main(
        coco_train=args.coco_train,
        n_diffusiondb=args.n_diffusiondb,
        max_coco_real=args.max_coco_real,
        skip_eval=args.skip_eval,
    )
