"""
Recalcula la columna `efficientnet_ffpp` (detector C) en los conjuntos del
meta-modelo tras reentrenar el probe CLIP.

Necesario porque el meta-modelo se entrena sobre salidas de los detectores: si
el detector C cambia, las puntuaciones guardadas quedan obsoletas y el
meta-modelo aprenderia una relacion que ya no se cumple en inferencia.

Solo recalcula el detector C. Los otros cinco no cambiaron.
"""
import os
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

import io  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

VARIANTES = {"jpeg_q55_1080": (55, 1080), "jpeg_q30_720": (30, 720)}
CSVS = [
    ROOT / "reports" / "dataset_v2_scores.csv",
    ROOT / "reports" / "dataset_v2_aug_scores.csv",
]
BATCH = 32


def abrir(path: Path, variante: str):
    im = Image.open(path).convert("RGB")
    if variante and variante in VARIANTES:
        q, ancho = VARIANTES[variante]
        if im.width > ancho:
            im = im.resize((ancho, max(1, int(im.height * ancho / im.width))),
                           Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        buf.seek(0)
        im = Image.open(buf).convert("RGB")
    return im


def main() -> int:
    from app.models.deepfake_detector import _model_c
    _model_c.load()
    if not getattr(_model_c, "_loaded", False):
        print("ERROR: el detector C no cargo. ¿Se entreno ya el probe?")
        return 1
    print(f"Detector C cargado: {_model_c.model_name}\n")

    for csv_path in CSVS:
        if not csv_path.exists():
            print(f"  omitido (no existe): {csv_path.name}")
            continue
        df = pd.read_csv(csv_path)
        variantes = (df["variante"].fillna("").astype(str)
                     if "variante" in df.columns else pd.Series([""] * len(df)))
        nuevos = [None] * len(df)
        t0 = time.time()

        for i in range(0, len(df), BATCH):
            idx = list(range(i, min(i + BATCH, len(df))))
            imgs, validos = [], []
            for j in idx:
                try:
                    imgs.append(abrir(Path(str(df.at[j, "path"])), variantes.iat[j]))
                    validos.append(j)
                except Exception:
                    continue
            if not imgs:
                continue
            res = _model_c.predict_batch(imgs)
            for k, j in enumerate(validos):
                nuevos[j] = (round(res[k]["fake_probability"], 6)
                             if res[k] else None)
            for im in imgs:
                im.close()
            if (i // BATCH) % 40 == 0 or i + BATCH >= len(df):
                el = time.time() - t0
                hecho = min(i + BATCH, len(df))
                eta = el / max(hecho, 1) * (len(df) - hecho)
                print(f"    {csv_path.name}: {hecho}/{len(df)}  "
                      f"{el/60:.1f}min ETA {eta/60:.1f}min", flush=True)

        antes = df["efficientnet_ffpp"].astype(float)
        df["efficientnet_ffpp"] = nuevos
        df.to_csv(csv_path, index=False)
        despues = df["efficientnet_ffpp"].astype(float)
        print(f"  {csv_path.name}: actualizado")
        print(f"     antes   media={antes.mean():.4f} desv={antes.std():.4f}")
        print(f"     despues media={despues.mean():.4f} desv={despues.std():.4f}\n")

    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
