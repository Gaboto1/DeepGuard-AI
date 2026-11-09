"""
Amplia la clase "real" del probe CLIP con el dominio que faltaba: capturas de
webcam y recortes faciales.

Problema que resuelve
---------------------
El probe daba falso positivo en 4 de 8 fotografias reales subidas por el
usuario, y 93.8 % sobre el recorte facial de una webcam. La causa es que su
clase "real" venia solo de COCO (fotografia de Flickr) y ff++ (fotogramas de
video comprimido): ninguna captura de webcam, que es justo lo que la gente
sube. Lo que el probe aprendio fue "se parece a COCO o a ff++", no "es real".

Dos aportes
-----------
1. Recortes faciales de COCO. El cabezal facial solo habia visto rostros de
   ff++; estos son rostros reales de otra procedencia.
2. Variantes con degradacion tipo webcam sobre COCO: reescalado, ruido de
   sensor, perdida de contraste, dominante de color y recompresion. Aproximan
   el dominio de despliegue sin necesitar un corpus de webcams.

Las muestras se añaden como fuentes propias (coco_faces, coco_webcam,
coco_face_webcam) para que el ponderado por fuente las trate aparte.

Salida: añade a models/advanced_detector/embeddings_*.npy
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
os.chdir(str(BACKEND))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
DIR = ROOT / "models" / "advanced_detector"
CLIP_ID = "openai/clip-vit-large-patch14"


def degradar_webcam(im: Image.Image, rnd: random.Random) -> Image.Image:
    """
    Aproxima una captura de webcam: resolucion modesta, ruido de sensor, menos
    contraste, dominante de color y compresion.
    """
    ancho = rnd.choice([640, 800, 960, 1280])
    if im.width > ancho:
        im = im.resize((ancho, max(1, int(im.height * ancho / im.width))), Image.LANCZOS)

    if rnd.random() < 0.6:
        im = im.filter(ImageFilter.GaussianBlur(radius=rnd.uniform(0.3, 1.0)))

    a = np.asarray(im).astype(np.float32)
    a += np.random.normal(0, rnd.uniform(2.0, 9.0), a.shape)      # ruido de sensor
    canal = rnd.randint(0, 2)
    a[..., canal] *= rnd.uniform(0.94, 1.08)                       # dominante de color
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    im = ImageEnhance.Contrast(im).enhance(rnd.uniform(0.80, 1.05))
    im = ImageEnhance.Brightness(im).enhance(rnd.uniform(0.82, 1.12))
    im = ImageEnhance.Color(im).enhance(rnd.uniform(0.85, 1.15))

    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=rnd.randint(45, 85), optimize=True)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-caras", type=int, default=2200)
    ap.add_argument("--n-webcam", type=int, default=2200)
    ap.add_argument("--batch", type=int, default=48)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    from transformers import CLIPModel, CLIPProcessor
    print("Cargando CLIP...")
    model = CLIPModel.from_pretrained(
        CLIP_ID, cache_dir=str(ROOT / "models"),
        torch_dtype=torch.float16 if device.type == "cuda" else torch.float32)
    proc = CLIPProcessor.from_pretrained(CLIP_ID, cache_dir=str(ROOT / "models"))
    model.to(device).eval()

    from app.models.face_detector import FaceDetector
    fd = FaceDetector.get_instance()
    fd.load()
    print("Listo.\n")

    coco = sorted((ROOT / "data" / "coco" / "val2017").glob("*.jpg"))
    rnd = random.Random(23)
    rnd.shuffle(coco)

    # ── Construye las muestras nuevas ────────────────────────────────────────
    tareas = []   # (fuente, imagen_pil)
    print("Extrayendo recortes faciales de COCO...")
    caras = 0
    for p in coco:
        if caras >= args.n_caras:
            break
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        c = fd.get_primary_face(im)
        im.close()
        if c is None or c.width < 70:
            continue
        tareas.append(("coco_faces", c))
        caras += 1
        # la mitad tambien en version webcam
        if rnd.random() < 0.5:
            tareas.append(("coco_face_webcam", degradar_webcam(c, rnd)))
        if caras % 500 == 0:
            print(f"   {caras}/{args.n_caras}", flush=True)
    print(f"   {caras} recortes faciales\n")

    print("Generando variantes tipo webcam de imagenes completas...")
    for p in coco[: args.n_webcam]:
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        tareas.append(("coco_webcam", degradar_webcam(im, rnd)))
        im.close()
    print(f"   {sum(1 for t,_ in tareas if t=='coco_webcam')} variantes webcam\n")

    rnd.shuffle(tareas)
    total = len(tareas)
    print(f"TOTAL muestras nuevas: {total} (todas clase REAL)\n")

    # ── Embeddings ───────────────────────────────────────────────────────────
    Xn = np.zeros((total, 1024), dtype=np.float32)
    srcn = np.empty(total, dtype=object)
    escritos, t0 = 0, time.time()

    for i in range(0, total, args.batch):
        lote = tareas[i:i + args.batch]
        imgs = [im for _, im in lote]
        try:
            inp = proc(images=imgs, return_tensors="pt", padding=True)
            px = inp["pixel_values"].to(device)
            if device.type == "cuda":
                px = px.half()
            with torch.no_grad():
                f = model.vision_model(pixel_values=px).pooler_output.float()
                f = f / f.norm(dim=-1, keepdim=True)
            f = f.cpu().numpy()
        except Exception as e:
            print(f"   lote fallido: {e}")
            continue
        for j, (fuente, _) in enumerate(lote):
            Xn[escritos] = f[j]
            srcn[escritos] = fuente
            escritos += 1
        for im in imgs:
            im.close()
        if (i // args.batch) % 20 == 0 or i + args.batch >= total:
            el = time.time() - t0
            hecho = min(i + args.batch, total)
            print(f"   [{hecho}/{total}] {el/60:.1f}min", flush=True)

    Xn, srcn = Xn[:escritos], srcn[:escritos]

    # ── Anexa a los embeddings existentes ────────────────────────────────────
    X = np.load(DIR / "embeddings_X.npy")
    y = np.load(DIR / "embeddings_y.npy")
    src = np.load(DIR / "embeddings_src.npy", allow_pickle=True)
    aug = np.load(DIR / "embeddings_aug.npy")
    rutas = np.load(DIR / "embeddings_path.npy", allow_pickle=True)

    # Conserva una copia antes de modificar
    for nom in ("X", "y", "src", "aug", "path"):
        orig = DIR / f"embeddings_{nom}.npy"
        bak = DIR / f"embeddings_{nom}.bak.npy"
        if not bak.exists():
            np.save(bak, np.load(orig, allow_pickle=True))

    np.save(DIR / "embeddings_X.npy", np.vstack([X, Xn]))
    np.save(DIR / "embeddings_y.npy", np.concatenate([y, np.zeros(escritos, dtype=y.dtype)]))
    np.save(DIR / "embeddings_src.npy", np.concatenate([src, srcn]))
    np.save(DIR / "embeddings_aug.npy", np.concatenate([aug, np.ones(escritos, dtype=bool)]))
    np.save(DIR / "embeddings_path.npy",
            np.concatenate([rutas, np.array([f"sintetico_dominio_{i}" for i in range(escritos)],
                                            dtype=object)]))

    print(f"\nAñadidas {escritos} muestras reales. Total ahora: {len(X) + escritos}")
    print(f"Tiempo: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
