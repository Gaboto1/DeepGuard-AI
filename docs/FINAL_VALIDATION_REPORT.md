# FINAL_VALIDATION_REPORT.md
## DeepGuard AI — Validación Final
**Benchmark:** massive  |  **Imágenes:** 512  |  **Fecha:** 20260529

---

## 1. Ranking de Modelos (por F1)

| Modelo | F1 | ROC-AUC | Precisión | Recall | FPR | FNR | Brier |
|--------|-----|---------|-----------|--------|-----|-----|-------|
| face_deepfake_vit | 67.3% | 0.569 | 50.8% | 99.6% | 96.5% | 0.4% | 0.252 |
| siglip_deepfake | 64.0% | 0.192 | 48.5% | 94.1% | 100.0% | 5.9% | 0.510 |
| sdxl_detector | 57.5% | 0.886 | 98.1% | 40.6% | 0.8% | 59.4% | 0.273 |
| ensemble | 49.0% | 0.812 | 100.0% | 32.4% | 0.0% | 67.6% | 0.229 |
| efficientnet_ffpp | 42.1% | 0.472 | 51.7% | 35.5% | 33.2% | 64.5% | 0.429 |
| ai_art_detector | 39.8% | 0.751 | 75.8% | 27.0% | 8.6% | 73.0% | 0.363 |

**ECE (ensemble):** 0.2156

---

## 2. Métricas por Categoría

| Categoría | Tipo | F1 | FPR | FNR | n |
|-----------|------|-----|-----|-----|---|
| ia | ia | 49.0% | 0.0% | 67.6% | 256 |
| real | real | 0.0% | 0.0% | 0.0% | 256 |

---

## 3. Robustez

| Variante | F1 | AUC | FPR | FNR |
|----------|-----|-----|-----|-----|
| jpeg_heavy | 0.0% | 0.500 | 0.0% | 0.0% |
| jpeg_medium | 0.0% | 0.500 | 0.0% | 0.0% |
| blur_light | 0.0% | 0.500 | 0.0% | 0.0% |
| blur_heavy | 0.0% | 0.500 | 80.0% | 0.0% |
| noise | 0.0% | 0.500 | 0.0% | 0.0% |
| resize_down | 0.0% | 0.500 | 0.0% | 0.0% |
| crop_center | 0.0% | 0.500 | 0.0% | 0.0% |
| whatsapp | 0.0% | 0.500 | 6.7% | 0.0% |

---

## 4. Optimización de Pesos del Ensemble

**F1 actual:** 49.0%
**F1 óptimo:** 69.1%

| Modelo | Peso Óptimo |
|--------|-------------|
| face_deepfake_vit | 0.30 |
| sdxl_detector | 0.20 |
| ai_art_detector | 0.20 |
| siglip_deepfake | 0.30 |

---

## 5. Modelos por Fortaleza / Debilidad

- **Modelo más fuerte (F1):** `face_deepfake_vit`
- **Modelo más débil (F1):** `ai_art_detector`
- **Más falsos positivos (FPR):** `siglip_deepfake`
- **Más falsos negativos (FNR):** `ai_art_detector`

---

## 6. Riesgos y Limitaciones

- El ensemble fue evaluado sin detección facial (modo no-face) en el benchmark.
- Las imágenes son sintéticas — rendimiento en fotos reales puede variar.
- ECE > 0.10 indica calibración deficiente. Considerar temperature scaling.
- Los pesos óptimos se calcularon sobre este benchmark específico — validar con datos reales.

---

## 7. Archivos Generados

- `reports\full_eval_massive_20260529_232242.csv` — resultados por imagen
- `reports\full_eval_massive_20260529_232242.json` — reporte completo JSON
- `reports/false_positives/` — imágenes reales mal clasificadas
- `reports/false_negatives/` — imágenes IA no detectadas