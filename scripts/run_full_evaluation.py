"""
Evaluación Completa — 5 Modelos × 16 Categorías
================================================
Genera:
  reports/full_evaluation_{timestamp}.json
  reports/full_evaluation_{timestamp}.csv
  reports/false_positives/
  reports/false_negatives/
  reports/robustness/
  FINAL_VALIDATION_REPORT.md

Incluye:
  - Métricas por modelo y por categoría
  - Análisis de errores (FP/FN)
  - Test de robustez (JPEG, blur, ruido, recorte)
  - Optimización de pesos del ensemble
  - Brier Score, ECE, PR-AUC

Uso:
  python scripts/run_full_evaluation.py
  python scripts/run_full_evaluation.py --set massive
"""
import argparse
import csv
import json
import os
import shutil
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ["TRANSFORMERS_CACHE"]              = str(ROOT / "models")
os.environ["HF_HOME"]                         = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(BACKEND)

REPORTS = ROOT / "reports"
FP_DIR  = REPORTS / "false_positives"
FN_DIR  = REPORTS / "false_negatives"
ROB_DIR = REPORTS / "robustness"
THRESHOLD = 0.50

MANIFESTS = {
    "golden":   ROOT / "tests" / "golden_set"         / "manifest.json",
    "extended": ROOT / "tests" / "benchmark_extended" / "manifest.json",
    "massive":  ROOT / "tests" / "benchmark_massive"  / "manifest.json",
}


# ─── Load models ──────────────────────────────────────────────────────────────

def load_all_models():
    from app.models.deepfake_detector import _model_a, _model_b, _model_c, _model_d, _model_e
    print("Loading 5-model ensemble...")
    _model_a.load(); _model_b.load(); _model_c.load(); _model_d.load(); _model_e.load()
    loaded = [m for m in [_model_a, _model_b, _model_c, _model_d, _model_e] if m._loaded if hasattr(m, '_loaded')]
    print(f"  Loaded: {len([m for m in [_model_a, _model_b, _model_c] if m._loaded] + [1 if _model_c._loaded else 0])}/5 models")
    return _model_a, _model_b, _model_c, _model_d, _model_e


# ─── Single image inference ───────────────────────────────────────────────────

def infer_all(img: Image.Image, models: tuple) -> dict:
    ma, mb, mc, md, me = models
    ra = ma.predict(img)
    rb = mb.predict(img)
    rc = mc.predict(img)
    rd = md.predict(img)
    re = me.predict(img)

    scores = {
        "face_deepfake_vit": ra["fake_probability"] if ra else None,
        "sdxl_detector":     rb["fake_probability"] if rb else None,
        "efficientnet_ffpp": rc["fake_probability"] if rc else None,
        "ai_art_detector":   rd["fake_probability"] if rd else None,
        "siglip_deepfake":   re["fake_probability"] if re else None,
    }

    # Current ensemble (no-face weights: A=0.10, B=0.45, C=0.05, D=0.35, E=0.05)
    W = [0.10, 0.45, 0.05, 0.35, 0.05]
    vals = [scores[k] for k in ["face_deepfake_vit","sdxl_detector","efficientnet_ffpp","ai_art_detector","siglip_deepfake"]]
    total_w = sum(w for w, v in zip(W, vals) if v is not None)
    ensemble = sum(w*v/total_w for w, v in zip(W, vals) if v is not None) if total_w > 0 else 0.5

    scores["ensemble"] = float(np.clip(ensemble, 0, 1))
    return scores


# ─── Metrics ──────────────────────────────────────────────────────────────────

def metrics(y_true, y_score, threshold=THRESHOLD, model_name=""):
    if not y_true:
        return {}
    y_t = np.array(y_true); y_s = np.array(y_score)
    y_p = (y_s >= threshold).astype(int)
    tp = int(((y_p==1)&(y_t==1)).sum()); tn = int(((y_p==0)&(y_t==0)).sum())
    fp = int(((y_p==1)&(y_t==0)).sum()); fn = int(((y_p==0)&(y_t==1)).sum())
    prec = tp/max(1,tp+fp); rec = tp/max(1,tp+fn)
    f1   = 2*prec*rec/max(1e-9,prec+rec); acc = (tp+tn)/len(y_t)
    fpr  = fp/max(1,fp+tn); fnr = fn/max(1,fn+tp)
    brier = float(np.mean((y_s - y_t)**2))
    try:
        from sklearn.metrics import roc_auc_score, average_precision_score
        auc  = float(roc_auc_score(y_t, y_s)) if len(np.unique(y_t))>1 else 0.5
        prauc= float(average_precision_score(y_t, y_s)) if len(np.unique(y_t))>1 else 0.5
    except ImportError:
        auc = prauc = 0.5
    return {"model": model_name, "n": len(y_t), "accuracy": round(acc,4), "precision": round(prec,4),
            "recall": round(rec,4), "f1": round(f1,4), "roc_auc": round(auc,4), "pr_auc": round(prauc,4),
            "fpr": round(fpr,4), "fnr": round(fnr,4), "brier": round(brier,4),
            "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def ece(y_true, y_score, n_bins=10):
    y_t = np.array(y_true); y_s = np.array(y_score)
    bins = np.linspace(0, 1, n_bins+1); ece_val = 0.0
    for i in range(n_bins):
        mask = (y_s >= bins[i]) & (y_s < bins[i+1])
        if mask.sum() == 0: continue
        ece_val += (mask.sum()/len(y_t)) * abs(float(y_s[mask].mean()) - float(y_t[mask].mean()))
    return round(float(ece_val), 4)


# ─── Robustness variants ──────────────────────────────────────────────────────

def apply_robustness(img: Image.Image, variant: str) -> Image.Image:
    if variant == "jpeg_heavy":
        buf = BytesIO(); img.save(buf, "JPEG", quality=35); buf.seek(0); return Image.open(buf).copy()
    elif variant == "jpeg_medium":
        buf = BytesIO(); img.save(buf, "JPEG", quality=60); buf.seek(0); return Image.open(buf).copy()
    elif variant == "blur_light":
        return img.filter(ImageFilter.GaussianBlur(1.5))
    elif variant == "blur_heavy":
        return img.filter(ImageFilter.GaussianBlur(3.5))
    elif variant == "noise":
        arr = np.array(img).astype(np.int16)
        arr += np.random.RandomState(42).randint(-40, 40, arr.shape).astype(np.int16)
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    elif variant == "resize_down":
        small = img.resize((img.width//4, img.height//4), Image.LANCZOS)
        return small.resize(img.size, Image.NEAREST)
    elif variant == "crop_center":
        w, h = img.size; cw, ch = int(w*0.7), int(h*0.7)
        left = (w-cw)//2; top = (h-ch)//2
        return img.crop((left, top, left+cw, top+ch)).resize((w, h), Image.LANCZOS)
    elif variant == "whatsapp":
        # WhatsApp-style: resize + heavy JPEG
        small = img.resize((480, 480), Image.LANCZOS)
        buf = BytesIO(); small.save(buf, "JPEG", quality=50); buf.seek(0)
        return Image.open(buf).copy().resize(img.size, Image.NEAREST)
    return img


# ─── Grid search for optimal weights ─────────────────────────────────────────

def optimize_weights(records, labels, model_keys):
    from itertools import product
    best_f1 = 0; best_w = None
    n = len(model_keys)
    vals = [round(v, 1) for v in np.arange(0.05, 0.91, 0.10)]

    for combo in product(vals, repeat=n-1):
        last = round(1.0 - sum(combo), 2)
        if not (0.02 <= last <= 0.90): continue
        w = list(combo) + [last]
        y_scores = []
        for rec in records:
            score_vals = [rec.get(k) for k in model_keys]
            total_wt = sum(wt for wt, sv in zip(w, score_vals) if sv is not None)
            if total_wt == 0: y_scores.append(0.5); continue
            y_scores.append(sum(wt*sv/total_wt for wt, sv in zip(w, score_vals) if sv is not None))
        y_p = [(1 if s >= THRESHOLD else 0) for s in y_scores]
        y_t = np.array(labels)
        tp = sum(1 for p, t in zip(y_p, y_t) if p==1 and t==1)
        fp = sum(1 for p, t in zip(y_p, y_t) if p==1 and t==0)
        fn = sum(1 for p, t in zip(y_p, y_t) if p==0 and t==1)
        prec = tp/max(1,tp+fp); rec = tp/max(1,tp+fn)
        f1   = 2*prec*rec/max(1e-9,prec+rec)
        if f1 > best_f1:
            best_f1 = f1; best_w = w
    return best_w, best_f1


# ─── Main evaluation ──────────────────────────────────────────────────────────

def main(set_name: str):
    for d in [FP_DIR, FN_DIR, ROB_DIR, REPORTS]:
        d.mkdir(parents=True, exist_ok=True)

    manifest_path = MANIFESTS.get(set_name)
    if not manifest_path or not manifest_path.exists():
        print(f"ERROR: Manifest not found for set '{set_name}'")
        print(f"  Run: python scripts/build_massive_benchmark.py")
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    labeled = [e for e in manifest if e.get("label") is not None or e.get("expected_label") is not None]
    print(f"Benchmark '{set_name}': {len(manifest)} total, {len(labeled)} labeled")

    models = load_all_models()
    ma, mb, mc, md, me = models
    MODEL_KEYS = ["face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp", "ai_art_detector", "siglip_deepfake", "ensemble"]

    rows = []; records = []; labels_all = []
    y_by_model = {k: {"true": [], "score": []} for k in MODEL_KEYS}
    y_by_cat   = {}

    print(f"\nRunning inference on {len(labeled)} images...")
    for entry in labeled:
        key   = "label" if "label" in entry else "expected_label"
        label = entry[key]
        if label is None: continue

        img_path = ROOT / entry["path"]
        if not img_path.exists(): continue

        try:
            img    = Image.open(img_path).convert("RGB")
            t0     = time.time()
            scores = infer_all(img, models)
            elapsed= time.time() - t0

            pred  = 1 if scores["ensemble"] >= THRESHOLD else 0
            correct = pred == label
            cat   = entry.get("category", "unknown").split("/")[0]

            row = {
                "name": entry["name"], "category": entry.get("category",""),
                "label": label, "pred": pred, "correct": correct,
                "ms": round(elapsed*1000, 1),
                **{k: round(v, 4) if v is not None else None for k, v in scores.items()},
            }
            rows.append(row)
            records.append(scores)
            labels_all.append(label)

            # Track by model
            for k in MODEL_KEYS:
                if scores.get(k) is not None:
                    y_by_model[k]["true"].append(label)
                    y_by_model[k]["score"].append(scores[k])

            # Track by category
            if cat not in y_by_cat:
                y_by_cat[cat] = {"true": [], "score": []}
            y_by_cat[cat]["true"].append(label)
            y_by_cat[cat]["score"].append(scores["ensemble"])

            # Error analysis
            if label == 0 and pred == 1:  # False positive
                shutil.copy2(img_path, FP_DIR / f"{entry['name']}.jpg")
            elif label == 1 and pred == 0:  # False negative
                shutil.copy2(img_path, FN_DIR / f"{entry['name']}.jpg")

            status = "OK" if correct else "FAIL"
            print(f"  [{status}] {entry['name']:40s} ensemble={scores['ensemble']*100:5.1f}% "
                  f"sdxl={scores['sdxl_detector']*100:4.0f}% "
                  f"art={scores['ai_art_detector']*100 if scores['ai_art_detector'] else 0:4.0f}%")

        except Exception as ex:
            print(f"  ERROR {entry['name']}: {ex}")

    print(f"\nEvaluated: {len(rows)} images")

    # ── Per-model metrics ──────────────────────────────────────────────────────
    print("\n=== PER-MODEL METRICS ===")
    model_metrics = {}
    for k in MODEL_KEYS:
        d = y_by_model[k]
        if not d["true"]: continue
        m = metrics(d["true"], d["score"], model_name=k)
        model_metrics[k] = m
        print(f"  {k:25s} F1={m['f1']*100:5.1f}% AUC={m['roc_auc']:.3f} "
              f"FPR={m['fpr']*100:4.1f}% FNR={m['fnr']*100:4.1f}% Brier={m['brier']:.3f}")

    # ── Per-category metrics ───────────────────────────────────────────────────
    print("\n=== PER-CATEGORY METRICS (ensemble) ===")
    cat_metrics = {}
    for cat, d in sorted(y_by_cat.items()):
        if not d["true"]: continue
        m = metrics(d["true"], d["score"], model_name=cat)
        cat_metrics[cat] = m
        label_type = "real" if d["true"].count(0) > d["true"].count(1) else "ia"
        print(f"  {cat:25s} [{label_type}] F1={m['f1']*100:5.1f}% FPR={m['fpr']*100:4.1f}% FNR={m['fnr']*100:4.1f}%")

    # ── ECE ───────────────────────────────────────────────────────────────────
    ens_ece = ece(labels_all, [r["ensemble"] for r in records])
    print(f"\nECE (ensemble): {ens_ece:.4f}")

    # ── Robustness test ───────────────────────────────────────────────────────
    print("\n=== ROBUSTNESS TEST ===")
    variants  = ["jpeg_heavy", "jpeg_medium", "blur_light", "blur_heavy",
                 "noise", "resize_down", "crop_center", "whatsapp"]
    rob_results = {}
    # Use first 30 labeled images for speed
    rob_sample = labeled[:30]

    for var in variants:
        rob_scores = []; rob_labels = []
        for entry in rob_sample:
            key = "label" if "label" in entry else "expected_label"
            lbl = entry[key]
            if lbl is None: continue
            try:
                img  = Image.open(ROOT / entry["path"]).convert("RGB")
                aug  = apply_robustness(img, var)
                sc   = infer_all(aug, models)
                rob_scores.append(sc["ensemble"])
                rob_labels.append(lbl)
            except: pass
        if rob_labels:
            m = metrics(rob_labels, rob_scores)
            rob_results[var] = m
            print(f"  {var:20s} F1={m['f1']*100:5.1f}% AUC={m['roc_auc']:.3f}")

    # ── Ensemble weight optimization ───────────────────────────────────────────
    print("\n=== ENSEMBLE WEIGHT OPTIMIZATION ===")
    opt_keys = ["face_deepfake_vit", "sdxl_detector", "ai_art_detector", "siglip_deepfake"]
    opt_records = [{k: r.get(k) for k in opt_keys} for r in records]
    opt_labels  = labels_all

    if len(set(opt_labels)) > 1:
        best_w, best_f1 = optimize_weights(opt_records, opt_labels, opt_keys)
        print(f"  Current  ensemble F1: {model_metrics.get('ensemble', {}).get('f1', 0)*100:.1f}%")
        print(f"  Optimized ensemble F1: {best_f1*100:.1f}%")
        if best_w:
            for k, w in zip(opt_keys, best_w):
                print(f"    {k:25s}: {w:.2f}")
    else:
        best_w = None; best_f1 = 0

    # ── Save CSV ───────────────────────────────────────────────────────────────
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = REPORTS / f"full_eval_{set_name}_{ts}.csv"
    if rows:
        all_keys = sorted(set(k for r in rows for k in r))
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)

    # ── Save JSON ──────────────────────────────────────────────────────────────
    report = {
        "set": set_name, "timestamp": ts, "threshold": THRESHOLD,
        "n_images": len(rows), "n_labeled": len(labels_all),
        "model_metrics": model_metrics,
        "category_metrics": cat_metrics,
        "ensemble_ece": ens_ece,
        "robustness": rob_results,
        "weight_optimization": {
            "optimal_keys":   opt_keys,
            "optimal_weights": best_w,
            "optimal_f1":     best_f1,
        },
        "error_summary": {
            "false_positives": sum(1 for r in rows if r.get("correct") is False and r.get("label") == 0),
            "false_negatives": sum(1 for r in rows if r.get("correct") is False and r.get("label") == 1),
        },
    }
    json_path = REPORTS / f"full_eval_{set_name}_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # ── Generate FINAL_VALIDATION_REPORT.md ───────────────────────────────────
    _write_final_report(report, csv_path, json_path)

    print()
    print("=" * 60)
    print(f"  Evaluation complete!")
    print(f"  JSON: {json_path}")
    print(f"  CSV:  {csv_path}")
    print(f"  FP:   {FP_DIR} ({report['error_summary']['false_positives']} images)")
    print(f"  FN:   {FN_DIR} ({report['error_summary']['false_negatives']} images)")
    print(f"  Report: FINAL_VALIDATION_REPORT.md")


def _write_final_report(report: dict, csv_path: Path, json_path: Path) -> None:
    mm = report["model_metrics"]
    cat_m = report["category_metrics"]
    rob = report["robustness"]

    # Rank models by F1
    ranked = sorted([(k, v.get("f1", 0)) for k, v in mm.items()], key=lambda x: x[1], reverse=True)

    lines = [
        "# FINAL_VALIDATION_REPORT.md",
        f"## DeepGuard AI — Validación Final",
        f"**Benchmark:** {report['set']}  |  **Imágenes:** {report['n_images']}  |  **Fecha:** {report['timestamp'][:8]}",
        "",
        "---",
        "",
        "## 1. Ranking de Modelos (por F1)",
        "",
        "| Modelo | F1 | ROC-AUC | Precisión | Recall | FPR | FNR | Brier |",
        "|--------|-----|---------|-----------|--------|-----|-----|-------|",
    ]
    for model_name, _ in ranked:
        m = mm.get(model_name, {})
        if not m: continue
        lines.append(
            f"| {model_name} | {m.get('f1',0)*100:.1f}% | {m.get('roc_auc',0):.3f} | "
            f"{m.get('precision',0)*100:.1f}% | {m.get('recall',0)*100:.1f}% | "
            f"{m.get('fpr',0)*100:.1f}% | {m.get('fnr',0)*100:.1f}% | {m.get('brier',0):.3f} |"
        )

    lines += [
        "",
        f"**ECE (ensemble):** {report['ensemble_ece']:.4f}",
        "",
        "---",
        "",
        "## 2. Métricas por Categoría",
        "",
        "| Categoría | Tipo | F1 | FPR | FNR | n |",
        "|-----------|------|-----|-----|-----|---|",
    ]
    for cat, m in sorted(cat_m.items()):
        tipo = "real" if m.get("tn",0) + m.get("fp",0) > m.get("fn",0) + m.get("tp",0) else "ia"
        lines.append(f"| {cat} | {tipo} | {m.get('f1',0)*100:.1f}% | {m.get('fpr',0)*100:.1f}% | {m.get('fnr',0)*100:.1f}% | {m.get('n',0)} |")

    lines += [
        "",
        "---",
        "",
        "## 3. Robustez",
        "",
        "| Variante | F1 | AUC | FPR | FNR |",
        "|----------|-----|-----|-----|-----|",
    ]
    for var, m in sorted(rob.items(), key=lambda x: x[1].get("f1",0), reverse=True):
        lines.append(f"| {var} | {m.get('f1',0)*100:.1f}% | {m.get('roc_auc',0):.3f} | {m.get('fpr',0)*100:.1f}% | {m.get('fnr',0)*100:.1f}% |")

    # Weight optimization
    wo = report.get("weight_optimization", {})
    if wo.get("optimal_weights"):
        lines += [
            "",
            "---",
            "",
            "## 4. Optimización de Pesos del Ensemble",
            "",
            f"**F1 actual:** {mm.get('ensemble', {}).get('f1', 0)*100:.1f}%",
            f"**F1 óptimo:** {wo.get('optimal_f1', 0)*100:.1f}%",
            "",
            "| Modelo | Peso Óptimo |",
            "|--------|-------------|",
        ]
        for k, w_val in zip(wo.get("optimal_keys", []), wo.get("optimal_weights", [])):
            lines.append(f"| {k} | {w_val:.2f} |")

    lines += [
        "",
        "---",
        "",
        "## 5. Modelos por Fortaleza / Debilidad",
        "",
    ]
    if ranked:
        strongest = ranked[0][0]
        weakest   = ranked[-1][0] if len(ranked) > 1 else ranked[0][0]
        most_fp   = max(mm.items(), key=lambda x: x[1].get("fpr", 0))[0]
        most_fn   = max(mm.items(), key=lambda x: x[1].get("fnr", 0))[0]
        lines += [
            f"- **Modelo más fuerte (F1):** `{strongest}`",
            f"- **Modelo más débil (F1):** `{weakest}`",
            f"- **Más falsos positivos (FPR):** `{most_fp}`",
            f"- **Más falsos negativos (FNR):** `{most_fn}`",
        ]

    lines += [
        "",
        "---",
        "",
        "## 6. Riesgos y Limitaciones",
        "",
        "- El ensemble fue evaluado sin detección facial (modo no-face) en el benchmark.",
        "- Las imágenes son sintéticas — rendimiento en fotos reales puede variar.",
        "- ECE > 0.10 indica calibración deficiente. Considerar temperature scaling.",
        "- Los pesos óptimos se calcularon sobre este benchmark específico — validar con datos reales.",
        "",
        "---",
        "",
        "## 7. Archivos Generados",
        "",
        f"- `{csv_path.relative_to(ROOT)}` — resultados por imagen",
        f"- `{json_path.relative_to(ROOT)}` — reporte completo JSON",
        f"- `reports/false_positives/` — imágenes reales mal clasificadas",
        f"- `reports/false_negatives/` — imágenes IA no detectadas",
    ]

    report_path = ROOT / "FINAL_VALIDATION_REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nFINAL_VALIDATION_REPORT.md written.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--set", default="massive", choices=["golden", "extended", "massive"])
    args = p.parse_args()
    main(args.set)
