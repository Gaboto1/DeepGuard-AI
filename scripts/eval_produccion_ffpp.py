"""
Mide la deteccion de deepfake FACIAL por la via de produccion, sobre ff++.

Por que existe este script aparte
---------------------------------
El KPI central del proyecto —"detecta deepfakes de rostro"— se venia midiendo
con `meta.predict(s, face=True)`, es decir el cabezal facial aislado. Pero
produccion no usa ese cabezal aislado. En app/services/image_service.py, cuando
se detecta un rostro:

    final_score = 0.60 * face_ens + 0.40 * full_ens

donde `full_ens` es el track de imagen completa, que sobre ff++ es incompetente.
Simulando la mezcla sobre reports/dataset_v2_scores.csv:

    cabezal facial solo     ff_fake score medio 0.9711  -> error  5.3 %
    mezcla 0.60/0.40        ff_fake score medio 0.7732  -> error 88.7 %
    umbral de decision      T = 0.8764

El cabezal que acierta queda arrastrado por debajo del umbral por el que falla,
y el KPI medido sobre el cabezal aislado sobrestima el sistema en mas de 80
puntos. Este script resuelve la duda sin simular nada: llama a la misma funcion
que atiende una carga de la pagina.

Por que no vale el conjunto retenido para esto
----------------------------------------------
data/heldout/ no contiene intercambio de rostro: lfw son rostros reales y
flux/dalle3 son rostros enteramente sinteticos, que es otro problema. ff++ es
el unico material de face-swap disponible, y SI participa en el entrenamiento.
La cifra que sale de aqui es DENTRO DE MUESTRA y hay que citarla como tal: es
un techo, no una estimacion de lo que pasara con un deepfake nuevo. Aun asi es
la cifra honesta para el KPI, porque mide el sistema entero en vez de una pieza.

Salida: reports/produccion_ffpp.json
"""
import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "models"))
os.environ.setdefault("HF_HOME", str(ROOT / "models"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(str(BACKEND))

import numpy as np  # noqa: E402

OUT = ROOT / "reports" / "produccion_ffpp.json"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}

FUENTES = [
    ("ff_real", 0, ROOT / "data" / "ff++_faces" / "real"),
    ("ff_fake", 1, ROOT / "data" / "ff++_faces" / "fake"),
]


def umbral_de_config() -> float:
    cfg = ROOT / "models" / "meta_ensemble" / "meta_config.json"
    T = (json.loads(cfg.read_text(encoding="utf-8"))
         .get("full_head", {}).get("cv", {}).get("T"))
    if T is None:
        raise SystemExit(f"ABORTA: {cfg.name} no trae full_head.cv.T")
    return float(T)


def recoger(base: Path, n: int, seed: int = 13) -> list[Path]:
    files = sorted(p for p in base.rglob("*") if p.suffix.lower() in EXTS)
    random.Random(seed).shuffle(files)
    return files[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400, help="imagenes por clase")
    ap.add_argument("--umbral", type=float, default=None)
    args = ap.parse_args()
    thr = args.umbral if args.umbral is not None else umbral_de_config()
    print(f"Umbral de decision: T = {thr}")

    tareas = []
    for nombre, label, base in FUENTES:
        if not base.exists():
            print(f"  [!] falta {base}")
            continue
        got = recoger(base, args.n)
        tareas.extend((nombre, label, p) for p in got)
        print(f"  {nombre:10s} label={label}  {len(got):5d}")
    if not tareas:
        print("ERROR: no hay material ff++")
        return 1

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
        raise SystemExit(f"ABORTA: detectores {faltan} sin cargar.")

    from app.services.image_service import _run_image_analysis
    from app.utils.helpers import get_evidence_level
    print(f"Listo -- 6/6 detectores en {det.device_name}.\n")

    filas = []
    t0 = time.time()
    for i, (fuente, label, path) in enumerate(tareas, 1):
        try:
            r = _run_image_analysis(path)
            p = float(r["fake_probability"])
            b = get_evidence_level(p)
            filas.append({
                "fuente": fuente, "label": label, "p": round(p, 6),
                "banda": getattr(b, "value", str(b)),
                "rostros": r.get("faces_detected"),
            })
        except Exception as e:
            filas.append({"fuente": fuente, "label": label, "p": None,
                          "error": f"{type(e).__name__}: {e}"[:160]})
        if i % 50 == 0 or i == len(tareas):
            el = time.time() - t0
            print(f"  [{i}/{len(tareas)}] {el/60:.1f}min  "
                  f"ETA {el/i*(len(tareas)-i)/60:.1f}min", flush=True)

    ok = [f for f in filas if f.get("p") is not None]
    y = np.array([f["label"] for f in ok])
    p = np.array([f["p"] for f in ok])

    rep = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "umbral": thr,
        "n_analizadas": len(ok),
        "n_fallidas": len(filas) - len(ok),
        "nota": ("DENTRO DE MUESTRA: ff++ participa en el entrenamiento del "
                 "meta-ensemble. Es un techo, no una estimacion de "
                 "generalizacion. Medido por la via de produccion, incluida "
                 "la mezcla 0.60*facial + 0.40*completa."),
        "por_fuente": {},
        "global": {},
    }

    print("\n=== ff++ POR LA VIA DE PRODUCCION ===")
    print(f"{'fuente':10s} {'clase':5s} {'n':>5s} {'media':>7s} {'mediana':>8s} "
          f"{'error':>7s} {'rostro':>7s}  bandas")
    for fuente in sorted({f["fuente"] for f in ok}):
        sub = [f for f in ok if f["fuente"] == fuente]
        ps = np.array([f["p"] for f in sub])
        lab = sub[0]["label"]
        err = float(((ps >= thr).astype(int) != lab).mean())
        con_rostro = sum(1 for f in sub if (f.get("rostros") or 0) > 0)
        bandas = Counter(f["banda"] for f in sub)
        rep["por_fuente"][fuente] = {
            "clase": "real" if lab == 0 else "deepfake",
            "n": len(sub),
            "score_medio": round(float(ps.mean()), 4),
            "score_mediana": round(float(np.median(ps)), 4),
            "error": round(err, 4),
            "con_rostro_detectado": con_rostro,
            "bandas": dict(bandas),
        }
        top = ", ".join(f"{k}={v}" for k, v in bandas.most_common(3))
        print(f"{fuente:10s} {'real' if lab == 0 else 'fake':5s} {len(sub):5d} "
              f"{ps.mean():7.4f} {np.median(ps):8.4f} {err:6.2%} "
              f"{con_rostro:6d}  {top}")

    if len(np.unique(y)) == 2:
        from sklearn.metrics import roc_auc_score
        rep["global"]["auc"] = round(float(roc_auc_score(y, p)), 4)
    real, fake = (y == 0), (y == 1)
    if real.any():
        rep["global"]["fpr"] = round(float((p[real] >= thr).mean()), 4)
    if fake.any():
        rep["global"]["deteccion_deepfake"] = round(
            float((p[fake] >= thr).mean()), 4)
    g = rep["global"]
    print(f"\n  AUC={g.get('auc')}  FPR={g.get('fpr')}  "
          f"deteccion deepfake={g.get('deteccion_deepfake')}")
    print("  (DENTRO DE MUESTRA: ff++ esta en el entrenamiento.)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\n-> {OUT}")
    print(f"Tiempo total: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
