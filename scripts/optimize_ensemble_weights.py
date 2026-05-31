"""
Ensemble Weight Optimizer — Grid Search
========================================
Tests all weight combinations [w_A, w_B, w_C] with w_A+w_B+w_C=1
to find the configuration that maximizes F1 and ROC-AUC on the golden set.

Does NOT modify the production code — saves recommendations only.
Apply the best weights manually after reviewing results.

Output:
  reports/ensemble_weight_search.json  ← top-20 configurations ranked by F1

Usage:
  python scripts/optimize_ensemble_weights.py
"""
import json
import os
import sys
from pathlib import Path
from itertools import product

import numpy as np
from PIL import Image

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

os.environ["TRANSFORMERS_CACHE"]          = str(ROOT / "models")
os.environ["HF_HOME"]                     = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(BACKEND)

from app.config import settings
from app.models.deepfake_detector import _model_a, _model_b, _model_c


def load_scores() -> tuple[list[dict], list[int]]:
    """Get raw per-model scores for all labeled golden images."""
    manifest_path = ROOT / "tests" / "golden_set" / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    _model_a.load()
    _model_b.load()
    _model_c.load()

    records, labels = [], []

    for entry in manifest:
        if entry["expected_label"] is None:
            continue
        img_path = ROOT / entry["path"]
        if not img_path.exists():
            continue
        img = Image.open(img_path).convert("RGB")
        ra  = _model_a.predict(img)
        rb  = _model_b.predict(img)
        rc  = _model_c.predict(img)
        records.append({
            "name":  entry["name"],
            "score_a": ra["fake_probability"],
            "score_b": rb["fake_probability"],
            "score_c": rc["fake_probability"] if rc else 0.5,
        })
        labels.append(entry["expected_label"])

    return records, labels


def evaluate_weights(
    records: list[dict],
    labels: list[int],
    w_a: float,
    w_b: float,
    w_c: float,
    threshold: float = 0.50,
) -> dict:
    y_t = np.array(labels)
    scores = np.array([
        w_a * r["score_a"] + w_b * r["score_b"] + w_c * r["score_c"]
        for r in records
    ])
    scores = np.clip(scores, 0, 1)
    y_p = (scores >= threshold).astype(int)

    tp = int(((y_p == 1) & (y_t == 1)).sum())
    tn = int(((y_p == 0) & (y_t == 0)).sum())
    fp = int(((y_p == 1) & (y_t == 0)).sum())
    fn = int(((y_p == 0) & (y_t == 1)).sum())

    precision = tp / max(1, tp + fp)
    recall    = tp / max(1, tp + fn)
    f1        = 2 * precision * recall / max(1e-9, precision + recall)
    accuracy  = (tp + tn) / max(1, len(y_t))

    try:
        from sklearn.metrics import roc_auc_score
        roc_auc = float(roc_auc_score(y_t, scores)) if len(np.unique(y_t)) > 1 else 0.5
    except ImportError:
        roc_auc = 0.5

    return {
        "w_a": round(w_a, 2),
        "w_b": round(w_b, 2),
        "w_c": round(w_c, 2),
        "f1": round(f1, 4),
        "roc_auc": round(roc_auc, 4),
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fpr": round(fp / max(1, fp + tn), 4),
        "fnr": round(fn / max(1, fn + tp), 4),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    }


def main() -> None:
    print("=" * 60)
    print("  ENSEMBLE WEIGHT OPTIMIZER")
    print("=" * 60)

    print("\nLoading golden set scores...")
    records, labels = load_scores()
    n = len(records)
    print(f"Labeled samples: {n}")

    # Current weights
    current = {"w_a": 0.30, "w_b": 0.45, "w_c": 0.25}
    current_result = evaluate_weights(records, labels, **current)
    print(f"\nCurrent weights: A={current['w_a']} B={current['w_b']} C={current['w_c']}")
    print(f"  F1={current_result['f1']:.4f} | ROC-AUC={current_result['roc_auc']:.4f} | "
          f"Acc={current_result['accuracy']:.4f}")

    # Grid search: w_A, w_B, w_C ∈ {0.05, 0.10, ..., 0.80}, sum = 1.0
    print("\nRunning grid search over weight combinations...")
    step  = 0.10
    vals  = [round(v, 2) for v in np.arange(0.05, 0.91, step)]
    all_results = []

    for w_a in vals:
        for w_b in vals:
            w_c = round(1.0 - w_a - w_b, 2)
            if w_c < 0.05 or w_c > 0.90:
                continue
            res = evaluate_weights(records, labels, w_a, w_b, w_c)
            all_results.append(res)

    # Also try fine-grained search around best so far
    if all_results:
        best_so_far = max(all_results, key=lambda r: r["f1"])
        fine_step   = 0.05
        for dw_a in np.arange(-0.15, 0.16, fine_step):
            for dw_b in np.arange(-0.15, 0.16, fine_step):
                w_a = round(best_so_far["w_a"] + dw_a, 2)
                w_b = round(best_so_far["w_b"] + dw_b, 2)
                w_c = round(1.0 - w_a - w_b, 2)
                if not (0.05 <= w_a <= 0.85 and 0.05 <= w_b <= 0.85 and 0.05 <= w_c <= 0.85):
                    continue
                res = evaluate_weights(records, labels, w_a, w_b, w_c)
                all_results.append(res)

    # Deduplicate
    seen = set()
    deduped = []
    for r in all_results:
        key = (r["w_a"], r["w_b"], r["w_c"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    # Sort by F1 (primary) then AUC (secondary)
    ranked = sorted(deduped, key=lambda r: (r["f1"], r["roc_auc"]), reverse=True)
    top20  = ranked[:20]

    print(f"\nGrid search complete: {len(deduped)} configurations tested")
    print()
    print(f"  {'Rank':>4} {'w_A':>5} {'w_B':>5} {'w_C':>5} {'F1':>8} {'AUC':>8} {'Acc':>8} {'FPR':>6} {'FNR':>6}")
    print(f"  {'-'*65}")
    for i, r in enumerate(top20[:10]):
        marker = " ← BEST" if i == 0 else (" ← current" if (r["w_a"], r["w_b"], r["w_c"]) == (current["w_a"], current["w_b"], current["w_c"]) else "")
        print(
            f"  {i+1:4d} "
            f"{r['w_a']:5.2f} {r['w_b']:5.2f} {r['w_c']:5.2f} "
            f"{r['f1']:8.4f} {r['roc_auc']:8.4f} {r['accuracy']:8.4f} "
            f"{r['fpr']:6.3f} {r['fnr']:6.3f}{marker}"
        )

    best = top20[0]
    print()
    print(f"  OPTIMAL WEIGHTS FOUND:")
    print(f"    face_deepfake_vit (A): {best['w_a']}")
    print(f"    sdxl_detector     (B): {best['w_b']}")
    print(f"    efficientnet_ffpp (C): {best['w_c']}")
    print(f"    F1 improvement: {best['f1'] - current_result['f1']:+.4f}")
    print(f"    AUC improvement: {best['roc_auc'] - current_result['roc_auc']:+.4f}")

    # ── Save ───────────────────────────────────────────────────────────────────
    out = {
        "current_weights":    {**current, **current_result},
        "optimal_weights":    best,
        "improvement": {
            "f1_delta":    round(best["f1"] - current_result["f1"], 4),
            "auc_delta":   round(best["roc_auc"] - current_result["roc_auc"], 4),
        },
        "top20_configurations": top20,
        "apply_instructions": (
            "To apply optimal weights, edit backend/app/models/deepfake_detector.py:\n"
            f"  _W_NO_FACE = [{best['w_a']}, {best['w_b']}, {best['w_c']}]  # optimized\n"
            "Restart the backend after editing."
        ),
    }
    out_path = ROOT / "reports" / "ensemble_weight_search.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nFull search results: {out_path}")

    if best["f1"] - current_result["f1"] > 0.02:
        print()
        print("  RECOMMENDATION: Apply optimal weights (F1 improvement > 2%)")
        print(f"  Edit _W_NO_FACE in deepfake_detector.py:")
        print(f"  _W_NO_FACE = [{best['w_a']}, {best['w_b']}, {best['w_c']}]")
    else:
        print()
        print("  Current weights are near-optimal. No change recommended.")


if __name__ == "__main__":
    main()
