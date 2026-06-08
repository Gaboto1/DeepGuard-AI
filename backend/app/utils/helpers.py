"""
Funciones utilitarias forenses — v3.0 (100% español técnico)
Interpretación basada en evidencia, sin etiquetas binarias.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from app.api.schemas import EvidenceLevel, ModelAgreement, UncertaintyLevel


def new_task_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Nivel de evidencia ───────────────────────────────────────────────────────

def get_evidence_level(probability: float) -> EvidenceLevel:
    """
    Mapea la probabilidad de manipulación a un nivel de evidencia.
    Nunca afirma 'real' o 'falso' — solo describe la fuerza de la evidencia.
    """
    if probability < 0.20:
        return EvidenceLevel.VERY_LOW
    elif probability < 0.40:
        return EvidenceLevel.LOW
    elif probability < 0.60:
        return EvidenceLevel.INCONCLUSIVE
    elif probability < 0.80:
        return EvidenceLevel.MODERATE
    else:
        return EvidenceLevel.STRONG


# ─── Consenso de modelos ──────────────────────────────────────────────────────

def get_model_agreement(scores: list[float]) -> tuple[ModelAgreement, float]:
    """
    Calcula el consenso entre modelos.
    Desviación alta → modelos en desacuerdo → resultado menos fiable.
    """
    if not scores:
        return ModelAgreement.LOW, 1.0
    valid = [s for s in scores if s is not None]
    if len(valid) < 2:
        return ModelAgreement.LOW, 1.0
    std = float(np.std(valid))
    if std < 0.10:
        return ModelAgreement.HIGH, std
    elif std < 0.25:
        return ModelAgreement.MEDIUM, std
    else:
        return ModelAgreement.LOW, std


# ─── Incertidumbre y riesgo de error ─────────────────────────────────────────

def get_uncertainty(
    probability: float,
    std: float,
    ood_signal: bool = False,
) -> tuple[UncertaintyLevel, float, str]:
    """
    Calcula el nivel de incertidumbre basado en la entropía y el desacuerdo entre modelos.
    Retorna (UncertaintyLevel, entropia_normalizada, descripcion_riesgo).
    """
    eps = 1e-8
    entropy = float(
        -probability * np.log(probability + eps)
        - (1 - probability) * np.log(1 - probability + eps)
    )
    entropy_norm    = entropy / 0.693  # normalizar a 0-1 (máx entropía = ln(2))
    uncertainty_score = float(np.clip(0.5 * entropy_norm + 0.5 * std / 0.5, 0, 1))

    if ood_signal or uncertainty_score > 0.70:
        level = UncertaintyLevel.HIGH
        risk  = (
            "Alto riesgo de error — la imagen podría estar fuera del dominio "
            "de entrenamiento de los modelos. Se recomienda revisión manual."
        )
    elif uncertainty_score > 0.40:
        level = UncertaintyLevel.MEDIUM
        risk  = (
            "Riesgo moderado de error — los modelos presentan desacuerdo parcial. "
            "El resultado es orientativo y debe contrastarse con otras evidencias."
        )
    else:
        level = UncertaintyLevel.LOW
        risk  = "Bajo riesgo de error — los modelos convergen en un resultado similar."

    return level, round(entropy_norm, 4), risk


# ─── Explicación forense ──────────────────────────────────────────────────────

# Mapas de nombres legibles para modelos (para mostrar en la explicación)
_NOMBRES_MODELO: dict[str, str] = {
    "face_deepfake_vit": "Detector facial ViT",
    "sdxl_detector":     "Detector SDXL",
    "efficientnet_ffpp": "EfficientNet FF++",
    "ai_art_detector":   "Detector de arte IA",
    "siglip_deepfake":   "SigLIP Deepfake",
    "face deepfake vit": "Detector facial ViT",
    "sdxl detector":     "Detector SDXL",
    "efficientnet ffpp": "EfficientNet FF++",
    "ai art detector":   "Detector de arte IA",
    "siglip deepfake":   "SigLIP Deepfake",
}


def generate_forensic_explanation(
    probability: float,
    evidence_level: EvidenceLevel,
    model_agreement: ModelAgreement,
    file_type: str,
    faces_detected: int = 0,
    frames_analyzed: int = 0,
    inconsistency_score: float = 0.0,
    model_scores: Optional[dict] = None,
    is_ood: bool = False,
    ood_signals: Optional[list] = None,
) -> str:
    """
    Genera la explicación forense exclusivamente en español técnico.
    Basada en evidencia medida — sin descripciones inventadas de artefactos.
    """
    pct = round(probability * 100)

    base_map = {
        EvidenceLevel.VERY_LOW: (
            f"El análisis arrojó una probabilidad de manipulación del {pct}%. "
            "El conjunto de modelos encontró señales muy débiles o inexistentes "
            "de generación artificial o manipulación."
        ),
        EvidenceLevel.LOW: (
            f"El análisis arrojó una probabilidad de manipulación del {pct}%. "
            "Se detectaron señales débiles, pero dentro de la variación normal "
            "para contenido auténtico."
        ),
        EvidenceLevel.INCONCLUSIVE: (
            f"El análisis arrojó una probabilidad de manipulación del {pct}%. "
            "Los modelos no pudieron determinar la autenticidad con suficiente confianza. "
            "El resultado es inconcluso y no debe emplearse como única base de decisión."
        ),
        EvidenceLevel.MODERATE: (
            f"El análisis arrojó una probabilidad de manipulación del {pct}%. "
            "Varios modelos identificaron patrones asociados con generación "
            "artificial o manipulación de contenido."
        ),
        EvidenceLevel.STRONG: (
            f"El análisis arrojó una probabilidad de manipulación del {pct}%. "
            "Se detectaron señales convergentes y robustas de manipulación "
            "en múltiples modelos del ensemble."
        ),
    }
    base = base_map[evidence_level]
    details = []

    # Consenso de modelos
    if model_agreement == ModelAgreement.HIGH:
        details.append(
            "Los modelos presentan alto consenso — el resultado es más fiable."
        )
    elif model_agreement == ModelAgreement.MEDIUM:
        details.append(
            "Los modelos muestran desacuerdo parcial — interprete con precaución."
        )
    else:
        details.append(
            "Los modelos presentan desacuerdo significativo — "
            "el resultado debe considerarse preliminar y revisarse manualmente."
        )

    # Scores individuales
    if model_scores:
        partes = []
        for k, v in model_scores.items():
            if v is not None:
                nombre = _NOMBRES_MODELO.get(k.lower().replace("_", " "), k)
                partes.append(f"{nombre}: {round(v * 100)}%")
        if partes:
            details.append("Puntuaciones individuales — " + ", ".join(partes) + ".")

    # Contexto de imagen
    if file_type == "image" and faces_detected > 0:
        details.append(
            f"Se detectaron {faces_detected} rostro(s) — "
            "el análisis incluye ponderación de la región facial."
        )
    elif file_type == "image":
        details.append(
            "No se detectaron rostros — se analizó la imagen completa."
        )

    # Contexto de video
    if file_type == "video" and frames_analyzed > 0:
        details.append(f"Se muestrearon {frames_analyzed} fotogramas para el análisis.")

    if file_type == "video" and inconsistency_score > 0.20:
        details.append(
            f"Alta inconsistencia temporal entre fotogramas (σ={inconsistency_score:.2f}), "
            "lo que podría indicar manipulación selectiva."
        )

    # Aviso legal / disclaimer
    details.append(
        "Este análisis es probabilístico, no definitivo. "
        "Se recomienda verificación externa y revisión de metadatos del archivo."
    )

    # Advertencia OOD — al final para mayor prominencia
    if is_ood:
        ood_detail = (
            "⚠ La imagen contiene elementos de diseño gráfico o texto renderizado "
            "que pueden distorsionar los componentes forenses tradicionales; "
            "interprete con precaución."
        )
        if ood_signals:
            sigs = [s for s in ood_signals[:3] if "hard_rule" not in s]
            if sigs:
                ood_detail += f" Señales detectadas: {', '.join(sigs)}."
        details.append(ood_detail)

    return " ".join([base] + details)
