# DeepScan — Estructura del Proyecto

Plataforma forense de detección de deepfakes con arquitectura híbrida:
API en la nube (Render) + Worker GPU local (RTX 4070 SUPER) + Frontend estático (Render Static Site).

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
│   │   └── _redirects               # SPA fallback (compatible Netlify, Cloudflare y Render Static Site)
│   ├── next.config.js               # output:'export' para despliegue estático
│   ├── netlify.toml                 # Build config legado de Netlify (ya no es el hosting activo)
│   ├── .env.local                   # URL API local (localhost:8000)
│   ├── .env.production              # URL API Render (NO subir si tiene secretos)
│   ├── .env.production.example      # Template de variables de build (Render Static Site)
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
│   │   │   ├── deepfake_detector.py # 6 detectores (ViT, SDXL, probe CLIP, AiArt, SigLIP2, umm-maybe)
│   │   │   ├── face_detector.py     # MTCNN para detección y crop de rostros
│   │   │   ├── meta_ensemble.py     # 3 cabezales: full/noart logreg + face XGBoost
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
├── INICIAR PAGINA WEB.bat           # Arranca el worker GPU local (es lo que hace funcionar la web)
├── INICIAR LOCAL.bat                # Arranca el stack completo en localhost
├── VER PROGRESO.bat                 # Panel en vivo del pipeline y de la fase de medicion
├── scripts/preparar_worker.ps1      # Comprobacion previa: venv, .env, worker duplicado, VRAM libre
├── scripts/tee_log.py               # Duplica la salida del worker a pantalla y a reports/worker.log
├── scripts/medir_latencia.py        # Latencia real por la via de produccion -> reports/latencia_medida.json
├── tools/generar_informe.py         # Generador del informe Word (.docx)
├── .gitignore                       # Reglas Git: venv, .env, models, uploads, etc.
└── ESTRUCTURA_PROYECTO.md           # Este archivo
```

---

## Arquitectura de despliegue

```
  Usuario (navegador)
       │
       ▼
  GitHub Pages ───────────────────── Frontend estático (Next.js export)
  gaboto1.github.io/DeepGuard-AI    HTML + CSS + JS puro, sin servidor
       │
       │  POST /api/v1/analyze
       │  GET  /api/v1/tasks/{id}
       ▼
  Render (cloud) ─────────────────── API FastAPI (API_ONLY=true)
  deepguard-ai-api.onrender.com      Sin PyTorch · RAM < 100 MB
       │
       │  Celery dispatch
       ▼
  Upstash Redis ──────────────────── Message Broker Redis TLS (plan Free permanente)
  *.upstash.io:6379                  Cola de tareas asíncronas
       │
       │  Task received
       ▼
  PC Local (GPU) ─────────────────── Worker Celery GPU
  RTX 4070 SUPER 12 GB VRAM          8 señales + LLaVA 4-bit (~7.1 GB VRAM)
  INICIAR PAGINA WEB.bat              Procesa y guarda resultado en Upstash
```

> **Nota histórica:** el frontend se hosteaba originalmente en Netlify y el broker en Aiven Valkey. Se migró a Render Static Site + Upstash en junio de 2026 tras quedarse sin créditos gratuitos (Netlify) y expirar el plan trial (Aiven) — ver `docs/RUNBOOK_REDIS_DOWN.md`.

---

## Stack tecnológico

| Capa | Tecnología | Versión |
|------|-----------|---------|
| Frontend | Next.js + React + TypeScript | 14.0.4 |
| Estilos | Tailwind CSS + Framer Motion | 3.x |
| API | FastAPI + Uvicorn | 0.104.1 |
| Cola | Celery + Upstash Redis | 5.3+ |
| ML | PyTorch + CUDA | 2.x + cu124 |
| VLM | LLaVA-1.5-7b-hf (4-bit NF4) | bitsandbytes 0.43+ |
| Meta-ensemble | 3 cabezales (full/noart logreg, face XGBoost), umbral 0.8764 | 2.x |
| Custodia | SHA-256 + HMAC-SHA256 v2 | stdlib |
| Hosting API | Render (free tier) | — |
| Hosting Web | GitHub Pages (gratuito permanente) | — |
| Broker | Upstash Redis (free tier permanente) | 8.x |

---

## Métricas del modelo

Toda cifra declara si se midió **dentro** de muestra (fuentes que participan en
el entrenamiento) o **fuera** de muestra (`data/heldout/`: LFW, ImageNet-val,
FLUX y DALL·E 3, 7.000 imágenes que no entran en ningún plan de entrenamiento).
Sin esa distinción el proyecto ha producido ya cuatro mediciones falsas; están
documentadas en `reports/MEJORA_ENSEMBLE_v4.md`, secciones 4 y 11.

| Métrica | Valor | Procedencia |
|---------|-------|-------------|
| KPI-01 — señalamiento de deepfake facial | 94,0 % | **dentro** de muestra (ff++) |
| KPI-02 — falsas alarmas sobre fotografía auténtica | 0,7 % | **fuera** de muestra |
| KPI-03 — capacidad discriminativa (AUC) | 0,990 | **fuera** de muestra |
| KPI-05 — exactitud de la compuerta de tipo de contenido | 0,973 | mixto, declarado |
| Latencia del ensemble, sin análisis semántico | 5,3 s mediana · 11,7 s p95 | 49 análisis, GPU dedicada |
| Latencia total, lo que espera el usuario | 32,4 s mediana · 61,6 s p95 | 49 análisis, GPU dedicada |
| VRAM con todo residente (ensemble + LLaVA) | 7,1 GB / 12,9 GB | arranque del worker |
| Batería de pruebas automatizadas | 81, todas en verde | `pytest` en `backend/` |

> **La latencia depende del equipo, no solo del sistema.** Las cifras de arriba
> suponen la GPU dedicada. Con la memoria de vídeo ocupada por otras
> aplicaciones se degrada un orden de magnitud: 8 de esos 49 análisis corrieron
> con la VRAM saturada y dieron una mediana de 1.709 s. Conviene cerrar
> navegadores y juegos antes de arrancar el worker.

> **El `F1-Score 94,7 %` que figuraba aquí era falso.** Se calculaba con el
> cabezal facial aislado cuando producción lo mezcla con el track completo.
> Medido por la vía real daba 11 %. El relato está en
> `reports/MEJORA_ENSEMBLE_v4.md`, sección 4.1.
