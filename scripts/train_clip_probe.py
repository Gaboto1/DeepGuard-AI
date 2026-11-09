"""
Reentrena el probe lineal del detector C sobre los embeddings CLIP extraidos.

El probe anterior se entreno con 512 imagenes y quedo con un rango dinamico
minimo (desviacion 0.05): tenia señal — AUC 0.863 sobre deepfakes faciales —
pero comprimida en una banda tan estrecha que el meta-modelo no podia
aprovecharla.

Criterio de seleccion
---------------------
El objetivo declarado del proyecto es la pregunta forense "¿fue manipulada esta
fotografia?", y el caso que el sistema fallaba era el deepfake facial. Por eso
el modelo se elige por su AUC en la particion ff_fake vs {coco, ff_real}, no
por la exactitud agregada, que esta dominada por el arte IA y ya se resuelve
bien con otros detectores.

Evaluacion: particion por identidad
-----------------------------------
FaceForensics++ agrupa fotogramas por video: real/000/, fake/Deepfakes/000_003/
(identidad 000 intercambiada con 003). Una particion aleatoria deja fotogramas
del mismo video a ambos lados, y entonces el probe memoriza la identidad en vez
de la manipulacion. Un primer entrenamiento asi dio AUC 0.9948 sobre deepfakes
faciales — una cifra que no habria sobrevivido al uso real.

Aqui las identidades se agrupan por componentes conexas: si el deepfake 000_003
existe, las identidades 000 y 003 quedan en el mismo grupo, y el grupo entero
cae de un solo lado de la particion. El resto de fuentes se particiona por
archivo, y cada variante recomprimida acompaña a su original.

Salida: models/advanced_detector/clip_probe.joblib (respalda el anterior)
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPClassifier

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "models" / "advanced_detector"
PROBE = DIR / "clip_probe.joblib"
CONFIG = DIR / "best_model_config.json"
REPORTE = ROOT / "reports" / "clip_probe_report.json"

REAL_SRC = {"coco", "ff_real"}
CARA_FAKE = "ff_fake"


def temperatura(probs, y):
    p = np.clip(probs, 1e-7, 1 - 1e-7)
    logit = np.log(p / (1 - p))

    def nll(T):
        T = max(T, 1e-3)
        q = np.clip(1 / (1 + np.exp(-logit / T)), 1e-7, 1 - 1e-7)
        return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))

    return float(minimize_scalar(nll, bounds=(0.2, 6.0), method="bounded").x)


def aplicar_T(p, T):
    p = np.clip(p, 1e-7, 1 - 1e-7)
    return np.clip(1 / (1 + np.exp(-np.log(p / (1 - p)) / T)), 0, 1)


def pesos_por_fuente(src):
    fuentes, cuentas = np.unique(src, return_counts=True)
    mapa = {f: len(src) / (len(fuentes) * c) for f, c in zip(fuentes, cuentas)}
    return np.array([mapa[s] for s in src], dtype=float)


def grupos_por_identidad(rutas, src):
    """
    Clave de agrupacion que impide la fuga por identidad.

    ff++ real:  .../ff++_faces/real/000/000_017.jpg            -> identidad 000
    ff++ fake:  .../fake/Deepfakes/000_003/000_003_017.jpg     -> une 000 y 003

    Las identidades que aparecen juntas en algun deepfake se fusionan por
    componentes conexas, de modo que ninguna pareja quede repartida entre
    entrenamiento y prueba. El resto de fuentes agrupa por ruta de archivo.
    """
    import re
    padre = {}

    def find(a):
        padre.setdefault(a, a)
        while padre[a] != a:
            padre[a] = padre[padre[a]]
            a = padre[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            padre[rb] = ra

    crudas = []
    for ruta, s in zip(rutas, src):
        p = Path(str(ruta))
        if s in ("ff_real", "ff_fake"):
            carpeta = p.parent.name           # "000"  o  "000_003"
            ids = re.findall(r"\d+", carpeta)
            if not ids:
                crudas.append(("ruta", str(ruta)))
                continue
            for extra in ids[1:]:
                union(f"id{ids[0]}", f"id{extra}")
            crudas.append(("id", f"id{ids[0]}"))
        else:
            crudas.append(("ruta", str(ruta)))

    return np.array([find(v) if t == "id" else v for t, v in crudas], dtype=object)


def metricas(y, p, src):
    out = {"auc_global": round(float(roc_auc_score(y, p)), 4)}
    # El caso que importa: deepfake facial contra fotografia autentica
    m = np.isin(src, list(REAL_SRC)) | (src == CARA_FAKE)
    if m.sum() > 10 and len(np.unique(y[m])) == 2:
        out["auc_deepfake_facial"] = round(float(roc_auc_score(y[m], p[m])), 4)
    # Falsos positivos sobre fotografia autentica. Es la metrica que delato el
    # fallo en uso real: el probe daba 4 falsos positivos de 8 fotos del
    # usuario mientras su AUC en el conjunto de prueba era 0.99.
    reales = p[y == 0]
    out["fpr_real"] = round(float((reales >= 0.5).mean()), 4)
    out["fpr_real_alto"] = round(float((reales >= 0.7).mean()), 4)
    for f in np.unique(src):
        fm = src == f
        out[f"media_{f}"] = round(float(p[fm].mean()), 4)
    out["rango_dinamico"] = round(float(p.std()), 4)
    return out


def main() -> int:
    X = np.load(DIR / "embeddings_X.npy")
    y = np.load(DIR / "embeddings_y.npy").astype(int)
    src = np.load(DIR / "embeddings_src.npy", allow_pickle=True).astype(str)
    rutas = np.load(DIR / "embeddings_path.npy", allow_pickle=True)
    print(f"Embeddings: {X.shape}  real={int((y==0).sum())}  "
          f"sintetica={int((y==1).sum())}")
    print(f"Fuentes: {dict(zip(*np.unique(src, return_counts=True)))}")

    grupos = grupos_por_identidad(rutas, src)
    n_grupos_ff = len({g for g, s in zip(grupos, src) if s in ("ff_real", "ff_fake")})
    print(f"Grupos de identidad en ff++: {n_grupos_ff}\n")

    # Particion por GRUPO. Las identidades de ff++ se reparten GLOBALMENTE, no
    # por fuente: una misma identidad aparece como rostro real y como deepfake,
    # asi que repartirla dentro de cada fuente por separado la dejaba en
    # entrenamiento por un lado y en prueba por el otro. El resto de fuentes se
    # reparte por archivo dentro de su propia fuente.
    rng = np.random.default_rng(42)
    test = np.zeros(len(y), dtype=bool)

    es_ff = np.isin(src, ["ff_real", "ff_fake"])
    grupos_ff = np.unique(grupos[es_ff])
    rng.shuffle(grupos_ff)
    ff_en_test = set(grupos_ff[: max(1, int(len(grupos_ff) * 0.25))])
    test[es_ff] = np.array([g in ff_en_test for g in grupos[es_ff]])

    for f in np.unique(src[~es_ff]):
        idx = np.flatnonzero(src == f)
        gs = np.unique(grupos[idx])
        rng.shuffle(gs)
        en_test = set(gs[: max(1, int(len(gs) * 0.25))])
        test[idx] = np.array([g in en_test for g in grupos[idx]])

    tr, te = ~test, test

    # Comprobacion explicita: ningun grupo a ambos lados
    solapados = set(grupos[tr]) & set(grupos[te])
    print(f"Entrenamiento: {tr.sum()}   Prueba: {te.sum()}")
    print(f"Grupos compartidos entre particiones: {len(solapados)} "
          f"{'(correcto)' if not solapados else '(FUGA)'}\n")
    assert not solapados, "fuga de identidad entre particiones"

    w = pesos_por_fuente(src[tr])

    candidatos = {
        "logreg_C0.1": lambda: LogisticRegression(C=0.1, max_iter=2000),
        "logreg_C1":   lambda: LogisticRegression(C=1.0, max_iter=2000),
        "logreg_C10":  lambda: LogisticRegression(C=10.0, max_iter=2000),
        "mlp_256":     lambda: MLPClassifier(hidden_layer_sizes=(256,), alpha=1e-3,
                                             max_iter=120, random_state=42,
                                             early_stopping=True, n_iter_no_change=6),
    }

    resultados = {}
    for nombre, fn in candidatos.items():
        clf = fn()
        try:
            clf.fit(X[tr], y[tr], sample_weight=w)
        except TypeError:   # MLPClassifier no admite sample_weight
            clf.fit(X[tr], y[tr])
        p_tr = clf.predict_proba(X[tr])[:, 1]
        T = temperatura(p_tr, y[tr])
        p_te = aplicar_T(clf.predict_proba(X[te])[:, 1], T)
        m = metricas(y[te], p_te, src[te])
        resultados[nombre] = {"T": round(T, 4), **m, "_clf": clf}
        print(f"  {nombre:12s} AUC={m['auc_global']:.4f}  "
              f"AUC_deepfake={m.get('auc_deepfake_facial', float('nan')):.4f}  "
              f"FPR_real={m['fpr_real']:.4f}  rango={m['rango_dinamico']:.3f}  T={T:.3f}")

    # Seleccion: entre los candidatos cuyos falsos positivos sobre fotografia
    # real se mantienen por debajo del 5 %, el de mejor AUC en deepfake facial.
    # Si ninguno cumple el limite, se elige el de menor FPR: un detector que
    # marca fotos autenticas no sirve por bueno que sea su AUC.
    admisibles = {k: v for k, v in resultados.items() if v["fpr_real"] <= 0.05}
    if admisibles:
        mejor = max(admisibles.items(),
                    key=lambda kv: (kv[1].get("auc_deepfake_facial", 0),
                                    kv[1]["auc_global"]))
    else:
        print("  AVISO: ningun candidato baja del 5 % de falsos positivos")
        mejor = min(resultados.items(), key=lambda kv: kv[1]["fpr_real"])
    nombre, info = mejor
    print(f"\n  Elegido: {nombre} "
          f"(AUC deepfake facial = {info.get('auc_deepfake_facial')}, "
          f"FPR real = {info['fpr_real']})")

    # Reentrena sobre el total con los hiperparametros elegidos
    clf = candidatos[nombre]()
    w_all = pesos_por_fuente(src)
    try:
        clf.fit(X, y, sample_weight=w_all)
    except TypeError:
        clf.fit(X, y)
    T = temperatura(clf.predict_proba(X)[:, 1], y)

    import joblib
    if PROBE.exists():
        shutil.copy(PROBE, PROBE.with_suffix(".joblib.bak"))
    joblib.dump({
        "clf": clf,
        "temperature": T,
        "n_features": int(X.shape[1]),
        "model_id": "openai/clip-vit-large-patch14",
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "n_train": int(len(y)),
        "selected": nombre,
        "holdout_metrics": {k: v for k, v in info.items() if k != "_clf"},
    }, str(PROBE))
    print(f"\n  Probe guardado: {PROBE.name}  (T={T:.3f}, n={len(y)})")

    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    cfg.update({
        "model_c_type": "clip_probe",
        "model_c_id": "openai/clip-vit-large-patch14",
        "model_c_name": f"CLIP ViT-L/14 + {nombre}",
        "probe_path": str(PROBE),
        "temperature": T,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "n_train": int(len(y)),
        "holdout_metrics": {k: v for k, v in info.items() if k != "_clf"},
    })
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))

    REPORTE.write_text(json.dumps(
        {k: {kk: vv for kk, vv in v.items() if kk != "_clf"}
         for k, v in resultados.items()}, indent=2, ensure_ascii=False))
    print(f"  Config  -> {CONFIG.name}")
    print(f"  Reporte -> {REPORTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
