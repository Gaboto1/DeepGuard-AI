"""
Amplía el conjunto de evaluación con variantes recomprimidas.

Motivo
------
El meta-modelo elevaba el score de las fotografías reales al recomprimirlas:
una foto de COCO pasaba de 26 % a 58 % con sólo guardarla en JPEG de calidad 55.
La causa es que la clase "real" del conjunto no contenía fotografía
recomprimida: COCO viene en buena calidad y ff++ es vídeo ya comprimido, pero
nunca el caso intermedio de una foto que pasó por redes sociales.

Se generan variantes recomprimidas de AMBAS clases. Augmentar sólo la real
enseñaría el sesgo contrario ("comprimido = auténtico").

Salida: reports/dataset_v2_aug_scores.csv con las mismas columnas que
        dataset_v2_scores.csv más `variante`.
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

import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

CSV_IN = ROOT / "reports" / "dataset_v2_scores.csv"
CSV_OUT = ROOT / "reports" / "dataset_v2_aug_scores.csv"

# Fuentes que solo existen en el conjunto v3. Si el CSV no las trae, la etapa de
# puntuacion no llego a rehacerse (por ejemplo, por falta de VRAM si el worker de
# Celery seguia cargado) y lo que hay en disco es el conjunto anterior. Entrenar
# sobre el sin avisar daria un modelo que parece nuevo y no lo es, asi que se
# aborta en vez de continuar en silencio.
FUENTES_V3 = {"coco_train", "celeba", "elsa_multigen", "midjourney"}


def exigir_csv_v3(csv_path) -> None:
    import datetime as _dt
    import pandas as _pd
    cab = _pd.read_csv(csv_path, usecols=["source"])
    presentes = set(cab["source"].unique())
    mtime = _dt.datetime.fromtimestamp(csv_path.stat().st_mtime)
    print(f"  {csv_path.name}: {len(cab):,} filas, {len(presentes)} fuentes, "
          f"modificado {mtime:%Y-%m-%d %H:%M}")
    faltan = FUENTES_V3 - presentes
    if faltan:
        raise SystemExit(
            f"ABORTA: {csv_path.name} no contiene {sorted(faltan)}. "
            f"  Fuentes presentes: {sorted(presentes)}. "
            f"  Es el conjunto anterior. Vuelve a ejecutar "
            f"scripts/score_dataset_v2.py con la GPU libre "
            f"(detener el worker de Celery) antes de esta etapa."
        )

TMP = ROOT / "reports" / "_tmp_aug"

COLUMNS = [
    "source", "label", "path", "variante",
    "face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
    "ai_art_detector", "siglip_deepfake", "ai_human_detector",
    "artwork_probability",
]

# (nombre, calidad JPEG, ancho máximo) — imitan el paso por redes sociales
VARIANTES = [
    ("jpeg_q55_1080", 55, 1080),
    ("jpeg_q30_720", 30, 720),
]


def recomprimir(src: Path, destino: Path, calidad: int, ancho: int) -> bool:
    try:
        im = Image.open(src).convert("RGB")
    except Exception:
        return False
    if im.width > ancho:
        im = im.resize((ancho, max(1, int(im.height * ancho / im.width))), Image.LANCZOS)
    try:
        im.save(destino, "JPEG", quality=calidad, optimize=True)
    except Exception:
        return False
    finally:
        im.close()
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--por-clase", type=int, default=1500,
                    help="imágenes base por clase antes de generar variantes")
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args()

    if not CSV_IN.exists():
        print(f"ERROR: falta {CSV_IN}")
        return 1

    exigir_csv_v3(CSV_IN)
    df = pd.read_csv(CSV_IN)
    df = df[df["path"].map(lambda p: Path(str(p)).exists())]
    print(f"Base disponible: {len(df)} filas")

    # Muestreo estratificado por fuente dentro de cada clase
    base = []
    for label in (0, 1):
        sub = df[df.label == label]
        fuentes = sub["source"].unique()
        por_fuente = max(1, args.por_clase // len(fuentes))
        for s in fuentes:
            ss = sub[sub.source == s]
            base.append(ss.sample(min(por_fuente, len(ss)), random_state=17))
    base = pd.concat(base, ignore_index=True)
    print(f"Seleccionadas {len(base)} imágenes base "
          f"({int((base.label==0).sum())} real, {int((base.label==1).sum())} IA)")
    print(f"Variantes por imagen: {len(VARIANTES)} -> "
          f"{len(base)*len(VARIANTES)} filas nuevas\n")

    TMP.mkdir(parents=True, exist_ok=True)

    print("Cargando modelos...")
    from app.models.deepfake_detector import (
        _model_a, _model_b, _model_c, _model_d, _model_e, _model_f,
    )
    for m in (_model_a, _model_b, _model_c, _model_d, _model_e, _model_f):
        m.load()
    from app.models.content_type_gate import ContentTypeGate
    gate = ContentTypeGate.get_instance()
    gate.load()
    print("Listo.\n")

    tareas = []
    for i, row in enumerate(base.itertuples(index=False)):
        for nombre, q, ancho in VARIANTES:
            tareas.append((row.source, int(row.label), Path(row.path), nombre, q, ancho, i))
    random.Random(3).shuffle(tareas)

    t0 = time.time()
    escritas = 0
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for i in range(0, len(tareas), args.batch):
            lote = tareas[i:i + args.batch]
            imgs, meta, temporales = [], [], []
            for src, label, path, nombre, q, ancho, idx in lote:
                dst = TMP / f"{idx}_{nombre}.jpg"
                if not recomprimir(path, dst, q, ancho):
                    continue
                try:
                    imgs.append(Image.open(dst).convert("RGB"))
                except Exception:
                    continue
                meta.append((src, label, path, nombre))
                temporales.append(dst)
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

            for j, (src, label, path, nombre) in enumerate(meta):
                w.writerow({
                    "source": src, "label": label, "path": str(path),
                    "variante": nombre,
                    "face_deepfake_vit": g(ra, j),
                    "sdxl_detector":     g(rb, j),
                    "efficientnet_ffpp": g(rc, j),
                    "ai_art_detector":   g(rd, j),
                    "siglip_deepfake":   g(re_, j),
                    "ai_human_detector": g(rf, j),
                    "artwork_probability": round(art[j], 6),
                })
                escritas += 1

            for im in imgs:
                im.close()
            for d in temporales:
                d.unlink(missing_ok=True)

            if (i // args.batch) % 20 == 0 or i + args.batch >= len(tareas):
                el = time.time() - t0
                hecho = min(i + args.batch, len(tareas))
                eta = el / max(hecho, 1) * (len(tareas) - hecho)
                print(f"  [{hecho}/{len(tareas)}] {el/60:.1f}min  ETA {eta/60:.1f}min",
                      flush=True)
                fh.flush()

    try:
        TMP.rmdir()
    except OSError:
        pass

    print(f"\nListo: {escritas} filas -> {CSV_OUT}")
    print(f"Tiempo: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
