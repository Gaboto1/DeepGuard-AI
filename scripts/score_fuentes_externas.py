# -*- coding: utf-8 -*-
"""
Puntua imagenes de OpenFake con los seis detectores, para entrenar SOLO el
segundo nivel (los cabezales del meta-ensemble).

El problema que resuelve
------------------------
El meta-ensemble se entrena sobre las salidas de los detectores. Pero uno de
ellos, el probe CLIP (detector C), se entrena en este mismo proyecto y con las
mismas fuentes que componen `dataset_v2_scores.csv`. Sobre esas fuentes el
probe es casi perfecto, y el meta-ensemble aprende lo unico que puede aprender
de ahi: a fiarse de el. El cabezal principal le da el 64 % del peso.

Es la fuga clasica del *stacking*: el segundo nivel debe entrenarse con datos
que el primer nivel no vio, porque solo ahi se ve como falla. En el conjunto
de entrenamiento no existe NI UNA fila donde el probe se equivoque y otro
detector acierte, de modo que el meta-ensemble no puede aprender a cubrirse.
Fuera de muestra esas filas existen: sobre el retenido, el probe falla en 37
de 1.000 imagenes de IA y en 35 de ellas el detector de arte IA si la veia.

Reentrenar con los mismos datos no lo arregla -se probo tres veces, seccion
12 del informe v4-. Hacen falta filas de fuentes que el probe NO haya visto.
De ahi salen estas.

Por que OpenFake, y que se deja fuera
-------------------------------------
OpenFake (ComplexDataLab, cc-by-nc-4.0) reune imagenes de decenas de
generadores con la columna `model`, y fotografia autentica de LAION y Pexels.
Esta centrado en contenido politico y de figuras publicas: retratos
fotorrealistas, que es exactamente la clase de imagen que el sistema dejaba
pasar.

Se EXCLUYE todo lo que pondria en riesgo el conjunto retenido:
  - cualquier generador FLUX o derivado (`flux*`, `chroma`, `mystic`)
  - `dalle-3`
  - la fuente real `imagenet`
FLUX, DALL-E 3, ImageNet y LFW siguen sin entrar en ningun entrenamiento.

Como se agrupan, y por que importa
----------------------------------
`train_meta_dual_head.py` iguala el peso total de cada fuente. Con un grupo
por generador habria decenas de fuentes de IA frente a dos reales, el
clasificador se inclinaria hacia "IA" y subirian las falsas alarmas. Se
agrupan en tres familias de IA y dos fuentes reales, que conserva la
proporcion que ya tenia el conjunto (5 fuentes de IA por 4 reales).

  of_sd_clasico   SD 1.x / 2.x / SDXL y sus ajustes: la familia que el probe
                  SI conoce por arquitectura, pero con imagenes que no vio
  of_abiertos     modelos abiertos modernos: SD 3.5, Qwen, HiDream, Kolors...
  of_cerrados     modelos comerciales: GPT-Image, Imagen, Midjourney,
                  Ideogram, Grok, Seedream...
  of_laion        fotografia autentica (LAION)
  of_pexels       fotografia autentica de archivo (Pexels)

Estas filas NO se usan para entrenar el probe CLIP. Si algun dia se usaran,
dejarian de servir para esto.

Salida: reports/dataset_meta_externo_scores.csv   e imagenes en data/openfake/img/

Uso
---
    python scripts/score_fuentes_externas.py
"""
import argparse
import csv
import io
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "models"))
os.environ.setdefault("HF_HOME", str(ROOT / "models"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(str(BACKEND))

from PIL import Image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

ORIGEN = ROOT / "data" / "openfake"
IMG = ORIGEN / "img"
OUT = ROOT / "reports" / "dataset_meta_externo_scores.csv"

COLUMNS = [
    "source", "label", "path", "modelo",
    "face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
    "ai_art_detector", "siglip_deepfake", "ai_human_detector",
    "artwork_probability", "compression_level",
]

# Lo que no puede entrar porque el conjunto retenido depende de ello.
EXCLUIDOS = ("flux", "chroma", "mystic", "dalle", "dall-e", "tiny-random")
REALES_EXCLUIDOS = ("imagenet",)

SD_CLASICO = (
    "sd-1.5", "sd-2.1", "sd-turbo", "sdxl", "sd-xl", "stable-diffusion-v1",
    "stable-diffusion-xl", "stable-diffusion-2", "realistic_vision", "pony",
    "animagine", "novaanime", "one-obsession", "juggernaut", "playground",
    "cyberrealistic", "epic", "dreamshaper", "illustrious", "noobai",
)
CERRADOS = (
    "gpt-image", "imagen-", "nano-banana", "midjourney", "ideogram", "grok",
    "seedream", "recraft", "firefly", "reve", "luma", "kling", "veo", "sora",
    "runway", "aurora",
)


def clasificar(label: str, modelo: str):
    """(fuente, etiqueta) o None si la fila no debe entrar."""
    m = (modelo or "").lower()
    if (label or "").lower() == "real":
        if any(x in m for x in REALES_EXCLUIDOS):
            return None
        return f"of_{m}", 0
    if any(x in m for x in EXCLUIDOS):
        return None
    if any(x in m for x in CERRADOS):
        return "of_cerrados", 1
    if any(x in m for x in SD_CLASICO):
        return "of_sd_clasico", 1
    return "of_abiertos", 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-por-shard", type=int, default=0, help="0 = todo")
    args = ap.parse_args()

    import pyarrow.parquet as pq

    shards = sorted(ORIGEN.glob("*.parquet"))
    if not shards:
        print(f"ERROR: no hay shards en {ORIGEN}")
        return 1
    print(f"  {len(shards)} shards en {ORIGEN}")

    print("Cargando modelos del ensemble...")
    from app.models.deepfake_detector import (
        _model_a, _model_b, _model_c, _model_d, _model_e, _model_f)
    for m in (_model_a, _model_b, _model_c, _model_d, _model_e, _model_f):
        m.load()
    faltan = [n for n, m in zip("ABCDEF",
              (_model_a, _model_b, _model_c, _model_d, _model_e, _model_f))
              if not getattr(m, "_loaded", False)]
    if faltan:
        raise SystemExit(f"ABORTA: detectores sin cargar: {faltan}")
    from app.models.content_type_gate import ContentTypeGate
    gate = ContentTypeGate.get_instance()
    gate.load()
    from app.models.compression_estimator import estimate_compression
    print("Modelos listos.\n")

    IMG.mkdir(parents=True, exist_ok=True)
    conteo, descartes = Counter(), Counter()
    t0 = time.time()
    escritas = 0

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()

        def volcar(lote):
            nonlocal escritas
            if not lote:
                return
            imgs = [x[3] for x in lote]
            ra = _model_a.predict_batch(imgs)
            rb = _model_b.predict_batch(imgs)
            rc = _model_c.predict_batch(imgs)
            rd = _model_d.predict_batch(imgs)
            re_ = _model_e.predict_batch(imgs)
            rf = _model_f.predict_batch(imgs)
            art = gate.artwork_probability_batch(imgs)

            def g(res, j):
                return round(res[j]["fake_probability"], 6) if res[j] else ""

            for j, (fuente, etiqueta, ruta, im, modelo) in enumerate(lote):
                try:
                    comp = estimate_compression(im)["compression_level"]
                except Exception:
                    comp = 0.5
                w.writerow({
                    "source": fuente, "label": etiqueta, "path": str(ruta),
                    "modelo": modelo,
                    "face_deepfake_vit": g(ra, j), "sdxl_detector": g(rb, j),
                    "efficientnet_ffpp": g(rc, j), "ai_art_detector": g(rd, j),
                    "siglip_deepfake": g(re_, j), "ai_human_detector": g(rf, j),
                    "artwork_probability": round(art[j], 6),
                    "compression_level": round(float(comp), 6),
                })
                escritas += 1
                im.close()

        for shard in shards:
            pf = pq.ParquetFile(str(shard))
            tomadas = 0
            lote = []
            for rg in range(pf.metadata.num_row_groups):
                filas = pf.read_row_group(
                    rg, columns=["image", "label", "model", "row_id"]).to_pylist()
                for fila in filas:
                    destino = clasificar(fila["label"], fila["model"])
                    if destino is None:
                        descartes[fila["model"]] += 1
                        continue
                    if args.max_por_shard and tomadas >= args.max_por_shard:
                        break
                    fuente, etiqueta = destino
                    datos = (fila["image"] or {}).get("bytes")
                    if not datos:
                        descartes["(sin bytes)"] += 1
                        continue
                    try:
                        cruda = Image.open(io.BytesIO(datos))
                        ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(
                            cruda.format or "", ".img")
                        im = cruda.convert("RGB")
                    except Exception:
                        descartes["(no abre)"] += 1
                        continue
                    # Se guardan los BYTES ORIGINALES, sin recodificar: los
                    # detectores leen los artefactos de compresion, y volver a
                    # guardar como JPEG los sustituiria por los nuestros.
                    carpeta = IMG / fuente
                    carpeta.mkdir(parents=True, exist_ok=True)
                    ruta = carpeta / f"{fila['row_id']}{ext}"
                    if not ruta.exists():
                        ruta.write_bytes(datos)
                    lote.append((fuente, etiqueta, ruta, im, fila["model"]))
                    conteo[fuente] += 1
                    tomadas += 1
                    if len(lote) >= args.batch:
                        volcar(lote)
                        lote = []
                el = (time.time() - t0) / 60
                if rg % 10 == 0:
                    print(f"  {shard.name[:22]} grupo {rg + 1}/"
                          f"{pf.metadata.num_row_groups}  filas {escritas}  "
                          f"{el:.1f}min", flush=True)
                    fh.flush()
            volcar(lote)
            fh.flush()

    print(f"\nListo: {escritas} filas -> {OUT}   "
          f"({(time.time() - t0) / 60:.1f} min)")
    print("\n  por fuente:")
    for k, v in sorted(conteo.items()):
        print(f"    {k:16s} {v:6d}")
    print("\n  descartadas a proposito (para no tocar el retenido):")
    for k, v in descartes.most_common(14):
        print(f"    {k:34s} {v:5d}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
