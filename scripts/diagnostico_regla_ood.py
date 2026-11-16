# -*- coding: utf-8 -*-
"""
Mide cuanto cuesta la Regla 1 (OOD-Manipulation Bypass) sobre el retenido.

La sospecha
-----------
Sobre el conjunto retenido, los detectores que ven bien el material de FLUX dan
medias de 0,88 a 0,92 (probe CLIP 0,916; arte IA 0,883; SigLIP2 0,920). Y sin
embargo la pagina puntua imagenes de FLUX en 0,34 y 0,565, es decir "Low" e
"Inconclusive". Algo hunde el score DESPUES de que los detectores acierten.

El sospechoso es `apply_forensic_corrections`, regla 1: cuando la imagen se
marca como composicion grafica (is_ood=True) y hay senal de manipulacion, la
regla **descarta el meta-ensemble** y lo sustituye por una media ponderada a
mano de los detectores crudos, amortiguada por 0,82 y topada en
OOD_BYPASS_MAX = 0,68.

Dos razones para dudar de ese cambio:

1. La media incluye `face_deepfake_vit` (AUC 0,451 fuera de muestra) y
   `ai_human_detector` (AUC 0,345, es decir anticorrelacionado). Se sustituye
   un estimador de AUC 0,990 por otro que incorpora dos senales peores que el
   azar.
2. El tope de 0,68 impide por construccion que una imagen marcada como obra
   grafica alcance la banda "Strong Evidence". Y lo que mas parece obra grafica
   es justamente el material de los generadores modernos.

Que mide este guion
-------------------
Envuelve `apply_forensic_corrections` tal como la importa `image_service` y
registra, imagen a imagen: el score que entra, el que sale, la regla que actuo
y si la imagen se marco OOD. Despues cruza eso con la clase real y con la banda
de evidencia, de modo que se puede responder a lo unico que importa:

  - cuantas imagenes de IA pierde la regla (eran senaladas y dejan de serlo)
  - cuantas falsas alarmas evita la regla (eran senaladas siendo autenticas)

Porque la regla existe por una razon: evitar que un diseno grafico autentico se
marque como IA. La pregunta no es si molesta, sino si su beneficio paga su
coste. Este guion NO cambia nada: solo mide.

Salida: reports/diagnostico_regla_ood.json

Uso
---
    python scripts/diagnostico_regla_ood.py --n 150
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "models"))
os.environ.setdefault("HF_HOME", str(ROOT / "models"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(str(BACKEND))

OUT = ROOT / "reports" / "diagnostico_regla_ood.json"
HELDOUT = ROOT / "data" / "heldout"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}

SENALADA = {"Moderate Evidence", "Strong Evidence"}


def recoger(base: Path, n: int, seed: int = 13) -> list[Path]:
    import random
    files = sorted(p for p in base.rglob("*") if p.suffix.lower() in EXTS)
    random.Random(seed).shuffle(files)
    return files[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150,
                    help="imagenes por fuente del retenido")
    args = ap.parse_args()

    if not HELDOUT.exists():
        print(f"ERROR: falta {HELDOUT}")
        return 1

    tareas = []
    for clase_dir in sorted(HELDOUT.iterdir()):
        if not clase_dir.is_dir():
            continue
        label = 0 if clase_dir.name == "real" else 1
        for fuente_dir in sorted(clase_dir.iterdir()):
            if not fuente_dir.is_dir():
                continue
            got = recoger(fuente_dir, args.n)
            tareas.extend((fuente_dir.name, label, p) for p in got)
            print(f"  {fuente_dir.name:12s} label={label}  {len(got):5d}")

    print("\nCargando el sistema completo (via de produccion)...")
    from app.models.deepfake_detector import DeepfakeDetector
    from app.models.face_detector import FaceDetector
    from app.models.meta_ensemble import MetaEnsemble
    det = DeepfakeDetector.get_instance()
    det.load()
    FaceDetector.get_instance().load()
    MetaEnsemble.get_instance().load()

    from app.models.deepfake_detector import (
        _model_a, _model_b, _model_c, _model_d, _model_e, _model_f)
    faltan = [n for n, m in zip("ABCDEF",
              (_model_a, _model_b, _model_c, _model_d, _model_e, _model_f))
              if not getattr(m, "_loaded", False)]
    if faltan:
        raise SystemExit(f"ABORTA: detectores sin cargar: {faltan}")

    from app.services import image_service
    from app.services.image_service import _run_image_analysis
    from app.utils.helpers import get_evidence_level

    # ── Instrumentacion ──────────────────────────────────────────────────────
    # Se envuelve la referencia que `image_service` ya importo, no la del
    # modulo de origen: parchear `forensic_corrections.apply_forensic_corrections`
    # no tendria efecto porque image_service la importo por valor en su linea 24.
    original = image_service.apply_forensic_corrections
    capturado = {}

    def espia(final_score, model_scores, ood_result, ai_art_excluded=False):
        salida = original(final_score, model_scores, ood_result,
                          ai_art_excluded=ai_art_excluded)
        corrected, ctype, _detalles = salida
        capturado.clear()
        capturado.update({
            "entra": float(final_score),
            "sale": float(corrected),
            "regla": ctype,
            "is_ood": bool(ood_result.get("is_ood", False)),
            "ai_art_excluded": bool(ai_art_excluded),
        })
        return salida

    image_service.apply_forensic_corrections = espia
    print(f"Listo -- 6/6 detectores en {det.device_name}.\n")

    filas = []
    t0 = time.time()
    for i, (fuente, label, ruta) in enumerate(tareas, 1):
        capturado.clear()
        try:
            # Toma un unico argumento, un Path. Pasarle dos da TypeError en
            # todas las imagenes y el diagnostico sale con todo a cero, que
            # parece un resultado y no lo es.
            res = _run_image_analysis(ruta)
        except Exception as e:
            print(f"  fallo {ruta.name}: {type(e).__name__}: {e}")
            continue
        p = res.get("fake_probability")
        if p is None:
            continue
        banda = res.get("evidence_level") or get_evidence_level(p)
        c = dict(capturado)
        entra = c.get("entra")
        banda_sin = get_evidence_level(entra) if entra is not None else None
        filas.append({
            "fuente": fuente, "label": label, "archivo": ruta.name,
            "score_final": round(float(p), 4),
            "score_antes_correccion": None if entra is None else round(entra, 4),
            "banda_final": banda,
            "banda_sin_correccion": banda_sin,
            "regla": c.get("regla"),
            "is_ood": c.get("is_ood"),
            "ai_art_excluded": c.get("ai_art_excluded"),
        })
        if i % 50 == 0:
            m = (time.time() - t0) / 60
            print(f"  [{i}/{len(tareas)}] {m:.1f}min  "
                  f"ETA {m / i * (len(tareas) - i):.1f}min")

    image_service.apply_forensic_corrections = original

    # ── Agregados ────────────────────────────────────────────────────────────
    por_fuente = defaultdict(lambda: defaultdict(int))
    for f in filas:
        s = por_fuente[f["fuente"]]
        s["n"] += 1
        if f["is_ood"]:
            s["ood"] += 1
        if f["regla"] == "ood_bypass":
            s["r1"] += 1
        if f["regla"] == "compression_veto":
            s["r2"] += 1

    # El balance de la regla 1: que gana y que pierde respecto de no aplicarla.
    ganadas = perdidas = neutras = 0          # sobre imagenes de IA
    fa_evitadas = fa_creadas = 0              # sobre fotografia autentica
    for f in filas:
        if f["banda_sin_correccion"] is None or f["regla"] is None:
            continue
        antes = f["banda_sin_correccion"] in SENALADA
        despues = f["banda_final"] in SENALADA
        if f["label"] == 1:
            if antes and not despues:
                perdidas += 1
            elif despues and not antes:
                ganadas += 1
            else:
                neutras += 1
        else:
            if antes and not despues:
                fa_evitadas += 1
            elif despues and not antes:
                fa_creadas += 1

    datos = {
        "generado": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "n": len(filas),
        "n_por_fuente": {k: dict(v) for k, v in por_fuente.items()},
        "balance_correcciones": {
            "ia_perdidas": perdidas,
            "ia_ganadas": ganadas,
            "ia_neutras": neutras,
            "falsas_alarmas_evitadas": fa_evitadas,
            "falsas_alarmas_creadas": fa_creadas,
        },
        "nota": (
            "'perdidas' = imagenes de IA que la banda habria senalado con el "
            "score del meta-ensemble y que dejan de senalarse tras la "
            "correccion. 'falsas_alarmas_evitadas' = fotografia autentica que "
            "se habria senalado y deja de senalarse. El balance decide si la "
            "regla paga su coste."
        ),
        "filas": filas,
    }
    OUT.write_text(json.dumps(datos, indent=2, ensure_ascii=False),
                   encoding="utf-8")

    print("\n  ACTIVACION POR FUENTE")
    print(f"  {'fuente':12s} {'n':>5s} {'OOD':>6s} {'R1':>6s} {'R2':>6s}")
    print("  " + "-" * 40)
    for k, v in sorted(por_fuente.items()):
        print(f"  {k:12s} {v['n']:5d} {v.get('ood',0):6d} "
              f"{v.get('r1',0):6d} {v.get('r2',0):6d}")
    b = datos["balance_correcciones"]
    print("\n  BALANCE DE LAS CORRECCIONES (en bandas)")
    print(f"    IA que deja de senalarse        {b['ia_perdidas']:5d}")
    print(f"    IA que pasa a senalarse         {b['ia_ganadas']:5d}")
    print(f"    Falsas alarmas evitadas         {b['falsas_alarmas_evitadas']:5d}")
    print(f"    Falsas alarmas creadas          {b['falsas_alarmas_creadas']:5d}")
    print(f"\n  -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
