"""
Proper Model Evaluation — Precision, Recall, F1, AUC, Confusion Matrix
=======================================================================
AUDIT FINDING: Only accuracy was used during training. This hides:
  - Class imbalance problems
  - High precision / low recall trade-offs (or vice versa)
  - Calibration issues

Usage:
  python scripts/evaluate_model.py
  python scripts/evaluate_model.py --split test
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.models import efficientnet_b4
from PIL import Image
from tqdm import tqdm

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data" / "ff++_faces"
MODEL_DIR = ROOT / "models" / "trained" / "efficientnet_b4_ffpp"
BEST_PTH = MODEL_DIR / "efficientnet_b4_ffpp_best.pth"


class EvalDataset(torch.utils.data.Dataset):
    MEAN = [0.485, 0.456, 0.406]
    STD  = [0.229, 0.224, 0.225]

    def __init__(self, csv_path: Path) -> None:
        with open(csv_path) as f:
            self.samples = [(r["path"], int(r["label"])) for r in csv.DictReader(f)]
        self.transform = transforms.Compose([
            transforms.Resize(256), transforms.CenterCrop(224),
            transforms.ToTensor(), transforms.Normalize(self.MEAN, self.STD),
        ])

    def __len__(self) -> int: return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        try: img = Image.open(path).convert("RGB")
        except: img = Image.new("RGB", (224, 224), (128, 128, 128))
        return self.transform(img), label


def compute_metrics(y_true: np.ndarray, y_score: np.ndarray, threshold: float = 0.5) -> dict:
    from sklearn.metrics import (
        precision_score, recall_score, f1_score,
        roc_auc_score, average_precision_score,
        confusion_matrix, classification_report, roc_curve,
    )

    y_pred = (y_score >= threshold).astype(int)

    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel()

    return {
        "accuracy":        float(np.mean(y_true == y_pred)),
        "precision":       float(precision_score(y_true, y_pred, zero_division=0)),
        "recall":          float(recall_score(y_true, y_pred, zero_division=0)),
        "f1":              float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc":         float(roc_auc_score(y_true, y_score)),
        "pr_auc":          float(average_precision_score(y_true, y_score)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "false_positive_rate": float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0,
        "false_negative_rate": float(fn / (fn + tp)) if (fn + tp) > 0 else 0.0,
        "threshold_used":  threshold,
        "n_samples":       len(y_true),
    }


def find_optimal_threshold(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Find threshold that maximizes F1 score."""
    from sklearn.metrics import f1_score
    best_f1, best_t = 0.0, 0.5
    for t in np.arange(0.3, 0.85, 0.05):
        f1 = f1_score(y_true, (y_score >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_t = f1, float(t)
    return best_t


def calibration_error(y_true: np.ndarray, y_score: np.ndarray, n_bins: int = 10) -> dict:
    """Expected Calibration Error (ECE) — measures probability calibration quality."""
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    bin_data = []
    for i in range(n_bins):
        mask = (y_score >= bins[i]) & (y_score < bins[i+1])
        if mask.sum() == 0:
            bin_data.append(None)
            continue
        avg_conf = float(y_score[mask].mean())
        avg_acc  = float(y_true[mask].mean())
        weight   = mask.sum() / len(y_true)
        ece += weight * abs(avg_conf - avg_acc)
        bin_data.append({"bin_center": round((bins[i]+bins[i+1])/2, 2),
                          "confidence": round(avg_conf, 4),
                          "accuracy": round(avg_acc, 4),
                          "count": int(mask.sum())})
    return {"ece": round(float(ece), 4), "bins": [b for b in bin_data if b is not None]}


def main(split: str = "test") -> None:
    try:
        from sklearn.metrics import f1_score
    except ImportError:
        print("Installing scikit-learn...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "scikit-learn", "-q"])
        from sklearn.metrics import f1_score

    csv_path = DATA_DIR / f"{split}.csv"
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found. Run prepare_dataset.py first.")
        sys.exit(1)

    if not BEST_PTH.exists():
        print(f"ERROR: Model not found at {BEST_PTH}. Run training first.")
        sys.exit(1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device} | Split: {split}")

    # Load model
    model = efficientnet_b4(weights=None)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, 2)
    state = torch.load(str(BEST_PTH), map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    model.to(device).eval()

    # Evaluate
    ds     = EvalDataset(csv_path)
    loader = DataLoader(ds, batch_size=64, shuffle=False, num_workers=4, pin_memory=True)

    all_probs = []
    all_labels = []

    with torch.no_grad():
        for imgs, labels in tqdm(loader, desc=f"Evaluating {split}"):
            imgs = imgs.to(device)
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                logits = model(imgs)
            probs = torch.softmax(logits, dim=-1)[:, 1].cpu().numpy()
            all_probs.extend(probs.tolist())
            all_labels.extend(labels.numpy().tolist())

    y_true  = np.array(all_labels)
    y_score = np.array(all_probs)

    # Find optimal threshold
    opt_t = find_optimal_threshold(y_true, y_score)
    print(f"Optimal threshold (max F1): {opt_t:.2f}")

    # Compute metrics at 0.5 and optimal
    metrics_05  = compute_metrics(y_true, y_score, threshold=0.50)
    metrics_opt = compute_metrics(y_true, y_score, threshold=opt_t)
    calib       = calibration_error(y_true, y_score)

    report = {
        "split": split,
        "model": str(BEST_PTH),
        "metrics_at_0.50": metrics_05,
        f"metrics_at_{opt_t:.2f}_optimal": metrics_opt,
        "calibration": calib,
    }

    # Print report
    print()
    print("=" * 60)
    print(f"  EVALUATION REPORT — {split.upper()} SET")
    print("=" * 60)

    def print_metrics(m: dict, label: str) -> None:
        print(f"\n  [{label}]")
        print(f"  Accuracy       : {m['accuracy']*100:.2f}%")
        print(f"  Precision      : {m['precision']*100:.2f}%  (of predicted fakes, how many are real fakes?)")
        print(f"  Recall         : {m['recall']*100:.2f}%  (of actual fakes, how many did we catch?)")
        print(f"  F1             : {m['f1']*100:.2f}%")
        print(f"  ROC-AUC        : {m['roc_auc']:.4f}")
        print(f"  PR-AUC         : {m['pr_auc']:.4f}")
        print(f"  False Pos Rate : {m['false_positive_rate']*100:.2f}%  (real images flagged as fake)")
        print(f"  False Neg Rate : {m['false_negative_rate']*100:.2f}%  (fakes that slipped through)")
        cm = m["confusion_matrix"]
        print(f"  Confusion Matrix:")
        print(f"    TN={cm['tn']:>6}  FP={cm['fp']:>6}   (real images)")
        print(f"    FN={cm['fn']:>6}  TP={cm['tp']:>6}   (fake images)")

    print_metrics(metrics_05,  "Threshold = 0.50 (default)")
    print_metrics(metrics_opt, f"Threshold = {opt_t:.2f} (optimal F1)")

    print(f"\n  CALIBRATION (ECE = {calib['ece']:.4f})")
    print(f"  {'ECE < 0.05':>25} = well calibrated")
    print(f"  {'ECE > 0.10':>25} = poorly calibrated, needs temperature scaling")
    for b in calib["bins"]:
        bar = "█" * int(abs(b["confidence"] - b["accuracy"]) * 50)
        flag = " ← OVERCALIBRATED" if b["confidence"] - b["accuracy"] > 0.15 else ""
        print(f"  bin {b['bin_center']:.2f}: conf={b['confidence']:.3f} acc={b['accuracy']:.3f} n={b['count']:>5} {bar}{flag}")

    # Save report
    report_path = MODEL_DIR / f"eval_{split}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Full report saved: {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    args = parser.parse_args()
    main(args.split)
