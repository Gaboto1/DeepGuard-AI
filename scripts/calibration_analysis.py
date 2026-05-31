"""
Calibration Analysis — Temperature Scaling + Reliability Diagram
=================================================================
Measures whether predicted probabilities match actual accuracy.
Applies Temperature Scaling to correct overconfidence/underconfidence.

Key question: When the model says 90% fake, is it right 90% of the time?

Outputs:
  reports/calibration/reliability_diagram_data.json
  reports/calibration/temperature_scaling_result.json
  reports/calibration/calibrated_results.csv

Usage:
  python scripts/calibration_analysis.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

os.environ["TRANSFORMERS_CACHE"]          = str(ROOT / "models")
os.environ["HF_HOME"]                     = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(BACKEND)

from app.config import settings
from app.models.deepfake_detector import _model_a, _model_b, _model_c, _calibrated_combine

CALIB_DIR = ROOT / "reports" / "calibration"
CALIB_DIR.mkdir(parents=True, exist_ok=True)


def load_golden_labeled() -> tuple[list[float], list[int], list[Path]]:
    """Load golden set and get ensemble scores + labels."""
    manifest_path = ROOT / "tests" / "golden_set" / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    _model_a.load()
    _model_b.load()
    _model_c.load()

    scores, labels, paths = [], [], []

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
        score, _ = _calibrated_combine(
            ra["fake_probability"], rb["fake_probability"],
            rc["fake_probability"] if rc else None, face=False,
        )
        scores.append(score)
        labels.append(entry["expected_label"])
        paths.append(img_path)

    return scores, labels, paths


def reliability_diagram(scores: list[float], labels: list[int], n_bins: int = 5) -> dict:
    """
    Compute calibration bins for a reliability diagram.
    Perfect calibration: confidence == accuracy in each bin.
    """
    y_s = np.array(scores)
    y_t = np.array(labels)
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    diagram_data = []

    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_s >= lo) & (y_s < hi)
        if mask.sum() == 0:
            continue
        avg_conf = float(y_s[mask].mean())
        avg_acc  = float(y_t[mask].mean())
        weight   = mask.sum() / len(y_t)
        ece += weight * abs(avg_conf - avg_acc)
        status = "OVER" if avg_conf > avg_acc + 0.1 else ("UNDER" if avg_conf < avg_acc - 0.1 else "OK")
        diagram_data.append({
            "bin_range":    f"[{lo:.1f}, {hi:.1f})",
            "confidence":   round(avg_conf, 4),
            "accuracy":     round(avg_acc, 4),
            "gap":          round(avg_conf - avg_acc, 4),
            "n_samples":    int(mask.sum()),
            "calibration":  status,
        })

    return {"ece": round(ece, 4), "n_bins": n_bins, "bins": diagram_data}


def temperature_scaling(scores: list[float], labels: list[int]) -> tuple[float, list[float]]:
    """
    Find optimal temperature T such that softmax(logits/T) is well-calibrated.
    For binary classification: scale logits = log(p/(1-p)).
    """
    from scipy.optimize import minimize_scalar

    scores_np = np.array(scores)
    labels_np = np.array(labels)

    # Convert probabilities to logits
    eps = 1e-7
    logits = np.log(np.clip(scores_np, eps, 1 - eps) / np.clip(1 - scores_np, eps, 1 - eps))

    def nll_loss(temperature: float) -> float:
        if temperature <= 0:
            return 1e10
        scaled = torch.sigmoid(torch.tensor(logits / temperature, dtype=torch.float32))
        labels_t = torch.tensor(labels_np, dtype=torch.float32)
        loss = nn.BCELoss()(scaled, labels_t)
        return float(loss.item())

    result = minimize_scalar(nll_loss, bounds=(0.01, 10.0), method="bounded")
    T = float(result.x)

    # Apply temperature scaling
    scaled_logits  = logits / T
    calibrated_scores = [float(torch.sigmoid(torch.tensor(l)).item()) for l in scaled_logits]

    return T, calibrated_scores


def main() -> None:
    print("=" * 60)
    print("  CALIBRATION ANALYSIS")
    print("=" * 60)

    print("\nLoading golden set predictions...")
    scores, labels, paths = load_golden_labeled()
    n = len(scores)
    print(f"Labeled samples: {n} ({sum(1 for l in labels if l==0)} real, {sum(1 for l in labels if l==1)} fake)")

    if n < 5:
        print("Too few samples for calibration analysis. Add more golden images.")
        sys.exit(1)

    # ── Reliability diagram ────────────────────────────────────────────────────
    print("\n[1/3] Reliability Diagram:")
    rel_data = reliability_diagram(scores, labels, n_bins=5)
    print(f"  ECE = {rel_data['ece']:.4f}")

    if rel_data['ece'] < 0.05:
        cal_status = "WELL CALIBRATED ✓"
    elif rel_data['ece'] < 0.10:
        cal_status = "ACCEPTABLE — minor overconfidence"
    else:
        cal_status = "POORLY CALIBRATED — temperature scaling recommended"
    print(f"  Status: {cal_status}")

    print(f"\n  {'Bin Range':15} {'Confidence':>12} {'Accuracy':>10} {'Gap':>8} {'N':>5} {'Status':>8}")
    print(f"  {'-'*60}")
    for b in rel_data["bins"]:
        flag = "← OVER" if b["calibration"] == "OVER" else ("← UNDER" if b["calibration"] == "UNDER" else "")
        print(
            f"  {b['bin_range']:15} "
            f"{b['confidence']:12.3f} "
            f"{b['accuracy']:10.3f} "
            f"{b['gap']:+8.3f} "
            f"{b['n_samples']:5d} "
            f"  {flag}"
        )

    # ── Temperature scaling ────────────────────────────────────────────────────
    print("\n[2/3] Temperature Scaling:")
    T, calibrated = temperature_scaling(scores, labels)
    rel_after = reliability_diagram(calibrated, labels, n_bins=5)
    print(f"  Optimal temperature T = {T:.3f}")
    print(f"  ECE before: {rel_data['ece']:.4f}")
    print(f"  ECE after:  {rel_after['ece']:.4f}")
    improvement = rel_data["ece"] - rel_after["ece"]
    print(f"  Improvement: {improvement:+.4f}")

    if T > 1.5:
        print("  NOTE: T > 1.5 means model is OVERCONFIDENT (predicted probs too extreme)")
    elif T < 0.7:
        print("  NOTE: T < 0.7 means model is UNDERCONFIDENT (probs too conservative)")
    else:
        print("  NOTE: T ≈ 1.0 means model is already well-calibrated")

    # ── Worst calibrated predictions ──────────────────────────────────────────
    print("\n[3/3] Worst calibrated predictions (largest gap between score and outcome):")
    gaps = [(abs(s - l), s, l, p) for s, l, p in zip(scores, labels, paths)]
    gaps.sort(reverse=True)
    for gap, score, label, path in gaps[:5]:
        expected = "REAL" if label == 0 else "AI"
        print(f"  gap={gap:.3f} | score={score:.3f} | truth={expected} | {path.name}")

    # ── Save outputs ───────────────────────────────────────────────────────────
    result = {
        "n_samples": n,
        "before_scaling": rel_data,
        "optimal_temperature": round(T, 4),
        "after_scaling": rel_after,
        "calibration_status": cal_status,
        "recommendation": (
            f"Apply temperature T={T:.2f} to all model outputs before thresholding."
            if abs(T - 1.0) > 0.15
            else "Model is well-calibrated. No temperature scaling needed."
        ),
    }

    out_path = CALIB_DIR / "temperature_scaling_result.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nCalibration report saved: {out_path}")

    # Save calibrated scores
    import csv
    csv_path = CALIB_DIR / "calibrated_results.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "true_label", "raw_score", "calibrated_score"])
        for p, l, s, c in zip(paths, labels, scores, calibrated):
            w.writerow([p.name, l, round(s, 4), round(c, 4)])
    print(f"Calibrated results CSV: {csv_path}")


if __name__ == "__main__":
    main()
