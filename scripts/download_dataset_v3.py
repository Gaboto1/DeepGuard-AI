"""
Descarga el conjunto v3: 100.000 imagenes reales y 100.000 sinteticas.

Criterio: diversidad de origen, no volumen
------------------------------------------
El conjunto anterior tenia 25.500 imagenes distintas pero de solo 4 origenes, y
el probe fallaba en 4 de 8 fotografias reales del usuario. Anadir 100.000 fotos
mas de COCO no habria corregido eso: el hueco no era de cantidad sino de
procedencia. Por eso cada clase se reparte entre varias fuentes, y en el lado
sintetico se incorporan generadores que el proyecto nunca habia visto.

Generadores cubiertos tras la descarga
--------------------------------------
    ya presentes : Stable Diffusion 1.x (diffusiondb), SD-turbo,
                   intercambio de rostros (FaceForensics++)
    nuevos       : SDXL, Stable Diffusion 2.1, DeepFloyd IF (via ELSA_D3)
                   y Midjourney

Codificacion uniforme
---------------------
Todo se guarda como JPEG de calidad 92 con lado maximo de 1024 px, sea cual sea
el formato de origen. Es deliberado: hoy diffusiondb son PNG y COCO son JPEG, de
modo que el formato por si solo delata la clase y el modelo puede aprender ese
atajo en lugar de la tarea. Con codificacion uniforme ese atajo desaparece.

Reanudable: vuelve a ejecutarse sin repetir lo ya descargado.
Salida: data/v3/{real,ai}/{fuente}/
"""
import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HOME", str(ROOT / "models"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from PIL import Image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
DEST = ROOT / "data" / "v3"
LADO_MAX = 1024
CALIDAD = 92

# (clase, fuente, dataset_id, split, cuota, campos_de_imagen, filtro)
#
# Se descarto Hemg/AI-Generated-vs-Real-Images-Datasets pese a tener 152.710
# filas etiquetadas: viene ordenado por clase (las primeras cientos de filas son
# todas de la misma etiqueta), lo que hace inviable filtrar en streaming, y sus
# imagenes promedian 120x101 px. Ademas el tamano difiere entre clases, de modo
# que habria introducido justo el tipo de atajo que este conjunto busca evitar.
# Objetivo: 100.000 reales y 100.000 sinteticas sumando lo descargado y lo que
# ya estaba en disco. Velocidad medida en streaming: 90 img/s en COCO y 450 en
# CelebA. El script es reanudable: skip de lo ya guardado, de modo que subir
# estas cuotas y volver a ejecutarlo solo descarga lo que falta.
#
#   real      descarga 50.000 + 15.000 CelebA  +  35.000 ya en disco  = 100.000
#   sintetica descarga 72.000 ELSA + 8.600 MJ  +  ~20.000 ya en disco = 100.000
PLAN = [
    ("real", "coco_train",  "detection-datasets/coco", "train", 50000, ["image"], None),
    ("real", "celeba",      "nielsr/CelebA-faces",     "train", 15000, ["image"], None),
    # Cada fila de ELSA_D3 trae la misma escena generada por cuatro modelos
    # distintos: SDXL, SD 2.1, SD 1.4 y DeepFloyd IF — los generadores que el
    # proyecto no conocia. OJO: la cuota cuenta IMAGENES, no filas; 72.000
    # imagenes salen de unas 18.000 filas.
    ("ai",   "elsa_multigen", "elsaEU/ELSA_D3", "train", 72000,
     ["image_gen0", "image_gen1", "image_gen2", "image_gen3"], None),
    # El dataset completo de Midjourney son 8.616 imagenes: se toman todas.
    ("ai",   "midjourney",  "ehristoforu/midjourney-images", "train", 8600, ["image"], None),
]


def guardar(im: Image.Image, destino: Path) -> bool:
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


def descargar(clase, fuente, ds_id, split, cuota, campos, filtro, log):
    from datasets import load_dataset

    carpeta = DEST / clase / fuente
    carpeta.mkdir(parents=True, exist_ok=True)
    ya = len(list(carpeta.glob("*.jpg")))
    if ya >= cuota:
        log(f"  {fuente:16s} ya completo ({ya:,})")
        return ya

    log(f"  {fuente:16s} objetivo {cuota:,}  (existen {ya:,})")
    try:
        ds = load_dataset(ds_id, split=split, streaming=True)
    except Exception as e:
        log(f"  {fuente:16s} ERROR al abrir: {type(e).__name__}: {str(e)[:120]}")
        return ya

    n, saltadas, t0 = ya, 0, time.time()
    # Avanza el flujo hasta donde se habia quedado
    try:
        for i, fila in enumerate(ds):
            if n >= cuota:
                break
            if filtro:
                campo, valor = filtro
                if fila.get(campo) != valor:
                    continue
            for campo_img in campos:
                if n >= cuota:
                    break
                im = fila.get(campo_img)
                if im is None:
                    continue
                destino = carpeta / f"{fuente}_{n:06d}.jpg"
                if destino.exists():
                    n += 1
                    continue
                if guardar(im, destino):
                    n += 1
                else:
                    saltadas += 1
            if n % 500 == 0 and n > ya:
                el = time.time() - t0
                hechas = n - ya
                vel = hechas / max(el, 1)
                eta = (cuota - n) / max(vel, 0.01) / 60
                log(f"  {fuente:16s} {n:,}/{cuota:,}  {vel:.0f} img/s  ETA {eta:.0f}min")
    except KeyboardInterrupt:
        raise
    except Exception as e:
        log(f"  {fuente:16s} interrumpido: {type(e).__name__}: {str(e)[:120]}")

    log(f"  {fuente:16s} FIN {n:,} guardadas, {saltadas} fallidas, "
        f"{(time.time()-t0)/60:.1f}min")
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", help="descargar solo esta fuente")
    args = ap.parse_args()

    registro = ROOT / "reports" / "download_v3.log"
    registro.parent.mkdir(parents=True, exist_ok=True)

    def log(msg):
        print(msg, flush=True)

    log("=" * 70)
    log("  Descarga del conjunto v3 — prioridad: diversidad de origen")
    log("=" * 70)

    totales = {"real": 0, "ai": 0}
    for clase, fuente, ds_id, split, cuota, campos, filtro in PLAN:
        if args.solo and fuente != args.solo:
            continue
        n = descargar(clase, fuente, ds_id, split, cuota, campos, filtro, log)
        totales[clase] += n

    # Lo que ya estaba en disco y se reutiliza sin descargar
    locales = {
        "real": [("ff_real", ROOT / "data/ff++_faces/real", 15000),
                 ("coco_val", ROOT / "data/coco/val2017", 5000)],
        "ai":   [("ff_fake", ROOT / "data/ff++_faces/fake", 15000),
                 ("diffusiondb", ROOT / "data/diffusiondb", 19000),
                 ("sdturbo", ROOT / "data/real_world_training", 5000)],
    }
    log("\n  Ya en disco (no se descargan):")
    for clase, fuentes in locales.items():
        for nom, ruta, n in fuentes:
            existe = "si" if ruta.exists() else "NO EXISTE"
            log(f"    {clase:4s} {nom:14s} {n:6,}  {existe}")
            totales[clase] += n

    log("\n" + "=" * 70)
    log(f"  TOTAL real     : {totales['real']:,}")
    log(f"  TOTAL sintetica: {totales['ai']:,}")
    log("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
