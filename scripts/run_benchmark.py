"""
Benchmark Runner — Evaluación periódica automática
===================================================
Ejecuta el ensemble completo sobre cualquier golden set.
Genera reportes CSV y JSON automáticamente.

Uso:
  python scripts/run_benchmark.py --set golden      (golden set original)
  python scripts/run_benchmark.py --set extended    (benchmark extendido)
  python scripts/run_benchmark.py --set all         (ambos juntos)

Los reportes se guardan en:
  reports/benchmark_{set}_{timestamp}.json
  reports/benchmark_{set}_{timestamp}.csv
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ["TRANSFORMERS_CACHE"] = str(ROOT / "models")
os.environ["HF_HOME"]            = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(BACKEND)

MANIFESTS = {
    "golden":   ROOT / "tests" / "golden_set"       / "manifest.json",
    "extended": ROOT / "tests" / "benchmark_extended" / "manifest.json",
}


def load_manifest(set_name: str) -> list[dict]:
    entries = []
    sets = ["golden", "extended"] if set_name == "all" else [set_name]
    for s in sets:
        mp = MANIFESTS.get(s)
        if mp and mp.exists():
            with open(mp) as f:
                entries += json.load(f)
    return entries


def run(set_name: str, threshold: float = 0.50) -> None:
    from app.config import settings
    from app.models.deepfake_detector import _model_a, _model_b, _model_c, _calibrated_combine

    entries = load_manifest(set_name)
    if not entries:
        print(f"ERROR: No manifest found for set '{set_name}'")
        sys.exit(1)

    labeled = [e for e in entries if e.get("label") is not None]
    print(f"Benchmark: {set_name} — {len(entries)} imágenes ({len(labeled)} etiquetadas)")

    _model_a.load(); _model_b.load(); _model_c.load()

    rows = []
    y_true, y_score = [], []

    for e in entries:
        path = ROOT / e["path"]
        if not path.exists():
            print(f"  MISSING: {path.name}")
            continue

        try:
            img = Image.open(path).convert("RGB")
            t0  = time.time()
            ra  = _model_a.predict(img)
            rb  = _model_b.predict(img)
            rc  = _model_c.predict(img)
            score, _ = _calibrated_combine(
                ra["fake_probability"], rb["fake_probability"],
                rc["fake_probability"] if rc else None, face=False
            )
            elapsed = time.time() - t0

            pred = 1 if score >= threshold else 0
            ok   = pred == e["label"] if e["label"] is not None else None

            rows.append({
                "name":      e["name"],
                "category":  e.get("category", ""),
                "label":     e["label"],
                "score":     round(score, 4),
                "score_a":   round(ra["fake_probability"], 4),
                "score_b":   round(rb["fake_probability"], 4),
                "score_c":   round(rc["fake_probability"] if rc else 0.5, 4),
                "pred":      pred,
                "correct":   ok,
                "ms":        round(elapsed * 1000, 1),
            })

            if e["label"] is not None:
                y_true.append(e["label"])
                y_score.append(score)

            status = "OK" if ok else ("FAIL" if ok is False else "?")
            print(f"  [{status}] {e['name']:42s} {score*100:5.1f}%")

        except Exception as ex:
            print(f"  ERROR {e['name']}: {ex}")

    # Metrics
    y_t = np.array(y_true); y_s = np.array(y_score)
    y_p = (y_s >= threshold).astype(int)

    tp = int(((y_p==1)&(y_t==1)).sum()); tn = int(((y_p==0)&(y_t==0)).sum())
    fp = int(((y_p==1)&(y_t==0)).sum()); fn = int(((y_p==0)&(y_t==1)).sum())
    prec = tp / max(1, tp+fp); rec = tp / max(1, tp+fn)
    f1   = 2*prec*rec / max(1e-9, prec+rec)
    acc  = (tp+tn) / max(1, len(y_t))
    fpr  = fp / max(1, fp+tn); fnr = fn / max(1, fn+tp)

    try:
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(y_t, y_s)) if len(np.unique(y_t)) > 1 else 0.5
    except ImportError:
        auc = 0.5

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    REPORTS = ROOT / "reports"
    REPORTS.mkdir(exist_ok=True)

    # Save CSV
    csv_path = REPORTS / f"benchmark_{set_name}_{ts}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    # Save JSON
    report = {
        "set": set_name, "timestamp": ts, "threshold": threshold,
        "n_total": len(rows), "n_labeled": len(y_true),
        "metrics": {
            "accuracy": round(acc, 4), "precision": round(prec, 4),
            "recall": round(rec, 4),   "f1": round(f1, 4),
            "roc_auc": round(auc, 4),  "fpr": round(fpr, 4), "fnr": round(fnr, 4),
        },
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "rows": rows,
    }
    json_path = REPORTS / f"benchmark_{set_name}_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print()
    print("=" * 55)
    print(f"  RESULTADOS — {set_name.upper()}")
    print("=" * 55)
    print(f"  Accuracy  : {acc*100:.1f}%   Precisión : {prec*100:.1f}%")
    print(f"  Recall    : {rec*100:.1f}%   F1        : {f1*100:.1f}%")
    print(f"  ROC-AUC   : {auc:.3f}        FPR       : {fpr*100:.1f}%   FNR: {fnr*100:.1f}%")
    print(f"  TN={tn} FP={fp} FN={fn} TP={tp}")
    print()
    print(f"  CSV  : {csv_path}")
    print(f"  JSON : {json_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--set",       default="golden", choices=["golden", "extended", "all"])
    p.add_argument("--threshold", type=float, default=0.50)
    args = p.parse_args()
    run(args.set, args.threshold)
