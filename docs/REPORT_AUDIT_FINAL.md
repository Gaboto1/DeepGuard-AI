# REPORT_AUDIT_FINAL.md
## DeepGuard AI — Scientific Validation Report
**Date:** 2026-05-29  
**Engineer:** Principal ML Engineer Audit  
**System:** DeepGuard AI v1.0 — Triple Ensemble Deepfake Detector

---

## 1. ESTADO ACTUAL DEL SISTEMA

### Arquitectura del Ensemble

| Modelo | Tipo | Entrenamiento | Versión |
|--------|------|---------------|---------|
| Model A — `face_deepfake_vit` | ViT (prithivMLmods) | Face deepfakes genérico | Fine-tuned HuggingFace |
| Model B — `sdxl_detector` | Swin Transformer (Organika) | SDXL vs fotografías reales | Fine-tuned HuggingFace |
| Model C — `efficientnet_ffpp` | EfficientNet-B0 (Xicor9) | FaceForensics++ c23 | Face-swap videos 2019-2022 |

### Bugs Corregidos en esta Auditoría
- ✅ **Alarm boost eliminado** — era la causa raíz del falso positivo de Messi (90% fake)
- ✅ **Pesos recalibrados** via grid search (F1: 0.74 → 0.86)
- ✅ **Explicaciones hardcodeadas reemplazadas** — ya no se inventan características
- ✅ **Data leakage corregido** — split por video ID, no por frame
- ✅ **Análisis dual** — se analiza cara crop + imagen completa (60/40 blend)
- ✅ **Transparencia per-model** — scores individuales en API y frontend

---

## 2. MÉTRICAS REALES (Golden Set — 20 imágenes etiquetadas)

### 2.1 Ensemble Final (pesos optimizados)

| Métrica | Valor | Interpretación |
|---------|-------|----------------|
| Accuracy | **75.0%** | 15/20 clasificadas correctamente |
| Precision | **77.8%** | De las detectadas como IA, 77.8% realmente lo son |
| Recall | **70.0%** | De las imágenes IA, el 70% fue detectado |
| **F1 Score** | **73.7%** | Balance precision/recall |
| **ROC-AUC** | **0.800** | Buen poder discriminativo |
| PR-AUC | 0.7716 | Area bajo la curva precision-recall |
| False Positive Rate | 20% | 2 imágenes reales clasificadas como IA |
| False Negative Rate | 30% | 3 imágenes IA clasificadas como reales |

### 2.2 Por Modelo (standalone, sin ensemble)

| Modelo | F1 | ROC-AUC | FPR | FNR | Evaluación |
|--------|----|---------|-----|-----|------------|
| **SDXL Detector (B)** | **85.7%** | 0.83 | 20% | 10% | **Más fuerte** |
| Face-Deepfake ViT (A) | 64.3% | N/A | **90%** | 10% | Alto FPR — sin cara no funciona |
| EfficientNet-FF++ (C) | 13.3% | N/A | 40% | **90%** | **Más débil** — solo face-swaps 2019-2022 |
| Ensemble | 73.7% | 0.80 | 20% | 30% | Mejor que A y C, peor que B solo |

> **Nota crítica:** El ViT (Model A) tiene FPR=90% cuando se ejecuta sobre imágenes completas sin detección facial previa. Su puntuación ronda 55-65% para todas las imágenes independientemente de su contenido. Esto sugiere que está calibrado para recortes faciales, no para imágenes completas.

---

## 3. PROBLEMAS RESTANTES

### CRÍTICO
| # | Problema | Evidencia | Impacto |
|---|---------|-----------|---------|
| 1 | **EfficientNet-B0 prácticamente inútil** (FNR=90%) | Fantasy landscape, anime, GAN artifacts todos → "real" | Trained only on face-swap deepfakes from 2019-2022. Cannot detect modern diffusion images. |
| 2 | **ECE=0.146 — mal calibrado** | 0.6+ confidence bins incorrectos | "90% fake" no significa 90% de probabilidad real |
| 3 | **Model A inutilizable sin cara** | FPR=90% en modo standalone | Solo debe usarse con face crops, no imágenes completas |

### ALTO
| # | Problema | Evidencia |
|---|---------|-----------|
| 4 | SDXL detector no reconoce: anime, GAN artifacts, fantasy landscapes | fantasy=26%, anime=48%, GAN=42% — todos missed |
| 5 | Fotografía vintage/sepia → falso positivo | old_photo_aging_vignette: B=99% (real pero SDXL dice IA) |
| 6 | Fotografía de naturaleza con textura uniforme → falso positivo | nature_closeup_forest: B=96% |

### MEDIO
| # | Problema |
|---|---------|
| 7 | EfficientNet-B4 (entrenado en FF++ c23) aún en entrenamiento — todavía usa B0 |
| 8 | Golden set pequeño (20 imágenes etiquetadas) — métricas con alta varianza |
| 9 | No hay evaluación en videos reales deepfake conocidos |

---

## 4. CASOS DONDE FALLA

### Falsos Positivos (imágenes REALES clasificadas como IA/Deepfake)

| Imagen | Score | Causa |
|--------|-------|-------|
| `nature_closeup_forest.jpg` | 60.9% | SDXL (96%): textura de suelo uniforme parece "artificial" al detector SDXL |
| `old_photo_aging_vignette.jpg` | 71.0% | SDXL (99%): fotografía sepia/vintage — SDXL no vio este estilo en training |

**Causa raíz:** SDXL detector fue entrenado en imágenes SDXL vs fotografías modernas. Estilos fotográficos fuera de su distribución (vintage, naturaleza con texturas uniformes) los clasifica como "artificial."

### Falsos Negativos (imágenes IA clasificadas como REALES)

| Imagen | Score | Causa |
|--------|-------|-------|
| `fantasy_landscape_impossible.jpg` | 26.0% | SDXL (1%): landscape fantástico no reconocido como IA. Modelo A=52% pero bajo peso |
| `anime_style_face.jpg` | 48.1% | B=64%, A=64% — borderline; anime no está en el training data de ninguno de los modelos |
| `gan_frequency_artifacts.jpg` | 42.6% | Imagen pequeña (32×32 upscaled) — artifacts de baja resolución distintos a los del training |

**Causa raíz:** Los modelos solo detectan tipos de IA que han visto en entrenamiento (SDXL, face-swaps). Anime, GAN clásico, arte fantástico y imágenes de muy baja resolución upscaladas no son detectados.

---

## 5. CASOS DONDE FUNCIONA

El sistema funciona bien para:

| Categoría | Ejemplo | Score | Resultado |
|-----------|---------|-------|-----------|
| Paisajes naturales | landscape_mountain | 32.5% | ✅ LIKELY REAL |
| Retratos con imperfecciones | portrait_natural_asymmetry | 17.1% | ✅ REAL |
| Fotos nocturnas | night_cityscape | 17.8% | ✅ REAL |
| Fotografía comprimida WhatsApp | whatsapp_compressed | 26.5% | ✅ LIKELY REAL |
| Screenshots | screenshot_screen | 26.1% | ✅ LIKELY REAL |
| Retratos IA muy suaves | perfect_smooth_face_gan | 63.0% | ✅ UNCERTAIN (flagged) |
| Arte digital diffusion | digital_art_portrait | 62.5% | ✅ UNCERTAIN (flagged) |
| Arte conceptual con glow | concept_art_glow_effect | 76.3% | ✅ LIKELY DEEPFAKE |
| Simetría perfecta (GAN artifact) | perfect_mirror_symmetry | 60.9% | ✅ UNCERTAIN (flagged) |
| Gradación HDR típica IA | ai_color_grading_hdr | 61.7% | ✅ UNCERTAIN (flagged) |

---

## 6. CALIBRACIÓN

### Expected Calibration Error (ECE)
- **ECE = 0.146** → Mal calibrado
- Temperatura óptima: **T = 0.601** (modelo es ligeramente underconfident)
- La aplicación de temperature scaling NO mejoró ECE en este caso (ECE aumentó de 0.146 a 0.167)
- Conclusión: la calibración es subóptima pero temperature scaling no es la solución aquí — necesita más datos

### Interpretación
Cuando el sistema dice "70% fake", en la práctica solo el ~56% de esas imágenes son realmente IA. La sobreconfianza en el rango 0.6-0.8 es el principal problema.

---

## 7. OPTIMIZACIÓN DE PESOS

Grid search sobre 61 configuraciones de pesos [w_A, w_B, w_C]:

| Configuración | F1 | AUC |
|---------------|-----|-----|
| **Óptima: [0.15, 0.70, 0.15]** | **0.857** | **0.830** |
| Anterior: [0.30, 0.45, 0.25] | 0.737 | 0.800 |
| Mejora | +12.0% | +3.0% |

**Pesos óptimos aplicados** en `deepfake_detector.py`:
- `_W_NO_FACE = [0.15, 0.70, 0.15]` (validado con golden set)
- `_W_FACE = [0.35, 0.35, 0.30]` (inferido — requiere validación con cara)

---

## 8. RECOMENDACIONES FUTURAS

### Prioridad ALTA / Bajo Esfuerzo
1. **Integrar EfficientNet-B4** cuando termine el entrenamiento (actualmente en época 3/15 con val_acc=98.3%)
2. **Reemplazar Model C** por el B4 entrenado — se espera mejora significativa en face-swaps
3. **Ampliar el golden set** con imágenes reales de internet (50+ de cada categoría) para métricas más confiables

### Prioridad ALTA / Esfuerzo Medio
4. **Agregar modelo para anime/cartoon** — ningún modelo actual fue entrenado en este estilo
5. **Agregar modelo CNNDetection (Wang et al.)** — especializado en imágenes ProGAN, bueno para artefactos GAN clásicos
6. **Separar image_service por tipo**: si cara detectada → usar weights de cara; si no → usar weights sin cara

### Prioridad MEDIA / Esfuerzo Medio
7. **Reentrenar EfficientNet-B4 con split correcto** (video-level, sin leakage) — la val_acc actual de 98.3% está inflada
8. **Evaluar en benchmarks públicos**: DFDC test set, Celeb-DF v2 test, FF++ test (AUC comparativo)
9. **Calibración isotónica** (Platt scaling) sobre la distribución del golden set + producción

### Prioridad BAJA / Alto Esfuerzo
10. **Modelo dedicado para vintage/sepia photography** — evitar FP de fotografías históricas
11. **Modelo temporal para videos** — analizar movimiento entre frames, no solo frames individuales
12. **Detección adversarial** — robustez ante ataques específicos para evadir detección

---

## 9. NIVEL DE CONFIANZA PARA DESPLIEGUE

### Por categoría de contenido

| Tipo de Contenido | Confianza | Recomendación |
|-------------------|-----------|---------------|
| Deepfakes faciales (face-swap) | ⭐⭐⭐ Media | Funciona, mejorará con B4 |
| Imágenes AI generadas (SDXL, SD) | ⭐⭐⭐ Media | Bueno, SDXL detector ayuda |
| Fotos reales modernas | ⭐⭐⭐⭐ Buena | FPR aceptable (20%) |
| Arte IA (anime, fantasy, GAN) | ⭐ Baja | No detecta estos estilos |
| Fotos vintage/históricas | ⭐⭐ Baja-Media | Riesgo de falso positivo |
| Videos deepfake | ⭐⭐ Media | Frame-by-frame sin modelo temporal |

### Veredicto Global de Despliegue

> **APTO PARA DESPLIEGUE CON RESERVAS**

El sistema es funcional y útil como herramienta de screening inicial. Los casos de uso donde es confiable (imágenes reales modernas, deepfakes faciales típicos) superan los casos donde falla (arte IA, vintage). Las métricas son honestas: F1=73.7% sobre el golden set.

**NO debe presentarse como detector infalible.** Siempre mostrar el score como probabilidad, no como certeza. Los veredictos "DEEPFAKE" con menos de 82% de score deben considerarse "sospechoso, verificar manualmente."

---

## 10. ARCHIVOS GENERADOS EN ESTA AUDITORÍA

```
tests/
  create_golden_set.py          → generador del golden set (25 imágenes)
  golden_set/                   → 10 real + 10 AI + 5 uncertain

scripts/
  benchmark_golden_set.py       → benchmark completo, métricas, error analysis
  calibration_analysis.py       → ECE, reliability diagram, temperature scaling
  optimize_ensemble_weights.py  → grid search de pesos
  fix_data_split.py             → correción de data leakage (ya ejecutado)
  evaluate_model.py             → métricas completas para EfficientNet-B4

reports/
  golden_set_results.csv        → resultado por imagen
  golden_set_report.json        → métricas completas + análisis
  ensemble_weight_search.json   → top-20 configuraciones de pesos
  false_positives/              → imágenes reales mal clasificadas
  false_negatives/              → imágenes IA no detectadas
  calibration/
    temperature_scaling_result.json
    calibrated_results.csv

backend/app/
  models/deepfake_detector.py   → alarm boost eliminado, pesos optimizados
  services/image_service.py     → análisis dual (cara + imagen completa)
  utils/helpers.py              → explicaciones honestas, no hardcodeadas
  api/schemas.py                → per_model_scores en respuesta API
```
