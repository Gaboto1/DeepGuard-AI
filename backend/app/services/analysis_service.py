"""
Central task management — v2.0 forensic edition.
Uses EvidenceLevel + ModelAgreement instead of binary verdicts.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from loguru import logger

from app.api.schemas import AnalysisResult, TaskStatus, FrameResult
from app.services.image_service import analyze_image
from app.services.video_service import _run_video_analysis
from app.services.custody_service import (
    compute_file_sha256, generate_custody_seal, persist_custody_report,
)
from app.services.forensic_metadata_service import (
    extract_forensic_metadata, apply_metadata_risk_to_score,
)
from app.utils.helpers import (
    get_evidence_level, get_model_agreement, get_uncertainty,
    generate_forensic_explanation, new_task_id, now,
)

_tasks: dict[str, AnalysisResult] = {}
_lock  = asyncio.Lock()
_video_executor = ThreadPoolExecutor(max_workers=1)
MAX_HISTORY = 100


async def create_task(filename: str, file_type: str) -> AnalysisResult:
    task_id = new_task_id()
    task = AnalysisResult(
        task_id=task_id,
        status=TaskStatus.PENDING,
        file_type=file_type,
        filename=filename,
        created_at=now(),
        progress=0.0,
    )
    async with _lock:
        if len(_tasks) >= MAX_HISTORY:
            oldest = sorted(_tasks.values(), key=lambda t: t.created_at)[0]
            del _tasks[oldest.task_id]
        _tasks[task_id] = task
    return task


async def get_task(task_id: str) -> Optional[AnalysisResult]:
    async with _lock:
        return _tasks.get(task_id)


async def list_tasks(limit: int = 20) -> list[AnalysisResult]:
    async with _lock:
        return sorted(_tasks.values(), key=lambda t: t.created_at, reverse=True)[:limit]


async def _update_task(task_id: str, **kwargs) -> None:
    async with _lock:
        if task_id in _tasks:
            task = _tasks[task_id]
            for k, v in kwargs.items():
                setattr(task, k, v)


async def run_analysis(task_id: str, file_path: Path, file_type: str) -> None:
    await _update_task(task_id, status=TaskStatus.PROCESSING, progress=0.05)

    try:
        # Cadena de custodia — SHA-256 del archivo original antes del análisis
        file_sha256 = await asyncio.get_event_loop().run_in_executor(
            None, compute_file_sha256, file_path
        )

        if file_type == "image":
            result = await analyze_image(file_path)

            # Metadatos forenses avanzados + señal de riesgo
            forensic_meta = await asyncio.get_event_loop().run_in_executor(
                None, extract_forensic_metadata, file_path
            )
            # Aplicar señal de metadatos al score
            adj_prob, meta_corr = apply_metadata_risk_to_score(
                result["fake_probability"], forensic_meta
            )

            # ── Análisis semántico VLM (LLaVA-1.5-7b-hf) ──────────────────────
            # Se ejecuta en executor para no bloquear el loop asíncrono.
            # Si LLaVA no está cargado, retorna resultado neutro sin degradar el análisis.
            from app.services.semantic_inspection_service import (
                analyze_semantic_coherence, apply_semantic_fusion,
            )
            semantic_raw = await asyncio.get_event_loop().run_in_executor(
                None, analyze_semantic_coherence, file_path
            )

            # Fusión semántica con el score del ensemble
            face_detected = (result.get("faces_detected", 0) or 0) > 0
            fused_prob, fusion_type, fusion_note = apply_semantic_fusion(
                adj_prob if meta_corr else result["fake_probability"],
                semantic_raw,
                face_detected,
            )
            if fused_prob != adj_prob:
                adj_prob = fused_prob
            if meta_corr:
                result["fake_probability"]    = adj_prob
                result["real_probability"]    = 1.0 - adj_prob
                result["metadata_correction"] = meta_corr

            prob         = result["fake_probability"]
            ev_level     = get_evidence_level(prob)
            model_scores = result.get("model_scores", {})
            raw_scores   = [v for v in model_scores.values() if v is not None]
            agreement, std = get_model_agreement(raw_scores)

            # Uncertainty quantification
            ens_meta    = result.get("ensemble_meta", {}) or {}
            ood_signal  = ens_meta.get("ood_signal", False)
            uncertainty_level, entropy_score, risk_desc = get_uncertainty(prob, std, ood_signal)
            ens_method  = ens_meta.get("method", "unknown")

            # OOD fields from image service
            is_ood          = result.get("is_ood", False)
            ood_confidence  = result.get("ood_confidence", 0.0)
            ood_score_raw   = result.get("ood_score", 0.0)
            ood_signals_list= result.get("ood_signals", [])

            explanation = generate_forensic_explanation(
                probability=prob,
                evidence_level=ev_level,
                model_agreement=agreement,
                file_type="image",
                faces_detected=result.get("faces_detected", 0),
                model_scores=model_scores,
                is_ood=is_ood,
                ood_signals=ood_signals_list,
            )

            # Construir objeto SemanticAnalysis para el schema
            from app.api.schemas import SemanticAnalysis as SemanticSchema
            semantic_obj = None
            try:
                sem_score = semantic_raw.get("risk_score", -1)
                sem_avail = sem_score >= 0
                semantic_obj = SemanticSchema(
                    risk_score             = max(0, sem_score),
                    risk_score_normalized  = semantic_raw.get("risk_score_normalized"),
                    semantic_observations  = semantic_raw.get("semantic_observations", ""),
                    model_used             = semantic_raw.get("model_used", ""),
                    quantization           = semantic_raw.get("quantization", ""),
                    analysis_time          = semantic_raw.get("analysis_time", 0.0),
                    fusion_type            = fusion_type,
                    fusion_note            = fusion_note,
                    available              = sem_avail,
                )
            except Exception as e_schema:
                logger.debug(f"SemanticAnalysis schema build failed: {e_schema}")

            await _update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=1.0,
                fake_probability=prob,
                real_probability=result["real_probability"],
                manipulation_probability=round(prob * 100, 1),
                evidence_level=ev_level,
                model_agreement=agreement,
                model_agreement_std=round(std, 4),
                uncertainty=uncertainty_level,
                uncertainty_score=entropy_score,
                # OOD
                is_ood=is_ood,
                ood_signal=ood_signal,
                ood_confidence=ood_confidence,
                ood_score=ood_score_raw,
                ood_signals=ood_signals_list,
                risk_of_error=risk_desc,
                ensemble_method=ens_method,
                explanation=explanation,
                analysis_time=result["analysis_time"],
                model_used=result["model_used"],
                device_used=result["device_used"],
                faces_detected=result.get("faces_detected", 0),
                heatmap=result.get("heatmap"),
                ensemble=result.get("ensemble"),
                metadata_analysis=result.get("metadata"),
                osint=result.get("osint"),
                semantic_analysis=semantic_obj,
                completed_at=now(),
            )

            # Sello de cadena de custodia (v2 incluye score semántico)
            sem_score_for_seal = semantic_raw.get("risk_score") if semantic_raw else None
            try:
                custody_seal = generate_custody_seal(
                    task_id=task_id,
                    file_sha256=file_sha256,
                    filename=_tasks[task_id].filename if task_id in _tasks else "unknown",
                    file_type="image",
                    final_score=prob,
                    evidence_level=ev_level.value,
                    semantic_score=sem_score_for_seal,
                )
                await _update_task(task_id, chain_of_custody=custody_seal)
                persist_custody_report(custody_seal, {"manipulation_probability": round(prob * 100, 2)})
            except Exception as e:
                logger.warning(f"Custody seal failed (non-critical): {e}")

        elif file_type == "video":
            progress_value: list[float] = [0.05]

            def progress_cb(p: float) -> None:
                progress_value[0] = 0.05 + p * 0.90

            loop   = asyncio.get_event_loop()
            future = loop.run_in_executor(_video_executor, _run_video_analysis, file_path, progress_cb)

            while not future.done():
                await _update_task(task_id, progress=progress_value[0])
                await asyncio.sleep(0.8)

            result = await future

            prob     = result["fake_probability"]
            ev_level = get_evidence_level(prob)
            agreement, std = get_model_agreement([prob])  # single aggregated score for video

            # Datos del análisis temporal
            temporal_raw = result.get("temporal_analysis")
            temporal_obj = None
            if temporal_raw is not None:
                from app.api.schemas import TemporalAnalysis
                temporal_obj = TemporalAnalysis(
                    temporal_anomaly_detected   = temporal_raw.temporal_anomaly_detected,
                    temporal_consistency_score  = temporal_raw.temporal_consistency_score,
                    temporal_discrepancy_values = temporal_raw.temporal_discrepancy_values,
                    temporal_variance           = temporal_raw.temporal_variance,
                    temporal_max_spike          = temporal_raw.temporal_max_spike,
                    optical_flow_values         = temporal_raw.optical_flow_values,
                    optical_flow_variance       = temporal_raw.optical_flow_variance,
                    optical_flow_anomaly        = temporal_raw.optical_flow_anomaly,
                    frames_with_faces           = temporal_raw.frames_with_faces,
                    frames_analyzed             = temporal_raw.frames_analyzed,
                    risk_multiplier             = temporal_raw.risk_multiplier,
                    anomaly_details             = temporal_raw.anomaly_details,
                    analysis_time               = temporal_raw.analysis_time,
                )

            explanation = generate_forensic_explanation(
                probability=prob,
                evidence_level=ev_level,
                model_agreement=agreement,
                file_type="video",
                frames_analyzed=result.get("frames_analyzed", 0),
                inconsistency_score=result.get("inconsistency_score", 0.0),
            )

            # Añadir nota temporal a la explicación si se detectó anomalía
            if temporal_obj and temporal_obj.temporal_anomaly_detected:
                explanation += (
                    " ⚠ Anomalía temporal detectada: inconsistencia en los embeddings "
                    "faciales entre frames consecutivos, lo que sugiere posible manipulación "
                    "de alta frecuencia o deepfake frame-by-frame."
                )

            frame_timeline = [
                FrameResult(
                    frame_index=fr["frame_index"],
                    timestamp=fr["timestamp"],
                    manipulation_probability=fr["fake_probability"],
                    face_detected=fr["face_detected"],
                )
                for fr in result.get("frame_timeline", [])
            ]

            await _update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=1.0,
                fake_probability=prob,
                real_probability=result["real_probability"],
                manipulation_probability=round(prob * 100, 1),
                evidence_level=ev_level,
                model_agreement=agreement,
                model_agreement_std=round(std, 4),
                explanation=explanation,
                analysis_time=result["analysis_time"],
                model_used=result["model_used"],
                device_used=result["device_used"],
                faces_detected=result.get("faces_detected", 0),
                frames_analyzed=result["frames_analyzed"],
                video_duration=result["video_duration"],
                frame_timeline=frame_timeline,
                inconsistency_score=result["inconsistency_score"],
                temporal_analysis=temporal_obj,
                temporal_anomaly_detected=temporal_obj.temporal_anomaly_detected if temporal_obj else None,
                completed_at=now(),
            )

        logger.success(
            f"Task {task_id[:8]}... done — {result['fake_probability']:.1%} "
            f"({ev_level.value})"
        )

    except Exception as e:
        logger.error(f"Task {task_id[:8]}... failed: {e}")
        await _update_task(
            task_id,
            status=TaskStatus.FAILED,
            progress=0.0,
            error=str(e),
            completed_at=now(),
        )
    finally:
        asyncio.create_task(_delayed_cleanup(file_path, delay=3600))


async def _delayed_cleanup(file_path: Path, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass
