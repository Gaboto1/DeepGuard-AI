"""
Correcciones Forenses Post-Hoc — Reglas de dominio para casos límite
=====================================================================
Dos reglas matemáticas derivadas de casos de producción reales que el
meta-modelo XGBoost no puede aprender porque ocurren en la cola de la
distribución de entrenamiento.

Regla 1 — OOD-Manipulation Bypass (Afiche Híbrido IA):
  Problema: La penalización OOD (diseño/afiche) destruye el score cuando
  el contenido DENTRO del afiche es manipulado artificialmente.
  Condición: is_ood=True AND (ViT > 0.75 OR AI Art > 0.55)
  Corrección: usa solo los detectores de manipulación (ignorando fondo gráfico)
  amortiguados por un factor de incertidumbre OOD.
  Rango objetivo: 35-50% (zona gris sospechosa pero inconclusa)

  Derivación:
    manip_signal = ViT×0.55 + AI_Art×0.45  (señal combinada de manipulación)
    corrected    = clip(manip_signal × OOD_DAMPER, 0.35, 0.50)
    Caso afiche: clip((0.795×0.55 + 0.594×0.45) × 0.60, 0.35, 0.50) = 42.2% ✓

Regla 2 — Compression Veto (Foto Real Comprimida):
  Problema: Los artefactos de compresión JPEG/redes sociales elevan
  EfficientNet y ViT a 46-60% en fotos perfectamente reales.
  Condición: score > 0.20 AND AI_Art < 0.05 AND SDXL < 0.50
  (ambos detectores especializados en IA moderna concuerdan en autenticidad)
  Corrección: escala a rango auténtico basado en AI Art Detector.
  Rango objetivo: 10-20%

  Derivación:
    corrected = 0.10 + AI_Art × 0.40
    Caso Messi (AI Art=0.5%): 0.10 + 0.005×0.40 = 10.2% ✓
    Foto real limpia (AI Art=1%): 0.10 + 0.01×0.40 = 10.4% ✓

Verificación de seguridad sobre Golden Set:
  - Regla 1: ninguna imagen del Golden Set es OOD + ViT>75% simultáneamente → sin cambio
  - Regla 2: reduce scores de imágenes reales (mejora TN) y no afecta TP con SDXL>50%
  - F1 objetivo >90% se mantiene o mejora
"""
from __future__ import annotations
from typing import Optional
from loguru import logger

# ─── Hiperparámetros Regla 1 (OOD Bypass) ─────────────────────────────────────
OOD_BYPASS_VIT_THRESHOLD   = 0.75   # ViT > 75%   → señal de manipulación facial fuerte
OOD_BYPASS_AIART_THRESHOLD = 0.55   # AI Art > 55% → señal de arte sintético fuerte
OOD_BYPASS_VIT_WEIGHT      = 0.55   # peso del ViT en la señal combinada
OOD_BYPASS_AIART_WEIGHT    = 0.45   # peso del AI Art
OOD_BYPASS_DAMPER          = 0.60   # factor de incertidumbre por contexto OOD
OOD_BYPASS_MIN             = 0.35   # límite inferior del rango objetivo
OOD_BYPASS_MAX             = 0.50   # límite superior del rango objetivo

# ─── Hiperparámetros Regla 2 (Compression Veto) ───────────────────────────────
COMPRESSION_VETO_AIART_MAX  = 0.05   # AI Art < 5%  → ningún generador moderno
COMPRESSION_VETO_SDXL_MAX   = 0.50   # SDXL < 50%  → no imagen SDXL
COMPRESSION_VETO_MIN_SCORE  = 0.20   # solo aplica si score actual es elevado
COMPRESSION_VETO_BASE       = 0.10   # score base para imagen auténtica
COMPRESSION_VETO_AIART_COEF = 0.40   # contribución de AI Art al score final


def apply_forensic_corrections(
    final_score: float,
    model_scores: dict,
    ood_result: dict,
) -> tuple[float, Optional[str], list[str]]:
    """
    Aplica correcciones forenses post-hoc basadas en conocimiento de dominio.

    Args:
        final_score:   Score del meta-ensemble XGBoost (0-1)
        model_scores:  Dict con scores individuales de cada modelo
        ood_result:    Dict con el diagnóstico OOD (de ood_detector.py)

    Returns:
        (corrected_score, correction_type, details_list)
        correction_type: None | "ood_bypass" | "compression_veto"
    """
    vit    = float(model_scores.get("face_deepfake_vit", 0) or 0)
    sdxl   = float(model_scores.get("sdxl_detector",     0) or 0)
    ai_art = float(model_scores.get("ai_art_detector",   0) or 0)
    is_ood = bool(ood_result.get("is_ood", False))

    # ── Regla 1: OOD Bypass ───────────────────────────────────────────────────
    if is_ood and (vit > OOD_BYPASS_VIT_THRESHOLD or ai_art > OOD_BYPASS_AIART_THRESHOLD):
        manip_signal = vit * OOD_BYPASS_VIT_WEIGHT + ai_art * OOD_BYPASS_AIART_WEIGHT
        corrected    = float(min(OOD_BYPASS_MAX, max(OOD_BYPASS_MIN, manip_signal * OOD_BYPASS_DAMPER)))

        details = [
            f"OOD-Manipulation Bypass activado: fondo gráfico detectado (is_ood=True) "
            f"pero señal de manipulación fuerte prevalece "
            f"(ViT={vit:.1%}, AI Art={ai_art:.1%}). "
            f"Señal combinada={manip_signal:.3f} × damper={OOD_BYPASS_DAMPER} → "
            f"{final_score:.3f} corregido a {corrected:.3f}. "
            f"Rango objetivo: {OOD_BYPASS_MIN:.0%}-{OOD_BYPASS_MAX:.0%} (sospechoso/inconcluso)."
        ]

        if abs(corrected - final_score) > 0.02:
            logger.info(
                f"Forensic Regla1 [OOD Bypass]: "
                f"ViT={vit:.2f} AIArt={ai_art:.2f} → "
                f"{final_score:.3f} → {corrected:.3f}"
            )

        return corrected, "ood_bypass", details

    # ── Regla 2: Compression Veto ─────────────────────────────────────────────
    if (
        final_score > COMPRESSION_VETO_MIN_SCORE
        and ai_art < COMPRESSION_VETO_AIART_MAX
        and sdxl   < COMPRESSION_VETO_SDXL_MAX
    ):
        corrected = float(COMPRESSION_VETO_BASE + ai_art * COMPRESSION_VETO_AIART_COEF)
        corrected = float(min(0.22, max(0.08, corrected)))

        details = [
            f"Compression Veto activado: detectores especializados en IA moderna "
            f"concuerdan en autenticidad (SDXL={sdxl:.1%} < {COMPRESSION_VETO_SDXL_MAX:.0%}, "
            f"AI Art={ai_art:.1%} < {COMPRESSION_VETO_AIART_MAX:.0%}). "
            f"Artefactos de compresión JPEG/redes sociales probable causa de scores elevados. "
            f"{final_score:.3f} → {corrected:.3f} "
            f"(fórmula: {COMPRESSION_VETO_BASE} + AI_Art×{COMPRESSION_VETO_AIART_COEF})."
        ]

        if abs(corrected - final_score) > 0.02:
            logger.info(
                f"Forensic Regla2 [Compression Veto]: "
                f"SDXL={sdxl:.2f} AIArt={ai_art:.2f} → "
                f"{final_score:.3f} → {corrected:.3f}"
            )

        return corrected, "compression_veto", details

    return final_score, None, []


def build_correction_explanation(correction_type: Optional[str], details: list[str]) -> str:
    """Genera texto de explicación para el usuario cuando se aplica una corrección."""
    if correction_type == "ood_bypass":
        return (
            "⚙ Corrección forense aplicada: la imagen contiene elementos de diseño gráfico "
            "(fondo OOD) pero también señales de manipulación de contenido. "
            "El score refleja la manipulación detectada, amortiguada por la incertidumbre "
            "introducida por el contexto gráfico. Verificación manual recomendada."
        )
    elif correction_type == "compression_veto":
        return (
            "⚙ Corrección forense aplicada: los detectores especializados en generación IA "
            "(SDXL Detector y AI Art Detector) no detectan síntesis moderna. "
            "Los scores elevados de otros modelos son consistentes con artefactos de "
            "compresión JPEG o procesamiento de redes sociales, no con manipulación."
        )
    return ""
