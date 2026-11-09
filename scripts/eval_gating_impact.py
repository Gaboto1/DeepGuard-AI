"""
Mide el impacto de la compuerta de arte IA sobre el score forense.

Compara tres configuraciones sobre el dataset multi-fuente:

  A. fallback       — pesos fijos codificados a mano. Es lo que el sistema
                      ejecutaba realmente en produccion, porque el meta-modelo
                      no llegaba a cargarse (KeyError 'model').
  B. cabezal unico  — meta-modelo completo para todo el contenido.
  C. doble cabezal  — compuerta de tipo de contenido: el detector de arte IA
                      sale del score en obra grafica.

Metricas por configuracion: FPR, FNR, F1 y exactitud, globales y desglosadas
por fuente y por tipo de contenido.

Salida: reports/gating_impact.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

CSV = ROOT / "reports" / "dataset_v2_scores.csv"
OUT = ROOT / "reports" / "gating_impact.json"

from app.models.meta_ensemble import (  # noqa: E402
    MetaEnsemble, _FALLBACK_NO_FACE, BASE_FEATURES,
)
from app.models.content_type_gate import ARTWORK_THRESHOLD  # noqa: E402

SCORE_KEYS = [
    "face_deepfake_vit", "sdxl_detector", "efficientnet_ffpp",
    "ai_art_detector", "siglip_deepfake", "ai_human_detector",
]


def row_scores(row) -> dict:
    d = {}
    for k in SCORE_KEYS:
        v = row.get(k)
        d[k] = None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)
    return d


def fallback_score(scores: dict) -> float:
    w = _FALLBACK_NO_FACE
    vals = [scores.get(k) if scores.get(k) is not None else 0.5 for k in BASE_FEATURES]
    return float(np.clip(sum(wt * v for wt, v in zip(w, vals)) / sum(w), 0, 1))


def metrics(y: np.ndarray, p: np.ndarray, thr: float = 0.5) -> dict:
    pred = (p >= thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "n": int(len(y)),
        "exactitud": round((tp + tn) / max(len(y), 1), 4),
        "f1": round(f1, 4),
        "fpr": round(fp / (fp + tn), 4) if (fp + tn) else None,
        "fnr": round(fn / (fn + tp), 4) if (fn + tp) else None,
        "score_medio": round(float(p.mean()), 4),
    }


def main() -> int:
    if not CSV.exists():
        print(f"ERROR: falta {CSV}")
        return 1

    df = pd.read_csv(CSV).dropna(subset=["label"])
    df["label"] = df["label"].astype(int)
    df["is_artwork"] = df["artwork_probability"] >= ARTWORK_THRESHOLD

    meta = MetaEnsemble.get_instance()
    meta.load()
    print(f"meta cargado: full={meta._full.available} noart={meta._noart.available}")

    import app.models.meta_ensemble as me

    rows = list(df.itertuples(index=False))
    scores_list = [row_scores(r._asdict()) for r in rows]

    df["p_fallback"] = [fallback_score(s) for s in scores_list]

    # B: el arte IA participa en fotografia (politica "gated")
    me.AI_ART_POLICY = "gated"
    df["p_con_arte"] = [
        meta.predict(s, face=False, is_artwork=False)[0] for s in scores_list
    ]

    # C: el arte IA siempre separado (politica por defecto)
    me.AI_ART_POLICY = "always_separate"
    df["p_separado"] = [
        meta.predict(s, face=False, is_artwork=bool(a))[0]
        for s, a in zip(scores_list, df["is_artwork"])
    ]

    y = df["label"].values
    COLS = {
        "A_fallback": "p_fallback",
        "B_con_arte_ia": "p_con_arte",
        "C_arte_separado": "p_separado",
    }
    configs = {name: df[col].values for name, col in COLS.items()}

    report = {"umbral_artwork": ARTWORK_THRESHOLD, "n_total": int(len(df)),
              "n_artwork": int(df["is_artwork"].sum()), "global": {}, "por_fuente": {},
              "por_tipo_contenido": {}}

    print("\n=== GLOBAL ===")
    print(f"{'config':20s} {'exact':>7s} {'F1':>7s} {'FPR':>7s} {'FNR':>7s}")
    for name, p in configs.items():
        m = metrics(y, p)
        report["global"][name] = m
        print(f"{name:20s} {m['exactitud']:7.4f} {m['f1']:7.4f} "
              f"{str(m['fpr']):>7s} {str(m['fnr']):>7s}")

    print("\n=== POR FUENTE (error sobre su propia clase) ===")
    for src in sorted(df["source"].unique()):
        sub = df[df["source"] == src]
        report["por_fuente"][src] = {}
        line = f"{src:16s} n={len(sub):5d} clase={'real' if sub.label.iloc[0]==0 else 'IA  '}"
        for name, col in COLS.items():
            m = metrics(sub["label"].values, sub[col].values)
            report["por_fuente"][src][name] = m
            line += f"  {name.split('_')[0]}:err={1 - m['exactitud']:.3f}"
        print(line)

    print("\n=== POR TIPO DE CONTENIDO ===")
    for tipo, mask in (("obra_grafica", df["is_artwork"]), ("fotografia", ~df["is_artwork"])):
        sub = df[mask]
        if not len(sub):
            continue
        report["por_tipo_contenido"][tipo] = {}
        print(f"\n  -- {tipo} (n={len(sub)}, real={int((sub.label==0).sum())}, "
              f"IA={int((sub.label==1).sum())}) --")
        for name, col in COLS.items():
            m = metrics(sub["label"].values, sub[col].values)
            report["por_tipo_contenido"][tipo][name] = m
            print(f"    {name:20s} exact={m['exactitud']:.4f} F1={m['f1']:.4f} "
                  f"FPR={m['fpr']} FNR={m['fnr']}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nreporte -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
