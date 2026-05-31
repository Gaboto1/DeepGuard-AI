"""
FastAPI application entry point.

Modos de operación controlados por la variable de entorno API_ONLY:
  API_ONLY=true  → Render / cloud: cero imports de PyTorch/transformers.
                   Solo valida, despacha a Redis y responde.  RAM < 100 MB.
  API_ONLY=false → Desarrollo local: carga modelos GPU en el lifespan.
"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

Path("logs").mkdir(exist_ok=True)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.routes import router
from app.api.v1.routes import router as router_v1
from app.config import settings

# True en Render / cualquier entorno cloud sin GPU
API_ONLY: bool = settings.API_ONLY

# Logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="DEBUG" if settings.DEBUG else "INFO",
)
if not API_ONLY:
    logger.add("logs/app.log", rotation="10 MB", retention="7 days", level="INFO")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if API_ONLY:
        logger.info(f"Starting {settings.APP_NAME} v{settings.VERSION} — modo API-only (cloud)")
        logger.info("Carga de modelos omitida: API_ONLY=true. El procesamiento ocurre en los workers GPU remotos.")
    else:
        logger.info(f"Starting {settings.APP_NAME} v{settings.VERSION} — modo completo (GPU local)")
        try:
            import torch
            logger.info(f"CUDA available: {torch.cuda.is_available()}")
            if torch.cuda.is_available():
                logger.info(f"GPU: {torch.cuda.get_device_name(0)}")
        except ImportError:
            logger.warning("PyTorch no disponible — modo CPU")

        try:
            from app.models.deepfake_detector import DeepfakeDetector
            from app.models.face_detector import FaceDetector
            logger.info("Pre-cargando modelos ensemble (ViT + CLIP + face detector)...")
            detector = DeepfakeDetector.get_instance()
            detector.load()
            FaceDetector.get_instance().load()
            logger.success(f"Modelos listos: {detector.model_name}")
        except Exception as e:
            logger.error(f"Pre-carga de modelos fallida: {e}")
            logger.warning("Los modelos se cargarán en la primera petición")

    yield
    logger.info("Shutting down...")


# Rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=(
        "DeepGuard AI — Plataforma forense de detección de deepfakes. "
        "Arquitectura híbrida: API en la nube + workers GPU locales via Celery/Redis."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — acepta orígenes de producción (Vercel) + desarrollo local
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(router)
app.include_router(router_v1)


@app.get("/")
async def root():
    return {
        "name":      settings.APP_NAME,
        "version":   settings.VERSION,
        "mode":      "api-only (cloud)" if API_ONLY else "full (local GPU)",
        "docs":      "/docs",
        "health":    "/api/v1/health",
        "analyze":   "POST /api/v1/analyze",
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check logs for details."},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )
