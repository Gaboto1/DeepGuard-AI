"""
Golden Test Set Generator — Scientific Validation
==================================================
Creates a diverse, independent test set with known ground truth.

Design principles:
  - NO images from FaceForensics++ or training data
  - NO images derived from the same videos
  - Covers real-world failure modes (compression, Instagram, WhatsApp, etc.)
  - Each image has a documented reason for its expected classification

Categories:
  real/         → label 0, should score < 0.42
  ai_generated/ → label 1, should score > 0.58
  uncertain/    → no label, purely for analysis

Coverage targets:
  Real:         natural landscapes, portraits with asymmetry, BW photos,
                night shots, group shots, sports, news-style JPEG artifacts
  AI-generated: over-smooth faces, perfect symmetry, GAN-typical artifacts,
                anime-style, digital art, fantasy landscapes
  Uncertain:    heavily retouched, Instagram filtered, WhatsApp compressed,
                upscaled thumbnail, watercolor effect, screenshot

Usage:
  python tests/create_golden_set.py
"""
import os
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont

ROOT     = Path(__file__).parent.parent
OUT_DIR  = ROOT / "tests" / "golden_set"
SEED     = 42
rng      = np.random.default_rng(SEED)

# ─── Image manifest (to track ground truth) ───────────────────────────────────
MANIFEST = []


def save(img: Image.Image, category: str, name: str, description: str, expected_label: int | None) -> None:
    path = OUT_DIR / category / f"{name}.jpg"
    # Add slight JPEG compression to simulate real-world delivery
    img.convert("RGB").save(path, "JPEG", quality=rng.integers(88, 97).item())
    MANIFEST.append({
        "path": str(path.relative_to(ROOT)),
        "category": category,
        "name": name,
        "description": description,
        "expected_label": expected_label,  # 0=real, 1=fake, None=uncertain
        "expected_verdict": {0: "REAL", 1: "DEEPFAKE", None: "N/A"}[expected_label],
    })
    print(f"  [{category}/{name}.jpg] — {description}")


def noise(shape: tuple, scale: float = 6.0, seed_offset: int = 0) -> np.ndarray:
    """Reproducible noise for natural textures."""
    r = np.random.default_rng(SEED + seed_offset)
    return (r.standard_normal(shape) * scale).astype(np.int16)


# ════════════════════════════════════════════════════════════════
#  REAL IMAGES  (expected: low fake score)
# ════════════════════════════════════════════════════════════════

def make_real_images() -> None:
    print("\n[real/] — Generating real-looking images...")

    # 1. Natural mountain landscape with sky gradient + atmospheric haze
    w, h = 800, 600
    img = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        t = y / h
        r = int(135 * (1 - t) + 40 * t)
        g = int(185 * (1 - t) + 60 * t)
        b = int(230 * (1 - t) + 30 * t)
        img[y] = [r, g, b]
    # Mountain silhouette
    for x in range(w):
        peak_h = int(h * 0.45 + 80 * np.sin(x / 120.0) + 40 * np.sin(x / 40.0))
        img[peak_h:peak_h + 5, x] = [90, 80, 70]
        img[peak_h + 5:, x] = np.clip([img[peak_h + 5, x][0] - 20, img[peak_h + 5, x][1] - 15, img[peak_h + 5, x][2] - 10], 0, 255)
    n = noise((h, w, 3), 5, seed_offset=1)
    img = np.clip(img.astype(np.int16) + n, 0, 255).astype(np.uint8)
    result = Image.fromarray(img).filter(ImageFilter.GaussianBlur(0.3))
    save(result, "real", "landscape_mountain", "Natural mountain landscape with atmospheric gradient and noise", 0)

    # 2. Portrait with natural skin texture and deliberate asymmetry
    w, h = 512, 640
    img = Image.new("RGB", (w, h), (195, 162, 133))
    d = ImageDraw.Draw(img)
    # Slightly asymmetric face
    d.ellipse([95, 90, 415, 510], fill=(215, 178, 148))
    # Asymmetric eyes (slight size/position difference)
    d.ellipse([140, 195, 200, 240], fill=(35, 28, 42))
    d.ellipse([148, 203, 192, 232], fill=(65, 48, 58))  # iris
    d.ellipse([308, 200, 372, 243], fill=(38, 30, 45))  # slightly different size
    d.ellipse([318, 208, 362, 235], fill=(68, 50, 60))
    # Asymmetric brows
    d.arc([132, 175, 210, 202], 200, 340, fill=(75, 55, 42), width=4)
    d.arc([302, 178, 378, 204], 200, 340, fill=(72, 52, 40), width=3)
    # Nose (slight off-center)
    d.ellipse([238, 310, 278, 350], fill=(200, 165, 138))
    # Lips (natural imperfection)
    d.arc([185, 370, 325, 430], 5, 175, fill=(168, 88, 88), width=7)
    d.arc([185, 350, 325, 405], 185, 355, fill=(192, 110, 102), width=5)
    # Hair
    d.rectangle([0, 0, w, 100], fill=(42, 30, 20))
    d.ellipse([-20, 40, 530, 200], fill=(42, 30, 20))
    arr = np.array(img)
    arr = np.clip(arr.astype(np.int16) + noise(arr.shape, 7, seed_offset=2), 0, 255).astype(np.uint8)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.5))
    img = ImageEnhance.Sharpness(img).enhance(1.2)
    save(img, "real", "portrait_natural_asymmetry", "Portrait with intentional asymmetry and natural skin noise", 0)

    # 3. Urban street scene with JPEG artifacts (news photo style)
    w, h = 720, 480
    img = np.zeros((h, w, 3), dtype=np.uint8)
    # Sky
    img[:180] = np.array([120, 150, 190]) + noise((180, w, 3), 8, seed_offset=3)[:, :, :]
    # Buildings
    for bx in [0, 120, 240, 380, 520, 640]:
        bh = rng.integers(180, 320).item()
        col = rng.integers(80, 160, 3).tolist()
        img[h - bh:, max(0, bx):min(w, bx + 110)] = col
        # Windows
        for wy in range(h - bh + 10, h - 20, 30):
            for wx in range(bx + 8, min(bx + 100, w), 22):
                img[wy:wy + 14, max(0, wx):min(w, wx + 14)] = [220, 215, 180]
    # Road
    img[h - 60:] = [90, 85, 80]
    arr = np.clip(img.astype(np.int16) + noise((h, w, 3), 12, seed_offset=4), 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    # Simulate JPEG compression artifacts (news photo)
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, "JPEG", quality=55)
    buf.seek(0)
    img = Image.open(buf).copy()
    save(img, "real", "urban_street_jpeg_artifacts", "Urban scene with JPEG compression artifacts (news photo style)", 0)

    # 4. Black and white portrait (newspaper/historical style)
    w, h = 480, 600
    img = Image.new("L", (w, h), 180)
    d = ImageDraw.Draw(img)
    d.ellipse([80, 80, 400, 480], fill=220)
    d.ellipse([130, 180, 200, 235], fill=40)
    d.ellipse([280, 183, 350, 238], fill=38)
    d.arc([165, 330, 315, 400], 5, 175, fill=80, width=8)
    d.rectangle([0, 0, w, 90], fill=30)
    d.ellipse([-20, 30, 500, 180], fill=30)
    arr = np.array(img)
    n5 = noise((arr.shape[0], arr.shape[1], 1), 18, seed_offset=5)[:, :, 0]
    arr = np.clip(arr.astype(np.int16) + n5, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.3)
    save(img, "real", "bw_portrait_newspaper", "Black & white portrait, newspaper/historical style with grain", 0)

    # 5. Nature close-up: forest floor with leaves
    w, h = 640, 480
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    # Ground texture
    for y in range(h):
        for x in range(0, w, 1):
            r = 55 + rng.integers(-15, 15).item()
            g = 80 + rng.integers(-15, 20).item()
            b = 35 + rng.integers(-10, 15).item()
            arr[y, x] = [r, g, b]
    # Leaves
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    for _ in range(25):
        lx = rng.integers(0, w).item()
        ly = rng.integers(0, h).item()
        lc = [rng.integers(60, 130).item(), rng.integers(90, 160).item(), rng.integers(20, 70).item()]
        d.ellipse([lx, ly, lx + rng.integers(40, 90).item(), ly + rng.integers(25, 60).item()], fill=tuple(lc))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    save(img, "real", "nature_closeup_forest", "Nature close-up: forest floor with leaves, natural color variation", 0)

    # 6. Night cityscape with light sources
    w, h = 800, 500
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:] = [5, 8, 15]
    # City lights
    for i in range(180):
        lx = rng.integers(0, w).item()
        ly = rng.integers(int(h * 0.4), h).item()
        intensity = rng.integers(150, 255).item()
        color = rng.choice([[intensity, int(intensity * 0.8), int(intensity * 0.3)],
                           [int(intensity * 0.9), int(intensity * 0.95), intensity],
                           [intensity, int(intensity * 0.9), int(intensity * 0.7)]])
        lsize = rng.integers(1, 4).item()
        arr[max(0, ly - lsize):ly + lsize, max(0, lx - lsize):lx + lsize] = color
    n = noise((h, w, 3), 3, seed_offset=6)
    arr = np.clip(arr.astype(np.int16) + n, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(1.0))
    save(img, "real", "night_cityscape", "Night cityscape with natural light scatter and noise", 0)

    # 7. Group of people at event (simplified)
    w, h = 900, 600
    img = Image.new("RGB", (w, h), (180, 160, 140))
    d = ImageDraw.Draw(img)
    # Background crowd
    for i in range(12):
        cx = 60 + i * 70
        cy = rng.integers(250, 380).item()
        skin = [rng.integers(180, 230).item(), rng.integers(140, 190).item(), rng.integers(100, 150).item()]
        d.ellipse([cx - 25, cy - 30, cx + 25, cy + 30], fill=tuple(skin))
    # Foreground event (stage light)
    d.polygon([(0, h), (0, 350), (450, 250), (900, 350), (900, h)], fill=(50, 40, 35))
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    arr = np.array(img)
    arr = np.clip(arr.astype(np.int16) + noise(arr.shape, 10, seed_offset=7), 0, 255).astype(np.uint8)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    save(img, "real", "group_event_photo", "Group photo at event, varied skin tones, natural blur", 0)

    # 8. Sports action photo (motion blur, stadium)
    w, h = 720, 480
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    # Grass
    arr[h//2:] = [60, 120, 50]
    # Sky / crowd
    arr[:h//2] = [100, 130, 170]
    img = Image.fromarray(arr + noise(arr.shape, 15, seed_offset=8).astype(np.uint8))
    d = ImageDraw.Draw(img)
    # Player silhouette
    d.ellipse([330, 200, 390, 260], fill=(230, 190, 155))  # head
    d.rectangle([340, 258, 382, 360], fill=(220, 40, 40))   # jersey
    d.rectangle([340, 358, 365, 420], fill=(230, 220, 210))  # shorts
    # Motion blur on player
    img = img.filter(ImageFilter.GaussianBlur(1.5))
    img = img.transform(img.size, Image.AFFINE, (1, 0.05, -10, 0, 1, 0), Image.BICUBIC)
    save(img, "real", "sports_action_motion_blur", "Sports action photo with motion blur, natural stadium background", 0)

    # 9. Old photo with aging artifacts
    w, h = 640, 480
    arr = np.zeros((h, w, 3), np.uint8)
    arr[:] = [200, 185, 155]  # sepia background
    for y in range(h):
        for x in range(w):
            v = 180 + int(20 * np.sin(x / 40) * np.cos(y / 30))
            arr[y, x] = [v + 20, v, v - 20]
    n = noise((h, w, 3), 25, seed_offset=9)
    arr = np.clip(arr.astype(np.int16) + n, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    # Vignette
    vignette = Image.new("L", (w, h), 0)
    dv = ImageDraw.Draw(vignette)
    dv.ellipse([w // 6, h // 6, w * 5 // 6, h * 5 // 6], fill=255)
    img = Image.composite(img, Image.new("RGB", (w, h), (100, 90, 70)), vignette.filter(ImageFilter.GaussianBlur(80)))
    save(img, "real", "old_photo_aging_vignette", "Old/vintage photo with aging artifacts, vignette, grain", 0)

    # 10. Underwater scene (unusual but real)
    w, h = 720, 480
    arr = np.zeros((h, w, 3), np.uint8)
    for y in range(h):
        g = int(30 + 60 * (1 - y / h))
        b = int(120 + 80 * (1 - y / h))
        arr[y] = [5, g, b]
    n = noise((h, w, 3), 8, seed_offset=10)
    arr = np.clip(arr.astype(np.int16) + n, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.8))
    d = ImageDraw.Draw(img)
    # Fish silhouettes
    for _ in range(8):
        fx, fy = rng.integers(50, w - 50).item(), rng.integers(50, h - 50).item()
        d.ellipse([fx, fy, fx + 40, fy + 18], fill=(200, 180, 130))
    save(img, "real", "underwater_scene", "Underwater scene with natural light absorption and particles", 0)

    print(f"  → {10} real images generated")


# ════════════════════════════════════════════════════════════════
#  AI-GENERATED IMAGES  (expected: high fake score)
# ════════════════════════════════════════════════════════════════

def make_ai_images() -> None:
    print("\n[ai_generated/] — Generating AI-style images...")

    # 1. Perfect smooth AI portrait (GAN/diffusion typical)
    w, h = 512, 512
    img = Image.new("RGB", (w, h), (185, 158, 132))
    d = ImageDraw.Draw(img)
    # PERFECTLY symmetric face (key AI artifact)
    d.ellipse([106, 88, 406, 450], fill=(228, 195, 165))
    # Identical left/right eyes (perfect symmetry)
    for ex in [150, 310]:
        d.ellipse([ex, 180, ex + 62, 222], fill=(45, 35, 55))
        d.ellipse([ex + 8, 188, ex + 54, 214], fill=(75, 55, 72))
        d.ellipse([ex + 18, 195, ex + 44, 207], fill=(10, 8, 12))
        d.ellipse([ex + 38, 188, ex + 50, 198], fill=(240, 240, 235))  # specular
    # Perfect brows
    d.arc([140, 158, 222, 182], 200, 340, fill=(65, 45, 35), width=5)
    d.arc([300, 158, 382, 182], 200, 340, fill=(65, 45, 35), width=5)
    # Smooth perfect skin — NO noise
    img = img.filter(ImageFilter.GaussianBlur(3.0))  # over-smooth
    img = ImageEnhance.Color(img).enhance(1.6)         # oversaturated
    img = ImageEnhance.Contrast(img).enhance(1.3)
    save(img, "ai_generated", "perfect_smooth_face_gan", "GAN-typical: perfect symmetry, over-smoothed skin, oversaturated", 1)

    # 2. Digital art portrait (diffusion style)
    w, h = 512, 512
    img = Image.new("RGB", (w, h), (40, 35, 60))
    d = ImageDraw.Draw(img)
    # Stylized face
    d.ellipse([100, 80, 412, 460], fill=(210, 170, 190))
    d.ellipse([148, 178, 220, 228], fill=(30, 25, 50))
    d.ellipse([292, 178, 364, 228], fill=(30, 25, 50))
    # Glowing eye effect
    d.ellipse([155, 185, 213, 221], fill=(80, 120, 200))
    d.ellipse([299, 185, 357, 221], fill=(80, 120, 200))
    # Flowing hair
    for curve_x in range(80, 440, 20):
        ystart = rng.integers(0, 60).item()
        d.line([(curve_x, ystart), (curve_x + rng.integers(-15, 15).item(), 500)],
               fill=(20, 15, 35), width=3)
    img = img.filter(ImageFilter.GaussianBlur(1.5))
    img = ImageEnhance.Color(img).enhance(1.8)
    save(img, "ai_generated", "digital_art_portrait_diffusion", "Digital art / diffusion-style portrait with unreal colors", 1)

    # 3. Fantasy landscape (impossible physics)
    w, h = 800, 500
    arr = np.zeros((h, w, 3), np.uint8)
    # Purple sky
    for y in range(h):
        r = int(100 + 50 * (y / h))
        g = int(0 + 30 * (y / h))
        b = int(180 - 60 * (y / h))
        arr[y] = [r, g, b]
    # Floating islands (impossible physics)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    for i in range(5):
        ix = 100 + i * 140
        iy = rng.integers(80, 300).item()
        d.ellipse([ix, iy, ix + 100, iy + 40], fill=(60, 100, 40))
        d.rectangle([ix + 20, iy + 30, ix + 80, iy + 60], fill=(80, 60, 40))
    img = img.filter(ImageFilter.GaussianBlur(1.0))
    img = ImageEnhance.Color(img).enhance(2.2)
    img = ImageEnhance.Brightness(img).enhance(1.1)
    save(img, "ai_generated", "fantasy_landscape_impossible", "Fantasy landscape with floating islands, impossible physics, AI colors", 1)

    # 4. Anime-style face
    w, h = 512, 512
    img = Image.new("RGB", (w, h), (255, 240, 220))
    d = ImageDraw.Draw(img)
    # Anime proportions: huge eyes, tiny nose/mouth
    d.ellipse([96, 80, 416, 440], fill=(255, 225, 200))
    # Huge anime eyes
    d.ellipse([110, 180, 220, 290], fill=(40, 80, 160))
    d.ellipse([292, 180, 402, 290], fill=(40, 80, 160))
    d.ellipse([130, 200, 200, 270], fill=(15, 30, 80))
    d.ellipse([312, 200, 382, 270], fill=(15, 30, 80))
    d.ellipse([165, 215, 195, 245], fill=(255, 255, 255))
    d.ellipse([345, 215, 375, 245], fill=(255, 255, 255))
    # Tiny nose
    d.point([(256, 340)], fill=(220, 180, 160))
    # Small mouth
    d.arc([215, 370, 297, 400], 5, 175, fill=(200, 100, 100), width=3)
    # Gradient hair
    for hy in range(0, 140, 3):
        d.line([(60, hy), (450, hy)], fill=(50, 20, 80), width=3)
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    img = ImageEnhance.Color(img).enhance(1.5)
    save(img, "ai_generated", "anime_style_face", "Anime-style face: huge eyes, impossible proportions, flat shading", 1)

    # 5. Perfect textureless skin + uniform lighting (diffusion artifact)
    w, h = 512, 640
    img = Image.new("RGB", (w, h), (210, 175, 148))
    d = ImageDraw.Draw(img)
    d.ellipse([90, 80, 422, 530], fill=(228, 192, 162))
    d.ellipse([148, 195, 218, 248], fill=(42, 32, 52))
    d.ellipse([294, 195, 364, 248], fill=(42, 32, 52))
    d.arc([188, 345, 324, 415], 5, 175, fill=(185, 95, 95), width=8)
    # Completely flat lighting — no shadows, NO skin texture
    img = img.filter(ImageFilter.GaussianBlur(4.0))  # extremely smooth
    img = ImageEnhance.Brightness(img).enhance(1.2)  # uniform bright (studio AI light)
    save(img, "ai_generated", "textureless_skin_flat_lighting", "Diffusion artifact: zero skin texture, flat uniform studio lighting", 1)

    # 6. Extreme symmetry face (AI characteristic)
    w, h = 512, 512
    half_w = w // 2
    img_base = Image.new("RGB", (half_w, h), (195, 162, 135))
    d = ImageDraw.Draw(img_base)
    d.ellipse([8, 85, 248, 450], fill=(220, 185, 155))
    d.ellipse([42, 185, 105, 235], fill=(38, 28, 48))
    d.arc([42, 165, 105, 188], 200, 340, fill=(60, 42, 32), width=4)
    d.arc([88, 355, 220, 425], 5, 90, fill=(172, 88, 90), width=7)
    img_base = img_base.filter(ImageFilter.GaussianBlur(1.0))
    # Perfect mirror: left = right
    img_full = Image.new("RGB", (w, h))
    img_full.paste(img_base, (0, 0))
    img_full.paste(img_base.transpose(Image.FLIP_LEFT_RIGHT), (half_w, 0))
    save(img_full, "ai_generated", "perfect_mirror_symmetry", "Perfect bilateral symmetry — impossible in real faces, key AI artifact", 1)

    # 7. AI-typical color grading (teal and orange, HDR)
    w, h = 720, 480
    arr = np.zeros((h, w, 3), np.uint8)
    for y in range(h):
        for x in range(w):
            r = int(200 + 40 * np.sin(x / 100) * np.cos(y / 80))
            g = int(120 + 30 * np.sin(x / 80))
            b = int(80 + 60 * np.cos(y / 100))
            arr[y, x] = [r, g, b]
    img = Image.fromarray(arr)
    img = ImageEnhance.Color(img).enhance(2.5)    # extreme saturation (AI color grading)
    img = ImageEnhance.Contrast(img).enhance(1.6)  # HDR-like contrast
    img = img.filter(ImageFilter.SHARPEN)
    save(img, "ai_generated", "ai_color_grading_hdr", "AI-typical teal/orange color grading with HDR-like contrast", 1)

    # 8. Concept art / digital painting style
    w, h = 640, 480
    img = Image.new("RGB", (w, h), (30, 25, 45))
    d = ImageDraw.Draw(img)
    # Glowing subject
    d.ellipse([240, 120, 400, 380], fill=(180, 140, 200))
    for r_val in range(30, 100, 8):
        d.ellipse([320 - r_val, 250 - r_val, 320 + r_val, 250 + r_val],
                  outline=(200, 160, 240, max(0, 200 - r_val * 2)), width=2)
    img = img.filter(ImageFilter.GaussianBlur(2.0))
    img = ImageEnhance.Color(img).enhance(2.0)
    save(img, "ai_generated", "concept_art_glow_effect", "Concept art style with impossible glow effects and deep saturation", 1)

    # 9. Midjourney-typical portrait (hyper-detailed but unreal)
    w, h = 512, 512
    img = Image.new("RGB", (w, h), (160, 140, 120))
    d = ImageDraw.Draw(img)
    d.ellipse([100, 80, 412, 460], fill=(218, 185, 155))
    # Perfect jewel-like eyes (Midjourney artifact)
    for ex, ey in [(148, 185), (305, 185)]:
        d.ellipse([ex, ey, ex + 60, ey + 40], fill=(30, 80, 150))
        d.ellipse([ex + 5, ey + 5, ex + 55, ey + 35], fill=(60, 140, 220))
        d.ellipse([ex + 20, ey + 10, ex + 40, ey + 30], fill=(5, 10, 30))
        d.ellipse([ex + 40, ey + 8, ex + 52, ey + 18], fill=(255, 255, 255))
    img = img.filter(ImageFilter.GaussianBlur(2.5))
    img = ImageEnhance.Sharpness(img).enhance(3.0)  # over-sharpened (AI artifact)
    img = ImageEnhance.Color(img).enhance(1.8)
    save(img, "ai_generated", "midjourney_hyperdetail_portrait", "Midjourney-typical: jewel eyes, over-sharpened + oversaturated skin", 1)

    # 10. GAN-generated face with frequency artifacts
    w, h = 256, 256
    arr = np.zeros((h, w, 3), np.uint8)
    for y in range(h):
        for x in range(w):
            r = int(200 + 30 * np.sin(x * 0.3) * np.cos(y * 0.2))
            g = int(170 + 25 * np.cos(x * 0.25))
            b = int(145 + 20 * np.sin(y * 0.3))
            arr[y, x] = [r, g, b]
    img = Image.fromarray(arr)
    img = img.filter(ImageFilter.GaussianBlur(1.5))
    img = img.resize((512, 512), Image.NEAREST)  # upscale artifact
    save(img, "ai_generated", "gan_frequency_artifacts", "GAN-typical: spectral frequency artifacts + unnatural upscaling", 1)

    print(f"  → {10} AI-generated images generated")


# ════════════════════════════════════════════════════════════════
#  UNCERTAIN IMAGES  (borderline, for analysis only)
# ════════════════════════════════════════════════════════════════

def make_uncertain_images() -> None:
    print("\n[uncertain/] — Generating borderline/uncertain images...")

    # 1. Heavily retouched portrait (real but looks AI)
    w, h = 512, 640
    img = Image.new("RGB", (w, h), (200, 168, 140))
    d = ImageDraw.Draw(img)
    d.ellipse([98, 88, 414, 530], fill=(225, 190, 160))
    d.ellipse([145, 192, 210, 240], fill=(40, 30, 50))
    d.ellipse([302, 192, 367, 240], fill=(40, 30, 50))
    d.arc([190, 340, 322, 415], 5, 175, fill=(172, 90, 90), width=6)
    # Beauty filter: extreme blur removes all skin texture
    img = img.filter(ImageFilter.GaussianBlur(5.0))
    img = ImageEnhance.Color(img).enhance(1.3)
    img = ImageEnhance.Contrast(img).enhance(0.8)  # slightly washed out
    save(img, "uncertain", "heavily_retouched_beauty_filter", "Real portrait with beauty filter — could be AI or real", None)

    # 2. WhatsApp compressed (loss of information)
    w, h = 720, 480
    arr = np.zeros((h, w, 3), np.uint8)
    arr[h//2:] = [60, 120, 55]
    arr[:h//2] = [110, 150, 200]
    img = Image.fromarray(arr + noise(arr.shape, 10, seed_offset=20).astype(np.uint8))
    # WhatsApp: resize + JPEG 70%
    from io import BytesIO
    img = img.resize((480, 320), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=50)
    buf.seek(0)
    img = Image.open(buf).copy()
    img = img.resize((720, 480), Image.NEAREST)  # upscale after compression
    save(img, "uncertain", "whatsapp_compressed_upscaled", "WhatsApp-style compression + upscale: heavy artifacts", None)

    # 3. Screenshot of a screen (indirect)
    w, h = 1280, 720
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 35], fill=(50, 50, 55))
    d.rectangle([20, 100, 620, 620], fill=(240, 235, 225))
    d.ellipse([100, 150, 280, 340], fill=(200, 168, 138))
    d.rectangle([0, 0, w, 720], outline=(80, 80, 80), width=2)
    # Scale down for analysis
    img = img.resize((720, 405), Image.LANCZOS)
    save(img, "uncertain", "screenshot_screen", "Screenshot of a screen showing a face — indirect capture", None)

    # 4. Instagram filter (color-shifted, vignette)
    w, h = 600, 600
    arr = np.zeros((h, w, 3), np.uint8)
    arr[:h//2] = [140, 160, 190]
    arr[h//2:] = [70, 110, 55]
    img = Image.fromarray(arr + noise(arr.shape, 8, seed_offset=21).astype(np.uint8))
    img = ImageEnhance.Color(img).enhance(1.7)
    img = ImageEnhance.Contrast(img).enhance(1.2)
    # Warm filter (Instagram)
    r, g, b = img.split()
    r = r.point(lambda x: min(255, int(x * 1.1 + 10)))
    b = b.point(lambda x: max(0, int(x * 0.88 - 8)))
    img = Image.merge("RGB", (r, g, b))
    save(img, "uncertain", "instagram_warm_filter", "Instagram warm filter: color-shifted, unnaturally saturated", None)

    # 5. Upscaled thumbnail (low-res origin)
    w, h = 512, 512
    img = Image.new("RGB", (32, 32), (180, 150, 130))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 5, 26, 27], fill=(215, 178, 148))
    d.ellipse([9, 10, 14, 15], fill=(40, 30, 50))
    d.ellipse([18, 10, 23, 15], fill=(40, 30, 50))
    img = img.resize((512, 512), Image.NEAREST)  # pixelated upscale
    save(img, "uncertain", "upscaled_thumbnail_pixelated", "Thumbnail upscaled to HD: block artifacts, loss of information", None)

    print(f"  → {5} uncertain images generated")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Golden Test Set Generator")
    print(f"Output: {OUT_DIR}")
    print("=" * 60)

    make_real_images()
    make_ai_images()
    make_uncertain_images()

    # Save manifest
    manifest_path = OUT_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        import json
        json.dump(MANIFEST, f, indent=2)

    print()
    print("=" * 60)
    real_count = sum(1 for m in MANIFEST if m["expected_label"] == 0)
    fake_count = sum(1 for m in MANIFEST if m["expected_label"] == 1)
    unc_count  = sum(1 for m in MANIFEST if m["expected_label"] is None)
    print(f"Golden Set Summary:")
    print(f"  Real images     : {real_count}")
    print(f"  AI-gen images   : {fake_count}")
    print(f"  Uncertain       : {unc_count}")
    print(f"  Total           : {len(MANIFEST)}")
    print(f"  Manifest saved  : {manifest_path}")
    print()
    print("Next: python scripts/benchmark_golden_set.py")


if __name__ == "__main__":
    main()

