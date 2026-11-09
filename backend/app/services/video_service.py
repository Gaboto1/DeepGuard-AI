"""
Video analysis service v3 — frame-by-frame + temporal forensics.
Combina:
  1. Análisis de ensemble por frame (8 modelos: A-F en batch GPU + freq + SRM en CPU).
  2. Análisis de consistencia temporal (ViT embeddings + flujo óptico Farneback).

Corrección v3 vs v2:
  - predict_batch ahora incluye Model F (AI-Human Detector) — fix crítico.
  - freq_detector y SRM_detector se aplican por frame con corrección conservadora.
  - Consistencia con image_service: ambos pipelines usan el mismo ensemble de 8 modelos.
"""
import time
from pathlib import Path
from typing import Callable, Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image
from loguru import logger

from app.models.deepfake_detector import DeepfakeDetector
from app.models.face_detector import FaceDetector
from app.services.video_temporal_service import (
    run_temporal_analysis,
    apply_temporal_risk,
    TemporalAnalysisResult,
)
from app.config import settings

_executor = ThreadPoolExecutor(max_workers=1)

# Las correcciones por fotograma con las señales frecuencial y SRM se retiraron
# al medirlas invertidas (AUC 0.296 y 0.409). Sus umbrales y pesos se eliminan
# junto con ellas para no dejar constantes que sugieran que siguen activas.


def _extract_frames(
    video_path: Path, max_frames: int = 50
) -> tuple[list[Image.Image], float, int]:
    """
    Extrae frames uniformemente espaciados del video.
    Returns: (frames, fps, total_frame_count)
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    fps   = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total <= 0:
        cap.release()
        raise ValueError("Video appears to have no frames")

    n_samples = min(max_frames, total)
    indices   = np.linspace(0, total - 1, n_samples, dtype=int)

    frames: list[Image.Image] = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if not ret:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames.append(Image.fromarray(rgb))

    cap.release()
    logger.debug(f"Extraídos {len(frames)} frames (total={total}, fps={fps:.1f})")
    return frames, fps, total


def _run_video_analysis(
    video_path: Path,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> dict:
    """Análisis de video sincrónico — corre en thread pool."""
    start_total = time.time()

    detector      = DeepfakeDetector.get_instance()
    face_detector = FaceDetector.get_instance()

    frames, fps, total_frames = _extract_frames(video_path, settings.MAX_FRAMES)
    duration = total_frames / fps

    if not frames:
        raise ValueError("Could not extract frames from video")

    frame_results: list[dict] = []
    batch_size    = 8
    batches       = [frames[i:i+batch_size] for i in range(0, len(frames), batch_size)]
    frame_indices = np.linspace(0, total_frames - 1, len(frames), dtype=int)

    processed = 0
    for batch_idx, batch in enumerate(batches):

        # ── Detección de caras + selección de imagen de análisis ─────────────
        analysis_images: list[Image.Image] = []
        face_flags:      list[bool]        = []

        for frame in batch:
            face = face_detector.get_primary_face(frame)
            if face:
                analysis_images.append(face)
                face_flags.append(True)
            else:
                analysis_images.append(frame)
                face_flags.append(False)

        # ── Batch GPU: modelos A-F (Model F incluido desde v3) ───────────────
        predictions = detector.predict_batch(analysis_images, face_flags=face_flags)

        for j, (pred, face_detected, img) in enumerate(
            zip(predictions, face_flags, analysis_images)
        ):
            global_frame_idx = batch_idx * batch_size + j
            if global_frame_idx >= len(frame_indices):
                break

            frame_score = pred["fake_probability"]

            # ── Correcciones CPU por frame: retiradas ─────────────────────────
            # Aquí se empujaba el score del fotograma hacia las señales
            # frecuencial y SRM. Medidas sobre 1.100 imágenes de cinco fuentes,
            # ambas resultaron invertidas (AUC 0.296 y 0.409): puntúan más alto
            # el material auténtico que el sintético, de modo que la corrección
            # elevaba el score de los vídeos reales. Se mantiene el mismo
            # criterio que en el análisis de imagen (ver _calibrated_combine).
            frame_score = float(np.clip(frame_score, 0.0, 1.0))

            frame_idx_in_video = int(frame_indices[global_frame_idx])
            timestamp          = frame_idx_in_video / fps

            frame_results.append({
                "frame_index":     frame_idx_in_video,
                "timestamp":       round(timestamp, 3),
                "fake_probability": frame_score,
                "real_probability": 1.0 - frame_score,
                "face_detected":    face_detected,
            })

            processed += 1
            if progress_cb:
                progress_cb(processed / len(frames))

    fake_probs = [r["fake_probability"] for r in frame_results]
    avg_fake   = float(np.mean(fake_probs))
    std_fake   = float(np.std(fake_probs))

    # ── Análisis temporal ─────────────────────────────────────────────────────
    temporal_result: Optional[TemporalAnalysisResult] = None
    try:
        logger.info("Iniciando análisis temporal (ViT embeddings + flujo óptico)...")
        temporal_result = run_temporal_analysis(video_path)

        avg_fake_before = avg_fake
        avg_fake = apply_temporal_risk(avg_fake, temporal_result)

        if temporal_result.temporal_anomaly_detected:
            logger.info(
                f"Anomalía temporal: embed_var={temporal_result.temporal_variance:.4f} "
                f"max_spike={temporal_result.temporal_max_spike:.3f} "
                f"score {avg_fake_before:.3f} → {avg_fake:.3f}"
            )
    except Exception as e:
        logger.warning(f"Análisis temporal falló (no crítico): {e}")
        temporal_result = None

    total_time = time.time() - start_total

    return {
        "fake_probability":    avg_fake,
        "real_probability":    float(1.0 - avg_fake),
        "frames_analyzed":     len(frame_results),
        "video_duration":      round(duration, 2),
        "frame_timeline":      frame_results,
        "inconsistency_score": std_fake,
        "analysis_time":       total_time,
        "model_used":          detector.model_name,
        "device_used":         detector.device_name,
        "faces_detected":      sum(1 for r in frame_results if r["face_detected"]),
        "temporal_analysis":   temporal_result,
    }


async def analyze_video(
    video_path: Path,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, _run_video_analysis, video_path, progress_cb
    )
