# DeepGuard AI — Estructura del Proyecto

Plataforma forense de detección de deepfakes con arquitectura híbrida:
API en la nube (Render) + Worker GPU local (RTX 4070 SUPER) + Frontend estático (Netlify).

---

## Árbol de directorios

```
PROYECTO TITULO FINAL/
│
├── frontend/                        # Interfaz web (Next.js 14, TypeScript)
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx           # Layout raíz con CSS global
│   │   │   └── page.tsx             # Página principal (única ruta)
│   │   ├── components/
│   │   │   ├── Navbar.tsx           # Barra de navegación + badge de estado API
│   │   │   ├── UploadZone.tsx       # Zona drag-and-drop de archivos
│   │   │   ├── AnalysisProgress.tsx # Terminal forense de progreso (8 etapas)
│   │   │   ├── ResultCard.tsx       # Tarjeta de resultados con gauge segmentado
│   │   │   ├── ForensicPanel.tsx    # Tab Ensemble: tabla de modelos + custodia
│   │   │   ├── MetadataPanel.tsx    # Tab Metadatos: EXIF/XMP/IPTC
│   │   │   ├── OsintPanel.tsx       # Tab Verificación: OSINT y hash perceptual
│   │   │   └── HistorySection.tsx   # Historial en localStorage (últimos 50)
│   │   ├── lib/
│   │   │   └── api.ts               # Cliente Axios: upload, polling, normalización
│   │   └── types/
│   │       └── index.ts             # Interfaces TypeScript del dominio forense
│   ├── public/
│   │   └── _redirects               # SPA fallback para Netlify
│   ├── next.config.js               # output:'export' para despliegue estático
│   ├── netlify.toml                 # Build config Netlify + env vars
│   ├── .env.local                   # URL API local (localhost:8000)
│   ├── .env.production              # URL API Render (NO subir si tiene secretos)
│   ├── .env.production.example      # Template documentado para Netlify
│   ├── tailwind.config.ts           # Paleta forense personalizada
│   └── Dockerfile                   # Imagen nginx para despliegue Docker alternativo
│
├── backend/                         # API FastAPI + Worker Celery (Python 3.13)
│   ├── app/
│   │   ├── main.py                  # Entry point FastAPI, CORS, lifespan condicional
│   │   ├── config.py                # Settings Pydantic (API_ONLY, REDIS_URL, CORS)
│   │   ├── celery_app.py            # Configuración Celery + colas (images/videos)
│   │   │
│   │   ├── api/
│   │   │   ├── schemas.py           # Modelos Pydantic: AnalysisResult, SemanticAnalysis...
│   │   │   ├── routes.py            # Rutas legacy /api/* (modo local)
│   │   │   └── v1/
│   │   │       └── routes.py        # API enterprise /api/v1/* (producción cloud)
│   │   │
│   │   ├── models/
│   │   │   ├── deepfake_detector.py # 5 modelos ensemble (ViT, SDXL, CLIP, AiArt, SigLIP)
│   │   │   ├── face_detector.py     # MTCNN para detección y crop de rostros
│   │   │   ├── meta_ensemble.py     # XGBoost + Temperature Scaling (T=0.581)
│   │   │   └── ood_detector.py      # Detector Out-of-Distribution (5 señales)
│   │   │
│   │   ├── services/
│   │   │   ├── analysis_service.py         # Orquestador async (modo local con LLaVA)
│   │   │   ├── image_service.py            # Pipeline imagen: OOD→ensemble→Grad-CAM
│   │   │   ├── video_service.py            # Pipeline video: frame-by-frame + temporal
│   │   │   ├── video_temporal_service.py   # ViT embeddings + flujo óptico Farneback
│   │   │   ├── semantic_inspection_service.py # LLaVA-1.5-7b-hf (4-bit NF4) análisis VLM
│   │   │   ├── forensic_metadata_service.py   # EXIF/XMP/IPTC + firmas generadores IA
│   │   │   ├── custody_service.py          # SHA-256 + HMAC-SHA256 cadena de custodia v2
│   │   │   ├── metadata_service.py         # Extracción básica de metadatos EXIF
│   │   │   └── osint_service.py            # Hash perceptual + links de búsqueda inversa
│   │   │
│   │   ├── tasks/
│   │   │   └── analysis_tasks.py    # Tareas Celery GPU (imagen + video)
│   │   │                            # Incluye transmisión base64 para arquitectura híbrida
│   │   └── utils/
│   │       ├── helpers.py           # get_evidence_level, generate_forensic_explanation
│   │       ├── file_validator.py    # Validación MIME, tamaño, tipo real
│   │       └── forensic_corrections.py # Reglas OOD Bypass + Compression Veto
│   │
│   ├── uploads/                     # Archivos temporales (en .gitignore)
│   ├── requirements.txt             # Deps completas con GPU (para worker local)
│   ├── requirements-api.txt         # Deps ligeras sin GPU (para Render)
│   ├── Dockerfile                   # Imagen slim para Render (API_ONLY=true)
│   ├── .env                         # Secretos locales (en .gitignore)
│   ├── .env.production.example      # Template para Render dashboard
│   └── .env.worker.example          # Template para worker GPU local
│
├── reports/                         # Reportes de análisis (en .gitignore)
│   ├── tasks/                       # JSON de resultados Celery por task_id
│   └── custody/                     # Sellos HMAC-SHA256 de cadena de custodia
│
├── models/                          # Pesos de modelos descargados (en .gitignore, >GB)
│
├── START CELERY WORKER.bat          # Script para arrancar el worker GPU local
├── start-backend.bat                # Script para arrancar FastAPI local
├── start-frontend.bat               # Script para arrancar Next.js local
├── generar_informe.py               # Generador del informe Word (.docx)
├── .gitignore                       # Reglas Git: venv, .env, models, uploads, etc.
└── ESTRUCTURA_PROYECTO.md           # Este archivo
```

---

## Arquitectura de despliegue

```
  Usuario (navegador)
       │
       ▼
  Netlify CDN ──────────────────── Frontend estático (Next.js export)
  deepguard-ai-inacap.netlify.app   HTML + CSS + JS puro, sin servidor
       │
       │  POST /api/v1/analyze
       │  GET  /api/v1/tasks/{id}
       ▼
  Render (cloud) ─────────────────── API FastAPI (API_ONLY=true)
  deepguard-ai-api.onrender.com      Sin PyTorch · RAM < 100 MB
       │
       │  Celery dispatch
       ▼
  Aiven Valkey ───────────────────── Message Broker Redis TLS
  valkey-3b64...aivencloud.com:13419 Cola de tareas asíncronas
       │
       │  Task received
       ▼
  PC Local (GPU) ─────────────────── Worker Celery GPU
  RTX 4070 SUPER 12 GB VRAM          5 modelos + LLaVA 4-bit (~6.8 GB VRAM)
  START CELERY WORKER.bat            Procesa y guarda resultado en Aiven
```

---

## Stack tecnológico

| Capa | Tecnología | Versión |
|------|-----------|---------|
| Frontend | Next.js + React + TypeScript | 14.0.4 |
| Estilos | Tailwind CSS + Framer Motion | 3.x |
| API | FastAPI + Uvicorn | 0.104.1 |
| Cola | Celery + Aiven Valkey (Redis) | 5.3+ |
| ML | PyTorch + CUDA | 2.x + cu124 |
| VLM | LLaVA-1.5-7b-hf (4-bit NF4) | bitsandbytes 0.43+ |
| Meta-ensemble | XGBoost + T-Scaling (T=0.581) | 2.x |
| Custodia | SHA-256 + HMAC-SHA256 v2 | stdlib |
| Hosting API | Render (free tier) | — |
| Hosting Web | Netlify (free tier) | — |
| Broker | Aiven Valkey (free tier) | 7.2.4 |

---

## Métricas del modelo

| Métrica | Valor |
|---------|-------|
| F1-Score | 94.7% |
| Error de Calibración (ECE) | 0.084 |
| Tasa de Falsos Positivos | 10% |
| VRAM utilizada (ensemble + LLaVA) | ~6.8 GB / 12.9 GB |
| Latencia imagen completa | < 5 s (GPU local) |
