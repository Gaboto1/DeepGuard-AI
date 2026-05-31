# REPORT_NEXT_GEN_UPGRADE.md
## DeepGuard AI v5.1 — Corrección de Bug + Optimización del Meta-Ensemble
**Fecha:** 2026-05-30

---

## 1. PROBLEMA ORIGINAL

Una foto real comprimida (JPEG Q=40) mostraba scores individuales bajos en todos los modelos pero el meta-ensemble LightGBM v1 la elevaba erróneamente a **68.2%**, creando una contradicción visual con la tabla de pesos.

**Causa raíz identificada:**
El LightGBM v1 aprendió que `SigLIP≈96% + ViT≈65%` = fake, aunque SDXL y AI Art dijeran lo contrario. Esto ocurrió porque:
- SigLIP tiene **FPR=100%** (lo marca todo como fake)
- ViT tiene **FPR=96.5%** (muy poco fiable como detector)
- Ambos estaban incluidos como features del meta-modelo
- Sin regularización suficiente, el modelo sobreajustó estas correlaciones espurias

---

## 2. CAMBIOS IMPLEMENTADOS

### 2.1 Exclusión de features no confiables
Los modelos ViT (FPR=96.5%) y SigLIP (FPR=100%) fueron **eliminados de las features del meta-modelo**.

```python
# ANTES: 5 features incluyendo modelos no confiables
FEATURE_COLS = ["face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
                "ai_art_detector", "siglip_deepfake"]

# DESPUÉS: solo detectores confiables (FPR < 35%)
META_RELIABLE_FEATURES = ["sdxl_detector", "ai_art_detector", "efficientnet_ffpp"]
```

Los modelos ViT y SigLIP continúan en el **ensemble ponderado** (contribuyen al score visual) pero **no guían al meta-modelo**.

### 2.2 Regularización XGBoost (max_depth=2)
```python
XGBClassifier(
    n_estimators=30,
    max_depth=2,           # Solo 2 niveles — no puede combinar 3+ modelos
    reg_alpha=0.2,         # L1 regularización
    reg_lambda=1.0,        # L2 regularización
    subsample=0.8,
    colsample_bytree=0.8,
)
```

### 2.3 Temperature Scaling (T=0.581)
Calibración post-training que agiliza las probabilidades. T<1 indica que el modelo era conservador — Temperature Scaling lo corrige.

### 2.4 Feature Engineering (producto de robustos)
```python
sdxl_x_aiart = sdxl_detector * ai_art_detector  # Alto solo si AMBOS dicen fake
robust_mean  = (sdxl_detector + ai_art_detector) / 2
reliable_std = std([sdxl, ai_art, effnet])
```

### 2.5 Veto de Consenso
Si los detectores robustos (SDXL + AI Art) dicen real con alta confianza, el meta no puede ignorarlo:
```python
VETO_THRESHOLD      = 0.25   # robust_mean < 25%
VETO_MIN_DISCREPANCY= 0.35   # Meta debe discrepar >35% de robustos para vetar
VETO_STRENGTH       = 0.60   # 60% del veto aplica al resultado final
```

---

## 3. MÉTRICAS ANTES / DESPUÉS

### Golden Set (20 imágenes etiquetadas, independientes)

| Métrica | v1 LightGBM | v2 XGBoost | Delta |
|---------|------------|-----------|-------|
| **F1 Score** | 84.2% | **90.0%** | **+5.8%** |
| **ROC-AUC** | 0.910 | **0.960** | **+5.5%** |
| **FNR** | 20% | **10%** | **-50%** |
| FPR | 10% | 10% | = |
| **ECE** | 0.202 | **0.084** | **-58%** |
| Brier Score | 0.128 | ~0.09 | mejor |

### Casos específicos del bug

| Caso | v1 LightGBM | v2 XGBoost | Correcto? |
|------|------------|-----------|-----------|
| Foto real sin compresión | 17.1% | **2.4%** | ✅ |
| Foto real JPEG Q=40 (bug) | **68.2%** | **1.5%** | ✅ CORREGIDO |
| Retrato IA | 84.5% | **98.6%** | ✅ |

### Benchmark masivo 5-fold CV (512 imágenes)

| Método | F1 (CV) | ECE | FPR | FNR |
|--------|---------|-----|-----|-----|
| Pesos fijos actuales | 58.6% | 0.193 | — | — |
| Grid-search manual | 69.1% | 0.209 | — | — |
| Logistic Regression | 70.1% | 0.061 | — | 38.7% |
| **XGBoost (seleccionado)** | **88.7%** | **0.038** | — | **10.9%** |

---

## 4. FEATURE IMPORTANCE (XGBoost)

```
sdxl_x_aiart    ████████████████████  36.0%  <- producto de robustos
sdxl_detector   █████████████         25.1%  <- SDXL (FPR=0.8%)
ai_art_detector █████████             17.5%  <- AI Art (FPR=8.6%)
robust_mean     █████                 10.5%  <- media de robustos
efficientnet    ███                    5.6%
reliable_std    ██                     5.2%
```

Los features del bug (ViT y SigLIP) están completamente excluidos.

---

## 5. ARCHIVOS MODIFICADOS

```
scripts/train_meta_ensemble.py     ← Regularización, features confiables, T-Scaling
backend/app/models/meta_ensemble.py ← XGBoost + veto de consenso calibrado
models/meta_ensemble/
  meta_classifier.joblib           ← XGBoost entrenado (nuevo)
  meta_config.json                 ← Configuración actualizada
```

---

## 6. ESTADO FINAL

```
Backend:          http://localhost:8000  [ACTIVO]
Frontend:         http://localhost:3000  [ACTIVO]
Meta-ensemble:    XGBoost (depth=2, T=0.581)
Bug reproducido:  68.2% → 1.5%  [CORREGIDO]
Golden Set F1:    84.2% → 90.0% [MEJORADO]
Golden Set ECE:   0.202 → 0.084 [MEJORADO]
Golden Set FNR:   20%   → 10%   [MEJORADO]
```
