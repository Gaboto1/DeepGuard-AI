"""
Extrae embeddings CLIP ViT-L/14 para reentrenar el probe del detector C.

Por que
-------
El probe actual se entreno con 512 imagenes. Medido sobre conjunto multifuente
da AUC 0.863 sobre deepfakes faciales — el mejor del conjunto para ese caso —
pero su rango dinamico es minimo (desviacion 0.05, valores pegados a 0.45), de
modo que el meta-modelo apenas puede usarlo. Con 93.000 imagenes disponibles,
reentrenarlo es la via mas directa para que el sistema detecte deepfakes.

Representacion
--------------
vision_model.pooler_output (1024 dim) normalizado L2, identica a la que usa
_EfficientNetFF._embed en inferencia, para que el probe nuevo sea un reemplazo
directo.

Aumento de compresion
---------------------
Una fraccion de las imagenes se recomprime antes de embeber. Asi el probe
aprende invarianza a los artefactos JPEG en lugar de confundirlos con sintesis,
que es el fallo que hacia subir el score de las fotos recomprimidas.

Salida: models/advanced_detector/embeddings_{X,y,src}.npy
"""
import argparse
import io
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

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
OUT_DIR = ROOT / "models" / "advanced_detector"

# (fuente, ruta, etiqueta, n)   etiqueta 1 = sintetica
#
# Nueve fuentes, frente a las cuatro del conjunto anterior. El salto importante
# no es el volumen sino la procedencia: en el lado sintetico entran SDXL,
# SD 2.1 y DeepFloyd IF (via ELSA_D3) y Midjourney, generadores que el proyecto
# no habia visto nunca; en el real entran rostros de CelebA y fotografia de
# COCO train, que no comparten origen con lo que ya habia.
PLAN = [
    # ── real (70.000) ──
    ("coco_train",     "data/v3/real/coco_train",                   0, 32000),
    ("celeba",         "data/v3/real/celeba",                       0, 14000),
    ("coco",           "data/coco/val2017",                         0,  5000),
    ("ff_real",        "data/ff++_faces/real",                      0, 19000),
    # ── sintetica (70.000) ──
    ("elsa_multigen",  "data/v3/ai/elsa_multigen",                  1, 38000),
    ("midjourney",     "data/v3/ai/midjourney",                     1,  8000),
    ("diffusiondb",    "data/diffusiondb",                          1, 10000),
    ("ff_fake",        "data/ff++_faces/fake",                      1, 11000),
    ("sdturbo",        "data/real_world_training/ai_sdturbo",       1,  1500),
    ("sdturbo_sports", "data/real_world_training/ai_sdturbo_sports", 1,  1500),
]
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
# Probabilidad de añadir ademas una variante recomprimida de la misma imagen
P_AUG = 0.35
CLIP_ID = "openai/clip-vit-large-patch14"


def recomprimir(im: Image.Image, rnd: random.Random) -> Image.Image:
    q = rnd.randint(28, 78)
    ancho = rnd.choice([640, 800, 1080, im.width])
    if im.width > ancho:
        im = im.resize((ancho, max(1, int(im.height * ancho / im.width))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=48)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Dispositivo: {device}")

    from transformers import CLIPModel, CLIPProcessor
    print("Cargando CLIP ViT-L/14...")
    model = CLIPModel.from_pretrained(
        CLIP_ID, cache_dir=str(ROOT / "models"),
        torch_dtype=torch.float16 if device.type == "cuda" else torch.float32)
    proc = CLIPProcessor.from_pretrained(CLIP_ID, cache_dir=str(ROOT / "models"))
    model.to(device).eval()
    print("Listo.\n")

    tareas = []
    rnd = random.Random(11)
    for fuente, rel, label, n in PLAN:
        base = ROOT / rel
        if not base.exists():
            print(f"  [!] {fuente}: no existe — omitido")
            continue
        files = [p for p in base.rglob("*") if p.suffix.lower() in EXTS]
        rnd.shuffle(files)
        sel = files[:n]
        for p in sel:
            tareas.append((fuente, label, p, False))
            if rnd.random() < P_AUG:
                tareas.append((fuente, label, p, True))
        print(f"  {fuente:16s} label={label}  {len(sel):5d} base")

    rnd.shuffle(tareas)
    total = len(tareas)
    print(f"\n  TOTAL con aumento: {total} embeddings\n")

    X = np.zeros((total, 1024), dtype=np.float32)
    y = np.zeros(total, dtype=np.int8)
    src = np.empty(total, dtype=object)
    aug = np.zeros(total, dtype=bool)
    # La ruta es imprescindible para particionar por identidad: FaceForensics++
    # agrupa fotogramas por video (real/000/, fake/Deepfakes/000_003/), y si
    # fotogramas del mismo video caen a ambos lados de la particion el probe
    # memoriza la identidad en vez de la manipulacion.
    rutas = np.empty(total, dtype=object)

    escritos = 0
    t0 = time.time()
    rnd_aug = random.Random(77)

    for i in range(0, total, args.batch):
        lote = tareas[i:i + args.batch]
        imgs, meta = [], []
        for fuente, label, path, es_aug in lote:
            try:
                im = Image.open(path).convert("RGB")
                if es_aug:
                    im = recomprimir(im, rnd_aug)
            except Exception:
                continue
            imgs.append(im)
            meta.append((fuente, label, es_aug, path))
        if not imgs:
            continue
        try:
            inp = proc(images=imgs, return_tensors="pt", padding=True)
            px = inp["pixel_values"].to(device)
            if device.type == "cuda":
                px = px.half()
            with torch.no_grad():
                feat = model.vision_model(pixel_values=px).pooler_output.float()
                feat = feat / feat.norm(dim=-1, keepdim=True)
            feat = feat.cpu().numpy()
        except Exception as e:
            print(f"    lote fallido: {e}")
            for im in imgs:
                im.close()
            continue

        for j, (fuente, label, es_aug, path) in enumerate(meta):
            X[escritos] = feat[j]
            y[escritos] = label
            src[escritos] = fuente
            aug[escritos] = es_aug
            rutas[escritos] = str(path)
            escritos += 1
        for im in imgs:
            im.close()

        if (i // args.batch) % 25 == 0 or i + args.batch >= total:
            el = time.time() - t0
            hecho = min(i + args.batch, total)
            eta = el / max(hecho, 1) * (total - hecho)
            print(f"  [{hecho}/{total}] {el/60:.1f}min  ETA {eta/60:.1f}min", flush=True)

    X, y, src, aug, rutas = (X[:escritos], y[:escritos], src[:escritos],
                             aug[:escritos], rutas[:escritos])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.save(OUT_DIR / "embeddings_X.npy", X)
    np.save(OUT_DIR / "embeddings_y.npy", y)
    np.save(OUT_DIR / "embeddings_src.npy", src)
    np.save(OUT_DIR / "embeddings_aug.npy", aug)
    np.save(OUT_DIR / "embeddings_path.npy", rutas)

    print(f"\nGuardados {escritos} embeddings en {OUT_DIR}")
    print(f"  real={int((y==0).sum())}  sintetica={int((y==1).sum())}  "
          f"recomprimidas={int(aug.sum())}")
    print(f"Tiempo: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
