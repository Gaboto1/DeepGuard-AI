"""
Video analysis service v2 — frame-by-frame + temporal forensics.
Combina:
  1. Análisis de ensemble por frame (5 modelos).
  2. Análisis de consistencia temporal (ViT embeddings + flujo óptico Farneback).
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


def _extract_frames(
    video_path: Path, max_frames: int = 50
) -> tuple[list[Image.Image], float, int]:
    """
    Extract evenly-spaced frames from a video.
    Returns: (frames, fps, total_frame_count)
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total <= 0:
        cap.release()
        raise ValueError("Video appears to have no frames")

    n_samples = min(max_frames, total)
    indices = np.linspace(0, total - 1, n_samples, dtype=int)

    frames: list[Image.Image] = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if not ret:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames.append(Image.fromarray(rgb))

    cap.release()
    logger.debug(f"Extracted {len(frames)} frames (total={total}, fps={fps:.1f})")
    return frames, fps, total


def _run_video_analysis(
    video_path: Path,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> dict:
    """Synchronous video analysis — runs in thread pool."""
    start_total = time.time()

    detector = DeepfakeDetector.get_instance()
    face_detector = FaceDetector.get_instance()

    frames, fps, total_frames = _extract_frames(video_path, settings.MAX_FRAMES)
    duration = total_frames / fps

    if not frames:
        raise ValueError("Could not extract frames from video")

    frame_results = []
    batch_size = 8
    batches = [frames[i:i+batch_size] for i in range(0, len(frames), batch_size)]
    frame_indices = np.linspace(0, total_frames - 1, len(frames), dtype=int)

    processed = 0
    for batch_idx, batch in enumerate(batches):
        # Detect faces per frame — needed for ensemble weighting
        analysis_images = []
        face_flags = []

        for frame in batch:
            face = face_detector.get_primary_face(frame)
            if face:
                analysis_images.append(face)
                face_flags.append(True)
            else:
                analysis_images.append(frame)
                face_flags.append(False)

        # Batch inference with face flags for adaptive ensemble weights
        predictions = detector.predict_batch(analysis_images, face_flags=face_flags)

        for j, (pred, face_detected) in enumerate(zip(predictions, face_flags)):
            global_frame_idx = batch_idx * batch_size + j
            if global_frame_idx >= len(frame_indices):
                break
            frame_idx_in_video = int(frame_indices[global_frame_idx])
            timestamp = frame_idx_in_video / fps

            frame_results.append({
                "frame_index": frame_idx_in_video,
                "timestamp": round(timestamp, 3),
                "fake_probability": pred["fake_probability"],
                "real_probability": pred["real_probability"],
                "face_detected": face_detected,
            })

            processed += 1
            if progress_cb:
                progress_cb(processed / len(frames))

    fake_probs = [r["fake_probability"] for r in frame_results]
    avg_fake   = float(np.mean(fake_probs))
    std_fake   = float(np.std(fake_probs))

    # ── Análisis temporal ─────────────────────────────────────────────────────
    # Corre después del análisis de ensemble para no competir por GPU.
    # Usa keyframes a 3 FPS (puede diferir del sampling del ensemble).
    temporal_result: Optional[TemporalAnalysisResult] = None
    try:
        logger.info("Iniciando análisis temporal (ViT embeddings + flujo óptico)...")
        temporal_result = run_temporal_analysis(video_path)

        # Aplicar multiplicador de riesgo temporal al score del ensemble
        avg_fake_before = avg_fake
        avg_fake = apply_temporal_risk(avg_fake, temporal_result)

        if temporal_result.temporal_anomaly_detected:
            logger.info(
                f"Anomalía temporal detectada: "
                f"embed_var={temporal_result.temporal_variance:.4f} "
                f"max_spike={temporal_result.temporal_max_spike:.3f} "
                f"score {avg_fake_before:.3f} → {avg_fake:.3f}"
            )
    except Exception as e:
        logger.warning(f"Análisis temporal falló (no crítico): {e}")
        temporal_result = None

    total_time = time.time() - start_total

    result = {
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
    return result


async def analyze_video(
    video_path: Path,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, _run_video_analysis, video_path, progress_cb
    )
