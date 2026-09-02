"""
Genera datos de entrenamiento reales para el meta-ensemble.

Estrategia:
  REAL : FF++ val.csv label=0 (2970 fotos reales de caras, ya en disco)
  IA   : Generación local con SD-Turbo usando GPU (RTX 4070 SUPER)
         → SD-Turbo descarga ~3.1 GB la primera vez, luego queda cacheado
         → ~0.5-1 seg/imagen → 1000 imágenes en ~15-20 min

Ventaja vs descargar dataset externo:
  - Ground-truth 100% garantizado (generamos nosotros)
  - No depende de APIs externas ni formatos de dataset
  - Prompts variados → buena diversidad de estilos

Salida:
  data/real_world_training/ai_sdturbo/  → imágenes SD-Turbo generadas
  reports/full_eval_massive_{ts}.csv    → listo para train_meta_ensemble.py

Uso:
  python scripts/download_real_world_data.py
  python scripts/download_real_world_data.py --n_real 1000 --n_ai 1000
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

ROOT     = Path(__file__).parent.parent
BACKEND  = ROOT / "backend"
OUT_DIR  = ROOT / "data" / "real_world_training"
REPORTS  = ROOT / "reports"
FFPP_VAL = ROOT / "data" / "ff++_faces" / "val.csv"

sys.path.insert(0, str(BACKEND))
os.environ["TRANSFORMERS_CACHE"]              = str(ROOT / "models")
os.environ["HF_HOME"]                         = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(BACKEND)

FEATURE_COLS = [
    "face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
    "ai_art_detector", "siglip_deepfake",
]

# Prompts variados para cubrir los mismos tipos de imágenes que ve el sistema en producción
PROMPTS = [
    # Retratos / personas
    "a professional portrait photo of a person smiling, studio lighting, photorealistic",
    "a candid street photo of a person walking in a city, natural light",
    "a sports athlete running in a stadium, action shot, photorealistic",
    "a business professional in an office, portrait, professional photo",
    "a young woman at the beach, sunset, photorealistic",
    "a man in casual clothes, outdoor photo, natural light",
    "a family photo at a park, candid shot, photorealistic",
    "a politician giving a speech, press photo, photorealistic",
    # Escenas / paisajes
    "a beautiful mountain landscape, golden hour, professional photography",
    "a modern city skyline at night, long exposure photography",
    "a serene beach with turquoise water, travel photography",
    "a lush green forest path, nature photography, photorealistic",
    "an urban street scene with people, documentary photography",
    "a cozy interior of a coffee shop, lifestyle photography",
    "a dramatic sunset over the ocean, landscape photography",
    "a snowy mountain peak, adventure photography, photorealistic",
    # Arte / estilo digital
    "digital painting of a fantasy landscape, highly detailed, concept art",
    "an oil painting portrait in renaissance style, old master technique",
    "a watercolor illustration of a forest scene, soft colors",
    "a cyberpunk city scene, neon lights, digital art, concept art",
    "a fantasy character illustration, dungeons and dragons style",
    "an impressionist painting of a field of flowers, vibrant colors",
    "a surrealist digital artwork, dreamlike atmosphere, highly detailed",
    "a comic book style illustration, bold colors and outlines",
]


# ─── Modelos base ────────────────────────────────────────────────────────────

def load_models():
    print("Cargando modelos del ensemble...")
    from app.models.deepfake_detector import _model_a, _model_b, _model_c, _model_d, _model_e
    for tag, m in [("A-ViT", _model_a), ("B-SDXL", _model_b),
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
        ra, rb, rc, rd, re = (m.predict(img) for m in [ma, mb, mc, md, me])
        return {
            "face_deepfake_vit": ra["fake_probability"] if ra else None,
            "sdxl_detector":     rb["fake_probability"] if rb else None,
            "efficientnet_ffpp": rc["fake_probability"] if rc else None,
            "ai_art_detector":   rd["fake_probability"] if rd else None,
            "siglip_deepfake":   re["fake_probability"] if re else None,
        }
    except Exception as e:
        print(f"    [infer ERR] {e}")
        return None


# ─── Fuente REAL: FF++ val.csv label=0 ───────────────────────────────────────

def load_ffpp_real(n: int, seed: int = 42) -> list[Path]:
    if not FFPP_VAL.exists():
        print(f"  [AVISO] FF++ val.csv no encontrado: {FFPP_VAL}")
        return []
    rng  = np.random.default_rng(seed)
    real = []
    with open(FFPP_VAL) as f:
        for row in csv.DictReader(f):
            if row["label"] == "0":
                p = Path(row["path"])
                if p.exists():
                    real.append(p)
    sample = rng.choice(real, min(n, len(real)), replace=False).tolist()
    print(f"  FF++ reales: {len(sample)}/{len(real)} imágenes seleccionadas")
    return sample


# ─── Fuente IA: SD-Turbo local (GPU) ─────────────────────────────────────────

def generate_sdturbo(n: int, out_dir: Path, seed: int = 2024) -> list[Path]:
    """
    Genera n imágenes con SD-Turbo usando la GPU local.
    Primera ejecución descarga el modelo (~3.1 GB) a models/sd-turbo/
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("sdturbo_*.jpg"))
    if len(existing) >= n:
        print(f"  SD-Turbo: {len(existing)} imágenes ya generadas — reutilizando")
        return existing[:n]

    already = len(existing)
    remaining = n - already
    print(f"  Generando {remaining} imágenes con SD-Turbo (GPU)...")
    if already:
        print(f"  ({already} ya existen, generando {remaining} adicionales)")

    try:
        import torch
        from diffusers import AutoPipelineForText2Image

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype  = torch.float16 if device == "cuda" else torch.float32
        print(f"  Dispositivo: {device} | dtype: {dtype}")
        print(f"  Descargando SD-Turbo (~3.1 GB la primera vez)...")

        pipe = AutoPipelineForText2Image.from_pretrained(
            "stabilityai/sd-turbo",
            torch_dtype=dtype,
            variant="fp16" if device == "cuda" else None,
            cache_dir=str(ROOT / "models"),
        )
        pipe = pipe.to(device)
        pipe.set_progress_bar_config(disable=True)

        rng    = np.random.default_rng(seed)
        t0     = time.time()
        saved  = list(existing)

        for i in range(remaining):
            prompt_idx = (already + i) % len(PROMPTS)
            prompt     = PROMPTS[prompt_idx]
            seed_i     = int(rng.integers(0, 2**31))

            try:
                generator = torch.Generator(device=device).manual_seed(seed_i)
                result    = pipe(
                    prompt=prompt,
                    num_inference_steps=4,   # SD-Turbo: 1-4 pasos
                    guidance_scale=0.0,
                    generator=generator,
                    height=512,
                    width=512,
                )
                img      = result.images[0]
                out_path = out_dir / f"sdturbo_{already + i:05d}.jpg"
                img.save(out_path, "JPEG", quality=92)
                saved.append(out_path)
            except Exception as e:
                print(f"  [skip gen {i}] {e}")
                continue

            if (i + 1) % 50 == 0 or (i + 1) == remaining:
                elapsed = time.time() - t0
                eta     = elapsed / (i + 1) * (remaining - i - 1)
                print(f"  [{i+1}/{remaining}] elapsed={elapsed:.0f}s ETA={eta:.0f}s  "
                      f"({elapsed/(i+1):.1f}s/img)")

        # Liberar VRAM
        del pipe
        if device == "cuda":
            torch.cuda.empty_cache()

        print(f"  SD-Turbo: {len(saved)} imágenes guardadas en {out_dir}")
        return saved[:n]

    except Exception as e:
        print(f"  ERROR generando con SD-Turbo: {e}")
        existing = sorted(out_dir.glob("sdturbo_*.jpg"))
        if existing:
            print(f"  Usando {len(existing)} imágenes generadas hasta ahora")
            return existing[:n]
        return []


# ─── Evaluación ───────────────────────────────────────────────────────────────

def evaluate_images(
    real_paths: list[Path],
    ai_paths:   list[Path],
    models:     tuple,
) -> list[dict]:
    all_items = [(p, 0) for p in real_paths] + [(p, 1) for p in ai_paths]
    np.random.default_rng(99).shuffle(all_items)  # type: ignore

    rows = []
    t0   = time.time()
    n    = len(all_items)
    print(f"\nEvaluando {n} imágenes ({len(real_paths)} real + {len(ai_paths)} IA)...")

    for i, (path, label) in enumerate(all_items, 1):
        try:
            img    = Image.open(path).convert("RGB")
            scores = infer(img, models)
            if scores is None:
                continue
            scores["label"] = label
            scores["path"]  = str(path)
            rows.append(scores)
        except Exception as e:
            print(f"  [skip] {Path(path).name}: {e}")
            continue

        if i % 100 == 0 or i == n:
            elapsed = time.time() - t0
            eta     = elapsed / i * (n - i)
            nr = sum(1 for r in rows if r["label"] == 0)
            nf = sum(1 for r in rows if r["label"] == 1)
            print(f"  [{i:4d}/{n}] real={nr} IA={nf} elapsed={elapsed:.0f}s ETA={eta:.0f}s")

    return rows


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(n_real: int = 1000, n_ai: int = 1000) -> None:
    print("=" * 65)
    print("  Generando datos reales para meta-ensemble")
    print("  REAL: FF++ val faces | IA: SD-Turbo (GPU local)")
    print("=" * 65)
    REPORTS.mkdir(parents=True, exist_ok=True)

    # 1. Imágenes reales de FF++
    print("\n[1/3] Cargando imágenes reales (FF++)...")
    real_paths = load_ffpp_real(n_real)
    if not real_paths:
        print("ERROR: No se encontraron imágenes reales de FF++")
        sys.exit(1)

    # 2. Generar imágenes IA con SD-Turbo
    ai_dir = OUT_DIR / "ai_sdturbo"
    print(f"\n[2/3] Generando imágenes IA con SD-Turbo...")
    ai_paths = generate_sdturbo(n_ai, ai_dir)
    if not ai_paths:
        print("ERROR: No se generaron imágenes IA")
        sys.exit(1)

    # 3. Evaluar con los 5 modelos del ensemble
    print(f"\n[3/3] Cargando modelos y evaluando...")
    models = load_models()
    rows   = evaluate_images(real_paths[:n_real], ai_paths[:n_ai], models)

    if not rows:
        print("ERROR: No se generaron filas")
        sys.exit(1)

    # Guardar CSV
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = REPORTS / f"full_eval_massive_{ts}.csv"
    cols     = FEATURE_COLS + ["label", "path"]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    nr = sum(1 for r in rows if r["label"] == 0)
    nf = sum(1 for r in rows if r["label"] == 1)
    print(f"\n{'='*65}")
    print(f"  CSV guardado: {out_path}")
    print(f"  {len(rows)} filas ({nr} real, {nf} IA)")
    print(f"\n  Siguiente paso:")
    print(f"  python scripts/train_meta_ensemble.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_real", type=int, default=1000, help="Fotos reales de FF++ (default: 1000)")
    parser.add_argument("--n_ai",   type=int, default=1000, help="Imágenes a generar con SD-Turbo (default: 1000)")
    args = parser.parse_args()
    main(args.n_real, args.n_ai)
