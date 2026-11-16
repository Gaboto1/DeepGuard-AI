# Mediciones de un cambio DESCARTADO — no son las del sistema

Corresponden al reentrenamiento de los cabezales del meta-ensemble con
candidatos que prescinden de `ai_human_detector`, el detector con AUC 0,345
fuera de muestra. La seleccion LOSO eligio el conjunto sin ese detector por
sus propios meritos (error medio 0,0114 frente a 0,0123), pero el conjunto
retenido lo rechazo: falsas alarmas 0,70 % -> 1,20 %, IA senalada 76,70 % ->
77,80 %. El criterio veta cualquier subida de falsas alarmas mayor de 0,3 pt.

Los pesos se restauraron del respaldo. Los candidatos anadidos SI se
conservan en scripts/train_meta_dual_head.py: amplian el espacio de busqueda
y un reentrenamiento futuro con datos distintos podria adoptarlos.

Relato completo en `reports/MEJORA_ENSEMBLE_v4.md`, seccion 12.5.

**No citar ninguna cifra de aqui como metrica del sistema.**
