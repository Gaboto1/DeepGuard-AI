"""
Mide el sistema completo sobre el conjunto RETENIDO, por la via de produccion.

Diferencia con scripts/eval_informe_kpis.py
-------------------------------------------
Aquel lee un CSV ya puntuado y reconstruye el score del meta-ensemble: mide el
meta-modelo. Este llama a `_run_image_analysis`, la misma funcion que atiende
una carga de la pagina web, de modo que mide **lo que el usuario ve**: deteccion
de rostro, senales auxiliares de CPU, compuerta de tipo de contenido, nivel de
compresion, los seis detectores, el meta-ensemble, las reglas forenses y la
banda de evidencia final. Si alguna de esas piezas rompe el resultado, aqui se
nota y en el otro no.

Por que el conjunto retenido
----------------------------
Las fuentes de `data/heldout/` no participan en ningun plan de entrenamiento.
Es la unica forma de responder a la pregunta que importa: que ocurre ante una
fotografia o un generador que el modelo no vio nunca. Medir sobre las fuentes
del entrenamiento fue lo que dejo pasar la selfie de webcam del usuario marcada
al 53 % mientras el banco de pruebas declaraba cero falsas alarmas.

Salida: reports/heldout_eval.json
"""
import argparse
import json
import os
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

OUT = ROOT / "reports" / "heldout_eval.json"
HELDOUT = ROOT / "data" / "heldout"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Umbral de decision del cabezal completo, el mismo que usa produccion.
#
# Se lee del config en vez de fijarlo aqui: cada reentrenamiento recalibra la
# temperatura y mueve T (0.9652 -> 0.9918 -> 0.8764 en tres corridas). Un valor
# escrito a mano en este archivo mide un sistema que ya no existe y da un FPR
# que no se parece al que ve el usuario.
def _umbral_de_config() -> float:
    cfg = ROOT / "models" / "meta_ensemble" / "meta_config.json"
    if not cfg.exists():
        raise SystemExit(f"ABORTA: falta {cfg}; no hay umbral que usar.")
    T = (json.loads(cfg.read_text(encoding="utf-8"))
         .get("full_head", {}).get("cv", {}).get("T"))
    if T is None:
        raise SystemExit(f"ABORTA: {cfg.name} no trae full_head.cv.T.")
    return float(T)


def recoger(base: Path, n: int, seed: int = 13) -> list[Path]:
    import random
    files = sorted(p for p in base.rglob("*") if p.suffix.lower() in EXTS)
    random.Random(seed).shuffle(files)
    return files[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500, help="imagenes por fuente")
    ap.add_argument("--umbral", type=float, default=None,
                    help="por defecto, full_head.cv.T del config")
    ap.add_argument("--extra", action="append", default=[],
                    help="ruta de imagen suelta a analizar aparte")
    args = ap.parse_args()
    if args.umbral is None:
        args.umbral = _umbral_de_config()
    print(f"Umbral de decision: T = {args.umbral}")

    if not HELDOUT.exists():
        print(f"ERROR: falta {HELDOUT}. Ejecuta scripts/download_heldout.py")
        return 1

    tareas: list[tuple[str, int, Path]] = []
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
    if not tareas:
        print("ERROR: el conjunto retenido esta vacio")
        return 1

    print(f"\n  TOTAL: {len(tareas)}  "
          f"(real={sum(1 for _, l, _ in tareas if l == 0)})\n")

    print("Cargando el sistema completo (via de produccion)...")
    # La carga EXPLICITA no es opcional. `_run_image_analysis` no carga los
    # modelos: espera que ya esten en GPU, como los deja el worker de Celery en
    # su hook `worker_process_init` (app/tasks/analysis_tasks.py). Sin esta
    # llamada los seis detectores devuelven None, el score final queda en manos
    # de dos heuristicas de CPU (SRM con peso 0.57) y el AUC medido cae a 0.52
    # -- azar -- mientras el informe parece haber medido el sistema completo.
    # Ocurrio en la primera corrida de este script: una foto real de ImageNet
    # daba 0.786 sin carga y 0.017 con ella.
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
        raise SystemExit(
            f"ABORTA: los detectores {faltan} no quedaron cargados. Medir asi "
            f"da un AUC de azar que parece una medicion valida.")

    from app.services.image_service import _run_image_analysis
    from app.utils.helpers import get_evidence_level
    print(f"Listo -- 6/6 detectores en {det.device_name}.")
    print()

    filas = []
    t0 = time.time()
    for i, (fuente, label, path) in enumerate(tareas, 1):
        try:
            r = _run_image_analysis(path)
            p = float(r["fake_probability"])
            banda = get_evidence_level(p)
            filas.append({
                "fuente": fuente, "label": label, "path": str(path),
                "p": round(p, 6),
                "banda": getattr(banda, "value", str(banda)),
                # La clave del dict es "content_type", no "type": con el
                # nombre equivocado esta columna salia None en las 2.000
                # filas y la medicion no permitia cruzar el resultado con
                # la compuerta de contenido, que es justo lo que hacia
                # falta para entender por que los retratos sinteticos se
                # comportan distinto de los intercambios de rostro.
                "tipo_contenido": (r.get("content_type") or {}).get("content_type"),
                "prob_obra_grafica": (r.get("content_type") or {}).get("artwork_probability"),
                "rostros": r.get("faces_detected"),
            })
        except Exception as e:
            filas.append({"fuente": fuente, "label": label, "path": str(path),
                          "p": None, "error": f"{type(e).__name__}: {e}"[:160]})
        if i % 50 == 0 or i == len(tareas):
            el = time.time() - t0
            print(f"  [{i}/{len(tareas)}] {el/60:.1f}min  "
                  f"ETA {el/i*(len(tareas)-i)/60:.1f}min", flush=True)

    ok = [f for f in filas if f.get("p") is not None]
    fallos = len(filas) - len(ok)
    y = np.array([f["label"] for f in ok])
    p = np.array([f["p"] for f in ok])
    thr = args.umbral

    rep = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "umbral": thr,
        "n_analizadas": len(ok),
        "n_fallidas": fallos,
        "nota": ("Fuentes ausentes de todo plan de entrenamiento. Medido por la "
                 "via de produccion (_run_image_analysis), incluidas reglas "
                 "forenses y banda de evidencia."),
        "por_fuente": {},
        "global": {},
    }

    print("\n=== CONJUNTO RETENIDO — via de produccion ===")
    print(f"{'fuente':14s} {'clase':5s} {'n':>5s} {'media':>7s} {'mediana':>8s} "
          f"{'error':>7s}  bandas")
    for fuente in sorted({f["fuente"] for f in ok}):
        sub = [f for f in ok if f["fuente"] == fuente]
        ps = np.array([f["p"] for f in sub])
        lab = sub[0]["label"]
        pred = (ps >= thr).astype(int)
        err = float((pred != lab).mean())
        bandas = Counter(f["banda"] for f in sub)
        rep["por_fuente"][fuente] = {
            "clase": "real" if lab == 0 else "IA",
            "n": len(sub),
            "score_medio": round(float(ps.mean()), 4),
            "score_mediana": round(float(np.median(ps)), 4),
            "error": round(err, 4),
            "bandas": dict(bandas),
        }
        top = ", ".join(f"{k}={v}" for k, v in bandas.most_common(3))
        print(f"{fuente:14s} {'real' if lab == 0 else 'IA':5s} {len(sub):5d} "
              f"{ps.mean():7.4f} {np.median(ps):8.4f} {err:6.2%}  {top}")

    if len(np.unique(y)) == 2:
        from sklearn.metrics import roc_auc_score
        rep["global"]["auc"] = round(float(roc_auc_score(y, p)), 4)
    real, ia = (y == 0), (y == 1)
    if real.any():
        rep["global"]["fpr"] = round(float((p[real] >= thr).mean()), 4)
    if ia.any():
        rep["global"]["deteccion_ia"] = round(float((p[ia] >= thr).mean()), 4)
    print(f"\n  AUC={rep['global'].get('auc')}  "
          f"FPR={rep['global'].get('fpr')}  "
          f"deteccion IA={rep['global'].get('deteccion_ia')}")

    # Imagenes sueltas (por ejemplo, la selfie de webcam del usuario)
    if args.extra:
        rep["extra"] = []
        print("\n=== IMAGENES SUELTAS ===")
        for ruta in args.extra:
            try:
                r = _run_image_analysis(Path(ruta))
                pp = float(r["fake_probability"])
                b = get_evidence_level(pp)
                item = {"path": ruta, "p": round(pp, 6),
                        "banda": getattr(b, "value", str(b)),
                        "tipo_contenido": (r.get("content_type") or {}).get("content_type"),
                        "prob_obra_grafica": (r.get("content_type") or {}).get("artwork_probability"),
                        "rostros": r.get("faces_detected")}
            except Exception as e:
                item = {"path": ruta, "error": f"{type(e).__name__}: {e}"[:160]}
            rep["extra"].append(item)
            print(f"  {Path(ruta).name:28s} {item.get('p')}  "
                  f"{item.get('banda', item.get('error'))}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {OUT}")
    print(f"Tiempo total: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
