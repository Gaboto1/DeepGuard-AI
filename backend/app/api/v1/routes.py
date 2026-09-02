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
import asyncio
import base64
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _validate_task_id(task_id: str) -> None:
    """Rechaza task_ids que no sean UUID v4 — previene path traversal."""
    if not _UUID_RE.match(task_id):
        raise HTTPException(
            status_code=400,
            detail={
                "error":   "task_id_invalido",
                "mensaje": "El task_id debe ser un UUID válido (formato: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx).",
            },
        )

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.utils.file_validator import (
    get_file_type, validate_file_size,
    validate_not_empty, validate_video_size_async, validate_mime_type,
)

# Rate limiter para este router. El mismo key_func que main.py para que los
# contadores sean coherentes entre routers. El límite de /analyze es más
# estricto que el global (GPU-bound — previene DoS).
_limiter = Limiter(key_func=get_remote_address)

# Pool dedicado para operaciones CPU-bound (base64, SHA-256) que no deben
# bloquear el event loop de FastAPI. max_workers=2 limita el paralelismo CPU.
_cpu_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dg-cpu")

# Pool para el sync_fallback (GPU local). max_workers=1 garantiza exclusividad GPU.
_fallback_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dg-fallback")

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
    "Procedencia C2PA":           "Verificando procedencia criptográfica C2PA...",
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

from app.config import settings as _route_settings
RESULTS_DIR = _route_settings.RESULTS_DIR   # fuente única de verdad — config.py

# ─── Helpers para Redis / Celery ──────────────────────────────────────────────


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
@_limiter.limit("20/minute")
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

    # Guardar en disco local (útil en modo local; en Render el disco es efímero)
    task_id  = str(uuid.uuid4())
    safe_ext = Path(file.filename).suffix.lower()
    dest     = settings.UPLOAD_DIR / f"{task_id}{safe_ext}"
    dest.write_bytes(content)

    # Validación MIME obligatoria — detecta archivos renombrados (P3)
    validate_mime_type(dest, file_type)

    # Codificar en Base64 en el thread pool — evita bloquear el event loop
    # de FastAPI durante operaciones CPU-bound sobre archivos grandes (ALTO-01).
    loop = asyncio.get_event_loop()
    file_content_b64: str = await loop.run_in_executor(
        _cpu_executor,
        lambda: base64.b64encode(content).decode("ascii"),
    )

    logger.info(f"v1: Dispatching {file_type} task {task_id[:8]}... ({len(content)/1e6:.1f}MB)")

    # Estimar tiempo de procesamiento
    size_mb   = len(content) / 1_048_576
    est_secs  = int(size_mb * (3 if file_type == "video" else 0.5) + 5)

    # Verificar Redis disponible antes de intentar Celery.
    # Usa make_redis_client() que corrige el bug ssl_cert_reqs=CERT_NONE de redis-py 6.x.
    redis_available = False
    try:
        from app.config import make_redis_client as _mkr
        _r = _mkr(socket_connect_timeout=8, socket_timeout=8)
        _r.ping()
        redis_available = True
    except Exception as _e:
        logger.warning(f"Redis ping failed: {type(_e).__name__}: {_e}")

    # Dispatch a Celery — siempre se intenta, con o sin ping previo exitoso.
    # El ping es solo diagnóstico; Celery tiene su propia gestión de conexión.
    from app.config import settings as _cfg
    _api_only = _cfg.API_ONLY

    if redis_available or _api_only:
        # API_ONLY: siempre intentar Celery aunque el ping haya fallado —
        # el ping usa 1 conexión corta; apply_async usa el pool de Celery
        # que puede tener una conexión previa activa.
        try:
            from app.tasks.analysis_tasks import analyze_image_task, analyze_video_task
            # file_content_b64 viaja en el payload para que el worker GPU local
            # reconstruya el archivo en su propio disco (arquitectura híbrida).
            if file_type == "image":
                analyze_image_task.apply_async(
                    args=[task_id, str(dest), file.filename],
                    kwargs={"file_content_b64": file_content_b64},
                    task_id=task_id,
                )
            else:
                analyze_video_task.apply_async(
                    args=[task_id, str(dest), file.filename],
                    kwargs={"file_content_b64": file_content_b64},
                    task_id=task_id,
                )
            dispatch_mode = "celery"
        except Exception as e:
            if _api_only:
                logger.error(f"Celery dispatch falló en modo API_ONLY: {e}")
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error":   "worker_no_disponible",
                        "mensaje": (
                            f"No se pudo conectar con el worker GPU remoto. "
                            f"Verifica que el worker Celery esté corriendo y conectado a Aiven. "
                            f"Error: {type(e).__name__}"
                        ),
                    },
                )
            else:
                logger.warning(f"Celery dispatch failed ({e}), using sync fallback")
                _process_sync_fallback(task_id, dest, file.filename, file_type)
                dispatch_mode = "sync_fallback"
    elif not _api_only:
        # Solo en modo local sin Redis: usar sync fallback con GPU local
        logger.info("Redis no disponible — usando modo síncrono (sync fallback)")
        _process_sync_fallback(task_id, dest, file.filename, file_type)
        dispatch_mode = "sync_fallback"
    else:
        # Caso imposible (api_only=False y redis_available=False) — ya manejado arriba
        raise HTTPException(
            status_code=503,
            detail={
                "error":   "worker_no_disponible",
                "mensaje": "Redis no disponible.",
            },
        )

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
    _validate_task_id(task_id)
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
    _validate_task_id(task_id)
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
        logger.error(f"Custody verification error for {task_id[:8]}: {e}")
        raise HTTPException(500, "Error interno al verificar el sello de custodia.")

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
    """Estado completo del sistema enterprise (API + Redis + Worker).
    Compatible con modo API_ONLY=true (sin PyTorch instalado en Render).
    """
    from app.config import settings as _cfg

    # CUDA / GPU — solo disponible en modo local con GPU
    cuda_ok = False
    gpu_name = "N/A (API-only mode)"
    if not _cfg.API_ONLY:
        try:
            import torch
            cuda_ok  = torch.cuda.is_available()
            gpu_name = torch.cuda.get_device_name(0) if cuda_ok else "N/A"
        except ImportError:
            pass

    # Estado de Redis — usa make_redis_client() que corrige el bug de
    # redis-py 6.x con ssl_cert_reqs=CERT_NONE en la query string de la URL.
    redis_ok   = False
    redis_info = "No disponible"
    r          = None
    try:
        from app.config import make_redis_client
        r = make_redis_client(
            socket_connect_timeout=4,
            socket_timeout=4,
            decode_responses=True,
        )
        r.ping()
        redis_ok   = True
        redis_info = "Conectado"
    except Exception as e:
        redis_info = f"No disponible: {type(e).__name__}: {str(e)[:60]}"

    # Estado del worker — lee la clave de heartbeat que el worker escribe cada 30s.
    # Reemplaza inspect.ping() que fallaba por:
    #   - socket_timeout=2s en broker_transport_options (roundtrip intercontinental > 2s)
    #   - Redis pub/sub del canal de control (diferente a las colas de tareas RPUSH/BLPOP)
    #   - task_default_exchange personalizado que interfiere con el canal de control
    # El heartbeat solo usa redis.EXISTS → mismo canal que el dispatch de tareas.
    HEARTBEAT_KEY  = "deepguard:worker:heartbeat"
    workers_info   = "N/A (requiere Redis)"
    workers_online = False
    if redis_ok:
        try:
            hb_value = r.get(HEARTBEAT_KEY)         # r ya está conectado desde el ping anterior
            hb_ttl   = r.ttl(HEARTBEAT_KEY) if hb_value else -1
            if hb_value:
                import json as _json
                try:
                    hb_data = _json.loads(hb_value)
                    worker_name = hb_data.get("worker", "worker")
                except Exception:
                    worker_name = "worker"
                workers_info   = f"{worker_name} activo (heartbeat caduca en {hb_ttl}s)"
                workers_online = True
            else:
                workers_info   = "Sin workers GPU activos (no hay heartbeat en Redis)"
                workers_online = False
        except Exception as e:
            workers_info   = f"Error verificando heartbeat: {type(e).__name__}"
            workers_online = False

    return JSONResponse(content={
        "version":         "enterprise-v1",
        "status":          "ok",
        "mode":            "api-only" if _cfg.API_ONLY else "full-gpu",
        "cuda":            cuda_ok,
        "gpu":             gpu_name,
        "redis_status":    redis_ok,
        "redis_info":      redis_info,
        "workers_status":  workers_info,
        "workers_online":  workers_online,   # bool — usado por el badge del Navbar
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
    _validate_task_id(task_id)
    disk_path = RESULTS_DIR / f"{task_id}.json"
    if not disk_path.exists():
        raise HTTPException(404, f"Tarea '{task_id}' no encontrada en disco")
    try:
        disk_path.unlink()
        return JSONResponse(content={"message": f"Tarea {task_id} eliminada"})
    except Exception as e:
        logger.error(f"Delete task error {task_id[:8]}: {e}")
        raise HTTPException(500, "Error interno al eliminar la tarea.")


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
    Usa _fallback_executor (max_workers=1) para garantizar exclusividad GPU
    y evitar la creación de threads sin límite (ALTO-02).
    """
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

            # ── 1b. C2PA — procedencia pre-neural (0 VRAM, ~10-50ms) ──────────
            from app.services.c2pa_service import read_c2pa_provenance as _read_c2pa
            try:
                _c2pa_size = file_path.stat().st_size
                _c2pa_bytes = file_path.read_bytes() if _c2pa_size < 100 * 1024 * 1024 else b""
                c2pa_provenance = _read_c2pa(_c2pa_bytes, filename)
            except Exception as _c2pa_err:
                logger.debug(f"C2PA sync_fallback skip: {_c2pa_err}")
                c2pa_provenance = {
                    "has_c2pa": False, "active": False, "verified": False,
                    "signed_by": None, "claim_generator": None, "issued_at": None,
                    "history_log": [], "error": str(_c2pa_err),
                }

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
                "c2pa_provenance":         c2pa_provenance,
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

    # ThreadPoolExecutor con max_workers=1 garantiza un solo análisis GPU
    # concurrente y backpressure natural si llegan más requests (ALTO-02).
    _fallback_executor.submit(_run)
