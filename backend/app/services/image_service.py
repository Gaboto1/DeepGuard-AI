"""
Image analysis service — v5.3 (8-model ensemble: 6 GPU + freq + SRM).
"""
import time
from pathlib import Path
from typing import Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from loguru import logger

from app.models.deepfake_detector import (
    DeepfakeDetector, _model_a, _model_b, _model_c, _model_d, _model_e, _model_f,
    _calibrated_combine, _W_FACE, _W_NO_FACE,
)
from app.models.face_detector import FaceDetector
from app.models.frequency_detector import predict_frequency
from app.models.srm_detector import predict_srm
from app.models.ood_detector import detect_ood, apply_ood_penalty
from app.services.metadata_service import extract_metadata
from app.services.osint_service import build_osint_result
from app.utils.forensic_corrections import apply_forensic_corrections, build_correction_explanation
from app.api.schemas import ModelScore, EnsembleBreakdown

_executor = ThreadPoolExecutor(max_workers=2)

# Orden: A, B, C, D, E, F, freq, SRM — sincronizado con _W_NO_FACE / _W_FACE
_MODEL_DEFS = [
    ("a",    "Face-Deepfake ViT"),
    ("b",    "SDXL Detector"),
    ("c",    "EfficientNet (FF++)"),
    ("d",    "AI Art Detector"),
    ("e",    "SigLIP Deepfake"),
    ("f",    "AI-Human Detector"),
    ("freq", "Freq. Spectral"),
    ("srm",  "SRM Noise Residual"),
]


def _build_ensemble_breakdown(
    scores: list[Optional[float]],
    face_detected: bool,
    final_score: float,
) -> EnsembleBreakdown:
    w = list(_W_FACE if face_detected else _W_NO_FACE)
    mode = "face_detected" if face_detected else "no_face"

    total_w = sum(wt for wt, sc in zip(w, scores) if sc is not None)
    if total_w == 0:
        total_w = 1.0

    models = []
    for (key, name), score, weight in zip(_MODEL_DEFS, scores, w):
        eff_score = score if score is not None else 0.0
        norm_w    = weight / total_w if score is not None else 0.0
        contrib   = norm_w * eff_score
        models.append(ModelScore(
            name=name,
            score=round(eff_score, 4),
            weight=round(norm_w, 3),
            contribution=round(contrib, 4),
            score_pct=round(eff_score * 100, 1),
        ))

    return EnsembleBreakdown(
        models=models,
        weights_mode=mode,
        final_probability=round(final_score, 4),
    )


def _run_image_analysis(image_path: Path) -> dict:
    start_total = time.time()

    detector      = DeepfakeDetector.get_instance()
    face_detector = FaceDetector.get_instance()

    image = Image.open(image_path).convert("RGB")

    # ── Pre-análisis OOD ──────────────────────────────────────────────────────
    ood_result = detect_ood(image)
    if ood_result["is_ood"]:
        logger.info(
            f"OOD detectado: score={ood_result['ood_score']:.3f} "
            f"conf={ood_result['ood_confidence']:.2f} "
            f"señales={ood_result['ood_signals']}"
        )

    faces         = face_detector.detect_faces(image)
    faces_count   = len(faces)
    face_detected = faces_count > 0

    # Señales auxiliares CPU (0 VRAM) — ejecutadas una sola vez sobre imagen completa
    freq_result = predict_frequency(image)
    score_freq  = freq_result.get("fake_probability", 0.5)

    srm_result  = predict_srm(image)
    score_srm   = srm_result.get("fake_probability", 0.5)

    # ── Predict — 8 modelos ───────────────────────────────────────────────────
    def _predict_all(img: Image.Image, face: bool) -> tuple[list[Optional[float]], float]:
        ra = _model_a.predict(img)
        rb = _model_b.predict(img)
        rc = _model_c.predict(img)
        rd = _model_d.predict(img)
        re = _model_e.predict(img)
        rf = _model_f.predict(img)
        scores_raw = [
            ra["fake_probability"] if ra else None,
            rb["fake_probability"] if rb else None,
            rc["fake_probability"] if rc else None,
            rd["fake_probability"] if rd else None,
            re["fake_probability"] if re else None,
            rf["fake_probability"] if rf else None,
            score_freq,   # slot 6: freq spectral
            score_srm,    # slot 7: SRM noise residual
        ]
        ens, _ = _calibrated_combine(
            scores_raw[0] or 0.5, scores_raw[1] or 0.5, scores_raw[2],
            face=face,
            score_d=scores_raw[3], score_e=scores_raw[4],
            score_f=scores_raw[5], score_freq=scores_raw[6],
            score_srm=scores_raw[7],
        )
        return scores_raw, ens

    full_scores, full_ens = _predict_all(image, face=False)

    if face_detected:
        face_scores, face_ens = _predict_all(faces[0], face=True)
        final_score  = 0.60 * face_ens + 0.40 * full_ens
        blend_scores = [
            (0.60 * (f or 0.0) + 0.40 * (u or 0.0)) if (f is not None or u is not None) else None
            for f, u in zip(face_scores, full_scores)
        ]
        use_face_mode = True
        logger.debug(f"Face blend: face={face_ens:.2f} full={full_ens:.2f} → {final_score:.2f}")
    else:
        final_score  = full_ens
        blend_scores = full_scores
        use_face_mode = False

    # ── Penalización OOD ──────────────────────────────────────────────────────
    raw_score   = final_score
    final_score = apply_ood_penalty(final_score, ood_result)

    if ood_result["is_ood"] and abs(raw_score - final_score) > 0.005:
        logger.debug(
            f"OOD penalty: {raw_score:.3f} → {final_score:.3f} "
            f"(α={ood_result['penalty_alpha']:.3f})"
        )

    # ── Correcciones forenses post-hoc ────────────────────────────────────────
    # Todos los 8 modelos disponibles para las reglas de corrección.
    model_scores_for_correction = {
        "face_deepfake_vit":  blend_scores[0],
        "sdxl_detector":      blend_scores[1],
        "efficientnet_ffpp":  blend_scores[2],
        "ai_art_detector":    blend_scores[3],
        "siglip_deepfake":    blend_scores[4],
        "ai_human_detector":  blend_scores[5],   # necesario para OOD bypass v2
        "frequency_spectral": blend_scores[6],
        "srm_noise_detector": blend_scores[7],   # necesario para OOD bypass v2
    }
    final_score, correction_type, correction_details = apply_forensic_corrections(
        final_score, model_scores_for_correction, ood_result
    )
    correction_explanation = build_correction_explanation(correction_type, correction_details)

    ensemble = _build_ensemble_breakdown(blend_scores, use_face_mode, final_score)

    # ── Grad-CAM ──────────────────────────────────────────────────────────────
    heatmap_b64: Optional[str] = None
    ood_bypassed = correction_type == "ood_bypass"
    if final_score > 0.38 and (not ood_result["is_ood"] or ood_bypassed):
        try:
            target = faces[0] if face_detected else image
            heatmap_b64 = detector.generate_heatmap(target, target_class=1)
        except Exception as e:
            logger.debug(f"Heatmap skipped: {e}")

    # ── Metadata + OSINT ──────────────────────────────────────────────────────
    metadata = extract_metadata(image_path)
    osint    = build_osint_result(image_path)

    total_time = time.time() - start_total

    # Meta-info (reutiliza scores ya calculados — sin inferencia extra)
    _, _pm = _calibrated_combine(
        blend_scores[0] or 0.5, blend_scores[1] or 0.5, blend_scores[2],
        face=use_face_mode,
        score_d=blend_scores[3], score_e=blend_scores[4],
        score_f=blend_scores[5], score_freq=blend_scores[6],
        score_srm=blend_scores[7],
    )
    ens_meta = {
        "method":     _pm.get("ensemble_method", "unknown"),
        "std":        _pm.get("std"),
        "entropy":    _pm.get("entropy"),
        "ood_signal": _pm.get("ood_signal", False),
    }

    def _r(v: Optional[float]) -> Optional[float]:
        return round(v, 4) if v is not None else None

    return {
        "fake_probability": final_score,
        "real_probability": 1.0 - final_score,
        "faces_detected":   faces_count,
        "heatmap":          heatmap_b64,
        "analysis_time":    total_time,
        "model_used":       detector.model_name,
        "device_used":      detector.device_name,
        "ensemble":         ensemble,
        "ensemble_meta":    ens_meta,
        "model_scores": {
            "face_deepfake_vit":  _r(blend_scores[0]),
            "sdxl_detector":      _r(blend_scores[1]),
            "efficientnet_ffpp":  _r(blend_scores[2]),
            "ai_art_detector":    _r(blend_scores[3]),
            "siglip_deepfake":    _r(blend_scores[4]),
            "ai_human_detector":  _r(blend_scores[5]),
            "frequency_spectral": _r(blend_scores[6]),
            "srm_noise_detector": _r(blend_scores[7]),
        },
        "forensic_correction_type":        correction_type,
        "forensic_correction_details":     correction_details,
        "forensic_correction_explanation": correction_explanation,
        "metadata": metadata,
        "osint":    osint,
        "is_ood":          ood_result["is_ood"],
        "ood_confidence":  ood_result["ood_confidence"],
        "ood_score":       ood_result["ood_score"],
        "ood_signals":     ood_result["ood_signals"],
    }


async def analyze_image(image_path: Path) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _run_image_analysis, image_path)
