"""
Entrena los dos cabezales del meta-ensemble v3.

    meta_classifier.joblib        CON features de arte IA   -> contenido fotografico
    meta_classifier_noart.joblib  SIN features de arte IA   -> obra grafica

Metrica principal: leave-one-source-out (LOSO)
----------------------------------------------
El dataset anterior confundia clase con fuente (todo lo real venia de
ff++_faces, todo lo IA de real_world_training), de modo que la validacion
cruzada estratificada daba F1=99% midiendo en realidad "de que carpeta salio
esta imagen". LOSO entrena dejando una fuente entera fuera y mide el error
sobre esa fuente no vista: es la unica cifra que dice algo sobre generalizacion.

Entrada:  reports/dataset_v2_scores.csv  (generado por score_dataset_v2.py)
Salida:   models/meta_ensemble/meta_classifier.joblib
          models/meta_ensemble/meta_classifier_noart.joblib
          models/meta_ensemble/meta_config.json
          reports/meta_dual_head_report.json
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from scipy.optimize import minimize_scalar

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "reports" / "dataset_v2_scores.csv"
# Variantes recomprimidas (ver scripts/augment_compresion.py). Se incorporan al
# entrenamiento para que el modelo no confunda artefactos de compresión con
# síntesis: sin ellas, recomprimir una foto real de COCO en JPEG de calidad 55
# subía su score del 26 % al 58 %.
CSV_AUG = ROOT / "reports" / "dataset_v2_aug_scores.csv"

# Fuentes que solo existen en el conjunto v3. Si el CSV no las trae, la etapa de
# puntuacion no llego a rehacerse (por ejemplo, por falta de VRAM si el worker de
# Celery seguia cargado) y lo que hay en disco es el conjunto anterior. Entrenar
# sobre el sin avisar daria un modelo que parece nuevo y no lo es, asi que se
# aborta en vez de continuar en silencio.
FUENTES_V3 = {"coco_train", "celeba", "elsa_multigen", "midjourney"}


def exigir_csv_v3(csv_path) -> None:
    import datetime as _dt
    import pandas as _pd
    cab = _pd.read_csv(csv_path, usecols=["source"])
    presentes = set(cab["source"].unique())
    mtime = _dt.datetime.fromtimestamp(csv_path.stat().st_mtime)
    print(f"  {csv_path.name}: {len(cab):,} filas, {len(presentes)} fuentes, "
          f"modificado {mtime:%Y-%m-%d %H:%M}")
    faltan = FUENTES_V3 - presentes
    if faltan:
        raise SystemExit(
            f"ABORTA: {csv_path.name} no contiene {sorted(faltan)}. "
            f"  Fuentes presentes: {sorted(presentes)}. "
            f"  Es el conjunto anterior. Vuelve a ejecutar "
            f"scripts/score_dataset_v2.py con la GPU libre "
            f"(detener el worker de Celery) antes de esta etapa."
        )

META_DIR = ROOT / "models" / "meta_ensemble"
REPORT = ROOT / "reports" / "meta_dual_head_report.json"

ARTWORK_THRESHOLD = 0.55

RAW_MODELS = [
    "face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
    "ai_art_detector", "siglip_deepfake", "ai_human_detector",
    "compression_level",
]

# Cabezal completo: replica el conjunto historico para no romper comparabilidad
FULL_FEATURES = [
    "sdxl_detector", "ai_art_detector", "efficientnet_ffpp",
    "ai_human_detector", "sdxl_x_aiart", "robust_mean", "reliable_std",
]
FULL_STAT_KEYS = [
    "sdxl_detector", "ai_art_detector", "efficientnet_ffpp", "ai_human_detector",
]

# Cabezal sin arte: candidatos evaluados por LOSO, se elige el mejor
# Cabezal facial: se omite el detector de arte IA y el de SDXL, que sobre
# rostros estan al nivel del azar (AUC 0.501 y 0.478 medidos dentro de ff++) y
# solo aportarian ruido al unico detector competente, el probe CLIP (0.976).
FACE_FEATURES = [
    "efficientnet_ffpp", "face_deepfake_vit", "ai_human_detector",
    "compression_level", "reliable_std",
]
FACE_STAT_KEYS = ["efficientnet_ffpp", "face_deepfake_vit", "ai_human_detector"]

NOART_CANDIDATES = {
    "compacto": (
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector",
         "robust_mean", "reliable_std"],
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector"],
    ),
    "con_rostro": (
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector",
         "face_deepfake_vit", "robust_mean", "reliable_std"],
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector"],
    ),
    "amplio": (
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector",
         "face_deepfake_vit", "siglip_deepfake", "robust_mean", "reliable_std"],
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector",
         "face_deepfake_vit"],
    ),
    # Con el nivel de compresión: permite al modelo aprender que, con artefactos
    # de compresión presentes, unas puntuaciones elevadas siguen siendo
    # compatibles con fotografía auténtica.
    "amplio_compresion": (
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector",
         "face_deepfake_vit", "siglip_deepfake", "compression_level",
         "robust_mean", "reliable_std"],
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector",
         "face_deepfake_vit"],
    ),
    "con_rostro_compresion": (
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector",
         "face_deepfake_vit", "compression_level", "robust_mean", "reliable_std"],
        ["sdxl_detector", "efficientnet_ffpp", "ai_human_detector"],
    ),
}


# ── feature engineering (identico al de inferencia) ──────────────────────────

def add_features(df: pd.DataFrame, stat_keys: list[str]) -> pd.DataFrame:
    d = df.copy()
    for c in RAW_MODELS:
        if c not in d.columns:
            d[c] = np.nan
    d["sdxl_x_aiart"] = d["sdxl_detector"].fillna(0.5) * d["ai_art_detector"].fillna(0.5)
    arr = d[stat_keys]
    d["robust_mean"] = arr.median(axis=1, skipna=True)
    d["reliable_std"] = arr.apply(
        lambda r: float(np.std(r.dropna())) if r.notna().sum() > 1 else 0.0, axis=1
    )
    return d


def temperature_scale(probs: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(probs, 1e-7, 1 - 1e-7)
    logit = np.log(p / (1 - p))

    def nll(T):
        T = max(T, 1e-3)
        q = np.clip(1 / (1 + np.exp(-logit / T)), 1e-7, 1 - 1e-7)
        return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))

    return float(minimize_scalar(nll, bounds=(0.05, 5.0), method="bounded").x)


def apply_T(p: np.ndarray, T: float) -> np.ndarray:
    p = np.clip(p, 1e-7, 1 - 1e-7)
    return np.clip(1 / (1 + np.exp(-np.log(p / (1 - p)) / T)), 0, 1)


def make_classifiers():
    out = {"logreg": lambda: LogisticRegression(C=1.0, max_iter=2000)}
    try:
        from xgboost import XGBClassifier
        out["xgboost"] = lambda: XGBClassifier(
            max_depth=3, n_estimators=200, learning_rate=0.08,
            subsample=0.9, colsample_bytree=0.9,
            eval_metric="logloss", verbosity=0, random_state=42,
        )
    except ImportError:
        pass
    try:
        from lightgbm import LGBMClassifier
        out["lightgbm"] = lambda: LGBMClassifier(
            max_depth=3, n_estimators=200, learning_rate=0.08,
            min_child_samples=20, reg_lambda=1.5, reg_alpha=0.5,
            verbose=-1, random_state=42,
        )
    except ImportError:
        pass
    return out


# ── evaluacion ───────────────────────────────────────────────────────────────

def loso_eval(df: pd.DataFrame, feats: list[str], clf_fn, thr: float = 0.5) -> dict:
    """Entrena dejando una fuente fuera; mide el error sobre esa fuente."""
    per_source = {}
    all_err = []
    for src in sorted(df["source"].unique()):
        tr = df[df["source"] != src]
        va = df[df["source"] == src]
        if tr["label"].nunique() < 2 or len(va) == 0:
            continue
        clf = clf_fn()
        clf.fit(tr[feats].fillna(0.5).values, tr["label"].values,
                sample_weight=source_weights(tr))
        p = clf.predict_proba(va[feats].fillna(0.5).values)[:, 1]
        pred = (p >= thr).astype(int)
        y = va["label"].values
        err = float((pred != y).mean())
        per_source[src] = {
            "n": int(len(va)),
            "clase": "real" if y[0] == 0 else "IA",
            "error": round(err, 4),
            "score_medio": round(float(p.mean()), 4),
        }
        all_err.append(err)
    return {
        "por_fuente": per_source,
        "error_medio": round(float(np.mean(all_err)), 4) if all_err else None,
        "error_peor": round(float(np.max(all_err)), 4) if all_err else None,
    }


def cv_eval(df: pd.DataFrame, feats: list[str], clf_fn) -> dict:
    X = df[feats].fillna(0.5).values
    y = df["label"].values
    w = source_weights(df)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    f1s, fprs, aucs, Ts = [], [], [], []
    for tr, va in skf.split(X, y):
        clf = clf_fn()
        clf.fit(X[tr], y[tr], sample_weight=w[tr])
        p = clf.predict_proba(X[va])[:, 1]
        T = temperature_scale(p, y[va])
        pc = apply_T(p, T)
        pred = (pc >= 0.5).astype(int)
        f1s.append(f1_score(y[va], pred, zero_division=0))
        aucs.append(roc_auc_score(y[va], pc))
        neg = y[va] == 0
        fprs.append(float(pred[neg].sum()) / max(int(neg.sum()), 1))
        Ts.append(T)
    return {
        "f1": round(float(np.mean(f1s)), 4),
        "auc": round(float(np.mean(aucs)), 4),
        "fpr": round(float(np.mean(fprs)), 4),
        "T": round(float(np.mean(Ts)), 4),
    }


def grupos_identidad(d: pd.DataFrame) -> np.ndarray:
    """
    Clave de identidad para las filas de ff++, usada en la validacion del
    cabezal facial. Sin ella, fotogramas del mismo video caen a ambos lados de
    la particion y la metrica mide memorizacion de identidad, no deteccion.
    """
    import re
    claves = []
    for p in d["path"]:
        carpeta = Path(str(p)).parent.name
        ids = re.findall(r"\d+", carpeta)
        claves.append(ids[0] if ids else str(p))
    return np.array(claves, dtype=object)


def source_weights(d: pd.DataFrame) -> np.ndarray:
    """
    Peso por muestra que iguala la contribucion de cada fuente.

    Sin esto, el entrenamiento queda dominado por las fuentes mas numerosas
    (arte IA: diffusiondb + sdturbo = 5400 filas) y el cabezal aprende a
    apoyarse en el detector de SDXL, que es el que separa bien ESE tipo de
    imagen. Los deepfakes faciales (ff_fake, 1600 filas) quedan ahogados, y el
    probe CLIP —el mejor detector para ese caso, AUC 0.863— acaba con una
    importancia marginal. Igualar el peso de cada fuente obliga al modelo a
    resolver tambien el caso forense clasico.
    """
    counts = d["source"].value_counts()
    n_src = len(counts)
    return (len(d) / (n_src * d["source"].map(counts))).to_numpy(dtype=float)


def train_head(df: pd.DataFrame, feats: list[str], stat_keys: list[str],
               name: str) -> dict:
    """Evalua todos los clasificadores y entrena el mejor sobre el total."""
    d = add_features(df, stat_keys)
    results = {}
    print(f"\n  --- cabezal '{name}' ({len(feats)} features) ---")
    for cname, fn in make_classifiers().items():
        cv = cv_eval(d, feats, fn)
        lo = loso_eval(d, feats, fn)
        results[cname] = {"cv": cv, "loso": lo}
        print(f"    {cname:9s} CV: F1={cv['f1']:.3f} AUC={cv['auc']:.3f} "
              f"FPR={cv['fpr']:.3f} | LOSO err medio={lo['error_medio']} "
              f"peor={lo['error_peor']}")

    # Seleccion: AUC de la CV ponderada por fuente redondeado a 3 decimales y,
    # a igualdad, el menor error leave-one-source-out.
    #
    # El redondeo importa: los candidatos empatan en CV y sin el la eleccion la
    # decide una cifra que es ruido. Con el empate resuelto por LOSO se elige
    # el que generaliza a fuentes no vistas, que es lo que separa de verdad a
    # los candidatos.
    #
    # Se redondea a DOS decimales, no a tres. Con 68.000 muestras el AUC de
    # validacion cruzada se satura: 0.9996 frente a 0.999 son 0.0006 de
    # diferencia, indistinguible del ruido de particion, y a tres decimales
    # esa diferencia rompia el empate y decidia la eleccion. En la corrida del
    # 2026-11-09 eso escogio xgboost (CV AUC 0.9996, LOSO 0.0178, FPR 0.0073)
    # sobre logreg (CV AUC 0.999, LOSO 0.0123, FPR 0.005): se cedio medio punto
    # de error ante fuentes nuevas a cambio de seis diezmilesimas de AUC dentro
    # de muestra. A dos decimales ambos empatan en 1.00 y decide el LOSO.
    def _criterio(kv):
        cv, lo = kv[1]["cv"], kv[1]["loso"]
        err = lo["error_medio"] if lo["error_medio"] is not None else 1.0
        return (round(cv["auc"], 2), -err, -cv["fpr"])

    best_name = max(results.items(), key=_criterio)[0]
    print(f"    -> elegido: {best_name}")

    clf = make_classifiers()[best_name]()
    X = d[feats].fillna(0.5).values
    y = d["label"].values
    clf.fit(X, y, sample_weight=source_weights(d))
    T = temperature_scale(clf.predict_proba(X)[:, 1], y)

    # Importancias. Un arbol las expone como `feature_importances_`; una
    # regresion logistica no las tiene, pero sus coeficientes son el dato
    # equivalente y de hecho mas interpretable: signo y magnitud sobre una
    # escala comun, porque las siete features ya viven en [0, 1].
    #
    # Antes esta rama solo cubria el caso de arbol, de modo que al elegirse
    # logreg el config guardaba importances=None y el informe se quedaba sin
    # el dato del peso por detector — la cifra que sostiene el hallazgo de que
    # un solo detector concentraba la decision.
    importances = None
    if hasattr(clf, "feature_importances_"):
        importances = {f: round(float(v), 4)
                       for f, v in zip(feats, clf.feature_importances_)}
    elif hasattr(clf, "coef_"):
        coef = np.ravel(clf.coef_)
        importances = {f: round(float(v), 4) for f, v in zip(feats, coef)}
    if importances:
        total = sum(abs(v) for v in importances.values()) or 1.0
        reparto = {f: round(100 * abs(v) / total, 1)
                   for f, v in importances.items()}
        print(f"    importancias: {importances}")
        print(f"    peso relativo (%): {reparto}")

    return {
        "clf": clf, "temperature": T, "feature_cols": feats,
        "stat_keys": stat_keys, "name": best_name,
        "metrics": results[best_name], "importances": importances,
        "peso_relativo_pct": (
            {f: round(100 * abs(v) / (sum(abs(x) for x in importances.values()) or 1.0), 1)
             for f, v in importances.items()} if importances else None),
        "all_results": results,
    }


def main() -> int:
    if not CSV.exists():
        print(f"ERROR: falta {CSV}. Ejecuta primero scripts/score_dataset_v2.py")
        return 1

    exigir_csv_v3(CSV)
    df = pd.read_csv(CSV)
    df["variante"] = "original"

    if CSV_AUG.exists():
        aug = pd.read_csv(CSV_AUG)
        # La fuente se marca para que el ponderado por fuente trate la variante
        # recomprimida como un modo propio y no infle el peso de la original.
        aug["source"] = aug["source"].astype(str) + "_comp"
        df = pd.concat([df, aug], ignore_index=True)
        print(f"  Variantes recomprimidas incorporadas: {len(aug)} filas")
    else:
        print(f"  AVISO: no existe {CSV_AUG.name}; se entrena sin variantes "
              f"de compresión y el modelo seguirá inflando el score de las "
              f"fotos recomprimidas.")

    df = df.dropna(subset=["label"])
    df["label"] = df["label"].astype(int)
    print("=" * 72)
    print(f"  Dataset: {len(df)} filas")
    print(df.groupby(["source", "label"]).size().unstack(fill_value=0).to_string())
    print(f"\n  artwork (gate>={ARTWORK_THRESHOLD}): "
          f"{int((df.artwork_probability >= ARTWORK_THRESHOLD).sum())} filas")
    print("=" * 72)

    # ── cabezal completo ─────────────────────────────────────────────────────
    full = train_head(df, FULL_FEATURES, FULL_STAT_KEYS, "full")

    # ── cabezal sin arte: elige el mejor conjunto de features ────────────────
    print("\n  === seleccion de features para el cabezal sin-arte ===")
    noart_runs = {}
    for cand, (feats, sk) in NOART_CANDIDATES.items():
        noart_runs[cand] = train_head(df, feats, sk, f"noart/{cand}")
    def _criterio_cand(kv):
        m = kv[1]["metrics"]
        err = m["loso"]["error_medio"] if m["loso"]["error_medio"] is not None else 1.0
        return (round(m["cv"]["auc"], 2), -err, -m["cv"]["fpr"])

    best_cand = max(noart_runs.items(), key=_criterio_cand)
    print(f"\n  -> conjunto sin-arte elegido: '{best_cand[0]}'")
    noart = best_cand[1]

    # ── comparacion en el subconjunto de obra grafica ────────────────────────
    art_mask = df["artwork_probability"] >= ARTWORK_THRESHOLD
    print(f"\n  === comportamiento sobre obra grafica (n={int(art_mask.sum())}) ===")
    comparison = {}
    for tag, head in (("full", full), ("noart", noart)):
        d = add_features(df, head["stat_keys"])
        sub = d[art_mask]
        if len(sub) and sub["label"].nunique() >= 1:
            p = apply_T(
                head["clf"].predict_proba(sub[head["feature_cols"]].fillna(0.5).values)[:, 1],
                head["temperature"],
            )
            y = sub["label"].values
            entry = {"n": int(len(sub)), "score_medio": round(float(p.mean()), 4)}
            if (y == 0).any():
                entry["fpr"] = round(float(((p >= 0.5) & (y == 0)).sum() / (y == 0).sum()), 4)
            if (y == 1).any():
                entry["recall"] = round(float(((p >= 0.5) & (y == 1)).sum() / (y == 1).sum()), 4)
            comparison[tag] = entry
            print(f"    {tag:6s} {entry}")

    # ── cabezal facial ───────────────────────────────────────────────────────
    # En contenido con rostro solo el probe CLIP es competente: medido dentro de
    # ff++, su AUC es 0.976 mientras los otros cinco detectores van de 0.48 a
    # 0.58, es decir al nivel del azar. El cabezal general los pondera como
    # iguales y el resultado de un deepfake acaba en la banda "inconcluyente".
    # Este cabezal se entrena solo con rostros para que aprenda esa jerarquia.
    print("\n  === cabezal facial (solo ff++: rostro real vs deepfake) ===")
    cara = df[df["source"].str.startswith(("ff_real", "ff_fake"))].copy()
    face_head = None
    if cara["label"].nunique() == 2 and len(cara) > 500:
        print(f"    muestras: {len(cara)} "
              f"({int((cara.label==0).sum())} real, {int((cara.label==1).sum())} deepfake)")
        ident = grupos_identidad(cara)
        print(f"    identidades distintas: {len(set(ident))}")
        d_cara = add_features(cara, FACE_STAT_KEYS)
        X = d_cara[FACE_FEATURES].fillna(0.5).values
        yv = d_cara["label"].values

        # Validacion agrupada por identidad
        from sklearn.model_selection import StratifiedGroupKFold
        sgkf = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=42)
        for cname, fn in make_classifiers().items():
            aucs, fprs, recs = [], [], []
            for tr_i, va_i in sgkf.split(X, yv, ident):
                clf = fn()
                clf.fit(X[tr_i], yv[tr_i])
                p = clf.predict_proba(X[va_i])[:, 1]
                T = temperature_scale(p, yv[va_i])
                pc = apply_T(p, T)
                yv_va = yv[va_i]
                aucs.append(roc_auc_score(yv_va, pc))
                fprs.append(float((pc[yv_va == 0] >= 0.5).mean()))
                recs.append(float((pc[yv_va == 1] >= 0.5).mean()))
            print(f"    {cname:9s} AUC={np.mean(aucs):.4f}  "
                  f"FPR={np.mean(fprs):.4f}  recall={np.mean(recs):.4f}")
            if face_head is None or np.mean(aucs) > face_head["auc"]:
                face_head = {"nombre": cname, "auc": float(np.mean(aucs)),
                             "fpr": float(np.mean(fprs)), "recall": float(np.mean(recs))}

        clf = make_classifiers()[face_head["nombre"]]()
        clf.fit(X, yv)
        T_face = temperature_scale(clf.predict_proba(X)[:, 1], yv)
        face_head.update({"clf": clf, "temperature": T_face,
                          "feature_cols": FACE_FEATURES, "stat_keys": FACE_STAT_KEYS})
        print(f"    -> elegido: {face_head['nombre']} (AUC {face_head['auc']:.4f}, "
              f"T={T_face:.3f})")
    else:
        print("    datos insuficientes — no se entrena")

    # ── guarda artefactos ────────────────────────────────────────────────────
    META_DIR.mkdir(parents=True, exist_ok=True)
    import joblib

    for path, head in ((META_DIR / "meta_classifier.joblib", full),
                       (META_DIR / "meta_classifier_noart.joblib", noart)):
        if path.exists():
            shutil.copy(path, path.with_suffix(".joblib.bak"))
        joblib.dump({
            "clf": head["clf"],
            "temperature": head["temperature"],
            "feature_cols": head["feature_cols"],
            "stat_keys": head["stat_keys"],
            "name": head["name"],
        }, str(path))
        print(f"\n  guardado: {path.name}  ({head['name']}, T={head['temperature']:.3f})")

    if face_head is not None:
        ruta_face = META_DIR / "meta_classifier_face.joblib"
        if ruta_face.exists():
            shutil.copy(ruta_face, ruta_face.with_suffix(".joblib.bak"))
        joblib.dump({
            "clf": face_head["clf"],
            "temperature": face_head["temperature"],
            "feature_cols": face_head["feature_cols"],
            "stat_keys": face_head["stat_keys"],
            "name": face_head["nombre"],
        }, str(ruta_face))
        print(f"  guardado: {ruta_face.name}  ({face_head['nombre']}, "
              f"T={face_head['temperature']:.3f})")

    cfg = {
        "version": "v3-dual-head",
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(CSV.name),
        "n_samples": int(len(df)),
        "artwork_threshold": ARTWORK_THRESHOLD,
        "best_method": full["name"],
        "full_head": {
            "features": full["feature_cols"], "stat_keys": full["stat_keys"],
            "classifier": full["name"], "temperature": round(full["temperature"], 4),
            "cv": full["metrics"]["cv"], "loso": full["metrics"]["loso"],
            "importances": full["importances"],
            "peso_relativo_pct": full["peso_relativo_pct"],
        },
        "noart_head": {
            "candidate": best_cand[0],
            "features": noart["feature_cols"], "stat_keys": noart["stat_keys"],
            "classifier": noart["name"], "temperature": round(noart["temperature"], 4),
            "cv": noart["metrics"]["cv"], "loso": noart["metrics"]["loso"],
            "importances": noart["importances"],
            "peso_relativo_pct": noart["peso_relativo_pct"],
        },
        "artwork_subset_comparison": comparison,
    }
    # El cabezal facial se guardaba SOLO en su .joblib: el config describia dos
    # de los tres cabezales que produccion carga. Sus metricas salen del mismo
    # bucle de validacion cruzada que las de los otros dos, de modo que
    # registrarlas aqui no introduce ninguna cifra nueva.
    if face_head is not None:
        cfg["face_head"] = {
            "features": face_head["feature_cols"],
            "stat_keys": face_head["stat_keys"],
            "classifier": face_head["nombre"],
            "temperature": round(face_head["temperature"], 4),
            "cv": {"auc": round(face_head["auc"], 4),
                   "fpr": round(face_head["fpr"], 4),
                   "recall": round(face_head["recall"], 4)},
            "entrenado_sobre": "solo ff++ (intercambio de rostro); NO cubre "
                               "rostros enteramente sinteticos",
        }
    with open(META_DIR / "meta_config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"\n  config -> {META_DIR / 'meta_config.json'}")
    print(f"  reporte -> {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
