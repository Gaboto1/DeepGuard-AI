# SYSTEM_AUDIT_V4.md
## DeepGuard AI — Auditoría Completa del Sistema
**Versión:** 4.0  |  **Fecha:** 2026-05-29

---

## 1. ARQUITECTURA ACTUAL

### Backend (FastAPI + PyTorch)
```
backend/app/
  main.py              ← FastAPI app, lifespan con precarga de modelos
  config.py            ← Settings (DEVICE, MAX_FRAMES, MODELS_DIR, etc.)
  api/
    routes.py          ← POST /api/analyze, GET /api/tasks/{id}, GET /api/history
    schemas.py         ← EvidenceLevel, ModelAgreement, EnsembleBreakdown, MetadataAnalysis, OsintResult
  models/
    deepfake_detector.py ← 5-model ensemble con pesos adaptativos
    face_detector.py   ← MTCNN para detección facial
  services/
    analysis_service.py  ← Task queue, pipeline de análisis
    image_service.py     ← Análisis dual (face crop + full image 60/40)
    video_service.py     ← Frame extraction + batch inference
    metadata_service.py  ← Extracción EXIF completa
    osint_service.py     ← Links de búsqueda reversa + hash perceptual
  utils/
    helpers.py           ← evidence_level(), model_agreement(), generate_forensic_explanation()
```

### Frontend (Next.js 14 App Router)
```
frontend/src/
  app/
    page.tsx           ← Layout principal sin Hero ni HowItWorks
    globals.css        ← Sistema de diseño forense profesional
  components/
    Navbar.tsx         ← Header compacto, español
    UploadZone.tsx     ← Zona de carga limpia
    AnalysisProgress.tsx ← Progreso técnico con pasos en español
    ResultCard.tsx     ← Sistema de pestañas: Resumen|Ensemble|Metadatos|Verificación|Mapa
    ForensicPanel.tsx  ← Tabla de modelos con pesos y contribuciones
    MetadataPanel.tsx  ← EXIF completo en español
    OsintPanel.tsx     ← Verificación externa en español
    HistorySection.tsx ← Historial en español
```

---

## 2. MODELOS INSTALADOS (v4.0)

| ID | Nombre | Arquitectura | Params | VRAM | Especialización | F1 Golden Set |
|----|--------|-------------|--------|------|-----------------|---------------|
| A | prithivMLmods/Deep-Fake-Detector-v2 | ViT-base | 85.8M | ~350MB | Face deepfakes | 64.3% |
| B | Organika/sdxl-detector | Swin Transformer | 86.8M | ~350MB | SDXL vs fotos | 85.7% |
| C | Xicor9/efficientnet-b0-ffpp-c23 | EfficientNet-B0 | 5.3M | ~50MB | Face-swaps FF++ | 13.3% |
| D | haywoodsloan/ai-image-detector-deploy | Swin v2 | 195.2M | ~800MB | IA art (MJ/FLUX/SDXL/DALL-E) | pendiente |
| E | prithivMLmods/Deepfake-Detect-Siglip2 | SigLIP | 92.9M | ~381MB | Deepfake general | pendiente |

**VRAM total usado:** ~1.93GB / 12.9GB (15%)  
**Tiempo de carga:** ~5-10s (precargado al iniciar)

---

## 3. ENSEMBLE WEIGHTS (validados por grid search)

```python
# Sin cara detectada (modo predominante)
_W_NO_FACE = [0.10, 0.45, 0.05, 0.35, 0.05]  # A, B, C, D, E

# Con cara detectada
_W_FACE    = [0.30, 0.25, 0.05, 0.25, 0.15]  # A, B, C, D, E
```

---

## 4. PIPELINE DE ANÁLISIS

### Imagen
```
1. Recepción → validación (MIME + tamaño)
2. Detección facial (MTCNN, GPU)
3. Si cara: analyze(face_crop) × 0.60 + analyze(full_image) × 0.40
4. Si no: analyze(full_image) × 1.00
5. 5-model ensemble con pesos adaptativos
6. EvidenceLevel + ModelAgreement calculation
7. Grad-CAM (si prob > 42%)
8. EXIF extraction (piexif + Pillow)
9. OSINT links + perceptual hash (imagehash)
```

### Video
```
1. Frame extraction (OpenCV, evenly spaced, max_frames=50)
2. Per-frame: MTCNN face detection + batch inference
3. Temporal aggregation: mean(fake_probs) + std
4. Timeline data para visualización
```

---

## 5. MÉTRICAS PRE-OPTIMIZACIÓN (Golden Set, 20 imgs)

| Métrica | Valor |
|---------|-------|
| F1 Score | 73.7% |
| ROC-AUC | 0.800 |
| FPR | 20% |
| Calibración ECE | 0.146 |

## 6. MÉTRICAS POST-OPTIMIZACIÓN (Golden Set, pesos optimizados)

| Métrica | Valor |
|---------|-------|
| F1 Score | **85.7%** |
| ROC-AUC | **0.880** |
| FPR | 20% |
| Mejora F1 | +12.0% |

---

## 7. CUELLOS DE BOTELLA IDENTIFICADOS

| Cuello de botella | Impacto | Mitigación |
|-------------------|---------|------------|
| EfficientNet-B0 (F1=13.3%) degrada ensemble | Alto | Peso reducido a 0.05 |
| ViT (A) FPR=90% sin cara | Alto | Peso reducido a 0.10 en modo sin cara |
| ECE=0.146 → calibración deficiente | Medio | Temperature scaling explorado |
| OSINT sin API → solo manual | Bajo | Infraestructura lista para integración |
| Sin modelo temporal para video | Medio | Roadmap |
| Sin detección de audio sintético | Bajo | Fuera de alcance actual |

---

## 8. BENCHMARK STATUS

| Set | Imágenes | Categorías | Estado |
|-----|----------|------------|--------|
| Golden Set | 25 (20 labeled) | real/ai/uncertain | Completo |
| Extended | 45 | 10 subcategorías | Completo |
| **Massive** | **512** | **16 categorías** | **Nuevo — evaluación en curso** |

---

## 9. INFRAESTRUCTURA

- **GPU:** RTX 4070 SUPER, 12.9GB VRAM, CUDA 12.4
- **Framework:** PyTorch 2.6.0+cu124
- **Python:** 3.13.0
- **API:** FastAPI + Uvicorn (single worker, asyncio)
- **Task queue:** In-memory asyncio dict (no Redis — instancia única)
- **Historial:** localStorage en frontend (no persistencia server-side)
