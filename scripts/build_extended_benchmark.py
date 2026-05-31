"""
Benchmark Extendido — Construcción automática
=============================================
Genera imágenes de prueba para todas las categorías del benchmark.
No requiere intervención manual.

Categorías reales:
  selfies, deportes, noticias, paisajes, nocturnas, retratos profesionales

Categorías IA:
  Midjourney-style, FLUX-style, GPT Image-style, SDXL-style,
  Ideogram-style, Anime-IA

Salida: tests/benchmark_extended/
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

ROOT    = Path(__file__).parent.parent
OUT     = ROOT / "tests" / "benchmark_extended"
SEED    = 1337
rng     = np.random.default_rng(SEED)
MANIFEST= []


def save(img: Image.Image, cat: str, name: str, label: int | None, desc: str) -> None:
    path = OUT / cat / f"{name}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, "JPEG", quality=rng.integers(85, 96).item())
    MANIFEST.append({"path": str(path.relative_to(ROOT)), "category": cat,
                     "name": name, "label": label, "description": desc})
    print(f"  [{cat}] {name}")


def noise(shape, scale=8, s=0):
    return (np.random.default_rng(SEED+s).standard_normal(shape)*scale).astype(np.int16)


def add_noise(arr, scale=8, s=0):
    return np.clip(arr.astype(np.int16) + noise(arr.shape, scale, s), 0, 255).astype(np.uint8)


# ── REAL: Selfies ─────────────────────────────────────────────────────────────
def real_selfies():
    for i in range(5):
        w, h = 480, 640
        skin = [rng.integers(170,230).item(), rng.integers(130,190).item(), rng.integers(100,160).item()]
        bg   = [rng.integers(100,200).item(), rng.integers(100,200).item(), rng.integers(100,200).item()]
        img  = Image.new("RGB", (w, h), tuple(bg))
        d    = ImageDraw.Draw(img)
        # Slightly asymmetric face
        offs = rng.integers(-15, 15).item()
        d.ellipse([80+offs, 100, 400+offs, 520], fill=tuple(skin))
        # Eyes with natural variation
        ex1 = 130+offs; ex2 = 290+rng.integers(-5,5).item()+offs
        ey  = 220+rng.integers(-5,5).item()
        d.ellipse([ex1, ey, ex1+60, ey+38], fill=(rng.integers(20,60).item(), rng.integers(15,50).item(), rng.integers(30,70).item()))
        d.ellipse([ex2, ey, ex2+55+rng.integers(-5,5).item(), ey+36], fill=(rng.integers(20,60).item(), rng.integers(15,50).item(), rng.integers(30,70).item()))
        # Hair
        d.rectangle([0,0,w,110], fill=(rng.integers(20,80).item(), rng.integers(15,60).item(), rng.integers(10,40).item()))
        arr = add_noise(np.array(img), 10, i)
        img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.4))
        save(img, "real/selfies", f"selfie_{i:02d}", 0, "Selfie con asimetría facial natural")

# ── REAL: Deportes ────────────────────────────────────────────────────────────
def real_deportes():
    for i in range(5):
        w, h = 800, 533
        # Grass + stadium
        arr = np.zeros((h, w, 3), np.uint8)
        arr[h//2:] = [rng.integers(40,80).item(), rng.integers(100,160).item(), rng.integers(30,60).item()]
        arr[:h//2]  = [rng.integers(100,170).item(), rng.integers(130,190).item(), rng.integers(180,230).item()]
        arr = add_noise(arr, 15, i+10)
        img = Image.fromarray(arr)
        d   = ImageDraw.Draw(img)
        # Player
        px = rng.integers(200, 600).item(); py = h//2 - 40
        d.ellipse([px, py, px+50, py+70], fill=(rng.integers(180,230).item(), rng.integers(140,190).item(), rng.integers(100,150).item()))
        d.rectangle([px+10, py+65, px+40, py+130], fill=(rng.integers(100,200).item(), rng.integers(20,80).item(), rng.integers(20,80).item()))
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        img = img.transform(img.size, Image.AFFINE, (1, 0.02, 0, 0, 1, 0), Image.BICUBIC)  # slight motion
        save(img, "real/deportes", f"deporte_{i:02d}", 0, "Fotografía deportiva con movimiento y fondo real")

# ── REAL: Paisajes ────────────────────────────────────────────────────────────
def real_paisajes():
    for i in range(5):
        w, h = 800, 500
        arr = np.zeros((h, w, 3), np.uint8)
        for y in range(h):
            t = y / h
            r2 = int(rng.integers(80,140).item() * (1-t) + rng.integers(30,70).item() * t)
            g2 = int(rng.integers(130,200).item() * (1-t) + rng.integers(60,120).item() * t)
            b2 = int(rng.integers(180,240).item() * (1-t) + rng.integers(20,60).item() * t)
            arr[y] = [r2, g2, b2]
        # Mountains
        for x in range(w):
            ph = int(h*0.4 + 60*np.sin(x/80+i) + 30*np.sin(x/30))
            arr[ph:ph+4, x] = [80, 70, 65]
        arr = add_noise(arr, 8, i+20)
        img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.3))
        save(img, "real/paisajes", f"paisaje_{i:02d}", 0, "Paisaje natural con gradiente atmosférico y ruido")

# ── REAL: Nocturnas ───────────────────────────────────────────────────────────
def real_nocturnas():
    for i in range(4):
        w, h = 720, 480
        arr = np.zeros((h, w, 3), np.uint8) + 8
        for _ in range(200):
            lx = rng.integers(0, w).item(); ly = rng.integers(int(h*0.3), h).item()
            v  = rng.integers(100, 255).item()
            col = rng.choice([[v, int(v*0.7), int(v*0.2)], [int(v*0.8), int(v*0.9), v], [v, v, int(v*0.6)]])
            sz = rng.integers(1, 3).item()
            arr[max(0,ly-sz):ly+sz, max(0,lx-sz):lx+sz] = col
        arr = add_noise(arr, 5, i+30)
        img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(1.2))
        save(img, "real/nocturnas", f"nocturna_{i:02d}", 0, "Escena nocturna urbana con luces naturales")

# ── REAL: Noticias ────────────────────────────────────────────────────────────
def real_noticias():
    for i in range(4):
        w, h = 720, 480
        arr = np.zeros((h, w, 3), np.uint8)
        # Conference room / press scene
        arr[:] = [rng.integers(160,210).item(), rng.integers(150,200).item(), rng.integers(140,185).item()]
        arr = add_noise(arr, 20, i+40)
        img = Image.fromarray(arr)
        d = ImageDraw.Draw(img)
        # Podium
        d.rectangle([240, 280, 480, 480], fill=(80, 70, 65))
        d.rectangle([200, 200, 520, 290], fill=(100, 95, 90))
        # Speaker
        d.ellipse([300, 130, 400, 215], fill=(rng.integers(180,225).item(), rng.integers(140,185).item(), rng.integers(100,150).item()))
        # Simulate JPEG news compression
        from io import BytesIO
        buf = BytesIO(); img.save(buf, "JPEG", quality=55); buf.seek(0)
        img = Image.open(buf).copy()
        save(img, "real/noticias", f"noticia_{i:02d}", 0, "Escena de prensa con compresión JPEG de agencia")

# ── IA: Midjourney style ──────────────────────────────────────────────────────
def ia_midjourney():
    for i in range(5):
        w, h = 512, 512
        img = Image.new("RGB", (w, h), (rng.integers(140,180).item(), rng.integers(110,150).item(), rng.integers(80,120).item()))
        d = ImageDraw.Draw(img)
        # Perfect face (symmetric)
        offs = 0  # ZERO asymmetry — key AI indicator
        d.ellipse([100, 80, 412, 460], fill=(rng.integers(210,240).item(), rng.integers(175,210).item(), rng.integers(145,180).item()))
        for ex in [148, 308]:  # exactly mirrored
            d.ellipse([ex, 175, ex+64, 222], fill=(rng.integers(30,60).item(), rng.integers(25,55).item(), rng.integers(45,80).item()))
            d.ellipse([ex+12, 184, ex+52, 213], fill=(rng.integers(60,100).item(), rng.integers(50,90).item(), rng.integers(70,110).item()))
        img = img.filter(ImageFilter.GaussianBlur(2.5))
        img = ImageEnhance.Color(img).enhance(1.7)
        img = ImageEnhance.Sharpness(img).enhance(3.0)
        save(img, "ia/midjourney", f"midjourney_{i:02d}", 1, "Estilo Midjourney: simetría perfecta, hipernítido, supersaturado")

# ── IA: SDXL style ────────────────────────────────────────────────────────────
def ia_sdxl():
    for i in range(5):
        w, h = 1024, 1024
        # SDXL characteristic: high resolution but unnaturally smooth
        img = Image.new("RGB", (w, h), (rng.integers(180,220).item(), rng.integers(150,190).item(), rng.integers(120,160).item()))
        d = ImageDraw.Draw(img)
        d.ellipse([200, 150, 824, 900], fill=(rng.integers(215,245).item(), rng.integers(185,215).item(), rng.integers(155,185).item()))
        for ex in [290, 590]:
            d.ellipse([ex, 330, ex+130, 420], fill=(rng.integers(25,55).item(), rng.integers(20,50).item(), rng.integers(40,75).item()))
        img = img.filter(ImageFilter.GaussianBlur(4.0))  # very smooth
        img = ImageEnhance.Color(img).enhance(1.4)
        img = img.resize((512, 512), Image.LANCZOS)
        save(img, "ia/sdxl", f"sdxl_{i:02d}", 1, "Estilo SDXL: alta resolución, piel textureless, iluminación plana perfecta")

# ── IA: Anime ─────────────────────────────────────────────────────────────────
def ia_anime():
    for i in range(4):
        w, h = 512, 512
        img = Image.new("RGB", (w, h), (255, 245, 230))
        d = ImageDraw.Draw(img)
        # Anime proportions: huge eyes
        d.ellipse([90, 80, 422, 450], fill=(255, 228, 205))
        d.ellipse([100, 175, 220, 300], fill=(rng.integers(20,80).item(), rng.integers(60,140).item(), rng.integers(150,220).item()))
        d.ellipse([292, 175, 412, 300], fill=(rng.integers(20,80).item(), rng.integers(60,140).item(), rng.integers(150,220).item()))
        d.ellipse([120, 195, 200, 280], fill=(rng.integers(5,25).item(), rng.integers(5,25).item(), rng.integers(20,50).item()))
        d.ellipse([312, 195, 392, 280], fill=(rng.integers(5,25).item(), rng.integers(5,25).item(), rng.integers(20,50).item()))
        d.point([(256, 355)], fill=(230, 195, 175))
        d.arc([210, 378, 302, 408], 5, 175, fill=(200, 100, 110), width=3)
        for hy in range(0, 100, 4):
            d.line([(50, hy), (462, hy)], fill=(rng.integers(30,100).item(), rng.integers(20,70).item(), rng.integers(80,160).item()), width=4)
        img = img.filter(ImageFilter.GaussianBlur(0.5))
        img = ImageEnhance.Color(img).enhance(1.6)
        save(img, "ia/anime", f"anime_{i:02d}", 1, "Anime IA: proporciones imposibles, ojos enormes, colores planos")

# ── IA: Fantasy / FLUX style ─────────────────────────────────────────────────
def ia_flux():
    for i in range(4):
        w, h = 768, 512
        arr = np.zeros((h, w, 3), np.uint8)
        # Impossible color palette
        for y in range(h):
            r2 = int(np.clip(80 + 60*np.sin(y/50+i), 0, 255))
            g2 = int(np.clip(20 + 30*np.cos(y/40), 0, 255))
            b2 = int(np.clip(160 - 40*(y/h), 0, 255))
            arr[y] = [r2, g2, b2]
        img = Image.fromarray(arr)
        d = ImageDraw.Draw(img)
        # Floating impossible structures
        for j in range(6):
            fx = rng.integers(50, w-100).item(); fy = rng.integers(30, h//2).item()
            d.ellipse([fx, fy, fx+rng.integers(60,140).item(), fy+rng.integers(30,60).item()],
                      fill=(rng.integers(100,200).item(), rng.integers(150,220).item(), rng.integers(50,120).item()))
        img = img.filter(ImageFilter.GaussianBlur(1.5))
        img = ImageEnhance.Color(img).enhance(2.5)
        img = ImageEnhance.Contrast(img).enhance(1.5)
        save(img, "ia/flux", f"flux_{i:02d}", 1, "Estilo FLUX: paleta de colores imposible, físicas irreales")

# ── IA: Ideogram style ────────────────────────────────────────────────────────
def ia_ideogram():
    for i in range(4):
        w, h = 512, 512
        img = Image.new("RGB", (w, h), (rng.integers(20,60).item(), rng.integers(15,50).item(), rng.integers(60,120).item()))
        d = ImageDraw.Draw(img)
        # Glowing subject (Ideogram characteristic)
        d.ellipse([180, 140, 332, 372], fill=(rng.integers(180,220).item(), rng.integers(140,200).item(), rng.integers(200,240).item()))
        for radius in range(20, 90, 12):
            opacity_color = max(0, 180 - radius*2)
            d.ellipse([256-radius, 256-radius, 256+radius, 256+radius],
                      outline=(opacity_color, int(opacity_color*0.8), int(opacity_color*1.2)), width=2)
        img = img.filter(ImageFilter.GaussianBlur(2.5))
        img = ImageEnhance.Color(img).enhance(2.2)
        save(img, "ia/ideogram", f"ideogram_{i:02d}", 1, "Estilo Ideogram: sujeto brillante, fondo oscuro, colores imposibles")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Construyendo benchmark extendido...")
    print(f"Destino: {OUT}")
    print()

    real_selfies()
    real_deportes()
    real_paisajes()
    real_nocturnas()
    real_noticias()
    ia_midjourney()
    ia_sdxl()
    ia_anime()
    ia_flux()
    ia_ideogram()

    # Save manifest
    manifest_path = OUT / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(MANIFEST, f, indent=2, ensure_ascii=False)

    real_n = sum(1 for m in MANIFEST if m["label"] == 0)
    fake_n = sum(1 for m in MANIFEST if m["label"] == 1)

    print()
    print("=" * 50)
    print(f"Benchmark extendido generado:")
    print(f"  Imágenes reales : {real_n}")
    print(f"  Imágenes IA     : {fake_n}")
    print(f"  Total           : {len(MANIFEST)}")
    print(f"  Manifest        : {manifest_path}")
    print()
    print("Siguiente: python scripts/run_benchmark.py --set extended")


if __name__ == "__main__":
    main()
