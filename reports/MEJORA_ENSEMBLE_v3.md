# Mejora del ensemble v3 — separación del detector de arte IA

**Fecha:** 2026-09-28
**Alcance:** compuerta de tipo de contenido, doble cabezal del meta-ensemble,
corrección de tres defectos encontrados por el camino.

> **Superado por `MEJORA_ENSEMBLE_v4.md` (2026-11-09).** Las cifras de
> este documento corresponden al conjunto de 14.000 imagenes y seis
> fuentes, y al meta-ensemble entrenado entonces. Se conserva porque
> explica por que se tomaron las decisiones de diseno que siguen
> vigentes; para el estado actual del sistema, ver la v4.

---

## 1. Lo que se pidió

Separar el detector de arte IA para que no influya en el porcentaje final, y
mejorar los modelos en general.

## 2. Lo que se encontró al abrir el código

### 2.1 El meta-ensemble entrenado nunca se ejecutó en producción

`meta_ensemble.py` cargaba el artefacto con `data["model"]`, pero el `.joblib`
guarda el estimador bajo la clave `"clf"`. El `KeyError` caía en el `except`,
dejaba `_use_meta = False` y el sistema corría **siempre** con los pesos
fallback codificados a mano. El XGBoost con F1=99.1% y FPR=0.3% que figura en la
documentación nunca llegó a evaluar una sola imagen en producción.

### 2.2 El vector de features estaba desalineado

Aunque hubiera cargado, la inferencia construía 6 posiciones a mano que no
coincidían ni en orden ni en contenido con las 7 columnas de entrenamiento:

| Posición | Entrenamiento | Inferencia (v2) |
|---|---|---|
| 4 | `ai_human_detector` | `sdxl * ai_art` |
| 5 | `sdxl_x_aiart` | `(sdxl + ai_art) / 2` |
| 6 | `robust_mean` (mediana de 4) | `std` de 3 |
| 7 | `reliable_std` | — ausente — |

Ahora el vector se arma leyendo `feature_cols` del propio artefacto, y la carga
aborta con un error explícito si `n_features_in_` no cuadra. No puede volver a
desalinearse en silencio.

### 2.3 El dataset de entrenamiento confundía clase con fuente

Las 6.970 muestras del entrenamiento anterior venían así:

- **todo lo real** de `ff++_faces` (fotogramas de vídeo comprimido)
- **todo lo IA** de `real_world_training` (SD-turbo)

El modelo no aprendía "IA vs real", aprendía "de qué carpeta salió esto". Por eso
`ai_art_detector` alcanzaba AUC=0.9953 y concentraba el **91% de la importancia**:
el porcentaje final era, en la práctica, su sola opinión.

Se construyó `reports/dataset_v2_scores.csv`: 14.000 imágenes, cada clase
alimentada por varias fuentes independientes (coco, ff_real / diffusiondb,
sdturbo, sdturbo_sports, ff_fake), con la fuente registrada por fila.

---

## 3. La compuerta de tipo de contenido

`backend/app/models/content_type_gate.py` — CLIP ViT-L/14 zero-shot con ensemble
de prompts, clasifica **fotografía** vs **obra gráfica**. Reutiliza el CLIP que
ya carga el modelo C: 0 VRAM adicional.

| Conjunto | `artwork_probability` |
|---|---|
| COCO (foto natural) | 0.097 |
| FF++ real | 0.028 |
| FF++ fake (deepfake) | 0.046 |
| sdturbo_sports (IA fotorrealista) | 0.103 |
| DiffusionDB (arte IA) | 0.881 |

AUC foto-vs-arte = **0.973**. El deepfake facial y la IA fotorrealista quedan del
lado *fotografía*: la compuerta separa por tipo de contenido, no por autoría.

Es complementaria al detector OOD, que es heurístico y busca afiches y texto
denso.

---

## 4. Por qué el arte IA se separa SIEMPRE, y no sólo en obra gráfica

Primera hipótesis: excluirlo sólo cuando el contenido es obra gráfica. Los datos
la desmontaron — en este dataset el subconjunto "obra gráfica" es **90.6% IA**
(no hay una sola ilustración hecha por humanos), así que esa comparación estaba
igual de confundida que la original.

El dato que decidió fue el AUC por pista:

| Detector | Fotografía | Obra gráfica | Deepfakes vs foto real |
|---|---|---|---|
| **ai_art_detector** | 0.850 | **0.975** | 0.609 |
| efficientnet_ffpp (probe CLIP) | 0.529 | 0.647 | **0.863** |
| siglip_deepfake | 0.507 | 0.359 | 0.227 ⚠ |
| face_deepfake_vit | 0.567 | 0.616 | 0.392 ⚠ |

El detector de arte IA responde muy bien a *"¿generó una IA esta obra?"* (0.975)
y bastante mal a la pregunta forense *"¿fue manipulada esta fotografía?"* (0.609,
frente al 0.863 del probe CLIP). Como además dominaba el meta-modelo, el número
único que se mostraba respondía sobre todo a la pregunta del arte, fuera cual
fuera la imagen subida.

`AI_ART_POLICY = "always_separate"` en `meta_ensemble.py`. Cambiar a `"gated"`
lo reincorpora en contenido fotográfico.

> ⚠ `siglip_deepfake` (0.227) y `face_deepfake_vit` (0.392) están **invertidos**
> sobre deepfakes faciales: puntúan más alto los rostros reales que los
> manipulados. Queda pendiente de revisar.

---

## 5. Resultado

Tres configuraciones sobre las 14.000 imágenes, en bandas de evidencia (que es
lo que ve el usuario, no un veredicto binario):

| | A: lo que corría | B: con arte IA | C: arte separado |
|---|---|---|---|
| **Deepfakes faciales señalados** | **0.1%** | 6.4% | **49.9%** |
| Fotos auténticas mal marcadas | 5.7% | 3.2% | 12.5% |
| Exactitud global | 0.750 | 0.854 | 0.778 |

Error por fuente:

| Fuente | Clase | A | B | C |
|---|---|---|---|---|
| ff_fake (deepfakes) | IA | 0.996 | 0.912 | **0.312** |
| coco (foto real) | real | 0.426 | 0.042 | 0.149 |
| ff_real | real | 0.003 | 0.052 | 0.323 |
| diffusiondb (arte IA) | IA | 0.052 | 0.052 | 0.216 |
| sdturbo_sports | IA | 0.024 | 0.060 | 0.192 |

**B gana en agregado, pero es ciego a los deepfakes faciales** (los detecta en el
6.4% de los casos). El agregado lo favorece porque el dataset está dominado por
imágenes tipo arte IA. **C detecta la mitad de los deepfakes** a cambio de
duplicar las falsas alarmas sobre fotografía auténtica — y la capacidad de
detectar arte IA no se pierde: se muestra como su propio número.

Se eligió C. Es la configuración que hace que DeepScan sea un detector de
deepfakes y no un detector de arte IA con otro nombre.

### Rebalanceo por fuente

Sin él, el cabezal se apoyaba en el detector de SDXL (importancia 0.44) porque
las fuentes de arte IA aportan 5.400 de las 14.000 filas y ahogan a los 1.600
deepfakes. Igualar el peso de cada fuente bajó el error en `ff_fake` de
**0.591 → 0.312**.

---

## 6. Punto de operación

`AUC global (arte separado) = 0.883`. Curva sobre el umbral de decisión:

| Umbral | FPR global | Recall global | Error ff_fake |
|---|---|---|---|
| 0.50 | 0.224 | 0.779 | 0.312 |
| 0.60 | 0.125 | 0.693 | 0.501 |
| 0.70 | 0.078 | 0.642 | 0.699 |
| 0.80 | 0.045 | 0.580 | 0.876 |

**No se cambió el umbral ni las bandas de evidencia** (`<0.20` muy baja, `0.20–0.40`
baja, `0.40–0.60` inconclusa, `0.60–0.80` moderada, `≥0.80` fuerte): es una
decisión de producto que conviene tomar con criterio, no un ajuste técnico.

---

## 7. Otros dos defectos corregidos

### 7.1 Un score ausente se trataba como 0.0 confiable

`model_scores.get(k, 0) or 0` convertía un `None` en `0.0`. Si el detector de
arte IA fallaba al cargar, el Compression Veto veía "AI Art = 0% < 20%" y hundía
el score a ~8%: **un fallo de modelo producía el veredicto "auténtica"**. Ahora
las reglas distinguen ausente de cero y no se activan sin la evidencia que
invocan. Es también lo que garantiza que el arte IA no reentre por esa vía
cuando la compuerta lo deja fuera.

### 7.2 Todos los mapas de calor fallaban en silencio

`grad_cam` fijaba la ruta `vit.encoder.layer`, que esta versión de transformers
expone como `vit.layers`. La excepción se capturaba y devolvía `None`, así que la
función llevaba tiempo muerta sin que nada lo reportase. Además, pytorch-grad-cam
recibía el `ImageClassifierOutput` de HuggingFace en vez de un tensor de logits.
Corregidos ambos; los mapas de calor se generan de nuevo.

---

## 8. Tests

43 pasan. Cuatro de `test_forensic_corrections.py` fallaban **antes** de estos
cambios: afirmaban `ctype is None` en escenarios que el Compression Veto pasó a
cubrir deliberadamente al ampliarse (commit `8230460`), y el caso Messi usaba
`ai_art=0.005` esperando un resultado de `ai_art=0.12`. Se ajustaron a la
intención de cada test (que *su* regla no se active) en vez de a una afirmación
global que había dejado de ser cierta.

Nuevos: `test_meta_ensemble_dual_head.py` (construcción del vector, enrutamiento,
ambas políticas) y `test_gradcam_backbone.py` (resolución del backbone en ambas
versiones de transformers).

---

## 9. Archivos

**Nuevos:** `backend/app/models/content_type_gate.py`,
`scripts/score_dataset_v2.py`, `scripts/train_meta_dual_head.py`,
`scripts/eval_gating_impact.py`, `models/meta_ensemble/meta_classifier_noart.joblib`,
dos ficheros de tests.

**Modificados:** `meta_ensemble.py`, `deepfake_detector.py`, `image_service.py`,
`forensic_corrections.py`, `analysis_tasks.py`, `schemas.py`, `types/index.ts`,
`ResultCard.tsx`, `README.md`, `.gitignore`.

`.gitignore` usaba `/models/`, que impedía versionar el nuevo cabezal (git no
desciende a un directorio excluido). Cambiado a `/models/*` con excepción para
`meta_ensemble/`; los 19 GB de pesos HuggingFace y los `.bak` siguen ignorados.

El artefacto original de producción sigue recuperable con
`git show HEAD:models/meta_ensemble/meta_classifier.joblib`.

---

## 10. Pendiente

- Decidir el punto de operación (sección 6).
- Conseguir **ilustración hecha por humanos**: el dataset no tiene ninguna, y es
  justo el caso que la separación protege. Sin ella sólo se puede medir el coste
  de separar, no el beneficio.
- Revisar `siglip_deepfake` y `face_deepfake_vit`, invertidos sobre deepfakes.
- El probe CLIP es el mejor detector para deepfakes (AUC 0.863) y recibe apenas
  0.077 de importancia. Merece un cabezal específico para rostros.
- Nada se ha commiteado; los cambios están en el working tree.
