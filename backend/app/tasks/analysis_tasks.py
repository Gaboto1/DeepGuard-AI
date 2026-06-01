"""
Celery Tasks — Workers GPU exclusivos para análisis forense
===========================================================
Los 5 modelos de IA se cargan UNA SOLA VEZ al arrancar el worker
(señal worker_init), no por tarea. Elimina el overhead de carga y
mantiene la GPU plenamente utilizada.

Flujo enterprise:
  POST /api/v1/analyze → FastAPI valida → Celery dispatch → 202 inmediato
  GET  /api/v1/tasks/{id} → FastAPI consulta Redis → JSON con resultado
"""
import json
import os
import time
from pathlib import Path
from typing import Optional

from celery import Task
from celery.signals import worker_init
from loguru import logger

from app.celery_app import celery_app
from app.config import settings

RESULTS_DIR = settings.RESULTS_DIR   # fuente única de verdad — definida en config.py

FILE_RETENTION_SECONDS = int(os.getenv("FILE_RETENTION_SECONDS", "3600"))


# ─── Carga de modelos al arrancar el worker ────────────────────────────────────

@worker_init.connect
def init_worker_models(**kwargs) -> None:
    """
    Ejecutado UNA VEZ por proceso worker al arrancar.
    Carga los 5 modelos + face detector + meta-ensemble en GPU.
    """
    logger.info("=== Worker DeepGuard: inicializando modelos GPU ===")
    try:
        os.environ["TRANSFORMERS_CACHE"]              = str(settings.MODELS_DIR)
        os.environ["HF_HOME"]                         = str(settings.MODELS_DIR)
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

        from app.models.deepfake_detector import DeepfakeDetector
        from app.models.face_detector import FaceDetector
        from app.models.meta_ensemble import MetaEnsemble
        from app.services.semantic_inspection_service import _SemanticInspector

        det = DeepfakeDetector.get_instance()
        det.load()
        FaceDetector.get_instance().load()
        MetaEnsemble.get_instance().load()

        # LLaVA-1.5-7b-hf (4-bit) — carga en GPU junto al ensemble principal
        # Se omite si bitsandbytes no está disponible o VRAM insuficiente
        try:
            sem_inspector = _SemanticInspector.get_instance()
            sem_inspector.load()
            if sem_inspector._loaded:
                import torch
                used = torch.cuda.memory_allocated(0) / 1e9
                total = torch.cuda.get_device_properties(0).total_memory / 1e9
                logger.success(
                    f"LLaVA cargado — VRAM total usada: {used:.1f}GB / {total:.1f}GB"
                )
        except Exception as e_llava:
            logger.warning(f"LLaVA no pudo cargarse (no crítico): {e_llava}")

        logger.success(f"Worker listo — GPU: {det.device_name} | Modelos: {det.model_name[:60]}")
    except Exception as e:
        logger.error(f"Worker model init FAILED: {e}")
        raise


# ─── Base Task ────────────────────────────────────────────────────────────────

class DeepGuardTask(Task):
    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Task {task_id[:8]}... FAILED: {exc}")
        _persist_result(task_id, {"status": "FAILED", "error": str(exc), "task_id": task_id})

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning(f"Task {task_id[:8]}... retrying: {exc}")


# ─── Task: Imagen ─────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=DeepGuardTask,
    name="app.tasks.analysis_tasks.analyze_image_task",
    max_retries=2,
    soft_time_limit=120,
    time_limit=180,
)
def analyze_image_task(
    self,
    task_id: str,
    file_path: str,
    filename: str,
    *,
    include_heatmap: bool = True,
    file_content_b64: str = "",
) -> dict:
    """Análisis completo de imagen en worker GPU con cadena de custodia.

    file_content_b64: contenido del archivo en base64. Obligatorio en arquitectura
    híbrida (API en Render + worker GPU local) ya que no comparten sistema de archivos.
    Si se provee, el archivo se escribe en el UPLOAD_DIR local antes de procesar.
    """
    self.update_state(state="PROCESSING", meta={"progress": 0.05, "stage": "Iniciando"})
    t0 = time.time()

    try:
        path = Path(file_path)

        # Arquitectura híbrida: la API (Render) envía el contenido del archivo
        # en base64 porque su disco no es compartido con el worker GPU local.
        if file_content_b64:
            import base64 as _b64
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_b64.b64decode(file_content_b64))
            logger.info(f"Archivo recibido via payload ({len(file_content_b64)//1024} KB b64) → {path.name}")

        if not path.exists():
            # Si no hay Base64 Y el archivo no existe en disco, es un error de
            # configuración (no transitorio) — no tiene sentido reintentar (ALTO-06).
            if not file_content_b64:
                raise ValueError(
                    f"Archivo no encontrado y file_content_b64 vacío: {file_path}. "
                    "Error de configuración — la API no envió el archivo correctamente."
                )
            raise FileNotFoundError(f"Archivo no encontrado tras decodificar Base64: {file_path}")

        # 1. SHA-256 antes de cualquier procesamiento
        self.update_state(state="PROCESSING", meta={"progress": 0.10, "stage": "Hash SHA-256"})
        from app.services.custody_service import (
            compute_file_sha256, generate_custody_seal, persist_custody_report,
        )
        sha256 = compute_file_sha256(path)

        # 2. Metadatos forenses EXIF/XMP
        self.update_state(state="PROCESSING", meta={"progress": 0.15, "stage": "Metadatos EXIF/XMP"})
        from app.services.forensic_metadata_service import (
            extract_forensic_metadata, apply_metadata_risk_to_score,
        )
        forensic_meta = extract_forensic_metadata(path)

        # 3. Ensemble de modelos
        self.update_state(state="PROCESSING", meta={"progress": 0.25, "stage": "Ensemble 5 modelos"})
        from app.services.image_service import _run_image_analysis
        raw = _run_image_analysis(path)

        # 4. Aplicar señal de metadatos al score
        prob, meta_note = apply_metadata_risk_to_score(
            raw["fake_probability"], forensic_meta
        )

        # 5. Evidencia + explicación
        from app.utils.helpers import (
            get_evidence_level, get_model_agreement, get_uncertainty,
            generate_forensic_explanation,
        )
        ev_level         = get_evidence_level(prob)
        scores_list      = [v for v in (raw.get("model_scores") or {}).values() if v is not None]
        agreement, std   = get_model_agreement(scores_list)
        unc_lvl, unc_sc, risk_desc = get_uncertainty(prob, std)

        explanation = generate_forensic_explanation(
            probability=prob, evidence_level=ev_level,
            model_agreement=agreement, file_type="image",
            faces_detected=raw.get("faces_detected", 0),
            model_scores=raw.get("model_scores"),
            is_ood=raw.get("is_ood", False),
        )
        if forensic_meta.get("ai_generator_detected"):
            explanation += (
                f" ⚠ ALERTA FORENSE: generador IA detectado en metadatos: "
                f"'{forensic_meta['ai_generator_name']}'."
            )
        elif meta_note:
            explanation += f" {meta_note}."

        # 6. Sello de custodia
        self.update_state(state="PROCESSING", meta={"progress": 0.90, "stage": "Sello de custodia"})
        seal = generate_custody_seal(
            task_id=task_id, file_sha256=sha256, filename=filename,
            file_type="image", final_score=prob, evidence_level=ev_level.value,
        )

        result = {
            "status": "SUCCESS", "task_id": task_id,
            "filename": filename, "file_type": "image",
            "fake_probability": prob, "real_probability": 1.0 - prob,
            "manipulation_probability": round(prob * 100, 1),
            "evidence_level": ev_level.value,
            "model_agreement": agreement.value,
            "model_agreement_std": round(std, 4),
            "uncertainty": unc_lvl.value,
            "uncertainty_score": unc_sc,
            "risk_of_error": risk_desc,
            "explanation": explanation,
            "model_used": raw.get("model_used"),
            "device_used": raw.get("device_used"),
            "faces_detected": raw.get("faces_detected", 0),
            "heatmap": raw.get("heatmap") if include_heatmap else None,
            # Ensemble breakdown — serializar Pydantic a dict para JSON
            "ensemble": (
                raw["ensemble"].model_dump()
                if raw.get("ensemble") and hasattr(raw["ensemble"], "model_dump")
                else raw.get("ensemble")
            ),
            "is_ood": raw.get("is_ood", False),
            "ood_confidence": raw.get("ood_confidence", 0.0),
            "ood_signals": raw.get("ood_signals", []),
            "forensic_metadata": {
                "ai_generator_detected":     forensic_meta["ai_generator_detected"],
                "ai_generator_name":         forensic_meta["ai_generator_name"],
                "editing_software_detected": forensic_meta["editing_software_detected"],
                "editing_software_name":     forensic_meta["editing_software_name"],
                "missing_exif":              forensic_meta["missing_exif"],
                "risk_signal":               forensic_meta["risk_signal"],
                "risk_reasons":              forensic_meta["risk_reasons"],
                "xmp_ai_hints":              forensic_meta["xmp_ai_hints"][:5],
                "inconsistencies":           forensic_meta["inconsistencies"],
                "raw_software_tag":          forensic_meta["raw_software_tag"],
                "has_gps":                   forensic_meta["has_gps"],
            },
            "chain_of_custody": seal,
            "analysis_time": round(time.time() - t0, 3),
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        _persist_result(task_id, result)
        persist_custody_report(seal, result)
        _schedule_file_cleanup(path)
        return result

    except ValueError as exc:
        # ValueError = error de configuración no transitorio (e.g., Base64 vacío).
        # No reintentar — el resultado no cambiará en un retry (ALTO-06).
        logger.error(f"Image task {task_id[:8]} config error (no retry): {exc}")
        raise
    except Exception as exc:
        logger.error(f"Image task {task_id[:8]} failed: {exc}")
        raise self.retry(exc=exc, countdown=30)


# ─── Task: Video ──────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=DeepGuardTask,
    name="app.tasks.analysis_tasks.analyze_video_task",
    max_retries=1,
    soft_time_limit=600,
    time_limit=900,
)
def analyze_video_task(self, task_id: str, file_path: str, filename: str, *, file_content_b64: str = "") -> dict:
    """Análisis completo de video: frame-by-frame + temporal Farneback."""
    self.update_state(state="PROCESSING", meta={"progress": 0.05, "stage": "Iniciando análisis"})
    t0 = time.time()

    try:
        path = Path(file_path)

        # Arquitectura híbrida: reconstruir archivo desde payload base64
        if file_content_b64:
            import base64 as _b64
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_b64.b64decode(file_content_b64))
            logger.info(f"Video recibido via payload ({len(file_content_b64)//1024} KB b64) → {path.name}")

        if not path.exists():
            if not file_content_b64:
                raise ValueError(
                    f"Video no encontrado y file_content_b64 vacío: {file_path}. "
                    "Error de configuración — no reintentar (ALTO-06)."
                )
            raise FileNotFoundError(f"Video no encontrado tras decodificar Base64: {file_path}")

        from app.services.custody_service import (
            compute_file_sha256, generate_custody_seal, persist_custody_report,
        )
        sha256 = compute_file_sha256(path)

        from app.services.forensic_metadata_service import (
            extract_forensic_metadata, apply_metadata_risk_to_score,
        )
        forensic_meta = extract_forensic_metadata(path)

        def progress_cb(p: float) -> None:
            self.update_state(state="PROCESSING",
                              meta={"progress": 0.15 + p * 0.70,
                                    "stage": f"Analizando frames ({p*100:.0f}%)"})

        from app.services.video_service import _run_video_analysis
        raw = _run_video_analysis(path, progress_cb=progress_cb)

        self.update_state(state="PROCESSING", meta={"progress": 0.90, "stage": "Generando sello"})

        prob, _ = apply_metadata_risk_to_score(raw["fake_probability"], forensic_meta)

        from app.utils.helpers import get_evidence_level, get_model_agreement, get_uncertainty
        from app.utils.helpers import generate_forensic_explanation

        ev_level       = get_evidence_level(prob)
        agreement, std = get_model_agreement([prob])
        unc_lvl, unc_sc, risk_desc = get_uncertainty(prob, std)

        explanation = generate_forensic_explanation(
            probability=prob, evidence_level=ev_level,
            model_agreement=agreement, file_type="video",
            frames_analyzed=raw.get("frames_analyzed", 0),
            inconsistency_score=raw.get("inconsistency_score", 0.0),
        )

        temporal = raw.get("temporal_analysis")
        if temporal and temporal.temporal_anomaly_detected:
            explanation += " ⚠ Anomalía temporal detectada entre frames consecutivos."

        seal = generate_custody_seal(
            task_id=task_id, file_sha256=sha256, filename=filename,
            file_type="video", final_score=prob, evidence_level=ev_level.value,
        )

        # Convertir frame_timeline: fake_probability → manipulation_probability
        raw_timeline = raw.get("frame_timeline", [])
        frame_timeline = [
            {
                "frame_index":             fr["frame_index"],
                "timestamp":               fr["timestamp"],
                "manipulation_probability":fr["fake_probability"],
                "face_detected":           fr["face_detected"],
            }
            for fr in raw_timeline
        ]

        result = {
            "status": "completed", "task_id": task_id,
            "filename": filename, "file_type": "video",
            "fake_probability": prob, "real_probability": 1.0 - prob,
            "manipulation_probability": round(prob * 100, 1),
            "evidence_level": ev_level.value,
            "model_agreement": agreement.value,
            "uncertainty": unc_lvl.value,
            "explanation": explanation,
            "model_used": raw.get("model_used"),
            "device_used": raw.get("device_used"),
            "faces_detected": raw.get("faces_detected", 0),
            "frames_analyzed": raw.get("frames_analyzed", 0),
            "video_duration": raw.get("video_duration"),
            "inconsistency_score": raw.get("inconsistency_score"),
            "frame_timeline": frame_timeline,
            "temporal_analysis": _serialize_temporal(temporal),
            "temporal_anomaly_detected": temporal.temporal_anomaly_detected if temporal else None,
            "forensic_metadata": {
                "ai_generator_detected": forensic_meta["ai_generator_detected"],
                "ai_generator_name":     forensic_meta["ai_generator_name"],
                "risk_signal":           forensic_meta["risk_signal"],
                "risk_reasons":          forensic_meta["risk_reasons"],
            },
            "chain_of_custody": seal,
            "progress": 1.0,
            "analysis_time": round(time.time() - t0, 3),
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "created_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        _persist_result(task_id, result)
        persist_custody_report(seal, result)
        _schedule_file_cleanup(path)
        return result

    except ValueError as exc:
        logger.error(f"Video task {task_id[:8]} config error (no retry): {exc}")
        raise
    except Exception as exc:
        logger.error(f"Video task {task_id[:8]} failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _persist_result(task_id: str, result: dict) -> None:
    try:
        with open(RESULTS_DIR / f"{task_id}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"Failed to persist task result: {e}")


def _schedule_file_cleanup(file_path: Path) -> None:
    import threading
    def _delete():
        time.sleep(FILE_RETENTION_SECONDS)
        try:
            if file_path.exists():
                file_path.unlink()
                logger.debug(f"Auto-deleted: {file_path.name}")
        except Exception:
            pass
    threading.Thread(target=_delete, daemon=True).start()


def _serialize_temporal(temporal) -> Optional[dict]:
    """Serializa TemporalAnalysisResult a dict JSON-safe con todos los campos."""
    if temporal is None:
        return None
    try:
        return {
            "temporal_anomaly_detected":   temporal.temporal_anomaly_detected,
            "temporal_consistency_score":  temporal.temporal_consistency_score,
            "temporal_discrepancy_values": list(temporal.temporal_discrepancy_values),
            "temporal_variance":           temporal.temporal_variance,
            "temporal_max_spike":          temporal.temporal_max_spike,
            "optical_flow_values":         list(temporal.optical_flow_values),
            "optical_flow_variance":       temporal.optical_flow_variance,
            "optical_flow_anomaly":        temporal.optical_flow_anomaly,
            "frames_with_faces":           temporal.frames_with_faces,
            "frames_analyzed":             temporal.frames_analyzed,
            "risk_multiplier":             temporal.risk_multiplier,
            "anomaly_details":             list(temporal.anomaly_details),
            "analysis_time":               temporal.analysis_time,
        }
    except Exception:
        return None
