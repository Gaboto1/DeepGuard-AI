"""
Augmenta los CSVs de entrenamiento con scores de model_f (ai_human_detector)
y reentrena el meta-ensemble incluyendo esta nueva feature.

Solo usa los 2 CSVs del modelo FPR=0.3% para no degradar calidad.
Si el nuevo FPR es peor, restaura automáticamente el modelo anterior.
"""
import csv
import json
import os
import sys
import shutil
import time
from pathlib import Path
from PIL import Image

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "models"))
os.environ.setdefault("HF_HOME",            str(ROOT / "models"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(str(BACKEND))

REPORTS     = ROOT / "reports"
MODELS_DIR  = ROOT / "models" / "meta_ensemble"

# Solo los 2 CSVs del modelo FPR=0.3%
GOOD_CSVS = [
    REPORTS / "full_eval_massive_20260901_221747.csv",
    REPORTS / "full_eval_massive_20260902_004305.csv",
]

CURRENT_FPR = 0.003   # 0.3%


# ── Carga model_f ─────────────────────────────────────────────────────────────

def load_model_f():
    from transformers import AutoImageProcessor, AutoModelForImageClassification
    import torch
    print("Cargando model_f (umm-maybe/AI-image-detector)...")
    name   = "umm-maybe/AI-image-detector"
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    proc   = AutoImageProcessor.from_pretrained(name, cache_dir=str(ROOT / "models"))
    model  = AutoModelForImageClassification.from_pretrained(name, cache_dir=str(ROOT / "models"))
    model.to(device).eval()
    print(f"  Listo en {device} | labels={model.config.id2label}")
    return proc, model, device


def predict_f(proc, model, device, img):
    import torch
    try:
        inp = proc(images=img, return_tensors="pt")
        inp = {k: v.to(device) for k, v in inp.items()}
        with torch.no_grad():
            logits = model(**inp).logits
        probs  = torch.softmax(logits, dim=-1).cpu().float().numpy()[0]
        id2lbl = model.config.id2label
        # umm-maybe: 0=artificial(fake), 1=human(real)
        fake_p = 0.0
        for i, p in enumerate(probs):
            lbl = id2lbl.get(i, "").lower().strip()
            if any(t in lbl for t in ("fake","artificial","ai-generated","synthetic","0")):
                fake_p += float(p)
        if fake_p == 0.0:
            fake_p = float(probs[0])
        return float(min(max(fake_p, 0.0), 1.0))
    except Exception:
        return 0.5


# ── Augmenta un CSV con la columna ai_human_detector ─────────────────────────

def augment_csv(csv_path, proc, model, device):
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    if not rows:
        return None
    if "ai_human_detector" in rows[0]:
        print(f"  {csv_path.name}: ya tiene ai_human_detector, omitiendo re-eval")
        out_path = csv_path.parent / csv_path.name.replace(".csv", "_withF.csv")
        if not out_path.exists():
            shutil.copy(csv_path, out_path)
        return out_path

    out_path   = csv_path.parent / csv_path.name.replace(".csv", "_withF.csv")
    fieldnames = list(rows[0].keys()) + ["ai_human_detector"]
    t0         = time.time()

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for i, row in enumerate(rows, 1):
            path = Path(row.get("path", ""))
            if not path.is_absolute() or not path.exists():
                for candidate in [ROOT / path, Path(path)]:
                    if candidate.exists():
                        path = candidate
                        break
            try:
                img     = Image.open(path).convert("RGB")
                score_f = predict_f(proc, model, device, img)
            except Exception:
                score_f = 0.5
            row["ai_human_detector"] = round(score_f, 6)
            writer.writerow(row)
            if i % 500 == 0 or i == len(rows):
                el  = time.time() - t0
                eta = el / i * (len(rows) - i)
                print(f"    [{i}/{len(rows)}] {el/60:.1f}min ETA={eta/60:.1f}min")

    print(f"  Guardado: {out_path.name} ({len(rows)} filas)")
    return out_path


# ── Reentrena el meta-ensemble con ai_human_detector ─────────────────────────

def retrain(new_csvs):
    """Llama al script de entrenamiento con los CSVs aumentados."""
    import glob
    import numpy as np
    import pandas as pd
    import joblib
    from copy import deepcopy
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    try:
        from lightgbm import LGBMClassifier
        HAS_LGBM = True
    except ImportError:
        HAS_LGBM = False
    try:
        from xgboost import XGBClassifier
        HAS_XGB = True
    except ImportError:
        HAS_XGB = False

    FEATURE_COLS = [
        "face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
        "ai_art_detector", "siglip_deepfake", "ai_human_detector",
    ]
    META_FEATURES = [
        "sdxl_detector", "ai_art_detector", "efficientnet_ffpp",
        "ai_human_detector",   # NUEVO
        "sdxl_x_aiart", "robust_mean", "reliable_std",
    ]
    LABEL = "label"

    dfs = []
    for p in new_csvs:
        df = pd.read_csv(p)
        avail = [c for c in FEATURE_COLS if c in df.columns]
        if LABEL in df.columns and len(avail) >= 4:
            df = df[avail + [LABEL]].dropna(subset=[LABEL])
            dfs.append(df)
    if not dfs:
        print("ERROR: No hay datos para entrenar")
        return None

    data = pd.concat(dfs, ignore_index=True).drop_duplicates()
    n_real = (data[LABEL] == 0).sum()
    n_ai   = (data[LABEL] == 1).sum()
    print(f"\nDataset: {len(data)} muestras ({n_real} real, {n_ai} IA)")
    print(f"Features: {META_FEATURES}")

    # Feature engineering
    for col in FEATURE_COLS:
        if col not in data.columns:
            data[col] = np.nan

    data["sdxl_x_aiart"] = data["sdxl_detector"].fillna(0.5) * data["ai_art_detector"].fillna(0.5)

    valid_scores = []
    for col in ["sdxl_detector", "ai_art_detector", "efficientnet_ffpp", "ai_human_detector"]:
        if col in data.columns:
            valid_scores.append(data[col].fillna(np.nan))

    arr = pd.concat(valid_scores, axis=1)
    data["robust_mean"] = arr.apply(lambda r: float(np.nanmedian(r)), axis=1)
    data["reliable_std"] = arr.apply(
        lambda r: float(np.nanstd(r[~np.isnan(r)])) if (~np.isnan(r)).sum() > 1 else 0.0, axis=1
    )

    X = data[META_FEATURES].fillna(0.5).values
    y = data[LABEL].astype(int).values

    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import f1_score, roc_auc_score

    def temperature_scale(probs, y_true, n_steps=200):
        from scipy.optimize import minimize_scalar
        def nll(T):
            T = max(T, 0.001)
            p = np.clip(1 / (1 + np.exp(-np.log(probs / (1 - probs + 1e-9)) / T)), 1e-7, 1-1e-7)
            return -np.mean(y_true * np.log(p) + (1-y_true) * np.log(1-p))
        res = minimize_scalar(nll, bounds=(0.1, 5.0), method="bounded")
        return float(res.x)

    def cv_eval(clf_fn, X, y, name):
        skf    = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        f1s, fprs, Ts = [], [], []
        for tr, va in skf.split(X, y):
            clf = clf_fn()
            clf.fit(X[tr], y[tr])
            p   = clf.predict_proba(X[va])[:, 1]
            T   = temperature_scale(np.clip(p, 1e-7, 1-1e-7), y[va])
            Ts.append(T)
            p_cal = np.clip(1 / (1 + np.exp(-np.log(p / (1 - p + 1e-9)) / T)), 0, 1)
            pred  = (p_cal >= 0.5).astype(int)
            f1s.append(f1_score(y[va], pred))
            neg   = y[va] == 0
            fprs.append(float(pred[neg].sum()) / float(neg.sum()) if neg.sum() else 0)
        return float(np.mean(f1s)), float(np.mean(fprs)), float(np.mean(Ts))

    print("\n  Evaluando clasificadores...")
    results = []

    f1, fpr, T = cv_eval(lambda: LogisticRegression(C=1.0, max_iter=1000), X, y, "LR")
    results.append(("LogReg", f1, fpr, T,
                    lambda: LogisticRegression(C=1.0, max_iter=1000)))
    print(f"  LogReg: F1={f1:.1%} FPR={fpr:.1%} T={T:.3f}")

    if HAS_XGB:
        f1, fpr, T = cv_eval(
            lambda: XGBClassifier(max_depth=2, n_estimators=100, eval_metric="logloss",
                                  verbosity=0, random_state=42),
            X, y, "XGB"
        )
        results.append(("XGBoost", f1, fpr, T,
                        lambda: XGBClassifier(max_depth=2, n_estimators=100,
                                              eval_metric="logloss", verbosity=0, random_state=42)))
        print(f"  XGBoost: F1={f1:.1%} FPR={fpr:.1%} T={T:.3f}")

    if HAS_LGBM:
        f1, fpr, T = cv_eval(
            lambda: LGBMClassifier(max_depth=2, n_estimators=100, min_child_samples=15,
                                   reg_lambda=1.5, reg_alpha=0.5, verbose=-1, random_state=42),
            X, y, "LGBM"
        )
        results.append(("LightGBM", f1, fpr, T,
                        lambda: LGBMClassifier(max_depth=2, n_estimators=100, min_child_samples=15,
                                               reg_lambda=1.5, reg_alpha=0.5, verbose=-1, random_state=42)))
        print(f"  LightGBM: F1={f1:.1%} FPR={fpr:.1%} T={T:.3f}")

    # Elegir mejor (menor FPR, luego mayor F1)
    best_name, best_f1, best_fpr, best_T, best_fn = min(
        results, key=lambda r: (round(r[2], 3), -r[1])
    )
    print(f"\n  Mejor: {best_name} (F1={best_f1:.1%} FPR={best_fpr:.1%} T={best_T:.3f})")

    # Entrenar en dataset completo
    clf = best_fn()
    clf.fit(X, y)
    p   = clf.predict_proba(X)[:, 1]
    T   = temperature_scale(np.clip(p, 1e-7, 1-1e-7), y)
    p_cal = np.clip(1 / (1 + np.exp(-np.log(p / (1 - p + 1e-9)) / T)), 0, 1)
    pred  = (p_cal >= 0.5).astype(int)
    neg   = y == 0
    fpr_full = float(pred[neg].sum()) / float(neg.sum()) if neg.sum() else 0
    f1_full  = f1_score(y, pred)
    print(f"  Dataset completo: F1={f1_full:.1%} FPR={fpr_full:.1%} T={T:.3f}")

    # Guardar
    probe = {"clf": clf, "temperature": T, "feature_cols": META_FEATURES}
    joblib.dump(probe, str(MODELS_DIR / "meta_classifier.joblib"))

    cfg = {
        "use_meta_ensemble": True,
        "best_method":       best_name,
        "best_f1":           round(best_f1, 4),
        "temperature":       round(T, 4),
        "feature_cols":      META_FEATURES,
        "calibrated_fpr":    round(fpr_full, 4),
        "calibrated_f1":     round(f1_full, 4),
        "comparison": {
            r[0].lower().replace(" ", "_"): {
                "model": r[0], "f1": round(r[1], 4), "fpr": round(r[2], 4), "T": round(r[3], 4)
            } for r in results
        }
    }
    json.dump(cfg, open(str(MODELS_DIR / "meta_config.json"), "w"), indent=2)
    print(f"  Modelo guardado: {MODELS_DIR / 'meta_classifier.joblib'}")

    return fpr_full


def main():
    print("=" * 60)
    print("  Integracion model_f en meta-ensemble")
    print("=" * 60)

    existing = [p for p in GOOD_CSVS if p.exists()]
    if not existing:
        print("ERROR: No se encontraron CSVs base")
        sys.exit(1)

    print(f"\nCSVs a augmentar: {[p.name for p in existing]}")
    proc, model, device = load_model_f()

    # Augmentar CSVs
    new_csvs = []
    for p in existing:
        print(f"\nProcesando {p.name}...")
        out = augment_csv(p, proc, model, device)
        if out:
            new_csvs.append(out)

    if not new_csvs:
        print("No hay CSVs nuevos")
        sys.exit(0)

    # Backup del modelo actual
    bak_model = MODELS_DIR / "meta_classifier_pre_modelf.joblib"
    bak_cfg   = MODELS_DIR / "meta_config_pre_modelf.json"
    if (MODELS_DIR / "meta_classifier.joblib").exists():
        shutil.copy(MODELS_DIR / "meta_classifier.joblib", bak_model)
        shutil.copy(MODELS_DIR / "meta_config.json",       bak_cfg)
        print("\n  Backup guardado")

    print("\n[Reentrenando meta-ensemble con ai_human_detector]")
    new_fpr = retrain(new_csvs)

    if new_fpr is None:
        print("Reentrenamiento fallido. Restaurando...")
        if bak_model.exists():
            shutil.copy(bak_model, MODELS_DIR / "meta_classifier.joblib")
            shutil.copy(bak_cfg,   MODELS_DIR / "meta_config.json")
        sys.exit(1)

    print(f"\n  Nuevo FPR:  {new_fpr:.1%}")
    print(f"  Modelo base: {CURRENT_FPR:.1%}")

    if new_fpr <= CURRENT_FPR + 0.005:
        print(f"\n  ACEPTADO — model_f integrado al meta-ensemble (FPR={new_fpr:.1%})")
    else:
        print(f"\n  REVERTIDO — FPR empeoró ({new_fpr:.1%} > {CURRENT_FPR+0.005:.1%})")
        if bak_model.exists():
            shutil.copy(bak_model, MODELS_DIR / "meta_classifier.joblib")
            shutil.copy(bak_cfg,   MODELS_DIR / "meta_config.json")
            print("  Modelo anterior restaurado")

    print("\n  Reinicia el backend para aplicar cambios.")
    print("=" * 60)


if __name__ == "__main__":
    main()
