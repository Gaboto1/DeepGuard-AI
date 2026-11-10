# Mejora del ensemble v4 — reentrenamiento y medición fuera de muestra

**Fecha:** 2026-11-09
**Continúa:** `MEJORA_ENSEMBLE_v3.md` (2026-09-28), cuyas cifras quedan superadas
**Alcance:** reentrenamiento con 68.000 muestras, construcción del primer
conjunto retenido del proyecto, corrección de tres defectos que afectaban al
resultado que ve el usuario, y actualización de los tres entregables.

---

## 1. Resumen

| | septiembre 2026 | noviembre 2026 |
|---|---|---|
| Deepfakes faciales señalados | 49,9 % | **94,0 %** |
| Fotografía auténtica marcada por error | 12,5 % | **0,7 %** |
| AUC | 0,883 | **0,990** *(fuera de muestra)* |
| Muestras de entrenamiento | 14.000 | **68.000** |
| Fuentes independientes | 6 | **9** *(+4 retenidas)* |
| Pruebas automatizadas | 58 | **78** |
| Error LOSO medio, cabezal completo | 5,47 % | **1,23 %** |
| Error LOSO medio, cabezal sin arte | 18,73 % | **1,23 %** |

Los tres KPI que el informe declaraba por debajo de su objetivo lo superan:
KPI-01 (meta ≥ 60 %), KPI-02 (meta ≤ 8 %) y KPI-03 (meta ≥ 0,90).

## 2. El cambio de método: un conjunto retenido

Hasta esta iteración **toda** cifra de validación procedía de las mismas
fuentes con las que se entrena. Eso basta para comparar configuraciones entre
sí, pero no responde la única pregunta que importa en producción: qué ocurre
ante una fotografía o un generador que el modelo no vio nunca.

Ese hueco explica el fallo que el usuario reportó: su propia selfie de webcam
marcada al 53 %, mientras el banco de pruebas declaraba cero falsas alarmas.
El banco compartía el punto ciego con el modelo.

Se construyeron 7.000 imágenes de cuatro dominios ausentes de todo plan de
entrenamiento (`scripts/download_heldout.py`):

| fuente | clase | n | por qué |
|---|---|---|---|
| LFW | auténtica | 2.000 | rostros fotografiados sin control de estudio; el dominio más cercano a lo que sube un usuario. CelebA, que sí está en entrenamiento, son retratos de prensa |
| ImageNet-val | auténtica | 2.000 | fotografía general de 1.000 categorías, donde COCO se concentra en escenas urbanas |
| FLUX | sintética | 1.500 | arquitectura de generación sin linaje común con lo entrenado |
| DALL·E 3 | sintética | 1.500 | ídem |

Codificación idéntica a la del conjunto v3 (JPEG 92, lado máximo 1024) para que
el formato no sea por sí mismo una pista de clase.

## 3. Tres defectos que afectaban al resultado del usuario

### 3.1 La selección de modelo premiaba el ajuste sobre la generalización

El entrenamiento elegía por AUC de validación cruzada redondeado a **tres**
decimales. Con 68.000 muestras ese AUC se satura y la tercera cifra es ruido:

| clasificador | CV AUC | FPR | LOSO medio | LOSO peor |
|---|---|---|---|---|
| xgboost (elegido antes) | 0,9996 | 0,73 % | 1,78 % | 10,87 % |
| logreg (elegido ahora) | 0,9988 | **0,49 %** | **1,23 %** | **8,62 %** |

Se cedía medio punto de error ante fuentes nuevas a cambio de seis
diezmilésimas de AUC dentro de muestra. Redondeando a dos decimales ambos
empatan y decide el error leave-one-source-out. El efecto más visible está en
`ff_real_comp` —rostros reales de vídeo recomprimido, el caso de la queja
original— que pasó del 9,40 % al 3,90 % de error.

Como efecto secundario el cabezal pasó a ser una regresión logística, más
interpretable que un árbol: sus coeficientes tienen signo y escala común.

### 3.2 El cabezal facial quedaba vetado por el track incompetente

Cuando se detecta un rostro, el resultado mezcla dos pasadas. El peso estaba en
0,60 desde el *release* v6.0, **anterior al cabezal facial**: se fijó cuando
ambos tracks corrían el mismo modelo genérico y no había razón para confiar más
en uno. Al entrenar un cabezal específico para rostro —validado por identidad,
AUC 0,9968— el peso no se movió.

Sobre ff++ el track de imagen completa promedia 0,476 ante un deepfake, porque
está calibrado para imagen de difusión. El facial promedia 0,971. Con 0,60/0,40
la mezcla daba 0,773 y el umbral es 0,8764:

| peso facial | detección IA | FPR | error `ff_fake` |
|---|---|---|---|
| 0,60 | 80,41 % | 0,030 % | 88,70 % |
| **0,80** | **93,23 %** | **0,027 %** | **11,74 %** |
| 1,00 | 94,30 % | 0,067 % | 5,32 % |

El 88,7 % de los deepfakes faciales caía del lado equivocado del umbral por una
constante heredada. Se eligió 0,80 y no 1,00 porque mejora la detección y
**además** baja el FPR respecto a 0,60 —no hay nada que ceder— y porque conserva
un 20 % del track completo, necesario por lo que sigue.

### 3.3 El cabezal facial opera fuera de dominio ante rostros sintéticos

Subir el peso a 0,80 introdujo una regresión: sobre el retenido, las imágenes de
IA erróneamente descartadas pasaron del 4,9 % al 12,6 %, y 29 imágenes de FLUX
se movieron de «Inconclusive» a «Low Evidence».

La causa es de dominio. El cabezal facial se entrena **solo** con ff++, es decir
intercambio de rostro sobre fotografía; nunca vio un rostro enteramente
sintético, y ante un retrato generado lo declara auténtico. FLUX y DALL·E 3
están llenos de retratos generados.

La compuerta de tipo de contenido separa los dos casos con holgura
(`reports/diagnostico_compuerta_rostro.json`, 200 imágenes por fuente):

| fuente | naturaleza | obra gráfica | con rostro | ambos |
|---|---|---|---|---|
| `ff_fake` | intercambio de rostro | 1,0 % | 100,0 % | 1,0 % |
| `ff_real` | rostro real | 0,0 % | 100,0 % | 0,0 % |
| `lfw` | rostro real retenido | 0,0 % | 100,0 % | 0,0 % |
| `flux` | rostro sintético | 68,5 % | 18,0 % | 5,5 % |
| `dalle3` | rostro sintético | 79,5 % | 32,5 % | 23,5 % |

La columna «ambos» es la decisiva: 5,5 % en FLUX, prácticamente la misma
proporción que la regresión medida (29 de 500 = 5,8 %). Y `ff_fake` es obra
gráfica en el 1 % de los casos, de modo que condicionar el peso no toca la
ganancia en deepfake facial.

El peso pasó a depender del tipo de contenido: 0,80 en fotografía, 0,30 en obra
gráfica. No se lleva a cero porque un intercambio de rostro dentro de una
ilustración es concebible, y el cabezal facial es la única pieza entrenada para
verlo.

| | w=0,60 | w=0,80 plano | w=0,80/0,30 |
|---|---|---|---|
| ff++ detección deepfake | 11,7 % | 85,5 % | **85,5 %** |
| retenido AUC | 0,9903 | 0,9894 | **0,9906** |
| retenido señala IA | 74,60 % | 73,90 % | **76,70 %** |
| retenido falsa alarma | 0,70 % | 0,70 % | **0,70 %** |
| retenido IA descartada | **4,90 %** | 12,60 % | 9,40 % |

La recuperación es parcial y la causa está identificada: el 12,5 % de FLUX tiene
rostro pero la compuerta lo clasifica como fotografía —son retratos
fotorrealistas— y ahí el peso alto sigue aplicándose. El enrutado no puede
arreglarlo. Ver §7.

## 4. Dos errores de medición corregidos

Ninguno afectaba al sistema; ambos afectaban a lo que el proyecto **creía** de
sí mismo, que en un trabajo de título es igual de grave.

### 4.1 El KPI principal se medía sobre una pieza, no sobre el sistema

El KPI de deepfake facial se calculaba con `meta.predict(s, face=True)`, es
decir el cabezal facial aislado. Producción no usa ese cabezal aislado: lo
mezcla con el track completo. La diferencia era de más de 80 puntos.

```
cabezal facial aislado    ff_fake score medio 0,9711  ->  error  5,3 %
mezcla de producción      ff_fake score medio 0,7732  ->  error 88,7 %
```

El informe habría declarado un 94,7 % de detección mientras la página web daba
un 11 %. `scripts/eval_informe_kpis.py` replica ahora la mezcla de producción.

### 4.2 Medir sin cargar los modelos da un AUC de azar que parece válido

`_run_image_analysis` no carga los detectores: espera que ya estén en GPU, como
los deja el worker de Celery en `worker_process_init`. Sin esa carga los seis
devuelven `None`, sus pesos caen a cero y el score final sale de dos heurísticas
de CPU donde SRM pesa el 57 % y devuelve ~0,7–1,0 para casi cualquier imagen.

El sistema no avisa: reporta `method: "meta_logreg_face"` y una banda de
evidencia con aire de confiable. Una foto real de ImageNet daba **0,786** sin
carga y **0,017** con ella; el AUC medido era 0,525, es decir azar.

El worker de producción sí precarga y hace `raise` si falla, de modo que la web
no sirve en ese estado. El defecto era del guion de medición, que ahora carga
explícitamente y **aborta** si algún detector no quedó cargado.

## 5. La tabla 4 del informe estaba sesgada

El AUC por detector se calculaba sobre `reports/dataset_v2_scores.csv`, donde un
detector no juega el mismo partido que los otros cinco: el probe CLIP se entrena
con embeddings de esas mismas fuentes, de modo que su AUC allí es **dentro de
muestra**, mientras los otros cinco son modelos preentrenados de terceros que
nunca vieron esas imágenes.

Medidos sobre el retenido, donde los seis están fuera de muestra, el orden
cambia:

| detector | AUC en el CSV | AUC fuera de muestra |
|---|---|---|
| D detector de arte IA | 0,869 | **0,992** |
| C probe CLIP ViT-L/14 | 0,9997 | **0,987** |
| B sdxl-detector | 0,811 | **0,905** |
| E Deepfake-Detect-Siglip2 | 0,559 | **0,765** |
| A Deep-Fake-Detector-v2 | 0,486 | **0,451** |
| F umm-maybe AI-detector | 0,622 | **0,345** |

Dos consecuencias para el relato del proyecto:

**El detector que se separó es el mejor del conjunto fuera de muestra.** Eso no
invalida la decisión de septiembre: se separó por responder a otra pregunta y
por concentrar el 91 % del peso, no por ser malo. Pero la respuesta honesta ante
un evaluador que pregunte es ésta, no la anterior.

**Dos detectores van por debajo del azar.** F puntúa los rostros reales de LFW
en 0,715 y las imágenes de FLUX en 0,307: está invertido. A hace lo mismo con
LFW en 0,760. Ambos aparecían ya marcados con ⚠ en la tabla de la v3; ahora hay
prueba fuera de muestra. El meta-ensemble dejó a A fuera de las features de su
cabezal principal por su cuenta.

## 6. Una feature con el signo mal aprendido, medida y conservada

`ai_human_detector` entra en el cabezal completo con coeficiente **positivo**
(+0,714, el 5,0 % del peso) y fuera de muestra está invertido. Un coeficiente
positivo sobre un detector invertido empuja la fotografía auténtica hacia «IA».

Se midió si conviene quitarlo, entrenando cada candidato sobre las 60.000 y
evaluando sobre las 2.000 retenidas (`scripts/seleccion_features_heldout.py`):

| candidato | n feat | AUC retenido | señala IA | falsa alarma |
|---|---|---|---|---|
| actual | 7 | 0,9948 | 99,00 % | 7,40 % |
| sin F | 6 | 0,9954 | 99,00 % | 7,40 % |
| sin F sin interacción | 5 | 0,9949 | 98,90 % | 7,20 % |
| solo los tres buenos | 5 | 0,9949 | 98,90 % | 7,20 % |
| mínimo (CLIP + arte) | 2 | 0,9961 | 97,50 % | 7,40 % |

Quitarlo no cambia nada medible. La razón es aritmética: el coeficiente del
probe CLIP es +9,18, trece veces mayor. La feature va en dirección equivocada
pero no tiene fuerza para mover el resultado. **Se conserva**, documentada.

El experimento reveló algo mayor que lo que iba a buscar. Sobre las mismas 2.000
imágenes retenidas:

```
                     meta-ensemble solo    sistema completo
señala IA                      99,0 %              76,7 %
falsa alarma                    7,4 %               0,7 %
```

La penalización OOD, las correcciones forenses y el enrutado por compuerta
recortan los falsos positivos diez veces y la detección un cuarto. Esa
maquinaria se construyó para corregir el fallo de las fotografías reales
marcadas como IA, y funciona. Pero el precio está ahora cuantificado, y es una
palanca documentada en vez de un comportamiento inexplicado.

## 7. Límites conocidos

**El sistema detecta la mitad de los generadores que no vio.** FLUX se le escapa
el 70 % contra el umbral binario. En términos de banda —que es lo que la página
muestra— señala el 76,7 % de la IA retenida y declara auténtico solo el 9,4 %;
el resto cae en «Inconclusive», que es la respuesta correcta cuando no se sabe.
No es un defecto de código: es el límite de los datos de entrenamiento.

**El cabezal facial no reconoce rostros enteramente sintéticos.** El arreglo de
fondo es entrenarlo con retratos generados como clase positiva, no solo con
intercambio de rostro. No se hizo en esta iteración porque toca el cabezal que
sostiene el KPI-01 y añadir miles de rostros sintéticos puede diluir la señal de
*face-swap* que se acaba de llevar del 11,7 % al 85,5 %. Es el siguiente trabajo
y necesita su propia validación.

**El KPI-01 es dentro de muestra.** ff++ participa en el entrenamiento y es el
único material de intercambio de rostro disponible. La cifra es un techo, no una
estimación de lo que ocurrirá ante una técnica nueva. Está declarado así en el
informe.

**La selección de features usó el retenido.** Al elegir mirando ese conjunto,
deja de ser un test ciego y pasa a ser validación: la cifra del ganador queda
ligeramente optimista. Para una cifra final limpia haría falta un tercer
conjunto de otros dominios.

**La selección del cabezal facial sigue premiando el ajuste.** El defecto 3.1 se
corrigió en los cabezales `full` y `noart` (AUC redondeado a dos decimales para
que los empates los rompa el error LOSO), pero el bucle del cabezal facial es
otro y compara el AUC crudo con `>` estricto, sin LOSO. En el entrenamiento del
9 de noviembre eligió `xgboost` con AUC 0,9968 sobre `lightgbm` con AUC 0,9968
—empatados a cuatro decimales, decididos por el orden de iteración— y sobre
`logreg` con 0,9947. Las tres cifras son dentro de muestra sobre ff++. No se
cambió porque el cabezal facial sostiene el KPI-01 y reentrenarlo exige
revalidar la mezcla completa; va junto al trabajo del párrafo anterior.

**El cabezal facial no se registraba en `meta_config.json`.** Se guardaba solo
en su `.joblib`, de modo que el archivo que documenta el modelo describía dos de
los tres cabezales que producción carga. No afectaba a la ejecución —el cargador
lee la temperatura y las features del propio `.joblib`—, pero sí a la
auditabilidad. `scripts/train_meta_dual_head.py` ya escribe la sección
`face_head`, y el reentrenamiento de las 18:51 lo confirmó: el config que
produjo sí la traía. Pero ese reentrenamiento se descartó por el criterio de
adopción (sección 10), de modo que el `meta_config.json` vigente es el
restaurado y **sigue sin la sección**. La tendrá el primer reentrenamiento que
llegue a adoptarse. Las cifras del cabezal vigente, tomadas del log de
entrenamiento `reports/etapa9_importancias.log`: xgboost, 13.800 muestras de
ff++ (8.000 auténticas, 5.800 deepfake), AUC 0,9968, FPR 1,81 %, recall 96,95 %,
temperatura 0,880 — todas dentro de muestra.

## 8. Procedencia de cada cifra

| cifra | archivo | dentro / fuera de muestra |
|---|---|---|
| KPI-01, 94,0 % | `reports/produccion_ffpp_bandas.json` | dentro (ff++) |
| KPI-02, 0,7 % | `reports/heldout_eval_bandas.json` | **fuera** |
| KPI-03, 0,990 | `reports/heldout_eval.json` | **fuera** |
| AUC por detector | `reports/heldout_detectores.json` | **fuera** |
| CV AUC y LOSO | `models/meta_ensemble/meta_config.json` | LOSO = fuente excluida |
| compuerta × rostro | `reports/diagnostico_compuerta_rostro.json` | mixto, declarado |
| selección de features | `reports/seleccion_features_heldout.json` | validación, no test |

## 9. Reproducir

```
scripts/pipeline_v3.py                   # 10 etapas, ~5 h con GPU libre
scripts/download_heldout.py              # conjunto retenido, 7.000 imágenes
scripts/eval_heldout.py --n 500          # KPI-02 y KPI-03
scripts/eval_produccion_ffpp.py --n 400  # KPI-01
scripts/score_heldout_detectores.py      # tabla 4 honesta
scripts/kpi_por_bandas.py <json>         # reexpresa en bandas de evidencia
scripts/eval_informe_kpis.py             # cifras del informe en una pasada
scripts/verificar_entregables.py         # comprueba el texto final
```

El worker de Celery debe estar detenido para las etapas que necesitan VRAM, y
hay que **reiniciarlo al terminar**: carga los modelos una sola vez al arrancar,
de modo que mientras siga el proceso antiguo la web sirve los modelos antiguos.
El comando está en `reports/REANUDAR_WORKER.txt`.


## 10. El segundo reentrenamiento del 9 de noviembre y por qué se descartó

Esta sección registra un reentrenamiento **que no está en el sistema**. Se anota
porque el resultado negativo es la evidencia de que el modelo vigente es el
mejor de los dos medidos, y porque muestra el criterio de adopción funcionando.

### 10.1 Qué se hizo

Entre las 15:46 y las 18:54 se ejecutaron las etapas 2 a 10 del pipeline sobre
un conjunto de imágenes ampliado: ELSA multigenerador pasó de 18.000 a 72.000
archivos, y el total en disco creció en unas 145.600 imágenes. Las nueve etapas
terminaron OK y las 78 pruebas pasaron.

Antes de arrancar se guardó un respaldo de los modelos vigentes en
`reports/snapshot_pre_v3_20261109_154502` y se escribió el criterio de adopción
en `scripts/decidir_adopcion.py` — **antes de medir**, para que la decisión no
pudiera acomodarse al resultado:

1. **Veto** si las falsas alarmas sobre fotografía auténtica suben más de
   0,3 puntos. Una acusación infundada es el error de mayor costo del sistema.
2. **Veto** si el AUC fuera de muestra baja más de 0,005.
3. Superados los vetos, se adopta si la IA señalada sube al menos 1,0 punto, o
   si se mantiene y las falsas alarmas bajan al menos 0,2 puntos.

### 10.2 Lo que midió el retenido

Las mismas 2.000 imágenes de LFW, ImageNet-val, FLUX y DALL·E 3, por la vía de
producción, en bandas de evidencia:

| | vigente | reentrenado | delta |
|---|---|---|---|
| Falsas alarmas sobre foto auténtica | 0,70 % | **1,40 %** | **+0,70 pt** |
| IA señalada | 76,70 % | 78,60 % | +1,90 pt |
| AUC fuera de muestra | 0,9906 | 0,9868 | −0,0038 |

El modelo reentrenado duplicó las falsas alarmas para ganar 1,9 puntos de
detección. El primer veto se activó y el veredicto fue **REVERTIR**. El respaldo
se restauró a las 19:21 y el worker se reinició a las 19:22 para que la página
volviera a servir los modelos vigentes.

Un detalle de método que importa para no fabricar una cifra falsa: medir
**sobrescribe** `reports/heldout_eval.json` y sus derivados, de modo que al
revertir los modelos esos archivos quedaron describiendo al modelo descartado
mientras el informe los citaba como fuente del KPI-02. Las mediciones del
reentrenamiento se apartaron a `reports/descartado_20261109_1854/` —con un
`LEEME.md` que advierte de no citarlas— y las del modelo vigente se
restauraron en `reports/`. Quien reentrene y revierta tiene que repetir ese
paso.

Un caso ilustra el costo mejor que la tabla: una fotografía real con un rostro,
medida en las dos corridas, pasó de 0,146 (*Very Low Evidence*) a 0,448
(*Inconclusive*). El modelo nuevo dudaba de una cara auténtica.

### 10.3 Por qué el reentrenamiento no mejoró, y qué dice del método

La causa es que **las etapas que construyen muestras llevan cuotas fijas**. La
etapa 2, que alimenta al probe CLIP, tiene cuotas por fuente que suman 140.000
imágenes base y 188.926 embeddings con aumento; la etapa 5 tiene un plan de
exactamente 60.000. Las 145.600 imágenes descargadas no agrandaron ninguna
muestra: solo agrandaron el fondo del que se sortea. El probe entrenó con
191.847 embeddings antes y 191.782 después.

Así que lo que se midió no fue «más datos contra menos datos», sino **un sorteo
distinto al mismo tamaño de muestra**. Y ese sorteo salió peor fuera de muestra.

Dentro de muestra, en cambio, el reentrenamiento se veía mejor: el probe subió
su AUC de deepfake facial de 0,9715 a 0,9770 y bajó sus falsos positivos de
1,84 % a 1,58 %, ambas sobre particiones por identidad con cero solapamiento de
grupos. **Esa es la lección del episodio**: una validación interna bien
construida —particiones por grupo, sin fuga— mejoró, y el comportamiento ante
fuentes nuevas empeoró de todos modos. Sin el retenido y sin un criterio escrito
por adelantado, este modelo habría entrado en producción con una tabla a favor.

Para que un fondo mayor se convierta en mejora real haría falta **subir las
cuotas de la etapa 2**, que es un cambio deliberado con su propio costo: 41,6
minutos para 188.926 embeddings, y escalando desde ahí.

### 10.4 Procedencia

| cifra | archivo |
|---|---|
| veredicto y criterio | `reports/decision_adopcion.json` |
| medición del reentrenado | `reports/descartado_20261109_1854/heldout_eval.json` |
| bandas del reentrenado | `reports/descartado_20261109_1854/heldout_eval_bandas.json` |
| línea base vigente | `reports/heldout_eval.json` y `reports/heldout_eval_bandas.json` |
| probe anterior y actual | `models/advanced_detector/best_model_config.json`, campo `holdout_metrics` |
| cuotas de la etapa 2 | `reports/pipeline_v3_etapa2.log`, cabecera |
| duración de las etapas | `reports/pipeline_v3_etapas2a10.log` |


## 11. El KPI de latencia medía otra cosa que la que declaraba

Un cuarto error de medición, de la misma familia que los tres de la sección 4,
encontrado el 9 de noviembre de 2026 al revisar si los entregables seguían al
día.

### 11.1 Qué declaraba y qué pasa en realidad

El **KPI-04 — Latencia de análisis de imagen** daba como valor actual
**«< 3 s»** y como meta «≤ 5 s en el percentil 95», y decía medirse *«mediante
el campo de tiempo de análisis»*. Ese campo es `analysis_time`, y sobre **49
análisis reales por la vía de producción nunca bajó de 17,3 s**, con mediana de
35,1 s. Incluye el análisis semántico con LLaVA, que es la parte lenta: su
mediana por sí sola es de 28,0 s.

El detalle SMART del mismo KPI decía, en cambio, que la cifra excluye el
análisis semántico. De modo que el KPI se contradecía consigo mismo: su fórmula
describía el tiempo total, su justificación decía excluir la parte semántica, y
su fuente de medición entregaba el total.

Como el resultado trae el desglose (`semantic_analysis.analysis_time`), la
resta se puede hacer y el KPI se puede medir como está definido. Hecha la resta,
tampoco eran 3 segundos:

| medición (49 análisis, vía de producción) | mediana | p95 |
|---|---|---|
| Total — lo que espera el usuario, GPU dedicada | 32,4 s | 61,6 s |
| Solo la parte semántica (LLaVA) | 28,0 s | — |
| **Ensemble sin semántica, GPU dedicada** | **5,3 s** | **11,7 s** |

El mínimo del ensemble aislado sobre las 49 medidas es **3,43 s**. No hay
ninguna lectura de los datos que sostenga «< 3 s».

### 11.2 Qué se corrigió

Las dos métricas se separan explícitamente, porque miden cosas distintas y las
dos hacen falta:

- **KPI-04** mide el componente propio del proyecto, el ensemble sin la parte
  semántica. Valor **11,7 s (p95)**, meta **≤ 15 s en el percentil 95**. Su
  fórmula pasa a decir lo que mide, y su apartado «Medible» nombra la resta
  exacta y el guion que la calcula.
- **SLA, tiempo de respuesta de imagen** compromete lo que el cliente espera de
  verdad, análisis semántico incluido. Meta **≤ 90 s en el percentil 95**,
  medida con el campo `analysis_time` tal cual. Un SLA que prometiera el tiempo
  del componente estaría prometiendo algo que el cliente no recibe.

Las dos metas se fijan **por encima** del percentil 95 medido, no igualadas a
él: una meta igual a la medición se incumple la mitad de las veces por puro
ruido.

### 11.3 La condición que la cifra no puede perder

Las dos metas se declaran sobre **GPU dedicada**. Con la memoria de vídeo
ocupada por otras aplicaciones la latencia se degrada un orden de magnitud: de
los 49 análisis, 8 corrieron con la VRAM saturada y dieron una mediana de
**1.709 s**, con un máximo de 2.677 s. No es un límite del sistema sino del
equipo donde corre, y por eso la condición va escrita en el detalle SMART del
KPI en vez de quedar como nota al pie.

El reparto de VRAM de LLaVA tenía además un defecto propio: se presupuestaba
sobre la memoria **total** de la tarjeta en lugar de la **libre**, de modo que
en una tarjeta de 12,9 GB reservaba 5,9 GiB para LLaVA aunque otras
aplicaciones ya ocuparan 3,5 GB. Corregido en
`backend/app/services/semantic_inspection_service.py`, que ahora lee
`torch.cuda.mem_get_info` y registra un error explícito cuando el presupuesto
no alcanza, en lugar de degradarse en silencio.

### 11.4 Procedencia

| cifra | archivo |
|---|---|
| todas las latencias de esta sección | `reports/latencia_medida.json` |
| guion que las calcula | `scripts/medir_latencia.py` |
| origen de los datos | backend de resultados de Celery en Redis, análisis reales por la vía de producción |
| sustituciones aplicadas al informe | `reports/mapa_cifras_fase6.json` |
