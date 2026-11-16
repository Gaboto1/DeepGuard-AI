# Mediciones de un cambio DESCARTADO — no son las del sistema

Corresponden a la variante de la Regla 1 que dejaba de rebajar cuando el
meta-ensemble superaba 0,95. Se midio el 16 de noviembre de 2026 y **se
descarto**: ganaba 5,8 puntos de deteccion pero subia las falsas alarmas del
0,70 % al 1,40 %, y el criterio de adopcion veta cualquier subida mayor de
0,3 puntos.

El codigo se revirtio con `git checkout`. El relato completo esta en
`reports/MEJORA_ENSEMBLE_v4.md`, seccion 12.

**No citar ninguna cifra de aqui como metrica del sistema.** Las del sistema
viven en `reports/heldout_eval.json` y `reports/heldout_eval_bandas.json`:
0,7 % de falsas alarmas, 76,7 % de IA senalada, AUC 0,990.
