"""
Celery Application — DeepScan Enterprise
=============================================
Workers exclusivos para procesamiento GPU pesado.
FastAPI solo recibe peticiones y despacha tareas.

Arquitectura:
  FastAPI (ligero, sin modelos) → Redis Broker → Celery Workers (GPU + modelos)
                                ← Redis Backend ← resultados JSON

El aislamiento garantiza:
  - API siempre responde < 200ms (solo valida y despacha)
  - Workers pueden usar toda la VRAM disponible sin compartirla con la API
  - Escalado horizontal: múltiples workers para procesamiento paralelo
"""
import os
from celery import Celery
from kombu import Queue

# Lee desde config (que a su vez lee desde .env)
# Soporta URLs TLS de Upstash/Aiven: rediss://user:token@host:port
from app.config import settings
REDIS_URL     = settings.REDIS_URL
REDIS_BACKEND = settings.REDIS_BACKEND

celery_app = Celery(
    "deepscan",
    broker=REDIS_URL,
    backend=REDIS_BACKEND,
    include=["app.tasks.analysis_tasks"],
)

celery_app.conf.update(
    # Broker connection timeout — evita bloqueos cuando Redis no está disponible
    broker_connection_timeout=2.0,
    broker_connection_retry=False,      # no reintentar al inicio (fail fast)
    broker_connection_retry_on_startup=False,
    broker_transport_options={
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "retry_policy": {"timeout": 2.0},
    },

    # Serialización
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    # Colas con prioridad
    task_queues=(
        Queue("images",  routing_key="image.#",   queue_arguments={"x-max-priority": 10}),
        Queue("videos",  routing_key="video.#",   queue_arguments={"x-max-priority": 5}),
        Queue("default", routing_key="default.#"),
    ),
    task_default_queue="default",
    task_default_exchange="deepscan",
    task_default_routing_key="default.task",

    # Performance
    worker_prefetch_multiplier=1,        # 1 tarea por worker a la vez (GPU exclusivo)
    task_acks_late=True,                 # ACK solo tras completar (evita pérdidas)
    task_reject_on_worker_lost=True,
    result_expires=86400,                # resultados 24h en Redis

    # Timeouts
    task_soft_time_limit=600,            # 10 minutos soft limit (video largo)
    task_time_limit=900,                 # 15 minutos hard limit

    # Reintentos automáticos
    task_max_retries=2,
    task_default_retry_delay=30,

    # Track state para endpoint /tasks/{id}
    task_track_started=True,
    result_extended=True,
)

# Routing: videos van a la cola de video, imágenes a la de imagen
celery_app.conf.task_routes = {
    "app.tasks.analysis_tasks.analyze_image_task": {
        "queue": "images",
        "routing_key": "image.analyze",
    },
    "app.tasks.analysis_tasks.analyze_video_task": {
        "queue": "videos",
        "routing_key": "video.analyze",
    },
}
