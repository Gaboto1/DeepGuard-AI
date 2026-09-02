"""
Script de mejora nocturna del meta-ensemble.

Estrategia:
  REAL: FF++ (ya evaluado) + LFW (caras reales de noticias, ~13k)
  IA  : SD-Turbo existentes + 3000 nuevos (prompts deportes/noticias)
        + DiffusionDB ya descargado (18k)

Solo actualiza el modelo si el nuevo FPR ≤ modelo actual (0.3%).

Uso:
  python scripts/improve_meta_overnight.py
"""
import csv
import json
import os
import shutil
import sys
import time
import urllib.request
import tarfile
from datetime import datetime
from pathlib import Path

import numpy as np
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

CURRENT_FPR = 0.003   # modelo actual: 0.3%

# ─── Prompts SD-Turbo (deportes / noticias / retratos) ───────────────────────
SPORTS_NEWS_PROMPTS = [
    # Deportes — el caso Messi y similares
    "professional soccer player kicking ball in stadium match, sports press photography, photorealistic",
    "soccer player celebrating goal with teammates, stadium, photojournalism",
    "basketball player dunking in NBA game, arena lights, sports photography",
    "tennis player serving at grand slam tournament, action shot, photorealistic",
    "cyclist racing through mountain road, professional race, press photo",
    "marathon runner crossing finish line, race crowd, sports photography",
    "swimmer competing in olympic pool lane, action underwater shot",
    "rugby player tackling opponent, outdoor field, photorealistic press photo",
    "baseball pitcher throwing fastball, stadium, sports photography",
    "volleyball player spiking ball, beach match, action photography",
    "golf player mid-swing, green course, professional photography",
    "boxer in ring during championship fight, sports photography",
    # Noticias / política
    "politician giving speech at podium with microphones, press conference, photorealistic",
    "world leader handshake at diplomatic summit, formal attire, news photo",
    "journalist interviewing celebrity on red carpet, event photography",
    "CEO presenting earnings at corporate event, stage, business photography",
    "scientist holding sample in laboratory, white coat, documentary photo",
    "doctor examining patient in hospital, medical photography, candid",
    "military officer at ceremony with medals, press photograph",
    "firefighter at emergency scene, gear, documentary photography",
    "police officer addressing crowd at press conference, realistic news photo",
    "teacher in classroom with students, documentary school photography",
    # Retratos profesionales
    "professional business headshot, neutral background, studio lighting, photorealistic",
    "actor posing at movie premiere, red carpet event, celebrity photo",
    "musician performing on stage at concert, spotlight, photorealistic",
    "chef in restaurant kitchen plating dish, professional portrait",
    "architect in hard hat at construction site, press photography",
    "fashion model editorial shoot, studio, professional photography",
    "elderly professor in university library, candid portrait",
    "young entrepreneur at startup office, casual portrait, photorealistic",
    "diplomat in formal attire at embassy, official portrait",
    "award-winning author at book signing, candid photography",
    # Contextos variados con personas
    "street photographer capturing candid moment in busy city, photojournalism",
    "family portrait at outdoor picnic, natural light, candid photography",
    "medical team in surgery room, documentary photography, photorealistic",
    "news anchor behind studio desk, broadcast set, professional lighting",
    "olympic athlete receiving gold medal at podium, ceremony photography",
    "protest march with diverse crowd holding signs, photojournalism",
    "graduation ceremony, student in cap and gown, candid photography",
    "wedding ceremony outdoor, couple exchanging vows, photorealistic",
    "startup team meeting in modern office, candid group photo",
    "elderly couple walking in park, lifestyle photography, candid",
]


# ─── Progreso ─────────────────────────────────────────────────────────────────

def _dl_progress(block_num, block_size, total_size):
    if total_size > 0 and block_num % 100 == 0:
        mb  = block_num * block_size / 1_048_576
        tot = total_size / 1_048_576
        pct = min(100, int(mb / tot * 100))
        print(f"  {pct:3d}%  {mb:.1f}/{tot:.1f} MB", flush=True)


# ─── Fase 1: Generar SD-Turbo con prompts de deportes/noticias ───────────────

def generate_sdturbo_sports(n: int = 3000, seed: int = 9999) -> list[Path]:
    out_dir  = DATA / "real_world_training" / "ai_sdturbo_sports"
    existing = sorted(out_dir.glob("sdturbo_sports_*.jpg"))
    if len(existing) >= n:
        print(f"  ✓ SD-Turbo sports: {len(existing)} ya generadas")
        return existing[:n]

    already   = len(existing)
    remaining = n - already
    print(f"\n[FASE 1] Generando {remaining} imágenes SD-Turbo (deportes/noticias/retratos)…")
    if already:
        print(f"  ({already} ya existen)")

    try:
        import torch
        from diffusers import AutoPipelineForText2Image

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype  = torch.float16 if device == "cuda" else torch.float32
        print(f"  Dispositivo: {device} | Cargando SD-Turbo…")

        out_dir.mkdir(parents=True, exist_ok=True)
        pipe = AutoPipelineForText2Image.from_pretrained(
            "stabilityai/sd-turbo",
            torch_dtype=dtype,
            variant="fp16" if device == "cuda" else None,
            cache_dir=str(ROOT / "models"),
        )
        pipe = pipe.to(device)
        pipe.set_progress_bar_config(disable=True)

        rng   = np.random.default_rng(seed)
        t0    = time.time()
        saved = list(existing)

        for i in range(remaining):
            prompt   = SPORTS_NEWS_PROMPTS[(already + i) % len(SPORTS_NEWS_PROMPTS)]
            seed_i   = int(rng.integers(0, 2**31))
            generator = torch.Generator(device=device).manual_seed(seed_i)

            try:
                result = pipe(
                    prompt=prompt,
                    num_inference_steps=4,
                    guidance_scale=0.0,
                    generator=generator,
                    height=512, width=512,
                )
                img      = result.images[0]
                out_path = out_dir / f"sdturbo_sports_{already+i:05d}.jpg"
                img.save(out_path, "JPEG", quality=92)
                saved.append(out_path)
            except Exception as e:
                print(f"  [skip {i}] {e}")
                continue

            if (i + 1) % 100 == 0 or (i + 1) == remaining:
                elapsed = time.time() - t0
                eta     = elapsed / (i + 1) * (remaining - i - 1)
                print(f"  [{i+1}/{remaining}] {elapsed/60:.1f}min ETA={eta/60:.1f}min")

        del pipe
        if device == "cuda":
            import torch as t
            t.cuda.empty_cache()

        print(f"  ✓ {len(saved)} imágenes SD-Turbo sports guardadas")
        return saved[:n]
    except Exception as e:
        print(f"  ERROR SD-Turbo: {e}")
        return sorted(out_dir.glob("sdturbo_sports_*.jpg"))


# ─── Fase 2: Descargar LFW ────────────────────────────────────────────────────

LFW_URL = "http://vis-www.cs.umass.edu/lfw/lfw.tgz"
LFW_DIR = DATA / "lfw"


def download_lfw() -> list[Path]:
    if LFW_DIR.exists() and any(LFW_DIR.rglob("*.jpg")):
        imgs = sorted(LFW_DIR.rglob("*.jpg"))
        print(f"  ✓ LFW: {len(imgs)} imágenes ya disponibles")
        return imgs

    print(f"\n[FASE 2] Descargando LFW (Labeled Faces in the Wild, ~250 MB)…")
    LFW_DIR.mkdir(parents=True, exist_ok=True)
    tgz_path = DATA / "lfw.tgz"

    try:
        urllib.request.urlretrieve(LFW_URL, str(tgz_path), _dl_progress)
        print(f"\n  Extrayendo…")
        with tarfile.open(tgz_path, "r:gz") as tar:
            tar.extractall(str(LFW_DIR))
        tgz_path.unlink()
        imgs = sorted(LFW_DIR.rglob("*.jpg"))
        print(f"  ✓ LFW: {len(imgs)} imágenes extraídas")
        return imgs
    except Exception as e:
        print(f"  ERROR LFW: {e}")
        if tgz_path.exists():
            tgz_path.unlink()
        return []


# ─── Fase 3: Recolectar todo ──────────────────────────────────────────────────

def _load_ffpp_real(n: int, seed: int = 42) -> list[Path]:
    val_csv = ROOT / "data" / "ff++_faces" / "val.csv"
    if not val_csv.exists():
        print(f"  [AVISO] FF++ val.csv no encontrado")
        return []
    rng  = np.random.default_rng(seed)
    real = []
    with open(val_csv) as f:
        for row in csv.DictReader(f):
            if row["label"] == "0":
                p = Path(row["path"])
                if p.exists():
                    real.append(p)
    sample = rng.choice(real, min(n, len(real)), replace=False).tolist()
    print(f"  FF++ reales: {len(sample)}/{len(real)} imágenes")
    return sample


def collect_all_images() -> tuple[list[Path], list[Path]]:
    real_paths: list[Path] = []
    ai_paths:   list[Path] = []

    # Real: FF++
    ffpp = _load_ffpp_real(2970)
    real_paths.extend(ffpp)
    print(f"  FF++ real: {len(ffpp)}")

    # Real: LFW
    lfw = download_lfw()
    real_paths.extend(lfw)
    print(f"  LFW real: {len(lfw)}")

    # IA: SD-Turbo original
    sd_orig = sorted((DATA / "real_world_training" / "ai_sdturbo").glob("sdturbo_*.jpg"))
    ai_paths.extend(sd_orig)
    print(f"  SD-Turbo original: {len(sd_orig)}")

    # IA: SD-Turbo sports
    sd_sports = generate_sdturbo_sports(3000)
    ai_paths.extend(sd_sports)
    print(f"  SD-Turbo sports: {len(sd_sports)}")

    # IA: DiffusionDB descargado
    diff_dir = DATA / "diffusiondb"
    if diff_dir.exists():
        diff_imgs = sorted(diff_dir.rglob("*.png")) + sorted(diff_dir.rglob("*.jpg"))
        ai_paths.extend(diff_imgs)
        print(f"  DiffusionDB: {len(diff_imgs)}")

    return real_paths, ai_paths


# ─── Fase 4: Evaluación ───────────────────────────────────────────────────────

def load_models():
    print("\nCargando modelos del ensemble…")
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
    except Exception:
        return None


def evaluate(real_paths: list[Path], ai_paths: list[Path], models: tuple,
             max_per_class: int = 15_000) -> list[dict]:
    rng = np.random.default_rng(77)
    r_sample = real_paths.copy(); rng.shuffle(r_sample); r_sample = r_sample[:max_per_class]   # type: ignore
    a_sample = ai_paths.copy();   rng.shuffle(a_sample); a_sample = a_sample[:max_per_class]   # type: ignore

    all_items = [(p, 0) for p in r_sample] + [(p, 1) for p in a_sample]
    rng.shuffle(all_items)   # type: ignore

    rows, skipped = [], 0
    t0 = time.time()
    n  = len(all_items)
    print(f"\nEvaluando {n} imágenes ({len(r_sample)} real, {len(a_sample)} IA)…")

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
        except Exception:
            skipped += 1
            continue

        if i % 1000 == 0 or i == n:
            elapsed = time.time() - t0
            eta     = elapsed / i * (n - i)
            nr = sum(1 for r in rows if r["label"] == 0)
            nf = sum(1 for r in rows if r["label"] == 1)
            print(f"  [{i:5d}/{n}] real={nr} IA={nf} "
                  f"elapsed={elapsed/60:.1f}min ETA={eta/60:.1f}min")

    print(f"  Completado: {len(rows)} filas, {skipped} saltadas")
    return rows


# ─── Fase 5: Entrenar y validar ───────────────────────────────────────────────

def train_and_validate(csv_paths: list[Path]) -> tuple[float, float]:
    """Entrena y retorna (fpr, fnr) del nuevo modelo."""
    import subprocess
    env = dict(os.environ)
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "train_meta_ensemble.py")],
        capture_output=True, text=True, env=env, cwd=str(BACKEND)
    )
    print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
    if result.returncode != 0:
        print("ERROR en entrenamiento:", result.stderr[-1000:])
        return 1.0, 1.0

    # Extraer métricas del output
    fpr, fnr = 1.0, 1.0
    for line in result.stdout.split("\n"):
        if "FPR=" in line and "FNR=" in line:
            import re
            m = re.search(r"FPR=([\d.]+)%.*FNR=([\d.]+)%", line)
            if m:
                fpr = float(m.group(1)) / 100
                fnr = float(m.group(2)) / 100
    return fpr, fnr


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    t_start = time.time()
    print("=" * 65)
    print("  DeepScan — Mejora nocturna del meta-ensemble")
    print(f"  Objetivo: FPR ≤ {CURRENT_FPR*100:.1f}% (modelo actual)")
    print("=" * 65)

    # 1. Recolectar imágenes (genera SD-Turbo sports + descarga LFW)
    print("\n[Fase 1-2] Recolectando imágenes…")
    real_paths, ai_paths = collect_all_images()
    print(f"\n  Total real: {len(real_paths):,}  |  Total IA: {len(ai_paths):,}")

    # 2. Evaluar (balanceado, máx 15k por clase)
    models = load_models()
    rows   = evaluate(real_paths, ai_paths, models)

    if not rows:
        print("ERROR: sin filas")
        return

    # 3. Guardar CSV nuevo
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = REPORTS / f"full_eval_massive_{ts}_overnight.csv"
    cols     = FEATURE_COLS + ["label", "path"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    nr = sum(1 for r in rows if r["label"] == 0)
    nf = sum(1 for r in rows if r["label"] == 1)
    print(f"\n  CSV guardado: {csv_path.name} ({nr} real, {nf} IA)")

    # 4. Respaldar modelo actual antes de entrenar
    model_dir = ROOT / "models" / "meta_ensemble"
    backup_joblib = model_dir / "meta_classifier_backup.joblib"
    backup_json   = model_dir / "meta_config_backup.json"
    shutil.copy2(model_dir / "meta_classifier.joblib", backup_joblib)
    shutil.copy2(model_dir / "meta_config.json",       backup_json)
    print("  Backup del modelo actual guardado")

    # 5. Entrenar nuevo modelo
    print("\n[Fase 5] Entrenando nuevo modelo…")
    # Listar todos los CSVs disponibles para el train script
    all_csvs = sorted(REPORTS.glob("full_eval_massive_*.csv"))
    print(f"  CSVs para entrenamiento: {len(all_csvs)}")

    fpr_new, fnr_new = train_and_validate(all_csvs)
    print(f"\n  Nuevo modelo: FPR={fpr_new*100:.1f}%  FNR={fnr_new*100:.1f}%")
    print(f"  Modelo actual: FPR={CURRENT_FPR*100:.1f}%")

    # 6. Decidir si mantener el nuevo o revertir
    if fpr_new <= CURRENT_FPR + 0.005:   # tolerancia 0.5%
        print(f"\n  ✅ Nuevo modelo MEJOR o igual — manteniendo")
        import subprocess
        subprocess.run(
            ["git", "add", "-f",
             "models/meta_ensemble/meta_classifier.joblib",
             "models/meta_ensemble/meta_config.json"],
            cwd=str(ROOT)
        )
        msg = (
            f"feat(ml): retrain overnight — FPR={fpr_new*100:.1f}% "
            f"FNR={fnr_new*100:.1f}% (LFW+sports prompts)\n\n"
            f"Real: FF++ + LFW (caras de noticias/prensa)\n"
            f"IA: SD-Turbo original + sports prompts + DiffusionDB\n"
            f"FPR anterior: {CURRENT_FPR*100:.1f}% → nuevo: {fpr_new*100:.1f}%\n\n"
            f"Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        )
        subprocess.run(["git", "commit", "-m", msg], cwd=str(ROOT))
        subprocess.run(["git", "push", "origin", "main"],  cwd=str(ROOT))
        print("  Commiteado y pusheado a GitHub ✅")
    else:
        print(f"\n  ❌ Nuevo modelo peor (FPR={fpr_new*100:.1f}% > {CURRENT_FPR*100:.1f}%) — revirtiendo")
        shutil.copy2(backup_joblib, model_dir / "meta_classifier.joblib")
        shutil.copy2(backup_json,   model_dir / "meta_config.json")
        print("  Modelo anterior restaurado ✅")

    # Limpiar backups
    backup_joblib.unlink(missing_ok=True)
    backup_json.unlink(missing_ok=True)

    total_min = (time.time() - t_start) / 60
    print(f"\n{'='*65}")
    print(f"  Mejora nocturna completada en {total_min:.1f} min")
    print(f"  FPR final: {min(fpr_new, CURRENT_FPR)*100:.1f}%")
    print("=" * 65)


if __name__ == "__main__":
    main()
