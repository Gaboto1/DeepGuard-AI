# Mediciones de un modelo DESCARTADO — no son las del sistema

Estos archivos describen el reentrenamiento del 9 de noviembre de 2026 que
terminó a las 18:54 y **se descartó** a las 19:21 por el criterio de adopción
(`reports/decision_adopcion.json`). Los modelos que produjo no están en
producción: se restauró el respaldo
`reports/snapshot_pre_v3_20261109_154502`.

Se conservan porque el resultado negativo es la evidencia de que el modelo
vigente es el mejor de los dos medidos fuera de muestra. El relato completo
está en `reports/MEJORA_ENSEMBLE_v4.md`, sección 10.

**No citar ninguna cifra de aquí como métrica del sistema.** Las del sistema
viven en `reports/heldout_eval.json`, `reports/heldout_eval_bandas.json`,
`reports/clip_probe_report.json` y `reports/meta_dual_head_report.json`, que
son los del modelo vigente.

| archivo | qué mide |
|---|---|
| `heldout_eval.json` | retenido de 2.000 imágenes, umbral 0,8884 — falsas alarmas 1,40 %, AUC 0,9868 |
| `heldout_eval_bandas.json` | lo mismo en bandas de evidencia |
| `clip_probe_report.json` | los cuatro candidatos del probe CLIP; ganó `mlp_256` |
| `meta_dual_head_report.json` | los tres cabezales del meta-ensemble reentrenados |
