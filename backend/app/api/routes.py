"""
FastAPI routes — legacy (/api/*).

En modo API_ONLY=true (Render/cloud):
  - /api/health  → responde sin importar torch ni modelos
  - /api/analyze → redirige al pipeline v1 (Celery)

En modo local con GPU:
  - Comportamiento completo con carga de modelos e inferencia in-process.
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.schemas import AnalysisResult, HealthResponse, TaskStatus, UploadResponse
from app.config import settings
from app.utils.file_validator import get_file_type, validate_file_size

router = APIRouter(prefix="/api", tags=["deepfake"])

_API_ONLY = settings.API_ONLY


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check. En modo cloud devuelve estado de la API sin cargar modelos."""
    if _API_ONLY:
        return HealthResponse(
            status="ok",
            model_loaded=False,
            cuda_available=False,
            device="remote-worker",
            version=settings.VERSION,
        )
    # Modo local — importa torch solo si está disponible
    try:
        import torch
        from app.models.deepfake_detector import DeepfakeDetector
        detector = DeepfakeDetector.get_instance()
        return HealthResponse(
            status="ok",
            model_loaded=detector._loaded,
            cuda_available=torch.cuda.is_available(),
            device=str(detector.device),
            version=settings.VERSION,
        )
    except ImportError:
        return HealthResponse(
            status="ok",
            model_loaded=False,
            cuda_available=False,
            device="cpu",
            version=settings.VERSION,
        )


# ── Analyze ───────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=UploadResponse)
async def analyze_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> UploadResponse:
    """
    En modo API_ONLY → despacha a Celery (equivalente a /api/v1/analyze).
    En modo local → ejecuta análisis en background thread con modelos locales.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    file_type = get_file_type(file.filename)
    content   = await file.read()
    validate_file_size(len(content))

    if _API_ONLY:
        # Modo cloud: guardar y despachar a Celery igual que v1
        task_id  = str(uuid.uuid4())
        safe_ext = Path(file.filename).suffix.lower()
        dest     = settings.UPLOAD_DIR / f"{task_id}{safe_ext}"
        dest.write_bytes(content)
        logger.info(f"[API-ONLY] Despachando tarea {task_id[:8]}... a Celery")
        try:
            from app.config import make_redis_client as _mkr
            _r = _mkr(socket_connect_timeout=2, socket_timeout=2)
            _r.ping()
            from app.tasks.analysis_tasks import analyze_image_task, analyze_video_task
            if file_type == "image":
                analyze_image_task.apply_async(args=[task_id, str(dest), file.filename], task_id=task_id)
            else:
                analyze_video_task.apply_async(args=[task_id, str(dest), file.filename], task_id=task_id)
        except Exception as e:
            logger.warning(f"Celery dispatch failed: {e}")
        return UploadResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message=f"Tarea {task_id} en cola. Consulta en /api/v1/tasks/{task_id}",
        )

    # Modo local: usa el pipeline completo con modelos in-process
    safe_name = f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in "._-")
    dest      = settings.UPLOAD_DIR / safe_name
    dest.write_bytes(content)
    logger.info(f"Saved upload: {safe_name} ({len(content)/1024/1024:.1f}MB, {file_type})")

    from app.services.analysis_service import create_task, run_analysis
    task = await create_task(filename=file.filename, file_type=file_type)
    background_tasks.add_task(run_analysis, task.task_id, dest, file_type)

    return UploadResponse(
        task_id=task.task_id,
        status=TaskStatus.PENDING,
        message=f"Analysis started for {file.filename}",
    )


# ── Task status (legacy) ──────────────────────────────────────────────────────

@router.get("/tasks/{task_id}", response_model=AnalysisResult)
async def get_task_status(task_id: str) -> AnalysisResult:
    if _API_ONLY:
        raise HTTPException(
            status_code=301,
            detail=f"Usa /api/v1/tasks/{task_id} en modo cloud.",
        )
    from app.services.analysis_service import get_task
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
    return task


@router.get("/history", response_model=list[AnalysisResult])
async def get_history(limit: int = 20) -> list[AnalysisResult]:
    if _API_ONLY:
        return []
    from app.services.analysis_service import list_tasks
    return await list_tasks(limit=min(limit, 100))


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str) -> JSONResponse:
    if _API_ONLY:
        raise HTTPException(status_code=404, detail="Usa /api/v1/tasks/{task_id} en modo cloud.")
    from app.services.analysis_service import _tasks, _lock
    import asyncio
    async with _lock:
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        del _tasks[task_id]
    return JSONResponse({"message": "Task deleted"})
