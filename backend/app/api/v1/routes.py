"""
API v1 — Enterprise Async Endpoints
=====================================
Endpoints asíncronos de grado comercial:
  POST /api/v1/analyze  → 202 Accepted + task_id inmediato
  GET  /api/v1/tasks/{id} → estado + resultado JSON completo
  GET  /api/v1/tasks/{id}/custody → verificar sello de custodia
  GET  /api/v1/health → estado del sistema incluyendo Redis + workers

FastAPI permanece ultra-ligero: solo valida, despacha a Celery y responde.
TODO el procesamiento GPU ocurre exclusivamente en los workers de Celery.
"""
import json
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import settings
from app.utils.file_validator import (
    get_file_type, validate_file_size,
    validate_not_empty, validate_video_size_async, validate_mime_type,
)

router = APIRouter(prefix="/api/v1", tags=["enterprise-v1"])

# ─── Mapeo de estados Celery → español legible ────────────────────────────────
# Los estados internos de Celery se traducen a mensajes comprensibles para el
# frontend y los usuarios finales. Nunca se expone jerga técnica de Celery.

_ESTADO_ES: dict[str, dict] = {
    "PENDING": {
        "estado":   "EN_COLA",
        "etiqueta": "En cola de procesamiento",
        "mensaje":  "La tarea está pendiente de ser procesada por un worker GPU.",
    },
    "STARTED": {
        "estado":   "INICIANDO",
        "etiqueta": "Iniciando análisis",
        "mensaje":  "El worker GPU ha recibido la tarea y está inicializando el análisis.",
    },
    "PROCESSING": {
        "estado":   "PROCESANDO",
        "etiqueta": "Analizando archivo",
        "mensaje":  "El archivo está siendo analizado por el ensemble de modelos.",
    },
    "RETRY": {
        "estado":   "REINTENTANDO",
        "etiqueta": "Reintentando análisis",
        "mensaje":  "Ocurrió un error transitorio. El sistema está reintentando automáticamente.",
    },
    "SUCCESS": {
        "estado":   "COMPLETADO",
        "etiqueta": "Análisis completado",
        "mensaje":  "El análisis forense se completó exitosamente.",
    },
    "FAILURE": {
        "estado":   "FALLIDO",
        "etiqueta": "Error en el procesamiento",
        "mensaje":  "El análisis no pudo completarse. Revise el campo 'detalle_error'.",
    },
    "FAILED": {
        "estado":   "FALLIDO",
        "etiqueta": "Error en el procesamiento del archivo",
        "mensaje":  "El análisis no pudo completarse. Revise el campo 'detalle_error'.",
    },
    "REVOKED": {
        "estado":   "CANCELADO",
        "etiqueta": "Tarea cancelada",
        "mensaje":  "La tarea fue cancelada antes de completarse.",
    },
}

# Etapas de procesamiento (para el campo 'stage' del progreso)
_ETAPAS_VIDEO: dict[str, str] = {
    "Iniciando":                  "Iniciando análisis de video...",
    "Hash SHA-256":               "Calculando huella digital SHA-256...",
    "Metadatos EXIF/XMP":         "Extrayendo metadatos forenses EXIF/XMP...",
    "Ensemble 5 modelos":         "Ejecutando ensemble de 5 modelos IA...",
    "Sello de custodia":          "Generando sello criptográfico de custodia...",
    "Iniciando análisis de video":"Iniciando análisis forense del video...",
    "Generando sello":            "Generando sello de cadena de custodia...",
}


def _enriquecer_estado(raw: dict) -> dict:
    """
    Enriquece la respuesta cruda de Celery/disco con campos legibles en español.
    Añade 'estado_es', 'etiqueta', 'mensaje_es' y traduce la etapa si aplica.
    """
    status_raw = raw.get("status", "PENDING")
    mapa = _ESTADO_ES.get(status_raw, _ESTADO_ES["PENDING"])

    result = dict(raw)
    result["estado_es"] = mapa["estado"]
    result["etiqueta"]  = mapa["etiqueta"]
    result["mensaje_es"]= mapa["mensaje"]

    # Traducir campo 'stage' si existe
    stage_raw = result.get("stage", "")
    result["etapa"] = _ETAPAS_VIDEO.get(stage_raw, stage_raw)

    # Renombrar campo 'error' a 'detalle_error' para mayor claridad
    if "error" in result and result["error"]:
        result["detalle_error"] = str(result.pop("error"))

    return result

RESULTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "reports" / "tasks"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ─── Helpers para Redis / Celery ──────────────────────────────────────────────

def _get_celery_and_redis():
    """Obtiene el app Celery y verifica que Redis esté disponible."""
    from app.celery_app import celery_app
    return celery_app


def _get_task_result(task_id: str) -> Optional[dict]:
    """
    Busca el resultado de una tarea en orden de prioridad:
      1. Redis (resultado Celery via AsyncResult)
      2. Disco (JSON persistido por el worker local)
      3. Fallback PENDING — NUNCA devuelve None para UUIDs válidos.
         Esto evita que el frontend reciba 404 mientras el worker procesa.

    Arquitectura híbrida: el worker GPU local escribe en Aiven Redis (backend
    de Celery) y en disco local. Render lee desde Aiven. Si la conexión a Aiven
    falla momentáneamente, se devuelve PENDING para que el frontend siga
    haciendo polling en lugar de abortar con error.
    """
    # ── 1. Redis via Celery AsyncResult ──────────────────────────────────────
    redis_error = None
    try:
        from app.celery_app import celery_app
        from celery.result import AsyncResult
        ar = AsyncResult(task_id, app=celery_app)
        if ar.ready():
            if ar.successful():
                return _enriquecer_estado({
                    "status":  "SUCCESS",
                    "result":  ar.result,
                    "task_id": task_id,
                })
            elif ar.failed():
                return _enriquecer_estado({
                    "status":  "FAILED",
                    "error":   str(ar.result),
                    "task_id": task_id,
                })
        elif ar.state in ("STARTED", "PROCESSING", "RETRY"):
            meta = ar.info or {}
            return _enriquecer_estado({
                "status":   ar.state,
                "task_id":  task_id,
                "progress": meta.get("progress", 0),
                "stage":    meta.get("stage", "Procesando..."),
            })
        else:
            # PENDING — tarea en cola o no iniciada aún
            return _enriquecer_estado({"status": "PENDING", "task_id": task_id})
    except Exception as e:
        redis_error = str(e)
        logger.debug(f"AsyncResult error para {task_id[:8]}...: {e}")

    # ── 2. Disco (worker local guarda JSON aquí) ──────────────────────────────
    disk_path = RESULTS_DIR / f"{task_id}.json"
    if disk_path.exists():
        try:
            with open(disk_path, encoding="utf-8") as f:
                raw = json.load(f)
            return _enriquecer_estado(raw)
        except Exception:
            pass

    # ── 3. Fallback seguro: PENDING ───────────────────────────────────────────
    # Si llegamos aquí, Redis no respondió y el disco no tiene el resultado aún.
    # Devolvemos PENDING en lugar de None para que el frontend siga haciendo
    # polling — el worker puede estar en medio del procesamiento GPU.
    # Esto es correcto porque el task_id fue generado por nuestra API.
    logger.debug(
        f"Task {task_id[:8]}... no encontrado aún "
        f"(redis_err={redis_error or 'ok'}) — devolviendo PENDING"
    )
    return _enriquecer_estado({"status": "PENDING", "task_id": task_id})


# ─── POST /api/v1/analyze ─────────────────────────────────────────────────────

@router.post("/analyze", status_code=202)
async def analyze_async(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    """
    202 Accepted — despacha análisis a Celery worker y responde inmediatamente.

    El procesamiento GPU ocurre en el worker (asíncrono).
    Consulta el resultado con: GET /api/v1/tasks/{task_id}
    """
    # Validación 1: nombre de archivo obligatorio
    if not file.filename or file.filename.strip() == "":
        raise HTTPException(
            status_code=400,
            detail={
                "error":   "nombre_archivo_requerido",
                "mensaje": "El archivo debe tener un nombre válido con extensión.",
            },
        )

    # Validación 2: tipo de archivo soportado
    file_type = get_file_type(file.filename)

    # Validación 3: leer y verificar tamaño
    content = await file.read()
    validate_not_empty(len(content), file.filename)
    validate_file_size(len(content))

    # Validación 4: límite adicional para videos en modo asíncrono
    if file_type == "video":
        validate_video_size_async(len(content))

    # Guardar en disco (Celery worker lo procesará)
    task_id  = str(uuid.uuid4())
    safe_ext = Path(file.filename).suffix.lower()
    dest     = settings.UPLOAD_DIR / f"{task_id}{safe_ext}"
    dest.write_bytes(content)

    logger.info(f"v1: Dispatching {file_type} task {task_id[:8]}... ({len(content)/1e6:.1f}MB)")

    # Estimar tiempo de procesamiento
    size_mb   = len(content) / 1_048_576
    est_secs  = int(size_mb * (3 if file_type == "video" else 0.5) + 5)

    # Verificar Redis disponible antes de intentar Celery (fail-fast)
    redis_available = False
    try:
        import redis as _redis
        _r = _redis.from_url(
            __import__("os").getenv("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1, socket_timeout=1,
        )
        _r.ping()
        redis_available = True
    except Exception:
        pass

    # Dispatch a Celery (si Redis disponible) o fallback síncrono
    # En modo API_ONLY el sync_fallback está deshabilitado: la API en la nube
    # no tiene PyTorch — el procesamiento SIEMPRE ocurre en el worker GPU remoto.
    from app.config import settings as _cfg
    _api_only = _cfg.API_ONLY

    if redis_available:
        try:
            from app.tasks.analysis_tasks import analyze_image_task, analyze_video_task
            if file_type == "image":
                analyze_image_task.apply_async(
                    args=[task_id, str(dest), file.filename],
                    task_id=task_id,
                )
            else:
                analyze_video_task.apply_async(
                    args=[task_id, str(dest), file.filename],
                    task_id=task_id,
                )
            dispatch_mode = "celery"
        except Exception as e:
            if _api_only:
                logger.error(f"Celery dispatch falló y API_ONLY=true — no hay fallback GPU: {e}")
                dispatch_mode = "celery_error"
            else:
                logger.warning(f"Celery dispatch failed ({e}), using sync fallback")
                _process_sync_fallback(task_id, dest, file.filename, file_type)
                dispatch_mode = "sync_fallback"
    elif _api_only:
        logger.error("Redis no disponible y API_ONLY=true — imposible procesar sin worker GPU remoto")
        raise HTTPException(
            status_code=503,
            detail={
                "error":   "worker_no_disponible",
                "mensaje": (
                    "El worker GPU remoto no está conectado a Redis. "
                    "Asegúrate de que el worker Celery local esté corriendo y "
                    "conectado a la misma instancia de Redis que la API."
                ),
            },
        )
    else:
        logger.info("Redis no disponible — usando modo síncrono (sync fallback)")
        _process_sync_fallback(task_id, dest, file.filename, file_type)
        dispatch_mode = "sync_fallback"

    return JSONResponse(
        status_code=202,
        content={
            "task_id":            task_id,
            "status":             "PENDING",
            "dispatch_mode":      dispatch_mode,
            "estimated_seconds":  est_secs,
            "poll_url":           f"/api/v1/tasks/{task_id}",
            "message": (
                f"Análisis en cola. Consulte el estado en /api/v1/tasks/{task_id}. "
                f"Tiempo estimado: ~{est_secs}s"
            ),
        },
    )


# ─── GET /api/v1/tasks/{task_id} ──────────────────────────────────────────────

# Mapa de estados Celery (mayúsculas) → estados frontend (minúsculas)
_STATUS_FRONTEND: dict[str, str] = {
    "PENDING":    "pending",
    "STARTED":    "processing",
    "PROCESSING": "processing",
    "RETRY":      "processing",
    "SUCCESS":    "completed",
    "FAILURE":    "failed",
    "FAILED":     "failed",
    "REVOKED":    "failed",
}


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str) -> JSONResponse:
    """
    Consulta el estado de un análisis.
    Devuelve siempre 'status' en minúsculas para compatibilidad con el frontend:
      pending | processing | completed | failed
    HTTP 202 mientras está en cola o procesando, 200 al completar.
    """
    result = _get_task_result(task_id)
    if result is None:
        raise HTTPException(404, f"Tarea '{task_id}' no encontrada")

    raw_status = result.get("status", "PENDING")
    frontend_status = _STATUS_FRONTEND.get(str(raw_status).upper(), "pending")

    # Si el resultado Celery está anidado bajo la clave 'result' (resultado exitoso)
    if raw_status == "SUCCESS" and "result" in result:
        final = dict(result["result"])
        final["status"]   = "completed"
        final["task_id"]  = final.get("task_id", task_id)
        final["progress"] = 1.0
        return JSONResponse(status_code=200, content=final)

    # Respuesta normalizada para el frontend
    result["status"]   = frontend_status
    result["task_id"]  = result.get("task_id", task_id)
    result["progress"] = result.get("progress", 1.0 if frontend_status == "completed" else 0.05)

    http_code = 202 if frontend_status in ("pending", "processing") else 200
    return JSONResponse(status_code=http_code, content=result)


# ─── GET /api/v1/tasks/{task_id}/custody ──────────────────────────────────────

@router.get("/tasks/{task_id}/custody")
async def verify_custody(task_id: str) -> JSONResponse:
    """
    Verifica la integridad del sello de cadena de custodia.
    Endpoint para auditorías forenses: confirma que el resultado
    no fue alterado después del análisis.
    """
    result = _get_task_result(task_id)
    if result is None:
        raise HTTPException(404, f"Tarea '{task_id}' no encontrada")

    raw = result.get("result", result)
    seal = raw.get("chain_of_custody")
    if not seal:
        raise HTTPException(422, "Esta tarea no tiene sello de cadena de custodia")

    try:
        from app.services.custody_service import verify_custody_seal
        is_valid = verify_custody_seal(seal)
    except Exception as e:
        raise HTTPException(500, f"Error verificando sello: {e}")

    return JSONResponse(content={
        "task_id":          task_id,
        "seal_version":     seal.get("seal_version"),
        "file_sha256":      seal.get("file_sha256"),
        "final_score":      seal.get("final_score"),
        "timestamp_utc":    seal.get("timestamp_utc"),
        "custody_token":    seal.get("custody_token"),
        "integrity_valid":  is_valid,
        "verification_message": (
            "Sello verificado: el resultado corresponde exactamente al archivo analizado."
            if is_valid else
            "⚠ ALERTA: Sello inválido — el resultado puede haber sido alterado."
        ),
    })


# ─── GET /api/v1/health ───────────────────────────────────────────────────────

@router.get("/health")
async def health_v1() -> JSONResponse:
    """Estado completo del sistema enterprise (API + Redis + Worker)."""
    import torch

    # Estado de Redis (con timeout estricto para no bloquear)
    redis_ok   = False
    redis_info = "No disponible (Redis no está corriendo localmente)"
    try:
        import redis as redis_lib
        r = redis_lib.from_url(
            __import__("os").getenv("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        r.ping()
        redis_ok   = True
        redis_info = "Conectado"
    except Exception as e:
        redis_info = f"No disponible: {type(e).__name__}"

    # Estado del worker (solo si Redis está up)
    workers_info = "N/A (requiere Redis)"
    if redis_ok:
        try:
            from app.celery_app import celery_app
            inspect = celery_app.control.inspect(timeout=2)
            active  = inspect.active()
            workers_info = f"{len(active)} worker(s) activos" if active else "Sin workers activos"
        except Exception:
            workers_info = "Celery no disponible"

    return JSONResponse(content={
        "version":       "enterprise-v1",
        "status":        "ok",
        "cuda":          torch.cuda.is_available(),
        "gpu":           torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A",
        "redis_status":  redis_ok,
        "redis_info":    redis_info,
        "workers_status":workers_info,
        "endpoints": {
            "analyze":  "POST /api/v1/analyze",
            "status":   "GET  /api/v1/tasks/{task_id}",
            "custody":  "GET  /api/v1/tasks/{task_id}/custody",
            "history":  "GET  /api/v1/history",
            "delete":   "DELETE /api/v1/tasks/{task_id}",
            "health":   "GET  /api/v1/health",
        },
    })


# ─── GET /api/v1/history ──────────────────────────────────────────────────────

@router.get("/history")
async def get_history_v1(limit: int = 20) -> JSONResponse:
    """
    Historial de análisis recientes — lee los JSON persistidos en disco.
    Ordenados por fecha de modificación descendente (más reciente primero).
    Máximo 100 resultados.
    """
    limit = min(limit, 100)
    results = []

    try:
        json_files = sorted(
            RESULTS_DIR.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:limit]

        for jf in json_files:
            try:
                with open(jf, encoding="utf-8") as f:
                    data = json.load(f)
                # Solo incluir tareas completadas (no en progreso)
                if data.get("status") in ("completed", "SUCCESS"):
                    data["status"] = "completed"
                    results.append(data)
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"History read error: {e}")

    return JSONResponse(content=results)


# ─── DELETE /api/v1/tasks/{task_id} ───────────────────────────────────────────

@router.delete("/tasks/{task_id}")
async def delete_task_v1(task_id: str) -> JSONResponse:
    """Elimina el resultado persistido en disco de una tarea."""
    disk_path = RESULTS_DIR / f"{task_id}.json"
    if not disk_path.exists():
        raise HTTPException(404, f"Tarea '{task_id}' no encontrada en disco")
    try:
        disk_path.unlink()
        return JSONResponse(content={"message": f"Tarea {task_id} eliminada"})
    except Exception as e:
        raise HTTPException(500, f"Error al eliminar: {e}")


# ─── Fallback síncrono (sin Redis) ────────────────────────────────────────────

def _serialize_temporal_fallback(temporal) -> Optional[dict]:
    """Serializa TemporalAnalysisResult (dataclass) a dict JSON-safe."""
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


def _process_sync_fallback(
    task_id: str,
    file_path: Path,
    filename: str,
    file_type: str,
) -> None:
    """
    Procesamiento síncrono en background cuando Redis/Celery no está disponible.
    Ejecuta el pipeline completo incluyendo LLaVA (si está cargado) y
    guarda el resultado en JSON para que GET /api/v1/tasks/{id} lo encuentre.
    """
    import threading
    import time as _time

    def _run():
        t0 = _time.time()
        try:
            from app.services.image_service import _run_image_analysis
            from app.services.video_service import _run_video_analysis
            from app.services.custody_service import (
                compute_file_sha256, generate_custody_seal, persist_custody_report,
            )
            from app.services.forensic_metadata_service import (
                extract_forensic_metadata, apply_metadata_risk_to_score,
            )
            from app.utils.helpers import (
                get_evidence_level, get_model_agreement, get_uncertainty,
                generate_forensic_explanation,
            )

            # ── 1. SHA-256 del archivo original ───────────────────────────────
            sha256 = compute_file_sha256(file_path)

            # ── 2. Metadatos forenses EXIF/XMP ────────────────────────────────
            forensic_meta = extract_forensic_metadata(file_path)

            # ── 3. Ensemble de modelos ────────────────────────────────────────
            if file_type == "image":
                raw = _run_image_analysis(file_path)
            else:
                raw = _run_video_analysis(file_path)

            # ── 4. Aplicar señal de metadatos ─────────────────────────────────
            prob, meta_note = apply_metadata_risk_to_score(
                raw["fake_probability"], forensic_meta
            )

            # ── 5. Análisis semántico LLaVA (si disponible) ───────────────────
            semantic_result = None
            semantic_obj    = None
            fusion_type     = None

            if file_type == "image":
                try:
                    from app.services.semantic_inspection_service import (
                        analyze_semantic_coherence, apply_semantic_fusion,
                    )
                    semantic_result = analyze_semantic_coherence(file_path)
                    face_detected   = (raw.get("faces_detected") or 0) > 0
                    fused, fusion_type, fusion_note = apply_semantic_fusion(
                        prob, semantic_result, face_detected
                    )
                    if fused != prob:
                        prob = fused
                    sem_score = semantic_result.get("risk_score", -1)
                    if sem_score >= 0:
                        semantic_obj = {
                            "risk_score":            sem_score,
                            "risk_score_normalized": semantic_result.get("risk_score_normalized"),
                            "semantic_observations": semantic_result.get("semantic_observations", ""),
                            "model_used":            semantic_result.get("model_used", ""),
                            "quantization":          semantic_result.get("quantization", ""),
                            "analysis_time":         semantic_result.get("analysis_time", 0.0),
                            "fusion_type":           fusion_type,
                            "fusion_note":           fusion_note,
                            "available":             True,
                        }
                except Exception as e_llava:
                    logger.debug(f"LLaVA sync_fallback skip: {e_llava}")

            # ── 6. Evidencia + consenso + explicación ─────────────────────────
            ev_level     = get_evidence_level(prob)
            scores_list  = [v for v in (raw.get("model_scores") or {}).values() if v is not None]
            agreement, std = get_model_agreement(scores_list)
            unc_lvl, unc_sc, risk_desc = get_uncertainty(prob, std)

            explanation = generate_forensic_explanation(
                probability=prob, evidence_level=ev_level,
                model_agreement=agreement, file_type=file_type,
                faces_detected=raw.get("faces_detected", 0),
                model_scores=raw.get("model_scores"),
                is_ood=raw.get("is_ood", False),
            )
            if forensic_meta.get("ai_generator_detected"):
                explanation += (
                    f" ALERTA FORENSE: generador IA detectado en metadatos: "
                    f"'{forensic_meta['ai_generator_name']}'."
                )
            elif meta_note:
                explanation += f" {meta_note}."

            # ── 7. Sello de cadena de custodia v2 ─────────────────────────────
            sem_score_for_seal = (
                semantic_result.get("risk_score") if semantic_result else None
            )
            seal = generate_custody_seal(
                task_id=task_id, file_sha256=sha256, filename=filename,
                file_type=file_type, final_score=prob, evidence_level=ev_level.value,
                semantic_score=sem_score_for_seal,
            )

            # ── 8. Resultado completo en formato frontend ──────────────────────
            result = {
                "status":                  "completed",   # minúscula para el frontend
                "task_id":                 task_id,
                "filename":                filename,
                "file_type":               file_type,
                "fake_probability":        prob,
                "real_probability":        1.0 - prob,
                "manipulation_probability":round(prob * 100, 1),
                "evidence_level":          ev_level.value,
                "model_agreement":         agreement.value,
                "model_agreement_std":     round(std, 4),
                "uncertainty":             unc_lvl.value,
                "uncertainty_score":       unc_sc,
                "risk_of_error":           risk_desc,
                "explanation":             explanation,
                "model_used":              raw.get("model_used"),
                "device_used":             raw.get("device_used"),
                "faces_detected":          raw.get("faces_detected", 0),
                "heatmap":                 raw.get("heatmap"),
                # EnsembleBreakdown es un modelo Pydantic — convertir a dict
                # para que json.dump() lo serialice correctamente
                "ensemble": (
                    raw["ensemble"].model_dump()
                    if raw.get("ensemble") and hasattr(raw["ensemble"], "model_dump")
                    else raw.get("ensemble")
                ),
                "is_ood":                  raw.get("is_ood", False),
                "ood_confidence":          raw.get("ood_confidence", 0.0),
                "ood_signals":             raw.get("ood_signals", []),
                "semantic_analysis":       semantic_obj,
                # ── Campos de video (solo si file_type=="video") ──────────────
                "frames_analyzed":         raw.get("frames_analyzed"),
                "video_duration":          raw.get("video_duration"),
                "inconsistency_score":     raw.get("inconsistency_score"),
                # frame_timeline: convertir fake_probability → manipulation_probability
                "frame_timeline": [
                    {
                        "frame_index":             fr["frame_index"],
                        "timestamp":               fr["timestamp"],
                        "manipulation_probability":fr["fake_probability"],
                        "face_detected":           fr["face_detected"],
                    }
                    for fr in (raw.get("frame_timeline") or [])
                ],
                # temporal_analysis: serializar dataclass a dict
                "temporal_analysis":       _serialize_temporal_fallback(raw.get("temporal_analysis")),
                "temporal_anomaly_detected": (
                    raw["temporal_analysis"].temporal_anomaly_detected
                    if raw.get("temporal_analysis") else None
                ),
                "forensic_metadata": {
                    "ai_generator_detected":     forensic_meta["ai_generator_detected"],
                    "ai_generator_name":         forensic_meta["ai_generator_name"],
                    "editing_software_detected": forensic_meta["editing_software_detected"],
                    "editing_software_name":     forensic_meta["editing_software_name"],
                    "missing_exif":              forensic_meta["missing_exif"],
                    "risk_signal":               forensic_meta["risk_signal"],
                    "risk_reasons":              forensic_meta["risk_reasons"],
                    "inconsistencies":           forensic_meta["inconsistencies"],
                },
                "chain_of_custody":        seal,
                "dispatch_mode":           "sync_fallback",
                "analysis_time":           round(_time.time() - t0, 3),
                "progress":                1.0,
                "completed_at":            _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                "created_at":              _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            }

            result_path = RESULTS_DIR / f"{task_id}.json"
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, default=str)

            persist_custody_report(seal, result)
            logger.success(
                f"sync_fallback task {task_id[:8]}... done — "
                f"{prob:.1%} ({ev_level.value}) in {result['analysis_time']}s"
            )

        except Exception as e:
            logger.error(f"sync_fallback task {task_id[:8]}... FAILED: {e}")
            error_result = {
                "status":   "failed",
                "task_id":  task_id,
                "error":    str(e),
                "progress": 0.0,
            }
            with open(RESULTS_DIR / f"{task_id}.json", "w", encoding="utf-8") as f:
                json.dump(error_result, f)

    threading.Thread(target=_run, daemon=True).start()
