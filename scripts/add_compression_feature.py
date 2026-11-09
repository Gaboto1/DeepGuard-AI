"""
Añade la columna `compression_level` a los conjuntos de evaluación.

Sólo usa CPU: no vuelve a ejecutar los detectores. Para el conjunto de
variantes recomprimidas regenera la variante segun su columna `variante`, de
modo que la compresion medida sea la de la imagen que realmente se puntuo.

Paralelismo
-----------
La medida es por imagen e independiente entre filas, pero no se puede agrupar
en lotes como en la GPU: hay que leer las tablas de cuantizacion del JPEG de
cada archivo. Con ~64.000 filas en un solo hilo la etapa se acercaba al limite
de tiempo del orquestador, asi que se reparte entre procesos.

El reparto exige el guardia `if __name__ == "__main__"`: en Windows cada
proceso hijo vuelve a importar este modulo, y sin el guardia cada hijo
reejecutaria el recorrido completo de los CSV.
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("HF_HOME", str(ROOT / "models"))

import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

from app.models.compression_estimator import estimate_compression  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

# Debe coincidir con scripts/augment_compresion.py
VARIANTES = {"jpeg_q55_1080": (55, 1080), "jpeg_q30_720": (30, 720)}

CSVS = [
    ROOT / "reports" / "dataset_v2_scores.csv",
    ROOT / "reports" / "dataset_v2_aug_scores.csv",
]

# Se deja un nucleo libre para que el resto del encadenamiento siga respondiendo.
PROCESOS = max(1, min(8, (os.cpu_count() or 4) - 1))


def nivel(args: tuple) -> float:
    path, variante = args
    try:
        im = Image.open(str(path)).convert("RGB")
    except Exception:
        return 0.5
    try:
        if variante and variante in VARIANTES:
            import io
            q, ancho = VARIANTES[variante]
            if im.width > ancho:
                im = im.resize((ancho, max(1, int(im.height * ancho / im.width))),
                               Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q, optimize=True)
            buf.seek(0)
            im = Image.open(buf)
        return estimate_compression(im)["compression_level"]
    except Exception:
        return 0.5
    finally:
        try:
            im.close()
        except Exception:
            pass


def main() -> int:
    print(f"Repartiendo entre {PROCESOS} procesos "
          f"({os.cpu_count()} nucleos detectados)\n", flush=True)

    for csv_path in CSVS:
        if not csv_path.exists():
            print(f"  omitido (no existe): {csv_path.name}")
            continue
        df = pd.read_csv(csv_path)
        if "variante" in df.columns:
            variantes = df["variante"].fillna("").astype(str).tolist()
        else:
            variantes = [""] * len(df)
        tareas = list(zip(df["path"].astype(str).tolist(), variantes))

        niveles = []
        # executor.map conserva el orden de entrada, de modo que la columna
        # resultante sigue alineada con las filas del CSV.
        with ProcessPoolExecutor(max_workers=PROCESOS) as ex:
            for i, v in enumerate(ex.map(nivel, tareas, chunksize=64), 1):
                niveles.append(v)
                if i % 5000 == 0:
                    print(f"    {csv_path.name}: {i}/{len(df)}", flush=True)

        assert len(niveles) == len(df), (
            f"{csv_path.name}: {len(niveles)} niveles para {len(df)} filas")
        df["compression_level"] = niveles
        df.to_csv(csv_path, index=False)
        print(f"  {csv_path.name}: columna añadida  "
              f"(media {df.compression_level.mean():.3f})", flush=True)

    print("\nListo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
