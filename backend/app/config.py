from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "DeepGuard AI"
    VERSION:  str = "6.0.0"
    DEBUG:    bool = False

    HOST: str = "0.0.0.0"
    PORT: int  = 8000

    # ── Modo de operación ─────────────────────────────────────────────────────
    # API_ONLY=true  → Render / cloud: SIN torch ni modelos. Solo valida y despacha.
    # API_ONLY=false → Desarrollo local: carga modelos GPU en el lifespan.
    API_ONLY: bool = False

    # ── Redis / Celery ────────────────────────────────────────────────────────
    # En producción: URL de Upstash o Aiven Redis con TLS
    # Ejemplo Upstash: rediss://default:TOKEN@HOST:PORT
    REDIS_URL:     str = "redis://localhost:6379/0"
    REDIS_BACKEND: str = "redis://localhost:6379/1"

    # ── CORS ──────────────────────────────────────────────────────────────────
    # CSV de orígenes permitidos.
    # En producción añadir la URL de Vercel: "https://deepguard.vercel.app"
    ALLOWED_ORIGINS_CSV: str = (
        "http://localhost:3000,"
        "http://localhost:3001,"
        "http://127.0.0.1:3000,"
        "https://deepguard-ai-inacap.netlify.app"
    )

    # ── Archivos ──────────────────────────────────────────────────────────────
    MAX_FILE_SIZE_MB: int  = 500
    UPLOAD_DIR:       Path = Path("uploads")
    MODELS_DIR:       Path = Path("models")

    # ── Modelos ───────────────────────────────────────────────────────────────
    MODEL_NAME: str = "dima806/deepfake_vs_real_image_detection"
    DEVICE:     str = "cuda"

    # ── Video ─────────────────────────────────────────────────────────────────
    MAX_FRAMES:          int = 50
    VIDEO_FRAME_INTERVAL:int = 10

    # ── Misc ──────────────────────────────────────────────────────────────────
    FILE_CLEANUP_DELAY:    int = 3600
    RATE_LIMIT_PER_MINUTE: int = 20

    @property
    def ALLOWED_ORIGINS(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS_CSV.split(",") if o.strip()]

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

# Ensure upload directory exists (models dir only needed on workers)
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
if not settings.API_ONLY:
    settings.MODELS_DIR.mkdir(parents=True, exist_ok=True)
