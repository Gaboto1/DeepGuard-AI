"""
Forensic-grade schemas — v2.0
Replaces binary REAL/FAKE classification with evidence-based forensic analysis.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class TaskStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"


# ── Evidence Level: replaces REAL/FAKE labels ──────────────────────────────────
class EvidenceLevel(str, Enum):
    VERY_LOW     = "Very Low Evidence"   # 0–20%
    LOW          = "Low Evidence"        # 20–40%
    INCONCLUSIVE = "Inconclusive"        # 40–60%
    MODERATE     = "Moderate Evidence"   # 60–80%
    STRONG       = "Strong Evidence"     # 80–100%


class ModelAgreement(str, Enum):
    HIGH   = "High Consensus"    # std < 0.10
    MEDIUM = "Medium Consensus"  # std 0.10–0.25
    LOW    = "Low Consensus"     # std > 0.25


# ── Per-model transparency ─────────────────────────────────────────────────────
class UncertaintyLevel(str, Enum):
    LOW    = "Baja"
    MEDIUM = "Moderada"
    HIGH   = "Alta"


class ModelScore(BaseModel):
    name: str
    score: float          # raw output 0–1
    weight: float         # ensemble weight applied
    contribution: float   # weight × score (unnormalized contribution)
    score_pct: float      # score × 100 for display


class EnsembleBreakdown(BaseModel):
    models: list[ModelScore]
    weights_mode: str      # "face_detected" or "no_face"
    final_probability: float


# ── OSINT ──────────────────────────────────────────────────────────────────────
class OsintSearchLink(BaseModel):
    engine: str
    url: str
    note: str


class OsintResult(BaseModel):
    status: str = "manual_review_required"
    note: str = (
        "Automated external search is not available. "
        "Manual reverse image search is recommended using the links below."
    )
    search_links: list[OsintSearchLink] = []
    perceptual_hash: Optional[str] = None
    disclaimer: str = (
        "No public records found does not indicate manipulation. "
        "Prior publication in a trusted source does not confirm authenticity."
    )


# ── Metadata ───────────────────────────────────────────────────────────────────
class MetadataAnalysis(BaseModel):
    has_exif: bool
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    software: Optional[str] = None
    datetime_original: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    color_space: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    compression: Optional[str] = None
    iso: Optional[int] = None
    focal_length: Optional[str] = None
    exposure_time: Optional[str] = None
    f_number: Optional[str] = None
    flash: Optional[str] = None
    forensic_notes: list[str] = []


# ── Análisis semántico VLM (LLaVA-1.5-7b) ────────────────────────────────────
class SemanticAnalysis(BaseModel):
    """
    Resultado del análisis forense semántico realizado por LLaVA-1.5-7b-hf.
    Añade comprensión de anatomía, física y coherencia visual que los modelos
    estadísticos no pueden proporcionar.
    """
    risk_score:             int              # 0-100 (output directo de LLaVA)
    risk_score_normalized:  Optional[float]  # 0.0-1.0 para integración con ensemble
    semantic_observations:  str              # Descripción forense en español
    model_used:             str              # "llava-hf/llava-1.5-7b-hf"
    quantization:           str              # "4-bit NF4 + bfloat16"
    analysis_time:          float            # segundos de inferencia
    fusion_type:            Optional[str]    # "semantic_blend" | "semantic_correction_up/down"
    fusion_note:            Optional[str]    # Explicación de la corrección aplicada
    available:              bool = True      # False si LLaVA no está cargado


# ── Análisis temporal de video ────────────────────────────────────────────────
class TemporalAnalysis(BaseModel):
    """Resultado del análisis de consistencia temporal entre frames consecutivos."""
    temporal_anomaly_detected:   bool
    temporal_consistency_score:  float              # 0-1: 1.0 = perfecto, 0.0 = máx anomalía
    temporal_discrepancy_values: list[float] = []   # distancias coseno entre frames
    temporal_variance:           float              # varianza de discrepancias
    temporal_max_spike:          float              # pico máximo de discrepancia
    optical_flow_values:         list[float] = []   # magnitudes de flujo óptico
    optical_flow_variance:       float              # varianza del flujo
    optical_flow_anomaly:        bool
    frames_with_faces:           int
    frames_analyzed:             int
    risk_multiplier:             float              # factor aplicado al score base
    anomaly_details:             list[str] = []     # descripción de anomalías
    analysis_time:               float


# ── Frame result (video) ───────────────────────────────────────────────────────
class FrameResult(BaseModel):
    frame_index: int
    timestamp: float
    manipulation_probability: float
    face_detected: bool


# ── Main analysis result ───────────────────────────────────────────────────────
class AnalysisResult(BaseModel):
    task_id: str
    status: TaskStatus
    file_type: str
    filename: str
    created_at: datetime

    # Core forensic result
    manipulation_probability: Optional[float] = None   # 0–100 scale for display
    evidence_level: Optional[EvidenceLevel] = None
    model_agreement: Optional[ModelAgreement] = None
    model_agreement_std: Optional[float] = None
    explanation: Optional[str] = None

    # Ensemble transparency
    ensemble: Optional[EnsembleBreakdown] = None

    # Analysis metadata
    analysis_time: Optional[float] = None
    model_used: Optional[str] = None
    device_used: Optional[str] = None
    faces_detected: Optional[int] = None

    # Visual evidence
    heatmap: Optional[str] = None

    # Supporting evidence modules
    metadata_analysis: Optional[MetadataAnalysis] = None
    osint: Optional[OsintResult] = None

    # Video-specific
    frames_analyzed: Optional[int] = None
    video_duration: Optional[float] = None
    frame_timeline: Optional[list[FrameResult]] = None
    inconsistency_score: Optional[float] = None

    # Análisis temporal (solo videos)
    temporal_analysis: Optional[TemporalAnalysis] = None
    temporal_anomaly_detected: Optional[bool] = None   # campo de acceso rápido

    # Análisis semántico VLM — LLaVA-1.5-7b-hf
    semantic_analysis: Optional[SemanticAnalysis] = None

    # Uncertainty & OOD detection
    uncertainty: Optional[UncertaintyLevel] = None
    uncertainty_score: Optional[float] = None   # entropy 0–1

    # OOD — Detección de imágenes fuera del dominio forense (afiche, diseño, texto)
    is_ood: Optional[bool] = None               # True = imagen OOD (diseño/afiche/texto)
    ood_signal: Optional[bool] = None           # alias heredado (modelo-level OOD)
    ood_confidence: Optional[float] = None      # 0-1 confianza del detector OOD
    ood_score: Optional[float] = None           # score bruto combinado
    ood_signals: Optional[list[str]] = None     # señales individuales activadas

    risk_of_error: Optional[str] = None
    ensemble_method: Optional[str] = None       # meta_xgboost / fallback_weights

    # Cadena de custodia forense (enterprise)
    chain_of_custody: Optional[dict] = None      # sello criptográfico SHA-256 + HMAC

    # Internal
    progress: float = 0.0
    error: Optional[str] = None
    completed_at: Optional[datetime] = None

    # Backward compatibility — raw 0–1 probability
    fake_probability: Optional[float] = None
    real_probability: Optional[float] = None


class UploadResponse(BaseModel):
    task_id: str
    status: TaskStatus
    message: str


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    cuda_available: bool
    device: str
    version: str
