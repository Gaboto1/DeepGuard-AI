import ssl as _ssl
from pathlib import Path
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "DeepScan"
    VERSION:  str = "6.0.0"
    DEBUG:    bool = False

    HOST: str = "0.0.0.0"
    PORT: int  = 8000

    # ── Modo de operación ─────────────────────────────────────────────────────
    API_ONLY: bool = False

    # ── Redis / Celery ────────────────────────────────────────────────────────
    REDIS_URL:     str = "redis://localhost:6379/0"
    REDIS_BACKEND: str = "redis://localhost:6379/1"

    # ── CORS ──────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS_CSV: str = (
        "http://localhost:3000,"
        "http://localhost:3001,"
        "http://127.0.0.1:3000,"
        "https://gaboto1.github.io"
    )

    # ── Archivos ──────────────────────────────────────────────────────────────
    MAX_FILE_SIZE_MB: int  = 500
    UPLOAD_DIR:       Path = Path("uploads")
    MODELS_DIR:       Path = Path("models")

    # ── Reportes ──────────────────────────────────────────────────────────────
    RESULTS_DIR: Path = Path("reports") / "tasks"
    CUSTODY_DIR: Path = Path("reports") / "custody"

    # ── Clave HMAC ────────────────────────────────────────────────────────────
    DEEPGUARD_SIGNING_KEY: str = ""

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

# Crear directorios necesarios al arrancar
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
settings.CUSTODY_DIR.mkdir(parents=True, exist_ok=True)
if not settings.API_ONLY:
    settings.MODELS_DIR.mkdir(parents=True, exist_ok=True)


def make_redis_client(url: str = "", **kwargs):
    """
    Crea un cliente redis-py compatible con redis-py 6.x y URLs de Aiven/Upstash.

    Problema: redis-py 6.x rechaza '?ssl_cert_reqs=CERT_NONE' en la URL con
    'Invalid SSL Certificate Requirements Flag: CERT_NONE'.
    Kombu (usado por Celery) parsea ese parámetro diferente — por eso las tareas
    funcionan pero redis.from_url() directo falla.

    Solución: strip del parámetro ssl_cert_reqs de la URL + pasarlo como objeto
    ssl.CERT_NONE directamente a from_url().
    """
    import redis

    if not url:
        url = settings.REDIS_URL

    parsed = urlparse(url)
    qs     = parse_qs(parsed.query, keep_blank_values=True)

    # Extraer ssl_cert_reqs de la query string y traducirlo a objeto Python
    ssl_param = qs.pop("ssl_cert_reqs", [None])[0]
    clean_url = urlunparse(parsed._replace(
        query=urlencode({k: v[0] for k, v in qs.items()}) if qs else ""
    ))

    # Configurar SSL si la URL usa rediss://
    if url.startswith("rediss://"):
        _map = {
            "CERT_NONE":     _ssl.CERT_NONE,
            "none":          _ssl.CERT_NONE,
            "CERT_OPTIONAL": _ssl.CERT_OPTIONAL,
            "optional":      _ssl.CERT_OPTIONAL,
            "CERT_REQUIRED": _ssl.CERT_REQUIRED,
            "required":      _ssl.CERT_REQUIRED,
        }
        kwargs.setdefault("ssl_cert_reqs", _map.get(ssl_param or "CERT_NONE", _ssl.CERT_NONE))

    return redis.from_url(clean_url, **kwargs)
