"""
Model Comparison: B0 vs B4 vs SDXL vs Ensemble
================================================
Evaluates all models independently on the golden set.
Answers: Does EfficientNet-B4 beat SDXL Detector?

Metrics per model:
  F1, Precision, Recall, ROC-AUC, FPR, FNR

Output:
  reports/model_comparison.json
  reports/model_comparison_table.txt

Usage:
  python scripts/compare_models.py
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torchvision import transforms

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

os.environ["TRANSFORMERS_CACHE"]              = str(ROOT / "models")
os.environ["HF_HOME"]                         = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(BACKEND)

from app.config import settings
from app.models.deepfake_detector import _model_a, _model_b, _model_c, _calibrated_combine

B4_PATH  = ROOT / "models" / "trained" / "efficientnet_b4_ffpp" / "efficientnet_b4_ffpp_best.pth"
REPORTS  = ROOT / "reports"
MANIFEST = ROOT / "tests" / "golden_set" / "manifest.json"

_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD  = [0.229, 0.224, 0.225]


# ─── Load golden set ──────────────────────────────────────────────────────────

def load_manifest() -> tuple[list[Path], list[int], list[str]]:
    with open(MANIFEST) as f:
        manifest = json.load(f)
    paths, labels, names = [], [], []
    for entry in manifest:
        if entry["expected_label"] is None:
            continue
        p = ROOT / entry["path"]
        if p.exists():
            paths.append(p)
            labels.append(entry["expected_label"])
            names.append(entry["name"])
    return paths, labels, names


# ─── EfficientNet-B4 loader (standalone, no HuggingFace) ─────────────────────

class EfficientNetB4:
    def __init__(self, pth_path: Path) -> None:
        from torchvision.models import efficientnet_b4
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = efficientnet_b4(weights=None)
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, 2)
        state = torch.load(str(pth_path), map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
        self.model = model.to(self.device).eval()
        self.preprocess = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(_IMAGENET_MEAN, _IMAGENET_STD),
        ])
        print(f"  EfficientNet-B4 loaded from {pth_path.name} on {self.device}")

    def predict_all(self, paths: list[Path]) -> list[float]:
        scores = []
        for p in paths:
            img = Image.open(p).convert("RGB")
            t   = self.preprocess(img).unsqueeze(0).to(self.device)
            with torch.no_grad():
                out = self.model(t)
            prob = torch.softmax(out, dim=-1)[0, 1].item()
            scores.append(prob)
        return scores


# ─── EfficientNet-B0 (same wrapper) ──────────────────────────────────────────

class EfficientNetB0:
    def __init__(self) -> None:
        from torchvision.models import efficientnet_b0
        from huggingface_hub import hf_hub_download
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        pth = hf_hub_download(
            repo_id="Xicor9/efficientnet-b0-ffpp-c23",
            filename="efficientnet_b0_ffpp_c23.pth",
            cache_dir=str(ROOT / "models"),
        )
        model = efficientnet_b0(weights=None)
        model.classifier[1] = nn.Linear(1280, 2)
        state = torch.load(pth, map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
        self.model = model.to(self.device).eval()
        self.preprocess = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(_IMAGENET_MEAN, _IMAGENET_STD),
        ])
        print(f"  EfficientNet-B0 (FF++ c23) loaded on {self.device}")

    def predict_all(self, paths: list[Path]) -> list[float]:
        scores = []
        for p in paths:
            img = Image.open(p).convert("RGB")
            t   = self.preprocess(img).unsqueeze(0).to(self.device)
            with torch.no_grad():
                out = self.model(t)
            prob = torch.softmax(out, dim=-1)[0, 1].item()
            scores.append(prob)
        return scores


# ─── Metrics ──────────────────────────────────────────────────────────────────

def metrics(y_true: list[int], y_score: list[float], threshold: float = 0.50) -> dict:
    y_t = np.array(y_true)
    y_s = np.array(y_score)
    y_p = (y_s >= threshold).astype(int)

    tp = int(((y_p==1)&(y_t==1)).sum())
    tn = int(((y_p==0)&(y_t==0)).sum())
    fp = int(((y_p==1)&(y_t==0)).sum())
    fn = int(((y_p==0)&(y_t==1)).sum())

    prec  = tp / max(1, tp+fp)
    rec   = tp / max(1, tp+fn)
    f1    = 2*prec*rec / max(1e-9, prec+rec)
    acc   = (tp+tn)/len(y_t)
    fpr   = fp / max(1, fp+tn)
    fnr   = fn / max(1, fn+tp)

    try:
        from sklearn.metrics import roc_auc_score, average_precision_score
        roc  = roc_auc_score(y_t, y_s) if len(np.unique(y_t))>1 else 0.5
        prauc= average_precision_score(y_t, y_s) if len(np.unique(y_t))>1 else 0.5
    except ImportError:
        roc = prauc = 0.5

    return {
        "f1":        round(f1,   4),
        "precision": round(prec, 4),
        "recall":    round(rec,  4),
        "roc_auc":   round(roc,  4),
        "pr_auc":    round(prauc,4),
        "accuracy":  round(acc,  4),
        "fpr":       round(fpr,  4),
        "fnr":       round(fnr,  4),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "n": len(y_t),
    }


def print_row(name: str, m: dict, highlight: bool = False) -> None:
    mark = " ◄ BEST F1" if highlight else ""
    print(
        f"  {name:30s} "
        f"F1={m['f1']*100:5.1f}%  "
        f"Prec={m['precision']*100:5.1f}%  "
        f"Rec={m['recall']*100:5.1f}%  "
        f"AUC={m['roc_auc']:.3f}  "
        f"FPR={m['fpr']*100:4.1f}%  "
        f"FNR={m['fnr']*100:4.1f}%"
        f"{mark}"
    )


# ─── Per-image detail ─────────────────────────────────────────────────────────

def per_image_detail(names, labels, b4_scores, b0_scores, b_scores, ens_scores) -> None:
    print()
    print(f"  {'Image':42s} {'Truth':6} {'B4':>6} {'B0':>6} {'SDXL':>6} {'Ens':>6}")
    print(f"  {'-'*75}")
    for name, lbl, s4, s0, sb, se in zip(names, labels, b4_scores, b0_scores, b_scores, ens_scores):
        truth = "REAL" if lbl == 0 else "AI"
        # Highlight misclassifications
        def fmt(score, lbl):
            pred = 1 if score >= 0.5 else 0
            ok = pred == lbl
            s = f"{score*100:5.1f}%"
            return s if ok else f"[{s}]"
        print(
            f"  {name:42s} {truth:6} "
            f"{fmt(s4,lbl):>8} {fmt(s0,lbl):>8} {fmt(sb,lbl):>8} {fmt(se,lbl):>8}"
        )
    print(f"  (brackets = wrong classification)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("=" * 70)
    print("  MODEL COMPARISON: B4 vs B0 vs SDXL vs Ensemble")
    print("=" * 70)

    # Check B4 availability
    if not B4_PATH.exists():
        print(f"\nERROR: EfficientNet-B4 not found at {B4_PATH}")
        print("Training must complete before running this comparison.")
        sys.exit(1)

    # Load golden set
    paths, labels, names = load_manifest()
    print(f"\nGolden set: {len(paths)} labeled images ({sum(1 for l in labels if l==0)} real, {sum(1 for l in labels if l==1)} AI)")

    # ── Load all models ────────────────────────────────────────────────────────
    print("\nLoading models...")
    _model_a.load()
    _model_b.load()
    _model_c.load()

    print("  Loading EfficientNet-B4...")
    b4 = EfficientNetB4(B4_PATH)
    b0 = EfficientNetB0()

    # ── Collect scores ─────────────────────────────────────────────────────────
    print("\nRunning inference on all images...")

    t0 = time.time()
    b4_scores = b4.predict_all(paths)
    t_b4 = time.time() - t0
    print(f"  EfficientNet-B4: {t_b4:.2f}s ({t_b4/len(paths)*1000:.0f}ms/img)")

    t0 = time.time()
    b0_scores = b0.predict_all(paths)
    t_b0 = time.time() - t0
    print(f"  EfficientNet-B0: {t_b0:.2f}s ({t_b0/len(paths)*1000:.0f}ms/img)")

    t0 = time.time()
    b_scores = [_model_b.predict(Image.open(p).convert("RGB"))["fake_probability"] for p in paths]
    t_b = time.time() - t0
    print(f"  SDXL Detector:   {t_b:.2f}s ({t_b/len(paths)*1000:.0f}ms/img)")

    t0 = time.time()
    a_scores = [_model_a.predict(Image.open(p).convert("RGB"))["fake_probability"] for p in paths]
    c_scores = [_model_c.predict(Image.open(p).convert("RGB")) for p in paths]
    c_scores_f = [r["fake_probability"] if r else 0.5 for r in c_scores]
    ens_scores = []
    for sa, sb, sc in zip(a_scores, b_scores, c_scores_f):
        score, _ = _calibrated_combine(sa, sb, sc, face=False)
        ens_scores.append(score)
    t_ens = time.time() - t0
    print(f"  Ensemble:        {t_ens:.2f}s total")

    # ── Compute metrics ────────────────────────────────────────────────────────
    m_b4  = metrics(labels, b4_scores)
    m_b0  = metrics(labels, b0_scores)
    m_b   = metrics(labels, b_scores)
    m_a   = metrics(labels, a_scores)
    m_ens = metrics(labels, ens_scores)

    # Ensemble with B4 replacing B0
    ens_b4_scores = []
    for sa, sb, s4 in zip(a_scores, b_scores, b4_scores):
        # Use B4 in place of B0, keep current weights
        w = [0.15, 0.70, 0.15]
        score = w[0]*sa + w[1]*sb + w[2]*s4
        ens_b4_scores.append(min(1.0, max(0.0, score)))
    m_ens_b4 = metrics(labels, ens_b4_scores)

    # ── Print comparison table ─────────────────────────────────────────────────
    all_f1 = {
        "EfficientNet-B4 (trained FF++)": m_b4["f1"],
        "SDXL Detector":                  m_b["f1"],
        "Ensemble (current, B0)":         m_ens["f1"],
        "Ensemble (B4 replacing B0)":     m_ens_b4["f1"],
        "Face-Deepfake ViT":              m_a["f1"],
        "EfficientNet-B0 (FF++ c23)":     m_b0["f1"],
    }
    best_name = max(all_f1, key=all_f1.get)

    print()
    print("=" * 70)
    print("  RESULTS")
    print("=" * 70)
    print()
    print(f"  {'Model':30s} {'F1':>7} {'Prec':>7} {'Rec':>7} {'AUC':>7} {'FPR':>6} {'FNR':>6}")
    print(f"  {'-'*70}")

    rows = [
        ("EfficientNet-B4 (FF++ trained)", m_b4),
        ("SDXL Detector (Organika)",       m_b),
        ("Ensemble (current, B0)",         m_ens),
        ("Ensemble (B4 replacing B0)",     m_ens_b4),
        ("Face-Deepfake ViT (A)",          m_a),
        ("EfficientNet-B0 (FF++ c23)",     m_b0),
    ]
    for name, m in rows:
        mark = " ◄ BEST" if m["f1"] == max(r["f1"] for _, r in rows) else ""
        print(
            f"  {name:30s} "
            f"{m['f1']*100:6.1f}%"
            f"{m['precision']*100:7.1f}%"
            f"{m['recall']*100:7.1f}%"
            f"{m['roc_auc']:7.3f}"
            f"{m['fpr']*100:6.1f}%"
            f"{m['fnr']*100:6.1f}%"
            f"{mark}"
        )

    print()
    print("=" * 70)
    print("  CONFUSION MATRICES")
    print("=" * 70)
    for name, m in rows:
        print(f"  {name}:")
        print(f"    TN={m['tn']:3d}  FP={m['fp']:3d}   (real images correctly/wrongly flagged)")
        print(f"    FN={m['fn']:3d}  TP={m['tp']:3d}   (AI images missed/caught)")

    # ── Verdict ────────────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  VERDICT")
    print("=" * 70)
    b4_beats_sdxl  = m_b4["f1"] > m_b["f1"]
    b4_beats_b0    = m_b4["f1"] > m_b0["f1"]
    b4_beats_ens   = m_b4["f1"] > m_ens["f1"]
    ens_b4_better  = m_ens_b4["f1"] > m_ens["f1"]

    print()
    print(f"  Does B4 beat SDXL Detector?     {'YES ✓' if b4_beats_sdxl  else 'NO ✗'}  "
          f"(B4={m_b4['f1']*100:.1f}% vs SDXL={m_b['f1']*100:.1f}%)")
    print(f"  Does B4 beat B0?                {'YES ✓' if b4_beats_b0    else 'NO ✗'}  "
          f"(B4={m_b4['f1']*100:.1f}% vs B0={m_b0['f1']*100:.1f}%)")
    print(f"  Does B4 beat current ensemble?  {'YES ✓' if b4_beats_ens   else 'NO ✗'}  "
          f"(B4={m_b4['f1']*100:.1f}% vs Ens={m_ens['f1']*100:.1f}%)")
    print(f"  Does B4 improve ensemble?       {'YES ✓' if ens_b4_better  else 'NO ✗'}  "
          f"(EnsB4={m_ens_b4['f1']*100:.1f}% vs EnsB0={m_ens['f1']*100:.1f}%)")
    print()

    if b4_beats_b0:
        print("  RECOMMENDATION: Replace B0 with B4 in the ensemble.")
    else:
        print("  RECOMMENDATION: Keep B0 (B4 did not outperform on golden set).")

    if ens_b4_better and m_ens_b4["f1"] - m_ens["f1"] > 0.02:
        print("  RECOMMENDATION: Deploy ensemble with B4 (meaningful improvement).")
    elif ens_b4_better:
        print("  RECOMMENDATION: B4 marginally better. Consider A/B testing.")
    else:
        print("  RECOMMENDATION: Keep current ensemble (B4 does not improve it).")

    # ── Per-image detail ───────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  PER-IMAGE DETAIL (brackets = wrong classification)")
    print("=" * 70)
    per_image_detail(names, labels, b4_scores, b0_scores, b_scores, ens_scores)

    # ── B4 failure analysis ────────────────────────────────────────────────────
    b4_errors = [(n, l, s) for n, l, s in zip(names, labels, b4_scores)
                 if (l==0 and s>=0.5) or (l==1 and s<0.5)]
    if b4_errors:
        print()
        print(f"  B4 Errors ({len(b4_errors)} total):")
        for n, l, s in b4_errors:
            truth = "REAL" if l==0 else "AI"
            pred  = "FAKE" if s>=0.5 else "REAL"
            print(f"    {n:42s} truth={truth} pred={pred} score={s*100:.1f}%")

    # ── Save report ────────────────────────────────────────────────────────────
    report = {
        "golden_set_n":     len(paths),
        "threshold":        0.50,
        "models": {
            "efficientnet_b4":      {**m_b4,  "inference_ms_per_img": round(t_b4/len(paths)*1000,1)},
            "efficientnet_b0":      {**m_b0,  "inference_ms_per_img": round(t_b0/len(paths)*1000,1)},
            "sdxl_detector":        {**m_b,   "inference_ms_per_img": round(t_b/len(paths)*1000,1)},
            "face_deepfake_vit":    {**m_a},
            "ensemble_current_b0":  {**m_ens},
            "ensemble_with_b4":     {**m_ens_b4},
        },
        "verdict": {
            "b4_beats_sdxl":       b4_beats_sdxl,
            "b4_beats_b0":         b4_beats_b0,
            "b4_beats_ensemble":   b4_beats_ens,
            "ensemble_b4_better":  ens_b4_better,
            "recommend_replace_b0": b4_beats_b0,
        },
        "b4_errors": [{"name": n, "truth": l, "score": s} for n, l, s in b4_errors],
    }

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "model_comparison.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Full comparison: {out}")

    # Text table
    table_lines = ["MODEL COMPARISON REPORT", "=" * 80,
        f"{'Model':<32}{'F1':>7}{'Prec':>8}{'Rec':>7}{'AUC':>8}{'FPR':>7}{'FNR':>7}",
        "-" * 80]
    for name, m in rows:
        mark = " ← BEST" if m["f1"] == max(r["f1"] for _, r in rows) else ""
        table_lines.append(
            f"{name:<32}{m['f1']*100:6.1f}%{m['precision']*100:7.1f}%"
            f"{m['recall']*100:6.1f}%{m['roc_auc']:7.3f}"
            f"{m['fpr']*100:6.1f}%{m['fnr']*100:6.1f}%{mark}"
        )
    tbl_path = REPORTS / "model_comparison_table.txt"
    tbl_path.write_text("\n".join(table_lines))
    print(f"  Text table:       {tbl_path}")


if __name__ == "__main__":
    main()
