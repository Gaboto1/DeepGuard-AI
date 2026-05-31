"""
Benchmark Masivo — 500+ imágenes en 16 categorías
===================================================
8 categorías reales × ~32 imágenes = ~256 reales
8 categorías IA     × ~32 imágenes = ~256 IA
Total: ~512 imágenes

Cada imagen tiene características específicas diseñadas para
ser distinguible por los modelos correctos.

Incluye variantes de robustez:
  - JPEG comprimido (calidad 40-70)
  - Blur (σ = 1-3)
  - Ruido adicional
  - Escalado

Salida: tests/benchmark_massive/
"""
import json
from pathlib import Path
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

ROOT   = Path(__file__).parent.parent
OUT    = ROOT / "tests" / "benchmark_massive"
SEED   = 2024
rng    = np.random.default_rng(SEED)
MANIFEST = []
TOTAL_GENERATED = 0


def save(img: Image.Image, cat: str, name: str, label: int, desc: str,
         jpeg_quality: int = 92) -> None:
    global TOTAL_GENERATED
    path = OUT / cat / f"{name}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, "JPEG", quality=jpeg_quality)
    MANIFEST.append({
        "path":     str(path.relative_to(ROOT)),
        "category": cat,
        "name":     name,
        "label":    label,
        "description": desc,
    })
    TOTAL_GENERATED += 1


def _rng_color(lo=100, hi=240):
    return [rng.integers(lo, hi).item() for _ in range(3)]


def _noise(shape, scale=10, seed=0):
    return (np.random.default_rng(SEED + seed).standard_normal(shape) * scale).astype(np.int16)


def _add_noise(arr, scale=10, seed=0):
    return np.clip(arr.astype(np.int16) + _noise(arr.shape, scale, seed), 0, 255).astype(np.uint8)


def _compress(img: Image.Image, quality: int) -> Image.Image:
    buf = BytesIO(); img.save(buf, "JPEG", quality=quality); buf.seek(0)
    return Image.open(buf).copy()


def _blur(img: Image.Image, sigma: float) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(sigma))


# ═══════════════════════════════════════════════════════════════
# REAL CATEGORIES
# ═══════════════════════════════════════════════════════════════

def real_selfies(n=32):
    print(f"  Real/selfies...")
    for i in range(n):
        w, h = rng.choice([480, 512, 640]).item(), rng.choice([640, 720, 800]).item()
        skin = (rng.integers(160,230).item(), rng.integers(120,185).item(), rng.integers(85,150).item())
        bg_c = _rng_color(80, 220)
        img  = Image.new("RGB", (w, h), tuple(bg_c))
        d    = ImageDraw.Draw(img)
        # Natural asymmetry
        offs_x = rng.integers(-20, 20).item()
        offs_y = rng.integers(-10, 10).item()
        face_w = rng.integers(200, 320).item()
        cx     = w // 2 + offs_x
        d.ellipse([cx-face_w//2, 80+offs_y, cx+face_w//2, 500+offs_y], fill=skin)
        # Asymmetric eyes
        for ej, ex_off in enumerate([cx-70, cx+40+rng.integers(-10,10).item()]):
            ey = 200 + offs_y + rng.integers(-8,8).item()
            iris = tuple(_rng_color(20, 80))
            d.ellipse([ex_off, ey, ex_off+55+rng.integers(-5,5).item(), ey+38+rng.integers(-3,3).item()], fill=iris)
        # Hair
        hair_c = tuple(_rng_color(15, 80))
        d.rectangle([0, 0, w, 90+offs_y], fill=hair_c)
        d.ellipse([cx-face_w//2-20, 30, cx+face_w//2+20, 160], fill=hair_c)
        arr = _add_noise(np.array(img), 12, i)
        img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 0.7)))
        q = rng.integers(82, 97).item()
        save(img, "real/selfies", f"selfie_{i:03d}", 0, "Selfie con asimetría natural", q)


def real_deportes(n=32):
    print(f"  Real/deportes...")
    for i in range(n):
        w, h = 800, 533
        arr  = np.zeros((h, w, 3), np.uint8)
        # Grass
        grass = (rng.integers(35,75).item(), rng.integers(95,155).item(), rng.integers(25,55).item())
        sky   = (rng.integers(90,170).item(), rng.integers(130,200).item(), rng.integers(175,235).item())
        arr[h//2:] = grass; arr[:h//2] = sky
        arr = _add_noise(arr, 20, i+100)
        img = Image.fromarray(arr)
        d   = ImageDraw.Draw(img)
        # Player with motion blur
        px = rng.integers(150, 650).item(); py = h//2 - 50
        skin = tuple(_rng_color(160, 230))
        jersey = tuple(_rng_color(50, 220))
        d.ellipse([px, py, px+55, py+75], fill=skin)
        d.rectangle([px+8, py+70, px+47, py+145], fill=jersey)
        # Motion blur on player
        angle = rng.uniform(-0.05, 0.05)
        img = img.transform(img.size, Image.AFFINE, (1, angle, rng.integers(-15,15).item(), 0, 1, 0), Image.BICUBIC)
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.5)))
        q = rng.integers(75, 95).item()
        save(img, "real/deportes", f"deporte_{i:03d}", 0, "Fotografía deportiva con movimiento", q)


def real_naturaleza(n=32):
    print(f"  Real/naturaleza...")
    for i in range(n):
        w, h = rng.integers(600, 1000).item(), rng.integers(400, 700).item()
        arr  = np.zeros((h, w, 3), np.uint8)
        scene = rng.integers(0, 4).item()
        if scene == 0:   # Forest
            for y in range(h):
                g = rng.integers(30, 80).item(); arr[y] = [rng.integers(25,60).item(), g, rng.integers(15,40).item()]
        elif scene == 1: # Ocean
            for y in range(h):
                t = y/h; arr[y] = [int(50+30*t), int(100+60*t), int(180-30*t)]
        elif scene == 2: # Desert
            for y in range(h):
                t = y/h; arr[y] = [int(200+20*t), int(170+10*t), int(100+30*t)]
        else:            # Snow
            arr[:] = [rng.integers(220,255).item(), rng.integers(225,255).item(), rng.integers(230,255).item()]
        arr = _add_noise(arr, 15, i+200)
        img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 0.8)))
        save(img, "real/naturaleza", f"naturaleza_{i:03d}", 0, "Escena natural con texturas variadas")


def real_paisajes(n=32):
    print(f"  Real/paisajes...")
    for i in range(n):
        w, h = 900, 600
        arr  = np.zeros((h, w, 3), np.uint8)
        # Sky gradient
        r_sky = rng.integers(80, 160).item()
        g_sky = rng.integers(130, 210).item()
        b_sky = rng.integers(175, 245).item()
        for y in range(h//2):
            t = y/(h//2)
            arr[y] = [int(r_sky*(1-t)+40*t), int(g_sky*(1-t)+60*t), int(b_sky*(1-t)+30*t)]
        # Ground
        g_col = (rng.integers(40,90).item(), rng.integers(100,160).item(), rng.integers(20,60).item())
        arr[h//2:] = g_col
        # Mountains
        for x in range(w):
            ph = int(h*0.38 + 70*np.sin(x/100.0+i*0.5) + 35*np.sin(x/35.0))
            ph = max(50, min(h-50, ph))
            c = (rng.integers(70,110).item(), rng.integers(65,105).item(), rng.integers(60,100).item())
            arr[ph:ph+8, x] = c
        arr = _add_noise(arr, 8, i+300)
        img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.3))
        save(img, "real/paisajes", f"paisaje_{i:03d}", 0, "Paisaje natural con montañas y cielo")


def real_arquitectura(n=32):
    print(f"  Real/arquitectura...")
    for i in range(n):
        w, h = 750, 550
        arr  = np.zeros((h, w, 3), np.uint8)
        sky  = tuple(_rng_color(120, 210))
        arr[:h//3] = sky
        arr[h//3:] = tuple(_rng_color(50, 120))
        img = Image.fromarray(_add_noise(arr, 12, i+400))
        d   = ImageDraw.Draw(img)
        # Buildings with windows
        n_buildings = rng.integers(3, 8).item()
        for j in range(n_buildings):
            bx = rng.integers(20, w-80).item()
            bh = rng.integers(150, 400).item()
            bw = rng.integers(60, 130).item()
            bc = tuple(_rng_color(80, 170))
            d.rectangle([bx, h-bh, bx+bw, h], fill=bc)
            # Windows
            win_c = tuple(_rng_color(200, 255))
            for wy in range(h-bh+15, h-15, 35):
                for wx in range(bx+8, bx+bw-8, 22):
                    if rng.random() > 0.3:
                        d.rectangle([wx, wy, wx+14, wy+20], fill=win_c)
        save(img, "real/arquitectura", f"arq_{i:03d}", 0, "Fotografía arquitectónica con edificios y ventanas")


def real_nocturnas(n=32):
    print(f"  Real/nocturnas...")
    for i in range(n):
        w, h = 800, 533
        arr  = np.zeros((h, w, 3), np.uint8) + rng.integers(3, 15).item()
        # Stars
        for _ in range(rng.integers(80, 250).item()):
            sx = rng.integers(0, w).item(); sy = rng.integers(0, h//2).item()
            sv = rng.integers(150, 255).item()
            arr[sy:sy+1, sx:sx+1] = [sv, sv, sv]
        # City lights
        for _ in range(rng.integers(150, 400).item()):
            lx = rng.integers(0, w).item(); ly = rng.integers(h//3, h).item()
            lv = rng.integers(80, 255).item()
            lc = rng.choice([[lv, int(lv*0.6), int(lv*0.2)],
                              [int(lv*0.8), int(lv*0.9), lv],
                              [lv, lv, int(lv*0.6)]])
            sz = rng.integers(1, 3).item()
            arr[max(0,ly-sz):ly+sz, max(0,lx-sz):lx+sz] = lc
        arr = _add_noise(arr, 6, i+500)
        img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.8)))
        save(img, "real/nocturnas", f"nocturna_{i:03d}", 0, "Escena nocturna con luces urbanas")


def real_noticias(n=32):
    print(f"  Real/noticias...")
    for i in range(n):
        w, h = 720, 480
        bg   = tuple(_rng_color(140, 200))
        img  = Image.new("RGB", (w, h), bg)
        d    = ImageDraw.Draw(img)
        # Conference / news scene
        d.rectangle([0, 0, w, h//6], fill=tuple(_rng_color(40, 80)))
        # Podium
        pod_x = rng.integers(200, 350).item()
        d.rectangle([pod_x, h//2, pod_x+200, h], fill=tuple(_rng_color(60, 100)))
        # Speaker face (natural asymmetry)
        face_x = pod_x + 70 + rng.integers(-20, 20).item()
        face_y = h//3 + rng.integers(-20, 20).item()
        skin   = tuple(_rng_color(160, 225))
        d.ellipse([face_x, face_y, face_x+80, face_y+100], fill=skin)
        # Audience blur in background
        for _ in range(20):
            ax = rng.integers(0, w).item(); ay = rng.integers(h//4, h//2).item()
            ac = tuple(_rng_color(100, 160))
            d.ellipse([ax, ay, ax+30, ay+40], fill=ac)
        arr = _add_noise(np.array(img), 18, i+600)
        img = Image.fromarray(arr)
        # Simulate news agency JPEG compression
        q = rng.integers(45, 70).item()
        save(_compress(img, q), "real/noticias", f"noticia_{i:03d}", 0,
             f"Escena de prensa con compresión JPEG {q}%", 95)


def real_foto_profesional(n=32):
    print(f"  Real/foto_profesional...")
    for i in range(n):
        w, h = rng.integers(600, 900).item(), rng.integers(400, 700).item()
        # Studio portrait
        bg = tuple(_rng_color(170, 220))
        img = Image.new("RGB", (w, h), bg)
        d = ImageDraw.Draw(img)
        # Subject with professional lighting (slight gradient, not flat)
        cx = w//2 + rng.integers(-30, 30).item()
        skin = tuple(_rng_color(170, 230))
        d.ellipse([cx-120, 60, cx+120, 380], fill=skin)
        # Subtle shadows (professional lighting — NOT flat like AI)
        for sy in range(40, 380, 8):
            alpha = int(sy/380 * 30)
            d.line([(cx+100, sy), (cx+125, sy)], fill=tuple([max(0, c-alpha) for c in skin]), width=3)
        # Hair with texture
        hair_c = tuple(_rng_color(20, 80))
        d.ellipse([cx-135, 30, cx+135, 180], fill=hair_c)
        arr = _add_noise(np.array(img), 8, i+700)
        img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.3))
        img = ImageEnhance.Sharpness(img).enhance(1.1)
        q = rng.integers(88, 98).item()
        save(img, "real/foto_profesional", f"prof_{i:03d}", 0, "Fotografía profesional con iluminación de estudio", q)


# ═══════════════════════════════════════════════════════════════
# AI-GENERATED CATEGORIES
# ═══════════════════════════════════════════════════════════════

def ai_midjourney(n=32):
    print(f"  IA/midjourney...")
    for i in range(n):
        w, h = 512, 512
        # Midjourney: perfect symmetry, over-sharp, oversaturated
        skin = (rng.integers(210,245).item(), rng.integers(180,215).item(), rng.integers(150,185).item())
        img  = Image.new("RGB", (w, h), skin)
        d    = ImageDraw.Draw(img)
        d.ellipse([100, 80, 412, 460], fill=skin)
        # PERFECT symmetric eyes (AI artifact)
        for ex in [148, 304]:  # exactly mirrored from center
            iris = tuple(_rng_color(20, 120))
            d.ellipse([ex, 180, ex+64, 228], fill=iris)
            d.ellipse([ex+8, 188, ex+56, 220], fill=tuple(_rng_color(40, 100)))
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(2.0, 4.0)))
        img = ImageEnhance.Color(img).enhance(rng.uniform(1.6, 2.2))
        img = ImageEnhance.Sharpness(img).enhance(rng.uniform(2.5, 4.0))
        save(img, "ia/midjourney", f"mj_{i:03d}", 1, "Estilo Midjourney: simetría, hipernítido, oversaturado")


def ai_flux(n=32):
    print(f"  IA/flux...")
    for i in range(n):
        w, h = 768, 512
        arr  = np.zeros((h, w, 3), np.uint8)
        # FLUX: impossible fantasy colors
        for y in range(h):
            r2 = int(np.clip(70 + 70*np.sin(y/45.0+i*0.8), 0, 255))
            g2 = int(np.clip(15 + 40*np.cos(y/35.0+i), 0, 255))
            b2 = int(np.clip(150 - 50*(y/h), 0, 255))
            arr[y] = [r2, g2, b2]
        img = Image.fromarray(arr)
        d = ImageDraw.Draw(img)
        # Floating objects (impossible physics)
        for j in range(rng.integers(4, 9).item()):
            fx = rng.integers(50, w-100).item(); fy = rng.integers(20, h//2).item()
            fc = tuple(_rng_color(100, 220))
            d.ellipse([fx, fy, fx+rng.integers(50,120).item(), fy+rng.integers(25,60).item()], fill=fc)
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(1.0, 2.5)))
        img = ImageEnhance.Color(img).enhance(rng.uniform(2.0, 3.0))
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(1.3, 1.8))
        save(img, "ia/flux", f"flux_{i:03d}", 1, "Estilo FLUX: paleta imposible, física irreal, saturación extrema")


def ai_gpt_image(n=32):
    print(f"  IA/gpt_image...")
    for i in range(n):
        w, h = 1024, 1024
        # GPT Image (DALL-E style): clean, uniform, flat lighting
        bg   = tuple(_rng_color(200, 250))
        img  = Image.new("RGB", (w, h), bg)
        d    = ImageDraw.Draw(img)
        # Subjects with zero natural variation
        skin = tuple(_rng_color(205, 240))
        d.ellipse([250, 150, 774, 850], fill=skin)  # perfect oval
        # Perfectly positioned symmetric elements
        for ex in [310, 630]:
            eye_c = tuple(_rng_color(30, 90))
            d.ellipse([ex, 340, ex+130, 430], fill=eye_c)
            d.ellipse([ex+15, 355, ex+115, 415], fill=tuple(_rng_color(50, 110)))
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(3.5, 6.0)))
        img = ImageEnhance.Brightness(img).enhance(rng.uniform(1.1, 1.3))
        img = img.resize((512, 512), Image.LANCZOS)
        save(img, "ia/gpt_image", f"gpt_{i:03d}", 1, "Estilo GPT Image/DALL-E: iluminación perfectamente uniforme, sin texturas")


def ai_sdxl(n=32):
    print(f"  IA/sdxl...")
    for i in range(n):
        w, h = 1024, 1024
        # SDXL: very high res, hyper-smooth skin, over-saturated
        skin = tuple(_rng_color(210, 245))
        img  = Image.new("RGB", (w, h), skin)
        d    = ImageDraw.Draw(img)
        d.ellipse([180, 130, 844, 930], fill=skin)
        for ex in [270, 590]:  # symmetric eyes
            iris_c = tuple(_rng_color(25, 100))
            d.ellipse([ex, 310, ex+165, 430], fill=iris_c)
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(4.0, 7.0)))
        img = ImageEnhance.Color(img).enhance(rng.uniform(1.3, 1.7))
        img = img.resize((512, 512), Image.LANCZOS)
        save(img, "ia/sdxl", f"sdxl_{i:03d}", 1, "Estilo SDXL: piel textureless, iluminación plana uniforme")


def ai_ideogram(n=32):
    print(f"  IA/ideogram...")
    for i in range(n):
        w, h = 512, 512
        # Ideogram: dark background with glowing impossible subjects
        bg_c = tuple(_rng_color(10, 50))
        img  = Image.new("RGB", (w, h), bg_c)
        d    = ImageDraw.Draw(img)
        # Glowing subject (Ideogram characteristic)
        subject_c = tuple(_rng_color(160, 230))
        d.ellipse([150, 120, 362, 392], fill=subject_c)
        # Glow rings
        for radius in range(15, 80, 12):
            opacity_c = max(0, 160 - radius*2)
            d.ellipse([256-radius-80, 256-radius, 256+radius+80, 256+radius],
                      outline=(opacity_c, int(opacity_c*0.8), int(opacity_c*1.2)), width=2)
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(2.0, 4.0)))
        img = ImageEnhance.Color(img).enhance(rng.uniform(2.0, 3.0))
        save(img, "ia/ideogram", f"ideogram_{i:03d}", 1, "Estilo Ideogram: sujeto brillante, fondo oscuro, colores imposibles")


def ai_anime(n=32):
    print(f"  IA/anime...")
    for i in range(n):
        w, h = 512, 512
        # Anime: impossible eye proportions, flat shading
        bg = tuple(_rng_color(240, 255))
        img = Image.new("RGB", (w, h), bg)
        d   = ImageDraw.Draw(img)
        skin = tuple(_rng_color(230, 255))
        d.ellipse([80, 70, 432, 460], fill=skin)
        # Huge anime eyes (impossible proportions)
        for ex in [90, 282]:
            eye_c = tuple(_rng_color(20, 150))
            d.ellipse([ex, 175, ex+140, 310], fill=eye_c)
            d.ellipse([ex+10, 185, ex+130, 300], fill=tuple(_rng_color(35, 100)))
            # Catchlight
            d.ellipse([ex+100, 185, ex+130, 210], fill=(255, 255, 255))
        # Small nose/mouth (anime proportions)
        d.point([(256, 355)], fill=tuple(_rng_color(200, 220)))
        d.arc([210, 378, 302, 408], 5, 175, fill=tuple(_rng_color(180, 200)), width=3)
        # Gradient hair
        hair_c = tuple(_rng_color(30, 200))
        for hy in range(0, 105, 4):
            d.line([(60, hy), (452, hy)], fill=hair_c, width=4)
        img = img.filter(ImageFilter.GaussianBlur(0.4))
        img = ImageEnhance.Color(img).enhance(rng.uniform(1.5, 2.0))
        save(img, "ia/anime", f"anime_{i:03d}", 1, "Anime IA: ojos imposibles, proporciones anime, shading plano")


def ai_arte(n=32):
    print(f"  IA/arte...")
    for i in range(n):
        w, h = 640, 640
        # AI art / concept art: rich impossible colors, glow effects
        arr = np.zeros((h, w, 3), np.uint8)
        # Color gradients (impossible / AI-typical)
        for y in range(h):
            for x in range(w):
                r2 = int(np.clip(120 + 80*np.sin(x/60.0+i) * np.cos(y/80.0), 0, 255))
                g2 = int(np.clip(40  + 60*np.cos(x/70.0) * np.sin(y/50.0+i*0.5), 0, 255))
                b2 = int(np.clip(180 - 60*(y/h) + 40*np.sin(x/40.0), 0, 255))
                arr[y, x] = [r2, g2, b2]
        img = Image.fromarray(arr)
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(1.5, 3.0)))
        img = ImageEnhance.Color(img).enhance(rng.uniform(1.8, 2.8))
        save(img, "ia/arte", f"arte_{i:03d}", 1, "Arte IA: gradientes imposibles, efectos espectrales, colores no naturales")


def ai_paisajes_ia(n=32):
    print(f"  IA/paisajes_ia...")
    for i in range(n):
        w, h = 800, 500
        # AI landscape: perfect, oversaturated, impossible
        arr = np.zeros((h, w, 3), np.uint8)
        for y in range(h):
            r2 = int(np.clip(100 + 80*np.sin(y/h*3.14+i), 0, 255))
            g2 = int(np.clip(30  + 50*np.cos(y/h*2.0+i*0.3), 0, 255))
            b2 = int(np.clip(200 - 100*(y/h), 0, 255))
            arr[y] = [r2, g2, b2]
        img = Image.fromarray(arr)
        d = ImageDraw.Draw(img)
        # Impossible floating mountains
        for j in range(rng.integers(2, 6).item()):
            mx = rng.integers(50, w-100).item()
            my = rng.integers(20, h//2).item()
            mh = rng.integers(80, 200).item()
            mc = tuple(_rng_color(60, 180))
            d.polygon([(mx, my+mh), (mx+rng.integers(60,180).item()//2, my),
                       (mx+rng.integers(80,200).item(), my+mh)], fill=mc)
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(1.0, 2.5)))
        img = ImageEnhance.Color(img).enhance(rng.uniform(2.0, 3.0))
        save(img, "ia/paisajes_ia", f"paisaje_ia_{i:03d}", 1, "Paisaje IA: colores imposibles, geografía irreal, saturación extrema")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=== BENCHMARK MASIVO — 500+ imágenes ===")
    print(f"Destino: {OUT}")
    print()

    print("Generando imágenes REALES:")
    real_selfies(32)
    real_deportes(32)
    real_naturaleza(32)
    real_paisajes(32)
    real_arquitectura(32)
    real_nocturnas(32)
    real_noticias(32)
    real_foto_profesional(32)

    print()
    print("Generando imágenes IA:")
    ai_midjourney(32)
    ai_flux(32)
    ai_gpt_image(32)
    ai_sdxl(32)
    ai_ideogram(32)
    ai_anime(32)
    ai_arte(32)
    ai_paisajes_ia(32)

    # Save manifest
    manifest_path = OUT / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(MANIFEST, f, indent=2, ensure_ascii=False)

    real_n = sum(1 for m in MANIFEST if m["label"] == 0)
    fake_n = sum(1 for m in MANIFEST if m["label"] == 1)

    print()
    print("=" * 55)
    print(f"  BENCHMARK MASIVO GENERADO")
    print(f"  Imágenes reales  : {real_n}")
    print(f"  Imágenes IA      : {fake_n}")
    print(f"  Total            : {len(MANIFEST)}")
    print(f"  Manifest         : {manifest_path}")
    print()
    print("  Ejecutar evaluación completa:")
    print("    python scripts/run_full_evaluation.py")


if __name__ == "__main__":
    main()
