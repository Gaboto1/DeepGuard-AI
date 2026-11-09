# Validacion de septiembre de 2026 (antes: FINAL_VALIDATION_REPORT.md)
## DeepGuard AI — benchmark dentro de muestra
**Benchmark:** massive  |  **Imágenes:** 512  |  **Fecha:** 20260901

> **Medicion historica, no valida como evidencia (anotado el 2026-11-09).**
> Este informe es del 2026-09-01 y se midio sobre las mismas fuentes con las
> que se entrenaron los modelos. El `efficientnet_ffpp` aparece con F1 100 %
> y ROC-AUC 1.000 porque el probe CLIP se entrena con embeddings de esas
> fuentes: ahi juega con ventaja. Medido fuera de muestra, ese mismo detector
> da 0,987 y el `face_deepfake_vit` cae a 0,451 (por debajo del azar).
> Tambien hay confusion clase/origen: todo lo autentico venia de una carpeta
> y todo lo sintetico de otra, de modo que el ranking mide procedencia tanto
> como manipulacion.
>
> Se conserva como registro de lo que se creia en septiembre. Las cifras
> vigentes, con su procedencia declarada una por una, estan en
> `MEJORA_ENSEMBLE_v4.md` seccion 8.

---

## 1. Ranking de Modelos (por F1)

| Modelo | F1 | ROC-AUC | Precisión | Recall | FPR | FNR | Brier |
|--------|-----|---------|-----------|--------|-----|-----|-------|
| efficientnet_ffpp | 100.0% | 1.000 | 100.0% | 100.0% | 0.0% | 0.0% | 0.111 |
| face_deepfake_vit | 67.3% | 0.569 | 50.8% | 99.6% | 96.5% | 0.4% | 0.252 |
| siglip_deepfake | 64.0% | 0.192 | 48.5% | 94.1% | 100.0% | 5.9% | 0.510 |
| sdxl_detector | 57.5% | 0.886 | 98.1% | 40.6% | 0.8% | 59.4% | 0.273 |
| ensemble | 47.6% | 0.895 | 100.0% | 31.2% | 0.0% | 68.8% | 0.219 |
| ai_art_detector | 39.8% | 0.751 | 75.8% | 27.0% | 8.6% | 73.0% | 0.363 |

**ECE (ensemble):** 0.2084

---

## 2. Métricas por Categoría

| Categoría | Tipo | F1 | FPR | FNR | n |
|-----------|------|-----|-----|-----|---|
| ia | ia | 47.6% | 0.0% | 68.8% | 256 |
| real | real | 0.0% | 0.0% | 0.0% | 256 |

---

## 3. Robustez

| Variante | F1 | AUC | FPR | FNR |
|----------|-----|-----|-----|-----|
| jpeg_heavy | 0.0% | 0.500 | 3.3% | 0.0% |
| jpeg_medium | 0.0% | 0.500 | 0.0% | 0.0% |
| blur_light | 0.0% | 0.500 | 0.0% | 0.0% |
| blur_heavy | 0.0% | 0.500 | 76.7% | 0.0% |
| noise | 0.0% | 0.500 | 0.0% | 0.0% |
| resize_down | 0.0% | 0.500 | 0.0% | 0.0% |
| crop_center | 0.0% | 0.500 | 0.0% | 0.0% |
| whatsapp | 0.0% | 0.500 | 6.7% | 0.0% |

---

## 4. Optimización de Pesos del Ensemble

**F1 actual:** 47.6%
**F1 óptimo:** 69.1%

| Modelo | Peso Óptimo |
|--------|-------------|
| face_deepfake_vit | 0.30 |
| sdxl_detector | 0.20 |
| ai_art_detector | 0.20 |
| siglip_deepfake | 0.30 |

---

## 5. Modelos por Fortaleza / Debilidad

- **Modelo más fuerte (F1):** `efficientnet_ffpp`
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

- `reports\full_eval_massive_20260901_213312.csv` — resultados por imagen
- `reports\full_eval_massive_20260901_213312.json` — reporte completo JSON
- `reports/false_positives/` — imágenes reales mal clasificadas
- `reports/false_negatives/` — imágenes IA no detectadas