"""
Benchmark Golden Set — Complete Scientific Validation
======================================================
Runs the full DeepGuard AI ensemble on every image in the golden set.
Computes all metrics independently per model and for the ensemble.
Generates error analysis, copies failed images to reports/.

Output:
  reports/golden_set_results.csv
  reports/golden_set_report.json
  reports/false_positives/   ← real images classified as FAKE
  reports/false_negatives/   ← AI images classified as REAL
  reports/calibration/       ← reliability plots data

Usage:
  cd "PROYECTO TITULO FINAL"
  python scripts/benchmark_golden_set.py
"""
import csv
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ROOT     = Path(__file__).parent.parent
BACKEND  = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

os.environ["TRANSFORMERS_CACHE"]          = str(ROOT / "models")
os.environ["HF_HOME"]                     = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(BACKEND)

from app.config import settings
from app.models.deepfake_detector import _model_a, _model_b, _model_c, _calibrated_combine

GOLDEN_DIR = ROOT / "tests" / "golden_set"
REPORTS    = ROOT / "reports"
FP_DIR     = REPORTS / "false_positives"
FN_DIR     = REPORTS / "false_negatives"
CALIB_DIR  = REPORTS / "calibration"
THRESHOLD  = 0.50


# ─── Load all models ──────────────────────────────────────────────────────────

def load_models() -> None:
    print("Loading models...")
    _model_a.load()
    print(f"  A (face-deepfake): {_model_a.model_name}")
    _model_b.load()
    print(f"  B (ai-image):      {_model_b.model_name}")
    _model_c.load()
    print(f"  C (efficientnet):  {_model_c.model_name} | loaded={_model_c._loaded}")


# ─── Per-image inference ──────────────────────────────────────────────────────

def run_inference(image_path: Path) -> dict:
    img = Image.open(image_path).convert("RGB")

    t0 = time.time()
    r_a = _model_a.predict(img)
    t_a = time.time() - t0

    t0 = time.time()
    r_b = _model_b.predict(img)
    t_b = time.time() - t0

    t0 = time.time()
    r_c = _model_c.predict(img)
    t_c = time.time() - t0 if r_c else 0.0

    # No face info available in standalone mode — use False (conservative)
    t0 = time.time()
    ensemble, per_model = _calibrated_combine(
        r_a["fake_probability"],
        r_b["fake_probability"],
        r_c["fake_probability"] if r_c else None,
        face=False,
    )
    t_ensemble = time.time() - t0 + t_a + t_b + t_c

    pred_label = 1 if ensemble >= THRESHOLD else 0
    if ensemble >= 0.82:       verdict = "DEEPFAKE"
    elif ensemble >= 0.65:     verdict = "LIKELY DEEPFAKE"
    elif ensemble >= 0.42:     verdict = "UNCERTAIN"
    elif ensemble >= 0.25:     verdict = "LIKELY REAL"
    else:                      verdict = "REAL"

    return {
        "score_a": round(r_a["fake_probability"], 4),
        "score_b": round(r_b["fake_probability"], 4),
        "score_c": round(r_c["fake_probability"], 4) if r_c else None,
        "score_ensemble": round(ensemble, 4),
        "pred_label": pred_label,
        "verdict": verdict,
        "inference_time_s": round(t_ensemble, 3),
    }


# ─── Metrics ──────────────────────────────────────────────────────────────────

def compute_metrics(y_true: list[int], y_score: list[float], y_pred: list[int], label: str) -> dict:
    if not y_true:
        return {}
    y_t = np.array(y_true)
    y_s = np.array(y_score)
    y_p = np.array(y_pred)

    tp = int(((y_p == 1) & (y_t == 1)).sum())
    tn = int(((y_p == 0) & (y_t == 0)).sum())
    fp = int(((y_p == 1) & (y_t == 0)).sum())
    fn = int(((y_p == 0) & (y_t == 1)).sum())

    accuracy  = (tp + tn) / max(1, len(y_t))
    precision = tp / max(1, tp + fp)
    recall    = tp / max(1, tp + fn)
    f1        = 2 * precision * recall / max(1e-9, precision + recall)
    fpr       = fp / max(1, fp + tn)
    fnr       = fn / max(1, fn + tp)

    try:
        from sklearn.metrics import roc_auc_score, average_precision_score
        if len(np.unique(y_t)) > 1:
            roc_auc = float(roc_auc_score(y_t, y_s))
            pr_auc  = float(average_precision_score(y_t, y_s))
        else:
            roc_auc = pr_auc = float("nan")
    except ImportError:
        roc_auc = pr_auc = float("nan")

    return {
        "label": label,
        "n": len(y_t),
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "roc_auc": round(roc_auc, 4) if not np.isnan(roc_auc) else "N/A",
        "pr_auc": round(pr_auc, 4) if not np.isnan(pr_auc) else "N/A",
        "false_positive_rate": round(fpr, 4),
        "false_negative_rate": round(fnr, 4),
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }


def calibration_error(y_true: list[int], y_score: list[float], n_bins: int = 10) -> dict:
    y_t = np.array(y_true)
    y_s = np.array(y_score)
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    bin_data = []
    for i in range(n_bins):
        mask = (y_s >= bins[i]) & (y_s < bins[i + 1])
        if mask.sum() == 0:
            continue
        avg_conf = float(y_s[mask].mean())
        avg_acc  = float(y_t[mask].mean())
        weight   = mask.sum() / len(y_t)
        ece += weight * abs(avg_conf - avg_acc)
        bin_data.append({
            "bin":        round((bins[i] + bins[i + 1]) / 2, 2),
            "confidence": round(avg_conf, 4),
            "accuracy":   round(avg_acc, 4),
            "gap":        round(abs(avg_conf - avg_acc), 4),
            "n":          int(mask.sum()),
        })
    return {"ece": round(ece, 4), "bins": bin_data}


# ─── Per-model standalone metrics ─────────────────────────────────────────────

def per_model_metrics(results: list[dict], manifests: list[dict]) -> dict:
    labeled = [(m, r) for m, r in zip(manifests, results) if m["expected_label"] is not None]
    y_true  = [m["expected_label"] for m, _ in labeled]

    out = {}
    for model_key, score_key in [
        ("face_deepfake_vit", "score_a"),
        ("sdxl_detector",     "score_b"),
        ("efficientnet_ffpp", "score_c"),
        ("ensemble",          "score_ensemble"),
    ]:
        scores = [r.get(score_key) for _, r in labeled]
        if any(s is None for s in scores):
            scores = [s if s is not None else 0.5 for s in scores]
        y_pred = [1 if s >= THRESHOLD else 0 for s in scores]
        out[model_key] = compute_metrics(y_true, scores, y_pred, model_key)

    return out


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # Setup
    for d in [FP_DIR, FN_DIR, CALIB_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    # Load manifest
    manifest_path = GOLDEN_DIR / "manifest.json"
    if not manifest_path.exists():
        print("ERROR: Run tests/create_golden_set.py first")
        sys.exit(1)
    with open(manifest_path) as f:
        manifest = json.load(f)

    load_models()
    print(f"\nBenchmarking {len(manifest)} images...")
    print("=" * 70)

    rows = []
    results = []

    for entry in manifest:
        img_path = ROOT / entry["path"]
        if not img_path.exists():
            print(f"  MISSING: {img_path}")
            continue

        result = run_inference(img_path)
        results.append(result)

        expected = entry["expected_label"]
        pred     = result["pred_label"]
        correct  = "✓" if expected is None or pred == expected else "✗"
        score    = result["score_ensemble"]

        print(
            f"  [{correct}] {entry['name']:40s} "
            f"| {score*100:5.1f}% | {result['verdict']:18s}"
            f"| A={result['score_a']*100:.0f}% B={result['score_b']*100:.0f}% "
            f"C={result['score_c']*100:.0f}% " if result['score_c'] is not None
            else f"  [{correct}] {entry['name']:40s} | {score*100:5.1f}% | {result['verdict']:18s}"
        )

        # Error analysis
        if expected == 0 and pred == 1:
            shutil.copy2(img_path, FP_DIR / img_path.name)
            rows.append({**entry, **result, "error_type": "false_positive",
                         "note": f"Real image scored {score*100:.1f}% fake"})
        elif expected == 1 and pred == 0:
            shutil.copy2(img_path, FN_DIR / img_path.name)
            rows.append({**entry, **result, "error_type": "false_negative",
                         "note": f"AI image scored {score*100:.1f}% fake (missed)"})
        else:
            rows.append({**entry, **result, "error_type": "correct" if expected is not None else "uncertain"})

    print("=" * 70)

    # ── Metrics ────────────────────────────────────────────────────────────────
    labeled = [(m, r) for m, r in zip(manifest, results) if m["expected_label"] is not None]
    y_true  = [m["expected_label"] for m, _ in labeled]
    y_score = [r["score_ensemble"]  for _, r in labeled]
    y_pred  = [r["pred_label"]      for _, r in labeled]

    ensemble_metrics = compute_metrics(y_true, y_score, y_pred, "ensemble")
    calib_data       = calibration_error(y_true, y_score)
    pm_metrics       = per_model_metrics(results, manifest)

    # Print metrics
    print("\n  ENSEMBLE METRICS (real=0, ai=1):")
    for k, v in ensemble_metrics.items():
        if k not in ("label", "confusion_matrix"):
            print(f"    {k:25s}: {v}")
    cm = ensemble_metrics["confusion_matrix"]
    print(f"    Confusion Matrix:")
    print(f"      TN={cm['tn']}  FP={cm['fp']}   (real images)")
    print(f"      FN={cm['fn']}  TP={cm['tp']}   (ai images)")

    print(f"\n  CALIBRATION ECE = {calib_data['ece']:.4f}")
    if calib_data['ece'] < 0.05:   print("    → WELL CALIBRATED")
    elif calib_data['ece'] < 0.10: print("    → ACCEPTABLE")
    else:                           print("    → POORLY CALIBRATED — needs temperature scaling")

    print("\n  PER-MODEL COMPARISON:")
    print(f"  {'Model':25s} {'Acc':>7} {'Prec':>7} {'Rec':>7} {'F1':>7} {'FPR':>7} {'FNR':>7}")
    for name, m in pm_metrics.items():
        if not m:
            continue
        print(
            f"  {name:25s} "
            f"{m['accuracy']*100:6.1f}% "
            f"{m['precision']*100:6.1f}% "
            f"{m['recall']*100:6.1f}% "
            f"{m['f1']*100:6.1f}% "
            f"{m['false_positive_rate']*100:6.1f}% "
            f"{m['false_negative_rate']*100:6.1f}%"
        )

    # ── Determine weakest model ────────────────────────────────────────────────
    model_names = [k for k in pm_metrics if k != "ensemble"]
    fpr_vals    = {k: pm_metrics[k].get("false_positive_rate", 1) for k in model_names}
    fnr_vals    = {k: pm_metrics[k].get("false_negative_rate", 1) for k in model_names}
    f1_vals     = {k: pm_metrics[k].get("f1", 0) for k in model_names}
    strongest   = max(f1_vals, key=f1_vals.get)
    weakest     = min(f1_vals, key=f1_vals.get)
    most_fp     = max(fpr_vals, key=fpr_vals.get)
    most_fn     = max(fnr_vals, key=fnr_vals.get)

    print(f"\n  MODEL STRENGTHS:")
    print(f"    Strongest (F1):          {strongest}")
    print(f"    Weakest   (F1):          {weakest}")
    print(f"    Most false positives:    {most_fp} (FPR={fpr_vals[most_fp]*100:.1f}%)")
    print(f"    Most false negatives:    {most_fn} (FNR={fnr_vals[most_fn]*100:.1f}%)")

    # ── Save outputs ───────────────────────────────────────────────────────────
    csv_path = REPORTS / "golden_set_results.csv"
    if rows:
        all_keys = sorted(set(k for r in rows for k in r.keys()))
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"\n  Results CSV: {csv_path}")

    json_report = {
        "golden_set_size": len(manifest),
        "labeled_images": len(labeled),
        "threshold": THRESHOLD,
        "ensemble_metrics": ensemble_metrics,
        "per_model_metrics": pm_metrics,
        "calibration": calib_data,
        "error_summary": {
            "false_positives": sum(1 for r in rows if r.get("error_type") == "false_positive"),
            "false_negatives": sum(1 for r in rows if r.get("error_type") == "false_negative"),
            "correct": sum(1 for r in rows if r.get("error_type") == "correct"),
        },
        "model_analysis": {
            "strongest_model": strongest,
            "weakest_model":   weakest,
            "most_fp_model":   most_fp,
            "most_fn_model":   most_fn,
        },
    }
    json_path = REPORTS / "golden_set_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_report, f, indent=2)
    print(f"  Full report:  {json_path}")

    calib_path = CALIB_DIR / "calibration_data.json"
    with open(calib_path, "w") as f:
        json.dump(calib_data, f, indent=2)

    print()
    fp_count = sum(1 for r in rows if r.get("error_type") == "false_positive")
    fn_count = sum(1 for r in rows if r.get("error_type") == "false_negative")
    print(f"  False positives saved to: reports/false_positives/ ({fp_count} images)")
    print(f"  False negatives saved to: reports/false_negatives/ ({fn_count} images)")
    print()
    print("  Next steps:")
    print("    python scripts/calibration_analysis.py")
    print("    python scripts/optimize_ensemble_weights.py")


if __name__ == "__main__":
    main()
