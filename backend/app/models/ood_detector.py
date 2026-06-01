"""
OOD Detector — Detección de imágenes fuera del dominio forense
==============================================================
Identifica si una imagen es un afiche publicitario, contiene texto
renderizado denso o es un diseño gráfico híbrido que puede distorsionar
los modelos de detección de deepfakes entrenados en fotografía real.

Enfoque: heurísticas de procesamiento de imagen (sin modelo ML pesado).
Latencia objetivo: < 80ms por imagen.

5 señales combinadas:
  1. Edge density     — el texto produce bordes horizontales muy densos
  2. Text regularity  — filas de texto crean periodicidad horizontal
  3. Palette compression — diseño gráfico usa pocas colores dominantes
  4. Extreme pixels   — blanco/negro puro o saturación máxima (colores planos)
  5. Uniform regions  — fondos lisos extensos (backgrounds de afiche)

Calibración del score OOD → penalización:
  score_penalizado = score × (1 - α × ood_conf) + 0.5 × α × ood_conf
  donde α = OOD_ALPHA_MAX = 0.35 (tira el score hacia 0.5)
"""
from __future__ import annotations
from typing import Optional
import numpy as np
from PIL import Image
from loguru import logger

# Thresholds calibrados para fotografías reales (naturaleza, retratos, deportes).
# NOTA: imágenes sintéticas ultra-suaves (PIL gradients) pueden tener alto s_uni
#       por ausencia de texturas naturales — esto NO ocurre en fotos reales.
OOD_THRESHOLD  = 0.43   # score >= este → OOD (bajado de 0.52 para diseños reales)
OOD_ALPHA_MAX  = 0.35   # penalización máxima

# Pesos de cada señal (ajustados para maximizar separación afiche/foto):
#   extreme_pixels  y uniform_regions son las señales más discriminativas para diseños.
#   edge_density    y text_regularity son las mejores para texto renderizado.
_W = {
    "edge_density":    0.25,   # alta: texto crea bordes densos
    "text_regularity": 0.15,   # periodicidad horizontal (filas de texto)
    "palette_compact": 0.15,   # colores limitados (corporativos)
    "extreme_pixels":  0.25,   # blanco/negro/saturados puros
    "uniform_regions": 0.20,   # fondos sólidos extensos
}


def _to_gray_np(image: Image.Image, size: int = 512) -> "np.ndarray":
    """Redimensiona y convierte a escala de grises (uint8)."""
    import cv2
    img_rgb = np.array(image.resize((size, size), Image.LANCZOS).convert("RGB"))
    return cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY), img_rgb


def _signal_edge_density(gray: "np.ndarray") -> tuple[float, str]:
    """
    Densidad de bordes Canny.
    Texto renderizado produce ~15-30% de píxeles de borde.
    Fotografías naturales: 3-10%.
    """
    import cv2
    edges     = cv2.Canny(gray, 80, 200)
    density   = float(edges.mean()) / 255.0
    # Normalizar: 0% → 0.0, ≥25% → 1.0
    score     = min(density / 0.25, 1.0)
    return score, f"densidad_bordes={density*100:.1f}%"


def _signal_text_regularity(gray: "np.ndarray") -> tuple[float, str]:
    """
    Periodicidad de proyección horizontal.
    Las filas de texto crean un patrón regular en la proyección horizontal.
    Mide la regularidad (coeficiente de variación bajo = muy regular).
    """
    import cv2
    edges        = cv2.Canny(gray, 80, 200)
    h_proj       = edges.mean(axis=1).astype(float)  # media por fila
    mean_proj    = h_proj.mean()
    if mean_proj < 1e-6:
        return 0.0, "regularidad_horizontal=N/A"
    cv_horiz     = h_proj.std() / mean_proj
    # CV bajo = muy regular (texto); CV alto = irregular (fotografía natural)
    # cv_horiz < 1.0 → regular; > 3.0 → muy irregular
    regularity   = float(max(0.0, 1.0 - cv_horiz / 2.5))
    return regularity, f"regularidad_horizontal={regularity:.2f}"


def _signal_palette_compact(image: Image.Image) -> tuple[float, str]:
    """
    Compresión de paleta.
    Diseño gráfico típicamente usa 4-8 colores dominantes.
    Fotografía real: paleta continua con 16+ colores significativos.
    """
    quantized    = image.resize((256, 256), Image.LANCZOS).convert("P",
                    palette=Image.ADAPTIVE, colors=16)
    hist         = quantized.histogram()
    total_pixels = 256 * 256
    # Contar colores que representan ≥5% de los píxeles
    dominant     = sum(1 for h in hist if h >= total_pixels * 0.05)
    # Pocos colores dominantes → diseño gráfico
    score        = float(max(0.0, 1.0 - dominant / 6.0))  # ≤6 → score > 0
    return score, f"colores_dominantes={dominant}"


def _signal_extreme_pixels(img_rgb: "np.ndarray") -> tuple[float, float, str]:
    """
    Píxeles extremos: blanco/negro puro o saturación máxima (colores planos).
    Fotografías naturales: < 30% extremos.
    Diseño gráfico / screenshot: fondos blancos + texto negro → 80-99%.
    Retorna (score 0-1, fraccion_raw 0-1, descripcion).
    """
    import cv2
    hsv         = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    sat         = hsv[:, :, 1] / 255.0
    # Extremos: muy baja saturación (blanco/gris/negro) O muy alta saturación
    extreme_frac= float(((sat < 0.08) | (sat > 0.88)).mean())
    score       = float(min(extreme_frac / 0.55, 1.0))
    return score, extreme_frac, f"pixeles_extremos={extreme_frac*100:.1f}%"


def _signal_uniform_regions(gray: "np.ndarray", block: int = 64) -> tuple[float, str]:
    """
    Regiones uniformes extensas (fondos de afiche, áreas de texto sobre color sólido).
    Divide la imagen en bloques de block×block y mide la desviación estándar.
    std < 12 → bloque casi uniforme.
    """
    h, w         = gray.shape
    n_blocks     = 0
    uniform      = 0
    for y in range(0, h - block + 1, block):
        for x in range(0, w - block + 1, block):
            blk  = gray[y:y+block, x:x+block]
            if blk.std() < 12.0:
                uniform += 1
            n_blocks += 1
    frac         = uniform / max(1, n_blocks)
    score        = float(min(frac / 0.35, 1.0))  # ≥35% bloques uniformes → score 1.0
    return score, f"bloques_uniformes={frac*100:.1f}%"


# ─── Función principal ────────────────────────────────────────────────────────

def detect_ood(image: Image.Image) -> dict:
    """
    Analiza la imagen y devuelve el diagnóstico OOD.

    Retorna:
      {
        "is_ood":       bool,
        "ood_confidence": float 0-1,
        "ood_score":    float 0-1,   # score bruto antes del threshold
        "ood_signals":  list[str],   # señales individuales activadas
        "penalty_alpha": float,      # factor de penalización aplicado
      }
    """
    try:
        import cv2  # noqa
    except ImportError:
        logger.debug("OOD: OpenCV no disponible, omitiendo análisis")
        return _no_ood()

    try:
        gray, img_rgb = _to_gray_np(image)

        s_edge,  d_edge  = _signal_edge_density(gray)
        s_reg,   d_reg   = _signal_text_regularity(gray)
        s_pal,   d_pal   = _signal_palette_compact(image)
        s_ext,   _ext_frac, d_ext = _signal_extreme_pixels(img_rgb)
        s_uni,   d_uni   = _signal_uniform_regions(gray)

        scores = {
            "edge_density":    s_edge,
            "text_regularity": s_reg,
            "palette_compact": s_pal,
            "extreme_pixels":  s_ext,
            "uniform_regions": s_uni,
        }

        ood_score = float(sum(_W[k] * v for k, v in scores.items()))

        # Señales activas (score individual > 0.40) — se construye ANTES del hard rule
        active_signals = [
            d for d, s in zip(
                [d_edge, d_reg, d_pal, d_ext, d_uni],
                [s_edge, s_reg, s_pal, s_ext, s_uni],
            )
            if s > 0.40
        ]

        # Hard rule: ≥85% de píxeles extremos (blanco/negro/saturado puro).
        # Diseño gráfico, screenshots y memes superan este umbral.
        # Fotografías naturales nunca lo superan (piel, follaje, cielo = saturación intermedia).
        # Captura casos donde texto fino sobre fondo blanco da s_uni bajo pero s_ext alto.
        if _ext_frac >= 0.85:
            ood_score = max(ood_score, 0.60)
            active_signals.append(f"hard_rule:extreme_pixels={_ext_frac*100:.1f}%")

        is_ood = ood_score >= OOD_THRESHOLD

        # Penalización proporcional a la confianza OOD
        # Zona gris: OOD_THRESHOLD → penalización mínima; 1.0 → OOD_ALPHA_MAX
        if is_ood:
            ood_confidence = min((ood_score - OOD_THRESHOLD) / (1.0 - OOD_THRESHOLD), 1.0)
            penalty_alpha  = OOD_ALPHA_MAX * ood_confidence
        else:
            ood_confidence = 0.0
            penalty_alpha  = 0.0

        logger.debug(
            f"OOD score={ood_score:.3f} | is_ood={is_ood} | "
            f"conf={ood_confidence:.2f} | alpha={penalty_alpha:.3f}"
        )

        return {
            "is_ood":          is_ood,
            "ood_confidence":  round(ood_confidence, 4),
            "ood_score":       round(ood_score, 4),
            "ood_signals":     active_signals,
            "penalty_alpha":   round(penalty_alpha, 4),
        }

    except Exception as e:
        logger.debug(f"OOD detection falló: {e}")
        return _no_ood()


def _no_ood() -> dict:
    return {
        "is_ood":         False,
        "ood_confidence": 0.0,
        "ood_score":      0.0,
        "ood_signals":    [],
        "penalty_alpha":  0.0,
    }


def apply_ood_penalty(score: float, ood_result: dict) -> float:
    """
    Aplica la penalización OOD al score final.
    Tira el score hacia 0.5 (máxima incertidumbre) en proporción a alpha.

    score_penalizado = score × (1 - α) + 0.5 × α
    """
    alpha = ood_result.get("penalty_alpha", 0.0)
    if alpha <= 0.0:
        return score
    penalized = score * (1.0 - alpha) + 0.5 * alpha
    logger.debug(f"OOD penalty: {score:.3f} → {penalized:.3f} (α={alpha:.3f})")
    return float(np.clip(penalized, 0.0, 1.0))
