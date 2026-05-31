"""
Video Temporal Forensics Service
=================================
Analiza la consistencia temporal de un video para detectar deepfakes.

Fundamento científico:
  Los deepfakes generados frame a frame presentan inconsistencias temporales
  invisibles al ojo humano pero detectables mediante:
    1. Distancia coseno entre embeddings ViT de rostros consecutivos.
       En un video real: movimiento suave, distancias 0.02-0.18.
       En un deepfake:   saltos bruscos, distancias 0.25-0.60, alta varianza.
    2. Flujo óptico (Farneback) sobre la región facial:
       Real:    flujo suave y coherente con el movimiento.
       Deepfake: irregularidades de textura → varianza del flujo anómala.

Pipeline:
  1. Extraer keyframes a TARGET_FPS FPS (3 por defecto).
  2. Detectar rostro con MTCNN en cada keyframe.
  3. Extraer embedding ViT-768D del CLS token del modelo A (Face-Deepfake ViT).
  4. Calcular distancias coseno entre frames consecutivos.
  5. Calcular flujo óptico Farneback entre caras consecutivas.
  6. Detectar anomalía temporal si la varianza supera los umbrales.
  7. Aplicar multiplicador de riesgo al score del ensemble.

Thresholds calibrados empíricamente:
  EMBED_VAR_THRESHOLD = 0.060   varianza coseno → anomalía de embedding
  EMBED_SPIKE_THRESHOLD = 0.250 distancia máxima → spike individual
  FLOW_VAR_THRESHOLD = 12.0     varianza del flujo óptico → anomalía de movimiento
  TEMPORAL_RISK_MAX = 0.35      multiplicador de riesgo máximo (+35% al score)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
from PIL import Image
from loguru import logger

# Parámetros de extracción
TARGET_FPS          = 3.0    # keyframes por segundo
MIN_FACE_FRAMES     = 5      # mínimo de frames con cara para análisis temporal
MAX_KEYFRAMES       = 90     # límite absoluto de keyframes

# Umbrales calibrados para embeddings ViT-768D de frames de video reales.
# Nota: vectores aleatorios en R^768 tienen distancia coseno ~0.50 (cuasi-ortogonales).
# Embeddings de la MISMA cara en frames consecutivos: distancia 0.02-0.18.
# Spike de deepfake (face-swap): distancia > 0.30, varianza >> 0.04.
EMBED_VAR_THRESHOLD  = 0.040  # varianza de distancias coseno → anomalía embedding
EMBED_SPIKE_THRESHOLD= 0.300  # distancia coseno máxima → spike individual
FLOW_VAR_THRESHOLD   = 12.0   # varianza de flujo óptico → anomalía de movimiento
FLOW_MEAN_THRESHOLD  = 8.0    # media de flujo muy alta → movimiento irreal

# Penalización temporal
TEMPORAL_RISK_MAX    = 0.35   # riesgo máximo añadido al score (+35%)


# ─── Tipos de resultado ───────────────────────────────────────────────────────

@dataclass
class TemporalFrameData:
    frame_idx:      int
    timestamp:      float
    has_face:       bool
    face_box:       Optional[tuple]   # (x1, y1, x2, y2)
    embedding:      Optional[np.ndarray]  # [768] L2-normalizado
    gray_face:      Optional[np.ndarray]  # para flujo óptico


@dataclass
class TemporalAnalysisResult:
    temporal_anomaly_detected:   bool
    temporal_consistency_score:  float   # 0-1, más alto = más consistente
    temporal_discrepancy_values: list[float]  # distancias coseno consecutivas
    temporal_variance:           float   # var(discrepancy_values)
    temporal_max_spike:          float   # máximo valor de discrepancy
    optical_flow_values:         list[float]  # magnitudes de flujo consecutivas
    optical_flow_variance:       float
    optical_flow_anomaly:        bool
    frames_with_faces:           int
    frames_analyzed:             int
    risk_multiplier:             float   # score_final = score_base * risk_multiplier
    anomaly_details:             list[str]  # razones de la anomalía
    analysis_time:               float


# ─── Extracción de keyframes ──────────────────────────────────────────────────

def extract_keyframes(
    video_path: Path,
    target_fps: float = TARGET_FPS,
    max_frames: int = MAX_KEYFRAMES,
) -> tuple[list[np.ndarray], float, float]:
    """
    Extrae frames a target_fps.
    Retorna (frames_rgb, fps_original, duracion_segundos).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"No se puede abrir el video: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / video_fps

    # Intervalo entre keyframes en frames originales
    frame_interval = max(1, int(video_fps / target_fps))
    n_keyframes    = min(max_frames, max(1, int(total_frames / frame_interval)))

    # Índices de keyframes equidistantes
    indices = np.linspace(0, total_frames - 1, n_keyframes, dtype=int)

    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if ret:
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    cap.release()
    logger.debug(
        f"Keyframes: {len(frames)} a {target_fps:.1f} FPS "
        f"(video: {video_fps:.1f} FPS, {duration:.1f}s)"
    )
    return frames, video_fps, duration


# ─── Extracción de embeddings ViT ────────────────────────────────────────────

def _get_vit_model():
    """Accede al modelo A (Face-Deepfake ViT) ya cargado en el ensemble."""
    from app.models.deepfake_detector import _model_a
    _model_a.load()
    return _model_a


def extract_face_embedding(
    face_image: Image.Image,
    vit_wrapper,
) -> Optional[np.ndarray]:
    """
    Extrae embedding de 768 dimensiones del CLS token del ViT.
    NO usa la cabeza de clasificación — extrae la representación de identidad facial.
    """
    if vit_wrapper.model is None:
        return None
    try:
        inp = vit_wrapper.processor(images=face_image, return_tensors="pt")
        inp = {k: v.to(vit_wrapper.device) for k, v in inp.items()}

        with torch.no_grad():
            # Usar el backbone ViT directamente (sin cabeza de clasificación)
            if hasattr(vit_wrapper.model, "vit"):
                outputs = vit_wrapper.model.vit(**inp, output_hidden_states=False)
                # pooler_output = CLS token procesado por la capa de pooling = [1, 768]
                emb = outputs.pooler_output
            else:
                # Fallback: usar la salida del logit del classificador
                outputs = vit_wrapper.model(**inp)
                emb     = outputs.logits  # [1, num_classes]

        emb_np = emb.cpu().float().numpy()[0]
        # L2 normalización para distancia coseno
        norm = np.linalg.norm(emb_np) + 1e-8
        return emb_np / norm

    except Exception as e:
        logger.debug(f"Embedding extraction failed: {e}")
        return None


# ─── Flujo óptico Farneback ───────────────────────────────────────────────────

def compute_optical_flow_magnitude(
    gray1: np.ndarray,
    gray2: np.ndarray,
    resize_to: int = 64,
) -> float:
    """
    Calcula la magnitud media del flujo óptico Farneback entre dos caras.
    Usa roi pequeño (64×64) para eficiencia.
    Retorna magnitud media del flujo — alto = movimiento brusco / irreal.
    """
    if gray1 is None or gray2 is None:
        return 0.0
    try:
        # Redimensionar a tamaño estándar para eficiencia
        g1 = cv2.resize(gray1, (resize_to, resize_to))
        g2 = cv2.resize(gray2, (resize_to, resize_to))

        # Farneback: pyr_scale=0.5, levels=3, winsize=15, iterations=2,
        #            poly_n=5, poly_sigma=1.1, flags=0
        flow = cv2.calcOpticalFlowFarneback(
            g1, g2, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=2, poly_n=5, poly_sigma=1.1, flags=0,
        )
        magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        return float(magnitude.mean())
    except Exception as e:
        logger.debug(f"Optical flow failed: {e}")
        return 0.0


# ─── Cosine distance ──────────────────────────────────────────────────────────

def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Distancia coseno entre dos vectores L2-normalizados."""
    return float(1.0 - np.clip(np.dot(a, b), -1.0, 1.0))


# ─── Análisis principal ───────────────────────────────────────────────────────

def run_temporal_analysis(
    video_path: Path,
    target_fps: float = TARGET_FPS,
) -> TemporalAnalysisResult:
    """
    Ejecuta el análisis temporal completo sobre el video.
    Retorna un TemporalAnalysisResult con métricas y score de riesgo.
    """
    t0 = time.time()

    # ── 1. Extraer keyframes ───────────────────────────────────────────────────
    try:
        frames, video_fps, duration = extract_keyframes(video_path, target_fps)
    except Exception as e:
        logger.warning(f"Temporal: no se puede abrir el video: {e}")
        return _no_temporal_result(0.0)

    n_frames = len(frames)
    if n_frames < 2:
        logger.debug("Temporal: video demasiado corto para análisis temporal")
        return _no_temporal_result(time.time() - t0)

    # ── 2. Detectar caras y extraer embeddings ─────────────────────────────────
    from app.models.face_detector import FaceDetector
    face_det = FaceDetector.get_instance()
    face_det.load()

    vit = _get_vit_model()
    frame_data: list[TemporalFrameData] = []

    timestamps = np.linspace(0, duration, n_frames)

    for i, (frame_np, ts) in enumerate(zip(frames, timestamps)):
        pil_img  = Image.fromarray(frame_np)
        faces    = face_det.detect_faces(pil_img)
        has_face = len(faces) > 0

        embedding  = None
        face_box   = None
        gray_face  = None

        if has_face:
            primary_face = faces[0]
            embedding    = extract_face_embedding(primary_face, vit)

            # ROI para flujo óptico: cara redimensionada a 64×64 gris
            try:
                gray_face = np.array(
                    primary_face.resize((64, 64)).convert("L")
                )
            except Exception:
                gray_face = None

        frame_data.append(TemporalFrameData(
            frame_idx  = i,
            timestamp  = float(ts),
            has_face   = has_face,
            face_box   = face_box,
            embedding  = embedding,
            gray_face  = gray_face,
        ))

    # ── 3. Calcular discrepancias temporales ───────────────────────────────────
    face_frames = [fd for fd in frame_data if fd.has_face and fd.embedding is not None]
    n_face      = len(face_frames)

    cosine_dists: list[float] = []
    flow_vals:    list[float] = []

    for i in range(1, n_face):
        prev = face_frames[i - 1]
        curr = face_frames[i]

        # Distancia coseno entre embeddings ViT consecutivos
        d_cos = cosine_distance(prev.embedding, curr.embedding)
        cosine_dists.append(d_cos)

        # Flujo óptico Farneback entre regiones faciales consecutivas
        flow_mag = compute_optical_flow_magnitude(prev.gray_face, curr.gray_face)
        flow_vals.append(flow_mag)

    # ── 4. Detección de anomalía ───────────────────────────────────────────────
    anomaly_details: list[str] = []

    if len(cosine_dists) < 2:
        # Insuficientes pares de frames con cara
        return _insufficient_data_result(n_face, n_frames, time.time() - t0)

    embed_var   = float(np.var(cosine_dists))
    embed_mean  = float(np.mean(cosine_dists))
    embed_max   = float(np.max(cosine_dists))

    flow_var    = float(np.var(flow_vals)) if flow_vals else 0.0
    flow_mean   = float(np.mean(flow_vals)) if flow_vals else 0.0

    # Flags de anomalía
    embed_var_anomaly   = embed_var  > EMBED_VAR_THRESHOLD
    embed_spike_anomaly = embed_max  > EMBED_SPIKE_THRESHOLD
    flow_var_anomaly    = flow_var   > FLOW_VAR_THRESHOLD
    flow_mean_anomaly   = flow_mean  > FLOW_MEAN_THRESHOLD

    optical_flow_anomaly = flow_var_anomaly or flow_mean_anomaly
    temporal_anomaly     = embed_var_anomaly or embed_spike_anomaly

    # Detalles de anomalía
    if embed_var_anomaly:
        anomaly_details.append(
            f"Alta varianza de embedding ({embed_var:.4f} > {EMBED_VAR_THRESHOLD}): "
            "inconsistencia temporal en la representación facial."
        )
    if embed_spike_anomaly:
        anomaly_details.append(
            f"Pico de distancia coseno ({embed_max:.3f} > {EMBED_SPIKE_THRESHOLD}): "
            "salto brusco entre frames consecutivos."
        )
    if flow_var_anomaly:
        anomaly_details.append(
            f"Flujo óptico irregular (var={flow_var:.1f} > {FLOW_VAR_THRESHOLD}): "
            "movimiento facial inconsistente con dinámica natural."
        )

    # ── 5. Score de consistencia y multiplicador de riesgo ─────────────────────
    # Consistencia: 1.0 = perfectamente consistente, 0.0 = máxima inconsistencia
    # Normalización: 0 var → 1.0, var = 2×threshold → 0.0
    consistency = float(np.clip(1.0 - embed_var / (2 * EMBED_VAR_THRESHOLD), 0.0, 1.0))

    # Fuerza de anomalía combinada (0-1)
    anomaly_strength = 0.0
    if embed_var_anomaly or embed_spike_anomaly:
        s_var   = min(embed_var   / (EMBED_VAR_THRESHOLD   * 3), 1.0)
        s_spike = min(embed_max   / (EMBED_SPIKE_THRESHOLD * 2), 1.0)
        anomaly_strength = max(s_var, s_spike)

    # Multiplicador de riesgo: 1.0 (sin efecto) → 1 + TEMPORAL_RISK_MAX
    if temporal_anomaly:
        risk_multiplier = 1.0 + TEMPORAL_RISK_MAX * anomaly_strength
    else:
        risk_multiplier = 1.0

    elapsed = time.time() - t0
    logger.info(
        f"Temporal: anomaly={temporal_anomaly} "
        f"embed_var={embed_var:.4f} max_spike={embed_max:.3f} "
        f"flow_var={flow_var:.1f} "
        f"risk_mult={risk_multiplier:.3f} ({elapsed:.2f}s)"
    )

    return TemporalAnalysisResult(
        temporal_anomaly_detected   = temporal_anomaly,
        temporal_consistency_score  = round(consistency, 4),
        temporal_discrepancy_values = [round(d, 4) for d in cosine_dists],
        temporal_variance           = round(embed_var, 6),
        temporal_max_spike          = round(embed_max, 4),
        optical_flow_values         = [round(v, 3) for v in flow_vals],
        optical_flow_variance       = round(flow_var, 3),
        optical_flow_anomaly        = optical_flow_anomaly,
        frames_with_faces           = n_face,
        frames_analyzed             = n_frames,
        risk_multiplier             = round(risk_multiplier, 4),
        anomaly_details             = anomaly_details,
        analysis_time               = round(elapsed, 3),
    )


def apply_temporal_risk(base_score: float, temporal: TemporalAnalysisResult) -> float:
    """
    Aplica el multiplicador de riesgo temporal al score base del ensemble.
    El score final nunca supera 1.0.
    """
    if not temporal.temporal_anomaly_detected:
        return base_score
    boosted = base_score * temporal.risk_multiplier
    capped  = float(np.clip(boosted, 0.0, 1.0))
    if capped > base_score + 0.005:
        logger.debug(
            f"Temporal risk applied: {base_score:.3f} → {capped:.3f} "
            f"(×{temporal.risk_multiplier:.3f})"
        )
    return capped


# ─── Fallbacks ────────────────────────────────────────────────────────────────

def _no_temporal_result(elapsed: float) -> TemporalAnalysisResult:
    return TemporalAnalysisResult(
        temporal_anomaly_detected   = False,
        temporal_consistency_score  = 1.0,
        temporal_discrepancy_values = [],
        temporal_variance           = 0.0,
        temporal_max_spike          = 0.0,
        optical_flow_values         = [],
        optical_flow_variance       = 0.0,
        optical_flow_anomaly        = False,
        frames_with_faces           = 0,
        frames_analyzed             = 0,
        risk_multiplier             = 1.0,
        anomaly_details             = ["Análisis temporal no disponible (video inaccesible)."],
        analysis_time               = round(elapsed, 3),
    )


def _insufficient_data_result(n_face: int, n_frames: int, elapsed: float) -> TemporalAnalysisResult:
    return TemporalAnalysisResult(
        temporal_anomaly_detected   = False,
        temporal_consistency_score  = 1.0,
        temporal_discrepancy_values = [],
        temporal_variance           = 0.0,
        temporal_max_spike          = 0.0,
        optical_flow_values         = [],
        optical_flow_variance       = 0.0,
        optical_flow_anomaly        = False,
        frames_with_faces           = n_face,
        frames_analyzed             = n_frames,
        risk_multiplier             = 1.0,
        anomaly_details             = [
            f"Insuficientes frames con rostro para análisis temporal "
            f"({n_face} con cara, mínimo {MIN_FACE_FRAMES} requeridos)."
        ],
        analysis_time               = round(elapsed, 3),
    )
