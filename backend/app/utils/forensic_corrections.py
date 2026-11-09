"""
Correcciones Forenses Post-Hoc — v2 (3 reglas)
===============================================
Reglas de dominio para casos límite que el meta-ensemble XGBoost no puede
aprender porque ocurren en la cola de su distribución de entrenamiento.

─────────────────────────────────────────────────────────────────────────────
Regla 1 — OOD-Manipulation Bypass (Afiche/Poster/Composición IA)
─────────────────────────────────────────────────────────────────────────────
  PROBLEMA: El penalizador OOD (aplica cuando hay diseño gráfico/texto) arrastra
  el score hacia 0.50, pero el afiche PUEDE contener contenido IA real.
  Adicionalmente, el SDXL Detector fue entrenado en imágenes fotorrealistas SDXL
  puros y falla en imágenes compuestas (posters, marketing deportivo, renders de
  juegos). Su score bajo arrastra incorrectamente el meta-ensemble.

  CONDICIÓN: is_ood=True AND (ViT > 72% OR AI Art > 52%)

  FÓRMULA v2 (incluye AI-Human Detector y SRM Noise Residual):
    manip_signal = ViT×0.35 + AI_Art×0.30 + AI_Human×0.20 + SRM×0.15
    damper       = 0.82 + 0.06 × (señales_presentes ≥ 4)  ← menos amortiguación
    corrected    = clip(manip_signal × damper, MIN, MAX)

  PARÁMETROS v2:
    MIN = 0.38  MAX = 0.68  (antes: 0.35 y 0.50)

  CASO COBRELOA (poster IA deportivo):
    ViT=79.5%, AI_Art=59.4%, AI_Human=61.2%, SRM=72.6% → todas señales presentes
    manip_signal = 0.795×0.35 + 0.594×0.30 + 0.612×0.20 + 0.726×0.15 = 0.687
    damper       = 0.82 + 0.06 = 0.88
    corrected    = clip(0.687 × 0.88, 0.38, 0.68) = clip(0.605, 0.38, 0.68) = 60.5% ✓

  CASO AFICHE REAL (diseño gráfico con foto real):
    ViT≈15%, AI_Art≈8% → ninguna condición cumple (bypass NO activa) → sin cambio ✓

─────────────────────────────────────────────────────────────────────────────
Regla 2 — Compression Veto (Foto Real Comprimida por Redes Sociales)
─────────────────────────────────────────────────────────────────────────────
  PROBLEMA: Los artefactos JPEG elevados por compresión de redes sociales
  hacen que ViT y EfficientNet suban a 46-60% en fotos perfectamente reales.
  SDXL y AI Art detectan correctamente la autenticidad.

  CONDICIÓN: score > 20% AND AI_Art < 20% AND SDXL < 50%
  CORRECCIÓN: corrected = 8% + AI_Art × 35%

  CASO MESSI (foto real comprimida): AI_Art=12%, SDXL=40% → 12.2% ✓
  (threshold subido de 5% → 20%: fotos de deportistas/celebridades puntúan 10-20% en AI Art)

─────────────────────────────────────────────────────────────────────────────
Regla 3 — Consensus Override (IA Fotorrealista — SDXL Disidente)
─────────────────────────────────────────────────────────────────────────────
  PROBLEMA NUEVO: El XGBoost usa SDXL como feature principal. Cuando la imagen
  IA NO es estilo SDXL (ej. Midjourney v6 hiper-realista, FLUX.1 portrait,
  renders de motor de juego), SDXL da < 15% aunque la imagen sea claramente IA.
  Si 4-5 modelos votan fuertemente FAKE pero SDXL dice REAL, el score cae a
  35-45% y la imagen escapa como "Inconclusa".

  CONDICIÓN: no es OOD (Regla 1 no aplica) Y
    ≥ 4 modelos de {ViT, AI_Art, SigLIP, AI_Human, SRM} superan el 52% Y
    SDXL < 22% (claramente fallando en este tipo de imagen) Y
    score actual < 50%

  CORRECCIÓN: floor gradual = 50% + (votos_extra_sobre_mínimo × 4%)
    - 4 votos → floor = 50%
    - 5 votos → floor = 54%

  CASO MIDJOURNEY PORTRAIT: ViT=75%, AI_Art=60%, SigLIP=65%, AI_Human=80%, SRM=70%
    5 votos; SDXL=12% < 22%; score_meta=38% < 50%
    floor = 50% + (5-4)×4% = 54% → score 54% ✓

  CASO FOTO REAL: ViT=35%, AI_Art=8%, SigLIP=30%, AI_Human=25%, SRM=20%
    0 votos > 52% → Regla 3 NO activa ✓

─────────────────────────────────────────────────────────────────────────────
Regla 4 — F+SRM Signal Alignment (Señal Espacial+Distribución Concordante)
─────────────────────────────────────────────────────────────────────────────
  PROBLEMA: El XGBoost no usa F (AI-Human Detector) ni SRM (Noise Residual)
  como features de entrenamiento. Cuando AMBAS señales espaciales concuerdan
  fuertemente en imagen IA (F > 72%, SRM > 65%) pero el score del meta-ensemble
  sigue bajo (< 50%), las correcciones proporcionales en _calibrated_combine
  no son suficientes para superar el umbral de decisión.

  CONDICIÓN: F > 72% Y SRM > 65% Y score < 50% Y no es OOD
    (La restricción no-OOD evita solapamiento con Regla 1)

  CORRECCIÓN: floor proporcional basado en la fuerza de ambas señales
    joint_signal = 0.55 × F + 0.45 × SRM
    floor = 0.50 + clip((joint_signal - 0.70) × 0.40, 0, 0.10)
    → máximo floor = 60%

  JUSTIFICACIÓN: F (entrenado en plataformas de IA reales) y SRM (residuos
  de ruido físicos) operan en dominios distintos al XGBoost (SDXL+AIArt+CLIP).
  Su acuerdo conjunto es una señal muy específica de imagen sintética.
  Para fotos reales: F rara vez supera 50%, SRM rara vez supera 45% → seguro.

  CASO F_AI_discrepa_fuerte: F=82%, SRM=75%, score=41.9%
    joint = 0.55×0.82 + 0.45×0.75 = 0.789
    floor = 0.50 + clip((0.789-0.70)×0.40, 0, 0.10) = 0.50 + 0.036 = 53.6% ✓

  CASO FOTO REAL: F=25%, SRM=20% → condición F>72% no cumple → no activa ✓
"""
from __future__ import annotations
from typing import Optional
from loguru import logger

# ─── Regla 1: OOD-Manipulation Bypass ────────────────────────────────────────
OOD_BYPASS_VIT_THRESHOLD    = 0.72   # ViT debe superar este umbral
OOD_BYPASS_AIART_THRESHOLD  = 0.52   # o AI Art debe superar este umbral
OOD_BYPASS_CLIP_THRESHOLD   = 0.70   # o el probe CLIP debe superar este umbral
OOD_BYPASS_VIT_W            = 0.20   # peso ViT en la señal combinada
OOD_BYPASS_AIART_W          = 0.20   # peso AI Art
OOD_BYPASS_AIHUMAN_W        = 0.15   # peso AI-Human Detector
# El probe CLIP lleva el mayor peso: reentrenado sobre 34.000 embeddings, es el
# unico detector con AUC alto en todas las pistas (0.976 en deepfake facial,
# donde los demas estan entre 0.48 y 0.58). La regla se escribio antes de ese
# reentrenamiento y lo ignoraba por completo, de modo que en composiciones
# graficas reemplazaba una deteccion correcta del probe por una media de
# detectores que no veian nada.
OOD_BYPASS_CLIP_W           = 0.45
OOD_BYPASS_SRM_W            = 0.00   # SRM retirado: AUC 0.409 (invertido)
OOD_BYPASS_DAMPER_BASE      = 0.82   # amortiguación base (subida de 0.60)
OOD_BYPASS_DAMPER_BONUS     = 0.06   # bonus si ≥4 señales presentes
OOD_BYPASS_MIN              = 0.38   # límite inferior del rango objetivo
OOD_BYPASS_MAX              = 0.68   # límite superior (subido de 0.50)

# ─── Regla 2: Compression Veto ───────────────────────────────────────────────
# AI Art subido de 5% → 20%: fotos reales de deportistas/celebridades
# suelen puntuar 10-20% en AI Art Detector. El threshold de 5% era demasiado
# estricto y dejaba pasar falsos positivos como una foto real de Messi.
COMPRESSION_VETO_AIART_MAX  = 0.20
COMPRESSION_VETO_SDXL_MAX   = 0.50
COMPRESSION_VETO_MIN_SCORE  = 0.20
COMPRESSION_VETO_BASE       = 0.08
COMPRESSION_VETO_AIART_COEF = 0.35

# Guarda: el veto NO se aplica si el probe CLIP ve síntesis con claridad.
#
# La premisa del veto es "si los dos especialistas en generación IA no ven nada,
# el score elevado viene de artefactos de compresión". Esa premisa dejó de valer
# al reentrenar el probe CLIP: en un deepfake facial, SDXL y Arte IA están bajos
# porque ninguno detecta intercambio de rostros, no porque la imagen sea
# auténtica. El veto estaba anulando detecciones correctas — el probe marcaba
# 100 % y el veto dejaba el resultado en 8 %.
#
# Umbral 0.70 medido sobre 20.000 imágenes: lo supera el 98,0 % del material
# sintético y sólo el 1,8 % de la fotografía auténtica.
COMPRESSION_VETO_CLIP_BLOCK = 0.70

# ─── Regla 3: Consensus Override ─────────────────────────────────────────────
# Votantes del consenso. Se excluyeron srm_noise_detector y siglip_deepfake:
# medidos sobre conjunto multifuente, SRM tiene AUC 0.409 (invertido, y supera
# su umbral en el 96,6 % de las fotos reales) y SigLIP 0.227 sobre deepfakes
# faciales. Ambos votaban "fake" en fotografía auténtica y completaban el
# quórum por sí solos.
CONSENSUS_MODELS     = [
    "face_deepfake_vit",
    "ai_art_detector",
    "ai_human_detector",
]
CONSENSUS_THRESHOLD  = 0.52   # score mínimo para contar como "voto fake"
CONSENSUS_MIN_VOTES  = 3      # unanimidad de los tres votantes que quedan
CONSENSUS_SDXL_MAX   = 0.22   # SDXL debe estar muy bajo (fallo claro)
CONSENSUS_SCORE_MAX  = 0.50   # solo activa si score < 50% (el meta-ensemble falló)
CONSENSUS_FLOOR_BASE = 0.50   # floor mínimo al activar
CONSENSUS_FLOOR_STEP = 0.04   # bonus por cada voto extra sobre el mínimo

# ─── Regla 4: F+SRM Signal Alignment ─────────────────────────────────────────
# Activa cuando el AI-Human Detector (F) y SRM Noise Residual concuerdan
# fuertemente en imagen sintética pero el meta-ensemble está bajo 50%.
# Ambas señales son ortogonales al XGBoost (entrenado en SDXL+AIArt+CLIP).
# DESACTIVADA. La regla elevaba el score cuando AI-Human y SRM coincidían por
# encima de sus umbrales, bajo el supuesto de que ese acuerdo era específico de
# imagen sintética. La medición sobre 1.100 imágenes de cinco fuentes desmintió
# el supuesto: SRM tiene AUC 0.409 (invertido) y el 96,6 % de las FOTOGRAFÍAS
# REALES supera su umbral de 0.65. La regla se activaba sobre fotografía
# auténtica y sólo podía subir el score, de modo que era una fuente neta de
# falsos positivos. Para reactivarla hay que recalibrar SRM y demostrar que el
# acuerdo discrimina.
F_SRM_ENABLED       = False
F_SRM_F_MIN         = 0.72   # AI-Human score mínimo (señal de distribución)
F_SRM_SRM_MIN       = 0.65   # SRM noise score mínimo (señal espacial)
F_SRM_SCORE_MAX     = 0.50   # solo activa si ensemble < 50%
F_SRM_JOINT_REF     = 0.70   # referencia base para calcular el floor extra
F_SRM_FLOOR_COEF    = 0.40   # coeficiente del bonus proporcional
F_SRM_FLOOR_BASE    = 0.50   # floor mínimo garantizado
F_SRM_FLOOR_MAX     = 0.60   # floor máximo (cap de seguridad)


def _avail(model_scores: dict, key: str) -> Optional[float]:
    """
    Score del modelo, o None si no esta disponible.

    Distinguir "ausente" de "0.0" es critico: varias reglas se activan cuando un
    detector puntua bajo, y tratar un score ausente como 0.0 las hacia disparar
    sin evidencia. Si el detector de arte IA fallaba al cargar, su None se
    convertia en 0.0, el Compression Veto veia "AI Art = 0% < 20%" y hundia el
    score a ~8%: un fallo de modelo producia el veredicto "autentica".
    """
    v = model_scores.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def apply_forensic_corrections(
    final_score: float,
    model_scores: dict,
    ood_result: dict,
    ai_art_excluded: bool = False,
) -> tuple[float, Optional[str], list[str]]:
    """
    Aplica correcciones forenses post-hoc basadas en conocimiento de dominio.

    ``ai_art_excluded``: cuando la compuerta de tipo de contenido determina que
    la imagen es una obra grafica, el detector de arte IA queda fuera del score
    forense. Las reglas que dependen de el se tratan entonces como si el score
    no estuviera disponible, para que no lo reintroduzcan por la puerta de atras.

    Returns: (corrected_score, correction_type, details_list)
    correction_type: None | "ood_bypass" | "compression_veto"
                     | "consensus_override" | "f_srm_alignment"
    """
    vit_o      = _avail(model_scores, "face_deepfake_vit")
    sdxl_o     = _avail(model_scores, "sdxl_detector")
    ai_art_o   = None if ai_art_excluded else _avail(model_scores, "ai_art_detector")
    ai_human_o = _avail(model_scores, "ai_human_detector")
    srm_o      = _avail(model_scores, "srm_noise_detector")
    is_ood     = bool(ood_result.get("is_ood", False))

    # Valores numericos para las formulas; las condiciones usan los *_o
    vit      = vit_o      or 0.0
    sdxl     = sdxl_o     or 0.0
    ai_art   = ai_art_o   or 0.0
    ai_human = ai_human_o or 0.0
    srm      = srm_o      or 0.0

    # ── Regla 1: OOD-Manipulation Bypass ─────────────────────────────────────
    clip_o = _avail(model_scores, "efficientnet_ffpp")
    clip_v = clip_o or 0.0
    _r1_trigger = (
        (vit_o is not None and vit > OOD_BYPASS_VIT_THRESHOLD)
        or (ai_art_o is not None and ai_art > OOD_BYPASS_AIART_THRESHOLD)
        or (clip_o is not None and clip_v > OOD_BYPASS_CLIP_THRESHOLD)
    )
    if is_ood and _r1_trigger:

        # Señales presentes (no-None) para calcular el damper adaptativo
        signals_present = sum(
            1 for s in [vit_o, ai_art_o, ai_human_o, clip_o]
            if s is not None and s > 0.01
        )
        damper = OOD_BYPASS_DAMPER_BASE + (
            OOD_BYPASS_DAMPER_BONUS if signals_present >= 4 else 0.0
        )

        # Los pesos se renormalizan sobre las señales realmente disponibles, de
        # modo que excluir una (p. ej. arte IA en obra grafica) redistribuya su
        # peso en lugar de restar magnitud a la señal combinada.
        # SRM queda fuera: medido invertido (AUC 0.409) y saturado alto sobre
        # fotografía real, sólo aportaba empuje hacia "sintético".
        _terms = [
            (vit_o,      OOD_BYPASS_VIT_W),
            (ai_art_o,   OOD_BYPASS_AIART_W),
            (ai_human_o, OOD_BYPASS_AIHUMAN_W),
            (clip_o,     OOD_BYPASS_CLIP_W),
        ]
        _w_total = sum(w for v, w in _terms if v is not None) or 1.0
        manip_signal = sum(v * w for v, w in _terms if v is not None) / _w_total
        corrected = float(min(OOD_BYPASS_MAX, max(OOD_BYPASS_MIN, manip_signal * damper)))

        details = [
            f"OOD-Manipulation Bypass v3 activado: contexto gráfico (is_ood=True) + "
            f"señal de manipulación: probe CLIP={clip_v:.1%}, ViT={vit:.1%}, "
            f"AI Art={ai_art:.1%}, AI-Human={ai_human:.1%}. "
            f"manip_signal={manip_signal:.3f} × damper={damper:.2f} → "
            f"{final_score:.3f} corregido a {corrected:.3f}. "
            f"Rango objetivo: {OOD_BYPASS_MIN:.0%}-{OOD_BYPASS_MAX:.0%}."
        ]

        if abs(corrected - final_score) > 0.02:
            logger.info(
                f"Forensic R1 [OOD Bypass v3]: "
                f"CLIP={clip_v:.2f} ViT={vit:.2f} AIArt={ai_art:.2f} "
                f"AIHuman={ai_human:.2f} "
                f"→ manip={manip_signal:.3f} × {damper:.2f} "
                f"→ {final_score:.3f} → {corrected:.3f}"
            )

        return corrected, "ood_bypass", details

    # ── Regla 2: Compression Veto ─────────────────────────────────────────────
    # Exige que AMBOS detectores esten disponibles: la regla concluye "es una
    # foto real comprimida" a partir de que los dos especialistas en generacion
    # IA no ven sintesis. Sin sus scores no hay tal evidencia, y con el arte IA
    # excluido por la compuerta la regla no aplica.
    _clip_bloquea = clip_o is not None and clip_o >= COMPRESSION_VETO_CLIP_BLOCK
    if (
        ai_art_o is not None
        and sdxl_o is not None
        and not _clip_bloquea
        and final_score > COMPRESSION_VETO_MIN_SCORE
        and ai_art < COMPRESSION_VETO_AIART_MAX
        and sdxl   < COMPRESSION_VETO_SDXL_MAX
    ):
        corrected = float(COMPRESSION_VETO_BASE + ai_art * COMPRESSION_VETO_AIART_COEF)
        corrected = float(min(0.22, max(0.08, corrected)))

        details = [
            f"Compression Veto activado: SDXL={sdxl:.1%} < {COMPRESSION_VETO_SDXL_MAX:.0%}, "
            f"AI Art={ai_art:.1%} < {COMPRESSION_VETO_AIART_MAX:.0%}. "
            f"Artefactos JPEG/redes sociales probable causa de scores elevados. "
            f"{final_score:.3f} → {corrected:.3f}."
        ]

        if abs(corrected - final_score) > 0.02:
            logger.info(
                f"Forensic R2 [Compression Veto]: "
                f"SDXL={sdxl:.2f} AIArt={ai_art:.2f} → "
                f"{final_score:.3f} → {corrected:.3f}"
            )

        return corrected, "compression_veto", details

    # ── Regla 3: Consensus Override ───────────────────────────────────────────
    # Solo activa en imágenes NO-OOD donde SDXL está fallando.
    if (
        not is_ood
        and sdxl_o is not None
        and final_score < CONSENSUS_SCORE_MAX
        and sdxl < CONSENSUS_SDXL_MAX
    ):
        # Solo votan los modelos con score disponible. Un detector ausente no
        # cuenta como voto "real": simplemente no vota.
        voters = {
            k: (None if (k == "ai_art_detector" and ai_art_excluded)
                else _avail(model_scores, k))
            for k in CONSENSUS_MODELS
        }
        available_voters = [v for v in voters.values() if v is not None]
        strong_votes = sum(1 for v in available_voters if v > CONSENSUS_THRESHOLD)

        if (
            len(available_voters) >= CONSENSUS_MIN_VOTES
            and strong_votes >= CONSENSUS_MIN_VOTES
        ):
            floor = CONSENSUS_FLOOR_BASE + (strong_votes - CONSENSUS_MIN_VOTES) * CONSENSUS_FLOOR_STEP
            if final_score < floor:
                corrected = float(floor)
                details = [
                    f"Consensus Override activado: {strong_votes} modelos "
                    f"[{', '.join(CONSENSUS_MODELS)}] superan {CONSENSUS_THRESHOLD:.0%} "
                    f"votando fake, pero SDXL={sdxl:.1%} < {CONSENSUS_SDXL_MAX:.0%} "
                    f"(fallo de cobertura del SDXL Detector en este tipo de imagen). "
                    f"Floor={floor:.0%}. {final_score:.3f} → {corrected:.3f}."
                ]

                logger.info(
                    f"Forensic R3 [Consensus Override]: "
                    f"{strong_votes} votos, SDXL={sdxl:.2f} "
                    f"→ {final_score:.3f} → {corrected:.3f}"
                )
                return corrected, "consensus_override", details

    # ── Regla 4: F+SRM Signal Alignment ──────────────────────────────────────
    # Cuando AI-Human (F) y SRM Noise concuerdan en imagen sintética con alta
    # confianza, aplica un floor proporcional a la fuerza de la señal conjunta.
    # Restricción not-is_ood evita solapamiento con Regla 1.
    # Ambas señales deben estar presentes: la regla se apoya en su *acuerdo*,
    # que no existe si una de las dos falta.
    f_score   = ai_human
    srm_score = srm
    if (
        F_SRM_ENABLED
        and not is_ood
        and ai_human_o is not None
        and srm_o is not None
        and f_score   >= F_SRM_F_MIN
        and srm_score >= F_SRM_SRM_MIN
        and final_score < F_SRM_SCORE_MAX
    ):
        joint_signal = 0.55 * f_score + 0.45 * srm_score
        floor = float(min(
            F_SRM_FLOOR_MAX,
            F_SRM_FLOOR_BASE + max(0.0, (joint_signal - F_SRM_JOINT_REF) * F_SRM_FLOOR_COEF),
        ))
        if final_score < floor:
            corrected = floor
            details = [
                f"F+SRM Signal Alignment activado: AI-Human={f_score:.1%}, "
                f"SRM Noise={srm_score:.1%} — ambas senales auxiliares concuerdan en imagen sintetica. "
                f"XGBoost no usa estas senales (entrenado en SDXL+AIArt+CLIP). "
                f"signal_conjunto={joint_signal:.3f}, floor={floor:.0%}. "
                f"{final_score:.3f} -> {corrected:.3f}."
            ]
            logger.info(
                f"Forensic R4 [F+SRM Alignment]: "
                f"F={f_score:.2f} SRM={srm_score:.2f} joint={joint_signal:.3f} "
                f"-> floor={floor:.3f}: {final_score:.3f} -> {corrected:.3f}"
            )
            return corrected, "f_srm_alignment", details

    return final_score, None, []


def build_correction_explanation(correction_type: Optional[str], _details: list[str]) -> str:
    """Genera texto de explicación para el usuario. _details reservado para futuros logs."""
    if correction_type == "ood_bypass":
        return (
            "⚙ Corrección forense aplicada: la imagen contiene elementos de diseño gráfico "
            "o composición (contexto OOD) junto con señales multi-modelo de contenido sintético. "
            "ViT, AI Art Detector, AI-Human y SRM Noise concuerdan en indicadores de "
            "manipulación. Score ajustado con amortiguación por incertidumbre del contexto "
            "gráfico. Verificación manual recomendada."
        )
    elif correction_type == "compression_veto":
        return (
            "⚙ Corrección forense aplicada: los detectores especializados en generación IA "
            "(SDXL Detector y AI Art Detector) no detectan síntesis moderna. "
            "Scores elevados en otros modelos son consistentes con artefactos de "
            "compresión JPEG o procesamiento de redes sociales."
        )
    elif correction_type == "consensus_override":
        return (
            "⚙ Corrección de consenso aplicada: múltiples modelos detectan indicadores de "
            "imagen sintética, pero el SDXL Detector da baja probabilidad (entrenado "
            "específicamente en imágenes SDXL, puede no reconocer Midjourney, FLUX o "
            "renders fotorrealistas). El score refleja el consenso de los detectores generales."
        )
    elif correction_type == "f_srm_alignment":
        return (
            "⚙ Corrección de señal espacial aplicada: el AI-Human Detector y el analizador "
            "de residuos de ruido SRM concuerdan en alta probabilidad de imagen sintética. "
            "Estas señales son ortogonales al meta-ensemble principal (entrenado en detectores "
            "SDXL y AI-Art) y capturan artefactos en el dominio de distribución y de frecuencia "
            "espacial que el ensemble puede subestimar en ciertos tipos de imagen."
        )
    return ""
