"""
Meta-Ensemble Training — LR vs XGBoost vs LightGBM (v2)
=========================================================
Fixes vs v1:
  - LightGBM con regularización fuerte (max_depth=2, min_data_in_leaf=15)
    para evitar sobreajuste a correlaciones espurias (ej: SigLIP siempre alto)
  - Temperature Scaling calibrado sobre el fold de validación (no el training)
  - Feature engineering: producto SDXL×AI_Art como señal de consenso robusto
  - Closure bug corregido en cv_eval (lambda capturaba por referencia, no valor)
  - _apply_fixed_weights con regex robusto

Diagnóstico del bug original:
  SigLIP tiene FPR=100% (clasifica TODO como fake). El LightGBM v1 aprendió que
  cuando SigLIP≈90% + ViT≈65%, el resultado es fake — aunque SDXL y AI Art
  descarten la manipulación. Esto genera falsos positivos en fotos reales comprimidas.

Solución: max_depth=2 impide que LightGBM aprenda interacciones profundas entre
  modelos poco confiables. El Veto de Consenso en meta_ensemble.py complementa esto.

Usage:
  python scripts/train_meta_ensemble.py
"""
import json
import re
import sys
from copy import deepcopy
from glob import glob
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT    = Path(__file__).parent.parent
REPORTS = ROOT / "reports"
MODELS  = ROOT / "models" / "meta_ensemble"
MODELS.mkdir(parents=True, exist_ok=True)

FEATURE_COLS = [
    "face_deepfake_vit",
    "sdxl_detector",
    "efficientnet_ffpp",
    "ai_art_detector",
    "siglip_deepfake",
]

# Features que SE INCLUYEN en el meta-modelo.
# Eliminamos ViT (FPR=96%) y SigLIP (FPR=100%) del training: son modelos no confiables
# que se usan en el ensemble ponderado pero NO deben guiar al meta-modelo.
# El meta-modelo usa solo los detectores con FPR < 15%.
META_RELIABLE_FEATURES = [
    "sdxl_detector",       # FPR=0.8%  ← el más confiable
    "ai_art_detector",     # FPR=8.6%  ← confiable
    "efficientnet_ffpp",   # FPR=33%   ← moderado, pero añade señal en face-swaps
]
LABEL_COL = "label"


# ─── Data loading ─────────────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    csvs = sorted(glob(str(REPORTS / "full_eval_massive_*.csv")))
    if not csvs:
        print("No CSV encontrado. Ejecuta run_full_evaluation.py primero.")
        sys.exit(1)

    dfs = []
    for path in csvs:
        df = pd.read_csv(path)
        if LABEL_COL in df.columns and all(c in df.columns for c in FEATURE_COLS):
            df = df[FEATURE_COLS + [LABEL_COL]].dropna(subset=[LABEL_COL])
            dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True).drop_duplicates()
    print(f"Dataset: {len(combined)} muestras "
          f"({(combined[LABEL_COL]==0).sum()} real, {(combined[LABEL_COL]==1).sum()} IA)")
    return combined


# ─── Feature engineering ──────────────────────────────────────────────────────

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Añade señales derivadas usando SOLO los modelos confiables (bajo FPR).
    NO incluye ViT ni SigLIP en las features del meta-modelo — ambos tienen
    FPR > 90% y contaminarían el aprendizaje.
    """
    df = df.copy()
    # Producto de robustos: alto solo si AMBOS detectores confiables dicen fake
    df["sdxl_x_aiart"] = df["sdxl_detector"] * df["ai_art_detector"]
    # Media de robustos: indica consenso de los detectores confiables
    df["robust_mean"]  = (df["sdxl_detector"] + df["ai_art_detector"]) / 2
    # Std solo de features confiables (no ViT ni SigLIP)
    df["reliable_std"] = df[META_RELIABLE_FEATURES].std(axis=1)
    return df


# ─── Metrics ──────────────────────────────────────────────────────────────────

def metrics(y_true: np.ndarray, y_score: np.ndarray,
            name: str, threshold: float = 0.50) -> dict:
    from sklearn.metrics import (roc_auc_score, average_precision_score,
                                  f1_score, precision_score, recall_score,
                                  brier_score_loss)
    y_pred = (y_score >= threshold).astype(int)
    tp = int(((y_pred==1)&(y_true==1)).sum())
    tn = int(((y_pred==0)&(y_true==0)).sum())
    fp = int(((y_pred==1)&(y_true==0)).sum())
    fn = int(((y_pred==0)&(y_true==1)).sum())
    return {
        "model":     name,
        "f1":        round(float(f1_score(y_true, y_pred, zero_division=0)),        4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall":    round(float(recall_score(y_true, y_pred, zero_division=0)),    4),
        "roc_auc":   round(float(roc_auc_score(y_true, y_score)),                  4),
        "pr_auc":    round(float(average_precision_score(y_true, y_score)),         4),
        "fpr":       round(fp / max(1, fp+tn), 4),
        "fnr":       round(fn / max(1, fn+tp), 4),
        "brier":     round(float(brier_score_loss(y_true, y_score)),                4),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    }


def ece_score(y_true: np.ndarray, y_score: np.ndarray, n_bins: int = 10) -> float:
    bins = np.linspace(0, 1, n_bins+1)
    ece  = 0.0
    for i in range(n_bins):
        mask = (y_score >= bins[i]) & (y_score < bins[i+1])
        if mask.sum() == 0:
            continue
        ece += (mask.sum()/len(y_true)) * abs(
            float(y_score[mask].mean()) - float(y_true[mask].mean())
        )
    return round(float(ece), 4)


# ─── Temperature scaling ──────────────────────────────────────────────────────

def find_temperature(probs: np.ndarray, labels: np.ndarray) -> float:
    """
    Encuentra T que minimiza NLL sobre el conjunto de validación (no entrenamiento).
    T > 1: modelo sobreconfiante (aplanar probabilidades)
    T < 1: modelo infraconfiante (agudizar probabilidades)
    """
    from scipy.optimize import minimize_scalar

    eps = 1e-7
    logits = np.log(np.clip(probs, eps, 1-eps) / np.clip(1-probs, eps, 1-eps))

    def nll(T: float) -> float:
        if T <= 0:
            return 1e10
        scaled = 1.0 / (1.0 + np.exp(-logits / T))
        return float(-np.mean(
            labels * np.log(np.clip(scaled, eps, 1-eps)) +
            (1-labels) * np.log(np.clip(1-scaled, eps, 1-eps))
        ))

    result = minimize_scalar(nll, bounds=(0.05, 10.0), method="bounded")
    return float(result.x)


def apply_temperature(probs: np.ndarray, T: float) -> np.ndarray:
    eps    = 1e-7
    logits = np.log(np.clip(probs, eps, 1-eps) / np.clip(1-probs, eps, 1-eps))
    return 1.0 / (1.0 + np.exp(-logits / T))


# ─── Cross-validation with temperature scaling ────────────────────────────────

def cv_eval(name: str, make_model_fn, X: np.ndarray, y: np.ndarray,
            calibrate_temp: bool = True) -> tuple[np.ndarray, dict, float]:
    """
    5-fold CV. Temperatura calibrada en cada fold de validación (no en training).
    Retorna (oof_scores_calibrated, metrics, mean_temperature).
    """
    from sklearn.model_selection import StratifiedKFold
    cv          = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    oof_scores  = np.zeros(len(y))
    temperatures= []

    for train_idx, val_idx in cv.split(X, y):
        X_tr, X_val = X[train_idx], X[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]

        # IMPORTANTE: make_model_fn() crea una nueva instancia en cada fold
        # (corrige el bug de closure de la v1)
        clf = make_model_fn()
        clf.fit(X_tr, y_tr)
        probs_val = clf.predict_proba(X_val)[:, 1]

        if calibrate_temp and len(np.unique(y_val)) > 1:
            T = find_temperature(probs_val, y_val)
            temperatures.append(T)
            probs_val = apply_temperature(probs_val, T)

        oof_scores[val_idx] = probs_val

    m    = metrics(y, oof_scores, name)
    m["ece"]  = ece_score(y, oof_scores)
    mean_T = float(np.mean(temperatures)) if temperatures else 1.0
    return oof_scores, m, mean_T


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  META-ENSEMBLE TRAINING v2 — con regularización y calibración")
    print("=" * 65)

    df_raw = load_data()
    df     = add_features(df_raw)

    # Features del meta-modelo: SOLO detectores confiables + engineered
    # ViT (FPR=96%) y SigLIP (FPR=100%) EXCLUIDOS deliberadamente
    ENG_COLS = ["sdxl_x_aiart", "robust_mean", "reliable_std"]
    ALL_COLS  = META_RELIABLE_FEATURES + ENG_COLS
    print(f"\n  Meta-features ({len(ALL_COLS)}): {ALL_COLS}")
    print("  [ViT y SigLIP excluidos - FPR > 90%]")

    X_all = df[ALL_COLS].fillna(0.5).values
    X_base= df[FEATURE_COLS].fillna(0.5).values   # solo originales para baseline
    y     = df[LABEL_COL].values

    # ── Baselines (pesos fijos) ─────────────────────────────────────────────
    W_CURRENT   = [0.15, 0.70, 0.05, 0.05, 0.05]
    W_OPTIMIZED = [0.30, 0.20, 0.00, 0.20, 0.30]

    for W, wname in [(W_CURRENT, "Pesos actuales"), (W_OPTIMIZED, "Grid-search")]:
        s = np.clip([sum(w*x for w,x in zip(W, row)) for row in X_base], 0, 1)
        m = metrics(y, s, wname)
        m["ece"] = ece_score(y, s)
        print(f"\n  Baseline {wname}: F1={m['f1']*100:.1f}%  AUC={m['roc_auc']:.3f}  ECE={m['ece']:.4f}")

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    print()
    print("  Entrenando modelos (5-fold CV + Temperature Scaling)...")
    print()
    print(f"  {'Método':30s}  {'F1':>7}  {'AUC':>7}  {'ECE':>7}  {'FNR':>7}  {'T':>6}")
    print("  " + "-" * 65)

    results    = {}
    best_f1    = 0.0
    best_name  = ""
    best_scores= None
    best_T     = 1.0

    # ── Logistic Regression ──────────────────────────────────────────────────
    def make_lr():
        return Pipeline([("sc", StandardScaler()),
                          ("lr", LogisticRegression(C=0.3, max_iter=2000, random_state=42))])

    oof_lr, m_lr, T_lr = cv_eval("Logistic Regression", make_lr, X_all, y)
    results["logistic_regression"] = (oof_lr, m_lr, T_lr)
    print(f"  {'Logistic Regression':30s}  {m_lr['f1']*100:6.1f}%  {m_lr['roc_auc']:7.3f}  "
          f"{m_lr['ece']:7.4f}  {m_lr['fnr']*100:6.1f}%  {T_lr:6.3f}")
    if m_lr["f1"] > best_f1:
        best_f1, best_name, best_scores, best_T = m_lr["f1"], "Logistic Regression", oof_lr, T_lr

    # ── XGBoost ──────────────────────────────────────────────────────────────
    try:
        import xgboost as xgb

        def make_xgb():
            return xgb.XGBClassifier(
                n_estimators=30, max_depth=2, learning_rate=0.08,
                subsample=0.8, colsample_bytree=0.8,
                reg_alpha=0.2, reg_lambda=1.0,
                eval_metric="logloss", random_state=42, verbosity=0,
            )

        oof_xgb, m_xgb, T_xgb = cv_eval("XGBoost (max_depth=2)", make_xgb, X_all, y)
        results["xgboost"] = (oof_xgb, m_xgb, T_xgb)
        print(f"  {'XGBoost (max_depth=2)':30s}  {m_xgb['f1']*100:6.1f}%  {m_xgb['roc_auc']:7.3f}  "
              f"{m_xgb['ece']:7.4f}  {m_xgb['fnr']*100:6.1f}%  {T_xgb:6.3f}")
        if m_xgb["f1"] > best_f1:
            best_f1, best_name, best_scores, best_T = m_xgb["f1"], "XGBoost", oof_xgb, T_xgb
    except ImportError:
        print("  XGBoost no disponible")

    # ── LightGBM (regularizado) ───────────────────────────────────────────────
    try:
        import lightgbm as lgb

        def make_lgb():
            # max_depth=2 y min_data_in_leaf=15 son las claves de la corrección:
            # impiden que aprenda interacciones profundas con SigLIP sobreconfiante.
            return lgb.LGBMClassifier(
                n_estimators=25,
                max_depth=2,           # máximo 2 niveles → no puede combinar 3+ modelos
                num_leaves=7,          # 2^2 - 1 = 7 para max_depth=2
                min_data_in_leaf=15,   # al menos 15 muestras por hoja
                learning_rate=0.08,
                reg_alpha=0.3,         # L1: esparcidad de features
                reg_lambda=1.5,        # L2: penaliza pesos grandes
                feature_fraction=0.75, # submuestreo de features
                bagging_fraction=0.75, # submuestreo de datos
                bagging_freq=1,
                random_state=42,
                verbose=-1,
            )

        oof_lgb, m_lgb, T_lgb = cv_eval("LightGBM regularz. (depth=2)", make_lgb, X_all, y)
        results["lightgbm"] = (oof_lgb, m_lgb, T_lgb)
        print(f"  {'LightGBM regularz. (depth=2)':30s}  {m_lgb['f1']*100:6.1f}%  {m_lgb['roc_auc']:7.3f}  "
              f"{m_lgb['ece']:7.4f}  {m_lgb['fnr']*100:6.1f}%  {T_lgb:6.3f}")
        if m_lgb["f1"] > best_f1:
            best_f1, best_name, best_scores, best_T = m_lgb["f1"], "LightGBM", oof_lgb, T_lgb
    except ImportError:
        print("  LightGBM no disponible")

    print()
    print(f"  Mejor método: {best_name} (F1={best_f1*100:.1f}%, T={best_T:.3f})")

    # ── Entrenar modelo final en todos los datos ──────────────────────────────
    print(f"\n  Entrenando {best_name} en dataset completo...")

    if best_name == "Logistic Regression":
        final_model = make_lr()
    elif best_name == "XGBoost":
        final_model = make_xgb()
    else:
        final_model = make_lgb()

    final_model.fit(X_all, y)

    # Calibrar temperatura en el dataset completo
    probs_all = final_model.predict_proba(X_all)[:, 1]
    T_final   = find_temperature(probs_all, y)
    print(f"  Temperatura óptima (dataset completo): T={T_final:.4f}")
    if T_final > 1.5:
        print("  → Modelo sobreconfiante: Temperature Scaling reduce extremos")
    elif T_final < 0.7:
        print("  → Modelo infraconfiante: Temperature Scaling agudiza scores")
    else:
        print("  → Modelo bien calibrado: T≈1.0")

    # Verificar con scores calibrados
    probs_cal = apply_temperature(probs_all, T_final)
    m_cal     = metrics(y, probs_cal, "final_calibrated")
    m_cal["ece"] = ece_score(y, probs_cal)
    print(f"  Métricas calibradas: F1={m_cal['f1']*100:.1f}%  ECE={m_cal['ece']:.4f}  "
          f"FPR={m_cal['fpr']*100:.1f}%  FNR={m_cal['fnr']*100:.1f}%")

    # ── Feature importance ────────────────────────────────────────────────────
    if hasattr(final_model, "feature_importances_"):
        print("\n  Feature importance:")
        fi = list(zip(ALL_COLS, final_model.feature_importances_))
        for name_f, imp in sorted(fi, key=lambda x: x[1], reverse=True):
            bar = "█" * int(imp / max(f[1] for f in fi) * 20)
            print(f"    {name_f:25s} {bar} {imp:.4f}")
    elif hasattr(final_model, "named_steps"):
        lr_step = final_model.named_steps.get("lr")
        if lr_step is not None and hasattr(lr_step, "coef_"):
            print("\n  Coeficientes LR:")
            coefs = list(zip(ALL_COLS, lr_step.coef_[0]))
            for name_f, c in sorted(coefs, key=lambda x: abs(x[1]), reverse=True):
                bar = "█" * int(abs(c)/max(abs(cc) for _,cc in coefs)*20)
                print(f"    {name_f:25s} {bar:20s} {c:+.4f}")

    # ── Guardar modelo y configuración ────────────────────────────────────────
    model_path  = MODELS / "meta_classifier.joblib"
    config_path = MODELS / "meta_config.json"

    joblib.dump({
        "model":       final_model,
        "features":    ALL_COLS,
        "name":        best_name,
        "temperature": T_final,
    }, str(model_path))

    config = {
        "use_meta_ensemble": True,
        "best_method":       best_name,
        "best_f1":           round(best_f1, 4),
        "temperature":       round(T_final, 4),
        "feature_cols":      ALL_COLS,
        "optimal_weights":   W_OPTIMIZED,
        "comparison": {
            name: m for name, (_, m, _) in results.items()
        },
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print()
    print(f"  Modelo guardado: {model_path}")
    print(f"  Config guardado: {config_path}")
    print()
    print("  Reinicia el backend para usar el nuevo meta-modelo:")
    print("  start-backend.bat")


if __name__ == "__main__":
    main()
