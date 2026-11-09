"""
Produce, en una sola pasada, las cifras exactas que citan los entregables.

Por que existe
--------------
Las metricas del informe ES2, del guion y de la presentacion estaban repartidas
entre varios registros de distintas fechas, y actualizarlas a mano es como se
cuelan cifras que ya no corresponden. Este script emite un unico JSON con todo
lo que los tres documentos citan, de modo que cada numero del informe tenga una
procedencia rastreable.

Honestidad de la medicion
-------------------------
1. El AUC de validacion cruzada y el error leave-one-source-out se reportan
   juntos, nunca el primero solo. El primero mide el ajuste dentro de las
   fuentes conocidas; el segundo, lo unico que importa en produccion: que pasa
   ante un generador que el modelo no vio.
2. El AUC sobre deepfake facial se calcula SOLO dentro de ff++ (ff_fake contra
   ff_real). Comparar ff_fake contra una mezcla de COCO y rostros reales
   confunde la clase con el origen del archivo y da cifras que parecen peores
   o mejores de lo que son: ese error ya aparecio una vez en este proyecto.
3. El cabezal facial se activa para ff_real, ff_fake y CelebA, que contienen
   rostros por construccion. Se aplica a ambas clases, de modo que no filtra
   la etiqueta. Y se MEZCLA con el track de imagen completa en la misma
   proporcion que usa produccion, no se reporta aislado: medirlo aislado
   inflaba el KPI de deepfake facial en mas de 80 puntos.
4. ATENCION: el meta-ensemble se entrena sobre este mismo CSV, de modo que el
   AUC que aparece bajo "META-ENSEMBLE" es DENTRO DE MUESTRA y sobrestima el
   sistema. No debe citarse como cifra de validacion. Para el informe sirven
   el AUC de validacion cruzada y el error LOSO del bloque final, que si
   dejan fuera lo que miden. El bloque de aqui vale para comparar
   configuraciones entre si y para ver donde falla el sistema por fuente.

Salida: reports/informe_kpis.json
"""
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

# LightGBM se entreno con nombres de columna y aqui recibe un array; el aviso
# no indica un problema real porque build_feature_vector conserva el orden
# declarado en feature_cols.
warnings.filterwarnings("ignore", message=".*valid feature names.*")

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

CSV = ROOT / "reports" / "dataset_v2_scores.csv"
CONFIG = ROOT / "models" / "meta_ensemble" / "meta_config.json"
OUT = ROOT / "reports" / "informe_kpis.json"

import app.models.meta_ensemble as me  # noqa: E402
from app.models.meta_ensemble import MetaEnsemble  # noqa: E402
from app.models.content_type_gate import ARTWORK_THRESHOLD  # noqa: E402

DETECTORES = {
    "face_deepfake_vit": "A  Deep-Fake-Detector-v2 (ViT)",
    "sdxl_detector":     "B  sdxl-detector (Swin)",
    "efficientnet_ffpp": "C  probe CLIP ViT-L/14",
    "ai_art_detector":   "D  detector de arte IA",
    "siglip_deepfake":   "E  Deepfake-Detect-Siglip2",
    "ai_human_detector": "F  umm-maybe AI-image-detector",
}
FUENTES_ROSTRO = {"ff_real", "ff_fake", "celeba"}
FUENTES_FFPP = {"ff_real", "ff_fake"}


def auc(y, p):
    y, p = np.asarray(y), np.asarray(p, dtype=float)
    ok = ~np.isnan(p)
    y, p = y[ok], p[ok]
    if len(np.unique(y)) < 2 or len(y) < 20:
        return None
    return round(float(roc_auc_score(y, p)), 4)


def tasas(y, p, thr):
    """FPR sobre lo autentico y tasa de deteccion sobre lo sintetico."""
    y, p = np.asarray(y), np.asarray(p, dtype=float)
    pred = (p >= thr).astype(int)
    real, ia = (y == 0), (y == 1)
    return {
        "n_real": int(real.sum()),
        "n_ia": int(ia.sum()),
        "fpr": round(float(pred[real].mean()), 4) if real.any() else None,
        "deteccion_ia": round(float(pred[ia].mean()), 4) if ia.any() else None,
        "score_medio_real": round(float(np.nanmean(p[real])), 4) if real.any() else None,
        "score_medio_ia": round(float(np.nanmean(p[ia])), 4) if ia.any() else None,
    }


def main() -> int:
    if not CSV.exists():
        print(f"ERROR: falta {CSV}")
        return 1
    cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}

    df = pd.read_csv(CSV)
    df["is_artwork"] = df["artwork_probability"] >= ARTWORK_THRESHOLD
    df["tiene_rostro"] = df["source"].isin(FUENTES_ROSTRO)
    print(f"Conjunto: {len(df):,} filas  "
          f"real={int((df.label == 0).sum()):,}  IA={int((df.label == 1).sum()):,}")
    print(f"Fuentes: {df['source'].nunique()}  -> "
          f"{', '.join(sorted(df['source'].unique()))}")
    print(f"Obra grafica (compuerta >= {ARTWORK_THRESHOLD}): "
          f"{int(df.is_artwork.sum()):,}\n")

    meta = MetaEnsemble.get_instance()
    meta.load()
    me.AI_ART_POLICY = "gated"
    print(f"Cabezales: full={meta._full.available} noart={meta._noart.available} "
          f"face={meta._face.available}\n")

    cols = list(DETECTORES) + (["compression_level"] if "compression_level" in df else [])
    registros = df[cols].to_dict("records")
    # Produccion NO usa el cabezal facial aislado. En image_service, cuando se
    # detecta un rostro, mezcla las dos pasadas:
    #
    #     final = PESO_TRACK_FACIAL * facial + (1 - PESO_TRACK_FACIAL) * completa
    #
    # Medir `predict(face=True)` a secas sobrestima el KPI central. Con el peso
    # antiguo de 0.60 la diferencia era de 89 puntos sobre ff_fake: el cabezal
    # facial aislado erraba el 5.3 % y la mezcla de produccion el 88.7 %,
    # porque el promedio caia justo por debajo del umbral. Esa cifra inflada
    # estuvo a punto de entrar en el informe como "deteccion de deepfakes
    # faciales: 94,7 %" cuando la pagina web habria dado un 11 %.
    from app.services.image_service import PESO_TRACK_FACIAL
    print(f"Peso del track facial en la mezcla: {PESO_TRACK_FACIAL}")
    p_final = []
    for rec, art, rostro in zip(registros, df.is_artwork, df.tiene_rostro):
        s = {k: (None if pd.isna(v) else float(v)) for k, v in rec.items()}
        p_completa = meta.predict(s, face=False, is_artwork=bool(art))[0]
        if not rostro:
            p_final.append(p_completa)
            continue
        p_facial = meta.predict(s, face=True, is_artwork=bool(art))[0]
        p_final.append(PESO_TRACK_FACIAL * p_facial
                       + (1.0 - PESO_TRACK_FACIAL) * p_completa)
    df["p_final"] = p_final

    # Umbral de produccion: el del cabezal completo
    thr = float(cfg.get("full_head", {}).get("cv", {}).get("T", 0.5))
    print(f"Umbral de decision: T = {thr}\n")

    rep = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "conjunto": {
            "n_total": int(len(df)),
            "n_real": int((df.label == 0).sum()),
            "n_ia": int((df.label == 1).sum()),
            "n_fuentes": int(df["source"].nunique()),
            "fuentes": sorted(df["source"].unique().tolist()),
            "n_obra_grafica": int(df.is_artwork.sum()),
            "umbral_artwork": ARTWORK_THRESHOLD,
        },
        "umbral_decision": thr,
    }

    # 1. meta-ensemble: AUC y tasas, global y por tipo de contenido
    ffpp = df[df["source"].isin(FUENTES_FFPP)]
    foto = df[~df.is_artwork]
    arte_vs_foto = pd.concat([
        df[df.is_artwork & (df.label == 1)],
        df[(~df.is_artwork) & (df.label == 0)],
    ])
    subconjuntos = {
        "global": df,
        "fotografia": foto,
        "obra_grafica_vs_foto_real": arte_vs_foto,
        "deepfake_facial_en_ffpp": ffpp,
    }
    rep["meta_ensemble"] = {}
    print("=== META-ENSEMBLE (produccion: compuerta + cabezal facial) ===")
    print("    DENTRO DE MUESTRA: el meta se entreno sobre este mismo CSV.")
    print("    No citar este AUC como validacion; usar el bloque LOSO final.")
    print(f"{'subconjunto':30s} {'n':>7s} {'AUC':>7s} {'FPR':>8s} {'detec.IA':>9s}")
    for nombre, sub in subconjuntos.items():
        if len(sub) < 20:
            continue
        m = {"n": int(len(sub)), "auc": auc(sub.label, sub.p_final),
             **tasas(sub.label, sub.p_final, thr)}
        rep["meta_ensemble"][nombre] = m
        print(f"{nombre:30s} {m['n']:7d} {str(m['auc']):>7s} "
              f"{str(m['fpr']):>8s} {str(m['deteccion_ia']):>9s}")

    # 2. AUC por detector y tipo de contenido (tabla 4 del informe)
    rep["detectores"] = {}
    print("\n=== AUC POR DETECTOR Y TIPO DE CONTENIDO (tabla 4) ===")
    print(f"{'detector':34s} {'global':>8s} {'obra graf':>10s} {'deepfake':>9s}")
    for col, etiqueta in DETECTORES.items():
        if col not in df:
            continue
        fila = {
            "global": auc(df.label, df[col]),
            "obra_grafica": auc(arte_vs_foto.label, arte_vs_foto[col]),
            "deepfake_facial": auc(ffpp.label, ffpp[col]),
        }
        rep["detectores"][col] = {"etiqueta": etiqueta, **fila}
        print(f"{etiqueta:34s} {str(fila['global']):>8s} "
              f"{str(fila['obra_grafica']):>10s} {str(fila['deepfake_facial']):>9s}")

    # 3. error por fuente sobre su propia clase
    rep["por_fuente"] = {}
    print("\n=== ERROR POR FUENTE (sobre su propia clase) ===")
    for src, sub in df.groupby("source"):
        clase = "real" if sub.label.iloc[0] == 0 else "IA"
        pred = (sub.p_final >= thr).astype(int)
        err = float((pred != sub.label).mean())
        rep["por_fuente"][src] = {
            "n": int(len(sub)), "clase": clase, "error": round(err, 4),
            "score_medio": round(float(sub.p_final.mean()), 4),
        }
        print(f"  {src:18s} {clase:4s} n={len(sub):6d}  error={err:6.2%}  "
              f"score medio={sub.p_final.mean():.4f}")

    # 4. generalizacion: se arrastra del entrenamiento, no se recalcula
    rep["generalizacion_loso"] = {
        cab: {"cv_auc": cfg.get(cab, {}).get("cv", {}).get("auc"),
              "cv_f1": cfg.get(cab, {}).get("cv", {}).get("f1"),
              "loso_error_medio": cfg.get(cab, {}).get("loso", {}).get("error_medio"),
              "loso_error_peor": cfg.get(cab, {}).get("loso", {}).get("error_peor")}
        for cab in ("full_head", "noart_head") if cab in cfg
    }
    print("\n=== GENERALIZACION (del entrenamiento) ===")
    for cab, v in rep["generalizacion_loso"].items():
        print(f"  {cab:12s} CV AUC={v['cv_auc']}  F1={v['cv_f1']}  "
              f"LOSO error medio={v['loso_error_medio']}  peor={v['loso_error_peor']}")
    print("\n  Nota: el AUC de validacion cruzada mide el ajuste dentro de las")
    print("  fuentes conocidas. El error LOSO mide lo que ocurre ante una fuente")
    print("  nueva. Citar solo el primero sobrestima el sistema.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
