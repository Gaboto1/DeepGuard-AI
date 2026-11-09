"""
Descarga un conjunto RETENIDO, independiente del entrenamiento.

Por que hace falta
------------------
Hasta ahora toda cifra de validacion salia de las mismas fuentes con las que se
entrena. Eso basta para comparar configuraciones entre si, pero no responde la
unica pregunta que importa en produccion: que pasa con una fotografia que no se
parece a nada de lo visto. El fallo que reporto el usuario — su propia selfie de
webcam marcada al 53 % — lo provoco exactamente ese hueco, y el banco de pruebas
de entonces no lo detecto porque compartia el punto ciego con el modelo.

Fuentes elegidas por ser de dominio distinto, no solo de imagenes distintas
-----------------------------------------------------------------------------
    lfw        rostros reales fotografiados sin control de estudio. Es el
               dominio mas cercano a la foto que sube un usuario cualquiera.
               CelebA (que si esta en entrenamiento) son retratos de prensa:
               encuadre, foco e iluminacion muy distintos.
    imagenet   fotografia general de 1.000 categorias. Cubre objeto, animal,
               interior y exterior, donde COCO se concentra en escenas urbanas
               con personas.

Ninguna de las dos aparece en los planes de scripts/extract_clip_embeddings.py
ni de scripts/score_dataset_v2.py. Esa es la condicion que las hace utiles: si
se usaran para entrenar dejarian de medir lo que aqui se quiere medir.

Codificacion identica a la del conjunto v3 (JPEG 92, lado maximo 1024) para que
el formato no sea por si mismo una pista.

Salida: data/heldout/real/{lfw,imagenet}/
"""
import argparse
import os

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HOME", str(ROOT / "models"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from PIL import Image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
DEST = ROOT / "data" / "heldout"
LADO_MAX = 1024
CALIDAD = 92

# (clase, fuente, dataset_id, config, split, cuota)
#
# El lado sintetico busca arquitecturas de generacion ausentes del
# entrenamiento. FLUX y DALL-E 3 no comparten linaje con lo entrenado (SDXL,
# SD 1.x, SD 2.1, DeepFloyd IF, Midjourney, SD-turbo e intercambio de rostros),
# de modo que miden si el sistema reconoce sintesis o solo reconoce las huellas
# concretas de los generadores que ya vio.
PLAN = [
    ("real", "lfw",      "logasja/lfw",            "default", "train",      2000),
    ("real", "imagenet", "mrm8488/ImageNet1K-val", None,      "train",      2000),
    ("ai",   "flux",     "jackyhate/text-to-image-2M", None,  "train",      1500),
    ("ai",   "dalle3",   "ehristoforu/dalle-3-images", None,  "train",      1500),
]
# Nombres de campo de imagen segun el conjunto: los empaquetados en webdataset
# la traen como "jpg" en vez de "image".
CAMPOS_IMAGEN = ("image", "img", "jpg", "jpeg", "png")


def guardar(im, destino: Path) -> bool:
    try:
        im = im.convert("RGB")
        if max(im.size) > LADO_MAX:
            f = LADO_MAX / max(im.size)
            im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))),
                           Image.LANCZOS)
        im.save(destino, "JPEG", quality=CALIDAD, optimize=True)
        return True
    except Exception:
        destino.unlink(missing_ok=True)
        return False


def descargar(clase, fuente, ds_id, cfg, split, cuota) -> int:
    from datasets import load_dataset

    carpeta = DEST / clase / fuente
    carpeta.mkdir(parents=True, exist_ok=True)
    ya = len(list(carpeta.glob("*.jpg")))
    if ya >= cuota:
        print(f"  {fuente:10s} ya completo ({ya:,})", flush=True)
        return ya

    print(f"  {fuente:10s} objetivo {cuota:,}  (existen {ya:,})", flush=True)
    kw = {"split": split, "streaming": True}
    if cfg:
        kw["name"] = cfg
    try:
        ds = load_dataset(ds_id, **kw)
    except Exception as e:
        print(f"  {fuente:10s} ERROR al abrir: {type(e).__name__}: {str(e)[:110]}")
        return ya

    n, fallidas, t0 = ya, 0, time.time()
    try:
        for fila in ds:
            if n >= cuota:
                break
            im = next((fila[c] for c in CAMPOS_IMAGEN
                       if fila.get(c) is not None), None)
            if im is None:
                continue
            destino = carpeta / f"{fuente}_{n:06d}.jpg"
            if destino.exists():
                n += 1
                continue
            if guardar(im, destino):
                n += 1
            else:
                fallidas += 1
            if n % 250 == 0 and n > ya:
                vel = (n - ya) / max(time.time() - t0, 1)
                print(f"  {fuente:10s} {n:,}/{cuota:,}  {vel:.0f} img/s", flush=True)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"  {fuente:10s} interrumpido: {type(e).__name__}: {str(e)[:110]}")

    print(f"  {fuente:10s} FIN {n:,} guardadas, {fallidas} fallidas, "
          f"{(time.time()-t0)/60:.1f}min", flush=True)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo")
    args = ap.parse_args()

    print("=" * 70)
    print("  Conjunto RETENIDO — fuentes ausentes del entrenamiento")
    print("=" * 70)
    total = 0
    for clase, fuente, ds_id, cfg, split, cuota in PLAN:
        if args.solo and fuente != args.solo:
            continue
        total += descargar(clase, fuente, ds_id, cfg, split, cuota)

    # Fuentes retenidas que ya estan en disco y no participan en ningun plan
    locales = [
        ("ai", "ai_stable_diffusion", ROOT / "data/real_world_training/ai_stable_diffusion"),
    ]
    print("\n  Retenidas ya en disco:")
    for clase, nom, ruta in locales:
        n = len(list(ruta.glob("*.jpg"))) + len(list(ruta.glob("*.png"))) if ruta.exists() else 0
        print(f"    {clase:4s} {nom:22s} {n:6,}  {'si' if ruta.exists() else 'NO EXISTE'}")

    print("\n" + "=" * 70)
    print(f"  Descargadas: {total:,}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
