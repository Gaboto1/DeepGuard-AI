# ──────────────────────────────────────────────────────────────────────────────
# DeepGuard AI — Dockerfile API-only para Render free tier
#
# SIN torch · transformers · bitsandbytes · OpenCV · CUDA
# Build resultante: ~180 MB   RAM en producción: < 100 MB
#
# El procesamiento GPU ocurre en el worker Celery local que se conecta
# al mismo Redis externo (Upstash / Aiven).
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    API_ONLY=true

WORKDIR /app

# Dependencias del sistema mínimas (sin libGL/CUDA/ffmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar solo dependencias ligeras (ver requirements-api.txt)
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Código fuente
COPY app/ ./app/

# Directorios runtime
RUN mkdir -p uploads logs

# Healthcheck — Render lo usa para saber cuándo el servicio está listo
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 CMD curl -f http://localhost:${PORT:-8000}/api/v1/health || exit 1

# Render inyecta $PORT en el entorno automáticamente
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --log-level info"]
