"""Evalúa las 3000 imágenes SD-Turbo de deportes/noticias (etiqueta=1)."""
import csv, os, sys, time
from datetime import datetime
from pathlib import Path
from PIL import Image

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "models"))
os.environ.setdefault("HF_HOME",            str(ROOT / "models"))
os.chdir(str(BACKEND))

COLS = ["face_deepfake_vit","sdxl_detector","efficientnet_ffpp",
        "ai_art_detector","siglip_deepfake","label","path"]

sports_dir = ROOT / "data" / "real_world_training" / "ai_sdturbo_sports"
imgs = sorted(sports_dir.glob("sdturbo_sports_*.jpg"))
print(f"Imágenes sports: {len(imgs)}")

from app.models.deepfake_detector import _model_a, _model_b, _model_c, _model_d, _model_e
for tag, m in [("A",_model_a),("B",_model_b),("C",_model_c),("D",_model_d),("E",_model_e)]:
    m.load(); print(f"  [{tag}] {'OK' if m._loaded else 'FAIL'}")

rows, t0 = [], time.time()
for i, path in enumerate(imgs, 1):
    try:
        img = Image.open(path).convert("RGB")
        ra,rb,rc,rd,re = (_model_a.predict(img),_model_b.predict(img),
                          _model_c.predict(img),_model_d.predict(img),_model_e.predict(img))
        rows.append({
            "face_deepfake_vit": ra["fake_probability"] if ra else None,
            "sdxl_detector":     rb["fake_probability"] if rb else None,
            "efficientnet_ffpp": rc["fake_probability"] if rc else None,
            "ai_art_detector":   rd["fake_probability"] if rd else None,
            "siglip_deepfake":   re["fake_probability"] if re else None,
            "label": 1, "path": str(path),
        })
    except Exception as e:
        print(f"  [skip] {path.name}: {e}")
    if i % 300 == 0 or i == len(imgs):
        el = time.time()-t0; eta = el/i*(len(imgs)-i)
        print(f"  [{i}/{len(imgs)}] {el/60:.1f}min ETA={eta/60:.1f}min")

ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
out = ROOT / "reports" / f"full_eval_massive_{ts}_sports_ai.csv"
with open(out, "w", newline="", encoding="utf-8") as f:
    csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore").writeheader()
    csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore").writerows(rows)
print(f"\nCSV: {out.name} | {len(rows)} filas IA (sports)")
