# -*- coding: utf-8 -*-
"""
Test de calibracion para apply_semantic_fusion.
Ejecutar desde backend/:  python test_semantic_fusion.py
No requiere GPU ni modelos — prueba solo la logica de fusion.
"""
import sys
import os

# Forzar UTF-8 en stdout (Windows cp1252 no soporta flechas Unicode)
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

# Importar solo la función de fusión (no el singleton LLaVA)
from app.services.semantic_inspection_service import apply_semantic_fusion

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def test(label, ensemble, llava_score, faces, lo, hi):
    semantic_result = {
        "risk_score": llava_score,
        "risk_score_normalized": llava_score / 100.0,
    }
    score, fusion_type, note = apply_semantic_fusion(ensemble, semantic_result, faces)
    pct = score * 100
    ok = lo <= score <= hi
    status = PASS if ok else FAIL
    print(
        f"  {status} [{label}] "
        f"ensemble={ensemble*100:.0f}% + LLaVA={llava_score}% "
        f"→ {pct:.1f}%  "
        f"(target: {lo*100:.0f}-{hi*100:.0f}%)  "
        f"tipo={fusion_type}"
    )
    if note:
        print(f"       nota: {note[:100]}")
    return ok


print("\n=== Test calibración apply_semantic_fusion ===\n")
results = []

# Caso 1: Foto real comprimida (Messi)
# LLaVA muy seguro que es real (8%), ensemble incierto (40%)
# Debe dar 10-30% — NO debe superar el umbral de sospecha
results.append(test(
    "CASO 1 - Foto real comprimida (Messi)",
    ensemble=0.40, llava_score=8, faces=True,
    lo=0.10, hi=0.30,
))

# Caso 2: Afiche IA híbrido (poster con cara AI + diseño gráfico)
# LLaVA detecta cara sospechosa (78%), ensemble dice real (25%)
# Debe dar 40-65% — debe alertar al usuario
results.append(test(
    "CASO 2 - Afiche IA híbrido",
    ensemble=0.25, llava_score=78, faces=True,
    lo=0.40, hi=0.65,
))

# Caso 3: Deepfake facial claro
# Ambos modelos alineados — blend debe quedar alto
results.append(test(
    "CASO 3 - Deepfake facial claro",
    ensemble=0.85, llava_score=88, faces=True,
    lo=0.80, hi=1.00,
))

# Caso 4: LLaVA no disponible (risk_score=-1)
# Debe devolver el ensemble sin tocar
ensemble_val = 0.42
_, ft, _ = apply_semantic_fusion(
    ensemble_val,
    {"risk_score": -1, "risk_score_normalized": None},
    True,
)
ok4 = ft is None
print(
    f"  {PASS if ok4 else FAIL} [CASO 4 - LLaVA no disponible] "
    f"score inalterado, fusion_type=None  tipo={ft}"
)
results.append(ok4)

# Caso 5: Imagen benigna sin cara, LLaVA también benigna
# Blend ponderado normal (peso LLaVA menor sin cara)
results.append(test(
    "CASO 5 - Imagen real sin cara",
    ensemble=0.12, llava_score=10, faces=False,
    lo=0.09, hi=0.16,
))

# Caso 6: Corrección descendente fuerte
# Ensemble muy alto (72%) pero LLaVA dice real (10%) → correction down
results.append(test(
    "CASO 6 - Corrección descendente fuerte",
    ensemble=0.72, llava_score=10, faces=True,
    lo=0.40, hi=0.68,
))

# ─── Resumen ──────────────────────────────────────────────────────────────────
print(f"\n=== {sum(results)}/{len(results)} tests pasaron ===\n")
sys.exit(0 if all(results) else 1)
