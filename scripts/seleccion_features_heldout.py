"""
Elige las features del cabezal completo midiendo sobre el conjunto RETENIDO.

El problema que resuelve
------------------------
El cabezal se entrena y se selecciona sobre reports/dataset_v2_scores.csv, y la
seleccion de features hereda el sesgo de ese conjunto. Caso concreto:

    ai_human_detector (F)   AUC 0.622 en el CSV    -> coeficiente +0.714 (5.0 %)
                            AUC 0.345 en retenido  -> esta INVERTIDO

Fuera de muestra F puntua los rostros reales de LFW en 0.715 y las imagenes de
FLUX en 0.307. Con coeficiente positivo eso empuja la fotografia autentica
hacia "IA". El modelo aprendio un signo que no sobrevive al cambio de dominio,
porque en el conjunto de entrenamiento F si era debilmente informativo.

Lo que hace
-----------
Entrena cada conjunto candidato sobre el CSV completo y lo evalua sobre
data/heldout/, leyendo los scores ya calculados en
reports/heldout_detectores.csv. No necesita GPU: los seis detectores ya
corrieron sobre el retenido.

Reporta, por candidato: AUC sobre el retenido, y —mas importante para este
producto— el reparto por bandas de evidencia, que es lo que la pagina muestra.

Honestidad del procedimiento
----------------------------
Al elegir mirando el retenido, ese conjunto deja de ser un test ciego y pasa a
ser un conjunto de VALIDACION: la cifra del candidato ganador queda ligeramente
optimista. Dos razones por las que sigue siendo preferible a seleccionar sobre
el CSV:

  1. El sesgo que se corrige es de SIGNO, no de magnitud. Una feature que
     apunta en direccion contraria no es un ajuste fino: resta.
  2. Se comparan pocos candidatos, de modo que el margen de sobreajuste por
     seleccion es pequeno frente a la diferencia que se busca.

Para una cifra final limpia haria falta un tercer conjunto de otros dominios.
Queda anotado como limitacion y no se presenta como test ciego.

Salida: reports/seleccion_features_heldout.json
"""
import json
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", message=".*valid feature names.*")

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent

CSV = ROOT / "reports" / "dataset_v2_scores.csv"
HELD = ROOT / "reports" / "heldout_detectores.csv"
CONFIG = ROOT / "models" / "meta_ensemble" / "meta_config.json"
OUT = ROOT / "reports" / "seleccion_features_heldout.json"

STAT_KEYS = ["sdxl_detector", "ai_art_detector", "efficientnet_ffpp",
             "ai_human_detector"]

# El conjunto actual del cabezal completo, y las variantes que interesa probar.
ACTUAL = ["sdxl_detector", "ai_art_detector", "efficientnet_ffpp",
          "ai_human_detector", "sdxl_x_aiart", "robust_mean", "reliable_std"]

CANDIDATOS = {
    "actual": ACTUAL,
    "sin_F": [f for f in ACTUAL if f != "ai_human_detector"],
    "sin_F_sin_interaccion": [f for f in ACTUAL
                              if f not in ("ai_human_detector", "sdxl_x_aiart")],
    "solo_los_tres_buenos": ["sdxl_detector", "ai_art_detector",
                             "efficientnet_ffpp", "robust_mean",
                             "reliable_std"],
    "minimo": ["efficientnet_ffpp", "ai_art_detector"],
}


def derivar(df: pd.DataFrame) -> pd.DataFrame:
    """Replica las derivadas de scripts/train_meta_dual_head.py."""
    d = df.copy()
    for c in STAT_KEYS:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    M = d[STAT_KEYS]
    d["robust_mean"] = M.median(axis=1)
    d["reliable_std"] = M.std(axis=1)
    d["sdxl_x_aiart"] = d["sdxl_detector"] * d["ai_art_detector"]
    return d


def temperatura(p: np.ndarray, y: np.ndarray) -> float:
    eps = 1e-7
    z = np.log(np.clip(p, eps, 1 - eps) / np.clip(1 - p, eps, 1 - eps))

    def perdida(T):
        q = np.clip(1.0 / (1.0 + np.exp(-z / max(T, 1e-3))), eps, 1 - eps)
        return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))

    return float(minimize_scalar(perdida, bounds=(0.05, 10.0),
                                 method="bounded").x)


def aplicar_T(p: np.ndarray, T: float) -> np.ndarray:
    eps = 1e-7
    z = np.log(np.clip(p, eps, 1 - eps) / np.clip(1 - p, eps, 1 - eps))
    return 1.0 / (1.0 + np.exp(-z / max(T, 1e-3)))


def pesos_por_fuente(df: pd.DataFrame) -> np.ndarray:
    """Cada fuente aporta lo mismo, para que no manden las mas numerosas."""
    cuenta = df["source"].value_counts()
    return (1.0 / df["source"].map(cuenta)).values


def main() -> int:
    for p in (CSV, HELD):
        if not p.exists():
            print(f"ERROR: falta {p.name}")
            if p is HELD:
                print("  Ejecuta scripts/score_heldout_detectores.py "
                      "(la version que guarda el CSV de filas).")
            return 1

    tr = derivar(pd.read_csv(CSV))
    he = derivar(pd.read_csv(HELD))
    ytr = tr["label"].values
    yhe = he["label"].values
    w = pesos_por_fuente(tr)

    print(f"Entrenamiento: {len(tr):,} filas, {tr['source'].nunique()} fuentes")
    print(f"Retenido:      {len(he):,} filas, "
          f"{he['source'].nunique()} fuentes -> "
          f"{', '.join(sorted(he['source'].unique()))}\n")

    rep = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "n_entrenamiento": int(len(tr)),
        "n_retenido": int(len(he)),
        "advertencia": ("El retenido se usa aqui para SELECCIONAR, de modo que "
                        "deja de ser un test ciego. La cifra del ganador queda "
                        "optimista. No citar como validacion independiente."),
        "candidatos": {},
    }

    cab = (f"{'candidato':24s} {'nfeat':>5s} {'AUC held':>9s} "
           f"{'senala IA':>10s} {'falsa alarma':>13s} {'IA descart.':>12s}")
    print(cab)
    print("-" * len(cab))

    for nombre, feats in CANDIDATOS.items():
        faltan = [f for f in feats if f not in tr.columns]
        if faltan:
            print(f"{nombre:24s} omitido: faltan {faltan}")
            continue
        Xtr = tr[feats].astype(float).fillna(0.5).values
        clf = LogisticRegression(max_iter=2000, C=1.0)
        clf.fit(Xtr, ytr, sample_weight=w)
        T = temperatura(clf.predict_proba(Xtr)[:, 1], ytr)

        phe = aplicar_T(clf.predict_proba(
            he[feats].astype(float).fillna(0.5).values)[:, 1], T)

        auc = roc_auc_score(yhe, phe)
        # Bandas: lo que la pagina muestra. >= 0.60 se pronuncia por IA,
        # < 0.40 se pronuncia por autentico.
        senala = float((phe[yhe == 1] >= 0.60).mean())
        alarma = float((phe[yhe == 0] >= 0.60).mean())
        descarta_ia = float((phe[yhe == 1] < 0.40).mean())

        coef = {f: round(float(c), 4) for f, c in zip(feats, np.ravel(clf.coef_))}
        rep["candidatos"][nombre] = {
            "features": feats, "temperatura": round(T, 4),
            "auc_retenido": round(float(auc), 4),
            "senala_ia_pct": round(100 * senala, 2),
            "falsa_alarma_pct": round(100 * alarma, 2),
            "ia_descartada_pct": round(100 * descarta_ia, 2),
            "coeficientes": coef,
            "signos_negativos": [f for f, c in coef.items() if c < 0],
        }
        print(f"{nombre:24s} {len(feats):5d} {auc:9.4f} "
              f"{100*senala:9.2f} % {100*alarma:12.2f} % "
              f"{100*descarta_ia:11.2f} %")

    mejor = max(rep["candidatos"].items(),
                key=lambda kv: (kv[1]["senala_ia_pct"]
                                - 3.0 * kv[1]["falsa_alarma_pct"]))
    print(f"\n  Mejor por (senala IA - 3x falsa alarma): '{mejor[0]}'")
    print("  El factor 3 refleja el criterio del propio proyecto: una "
          "acusacion")
    print("  infundada cuesta mas que una deteccion perdida.")
    rep["mejor"] = mejor[0]

    act = rep["candidatos"].get("actual")
    if act and mejor[0] != "actual":
        m = mejor[1]
        print(f"\n  actual      senala {act['senala_ia_pct']:.2f} %  "
              f"falsa alarma {act['falsa_alarma_pct']:.2f} %  "
              f"AUC {act['auc_retenido']}")
        print(f"  {mejor[0]:11s} senala {m['senala_ia_pct']:.2f} %  "
              f"falsa alarma {m['falsa_alarma_pct']:.2f} %  "
              f"AUC {m['auc_retenido']}")

    for nombre, v in rep["candidatos"].items():
        if v["signos_negativos"]:
            print(f"\n  [!] '{nombre}' aprendio coeficiente NEGATIVO en "
                  f"{v['signos_negativos']}: el modelo esta invirtiendo esa "
                  f"senal, señal de que la feature no aporta en la direccion "
                  f"que se supone.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
