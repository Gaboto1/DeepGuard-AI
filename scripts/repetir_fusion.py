# -*- coding: utf-8 -*-
"""
Reevalua variantes de la fusion sobre una traza, sin GPU y de forma exacta.

No reimplementa nada: vuelve a llamar a las funciones de produccion
(`_calibrated_combine`, `apply_ood_penalty`, `apply_forensic_corrections`,
`get_evidence_level`) con las entradas que `scripts/traza_retenido.py` grabo.
Lo unico que cambia entre variantes es lo que se quiere estudiar:

  - los cabezales del meta-ensemble (otro directorio de .joblib)
  - la mezcla de las dos ramas cuando hay rostro

La variante V0 -cabezales vigentes, mezcla vigente- debe reproducir el score
que produccion dio a cada imagen. El guion lo comprueba y ABORTA si no: una
repeticion que no reproduce el original no mide el sistema, mide un parecido.

Las dos mezclas
---------------
`lineal`  la vigente: w * rostro + (1 - w) * completa, con w = 0,80 en
          fotografia y 0,30 en obra grafica.
`o`       es IA si lo dice CUALQUIERA de las dos ramas: max(rostro, completa).

Por que la segunda tiene sentido y no es un ajuste mas: las dos ramas no
estiman lo mismo. La rama de rostro responde "¿es un intercambio de rostro?" y
la rama completa "¿es una imagen sintetica?". Promediarlas trata un "no es un
intercambio" como evidencia de autenticidad, cuando el cabezal facial es ciego
a los rostros enteramente sinteticos: con el rostro en 0,00 y w = 0,80, la
imagen no puede pasar de 0,20 por mucho que la rama completa este segura.

La mezcla `o` se aplica SOLO en fotografia. En obra grafica se conserva la
lineal con 0,30: ese peso se valido aparte y por otro motivo -el cabezal
facial, entrenado con fotogramas, esta fuera de dominio ante rostros dibujados-
y un maximo dejaria pasar sus falsos positivos.

Uso
---
    python scripts/repetir_fusion.py --traza reports/traza_dev.json
    python scripts/repetir_fusion.py --traza reports/traza_dev.json \
        --cabezales-nuevos models/meta_ensemble_candidato
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(str(BACKEND))

SENALADA = 0.60     # frontera inferior de 'Moderate Evidence' (helpers.py)


def usar_cabezales(directorio: Path) -> None:
    """Apunta el singleton del meta-ensemble a otro directorio de cabezales."""
    from app.models import meta_ensemble as me
    m = me.MetaEnsemble.get_instance()
    m._full = me._Head(directorio / "meta_classifier.joblib", "full")
    m._noart = me._Head(directorio / "meta_classifier_noart.joblib", "noart")
    m._face = me._Head(directorio / "meta_classifier_face.joblib", "face")
    me._CONFIG_PATH = directorio / "meta_config.json"
    m._loaded = False
    m.load()
    if not (m._full.available and m._noart.available and m._face.available):
        raise SystemExit(f"ABORTA: faltan cabezales en {directorio}")


def _combinar(d: dict) -> float:
    from app.models.deepfake_detector import _calibrated_combine
    return float(_calibrated_combine(
        d["score_a"], d["score_b"], d["score_c"], face=d["face"],
        score_d=d["score_d"], score_e=d["score_e"], score_f=d["score_f"],
        score_freq=d["score_freq"], score_srm=d["score_srm"],
        score_ela=d["score_ela"], is_artwork=d["is_artwork"],
        compression_level=d["compression_level"],
    )[0])


def puntuar(filas: list[dict], mezcla: str) -> list[float]:
    from app.services import image_service as isv
    from app.models.ood_detector import apply_ood_penalty
    from app.utils.forensic_corrections import apply_forensic_corrections
    out = []
    for f in filas:
        completa = _combinar(f["completa"])
        s = completa
        if f["rostro"] is not None:
            rostro = _combinar(f["rostro"])
            obra = bool(f["completa"]["is_artwork"])
            # La misma funcion que usa produccion, no una copia de su formula.
            s = isv.mezclar_ramas(rostro, completa, obra, modo=mezcla)
        ood = {"is_ood": f["ood"]["is_ood"],
               "penalty_alpha": f["ood"]["penalty_alpha"]}
        s = apply_ood_penalty(s, ood)
        s, _regla, _ = apply_forensic_corrections(
            s, f["corr"]["model_scores"], ood,
            ai_art_excluded=f["corr"]["ai_art_excluded"])
        out.append(float(s))
    return out


def resumen(filas: list[dict], scores: list[float]) -> dict:
    from sklearn.metrics import roc_auc_score
    por_fuente = {}
    y, p = [], []
    for f, s in zip(filas, scores):
        if f["label"] not in (0, 1):
            continue
        d = por_fuente.setdefault(f["fuente"], {"label": f["label"], "n": 0,
                                                "senaladas": 0})
        d["n"] += 1
        d["senaladas"] += int(s >= SENALADA)
        y.append(f["label"])
        p.append(s)
    real = [v for v in por_fuente.values() if v["label"] == 0]
    ia = [v for v in por_fuente.values() if v["label"] == 1]
    n_real = sum(v["n"] for v in real) or 1
    n_ia = sum(v["n"] for v in ia) or 1
    return {
        "falsas_alarmas_pct": round(100 * sum(v["senaladas"] for v in real) / n_real, 2),
        "ia_senalada_pct": round(100 * sum(v["senaladas"] for v in ia) / n_ia, 2),
        "auc": round(float(roc_auc_score(y, p)), 4) if len(set(y)) == 2 else None,
        "por_fuente": por_fuente,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traza", required=True)
    ap.add_argument("--cabezales-nuevos", default=None,
                    help="directorio con los tres .joblib y el config candidatos")
    args = ap.parse_args()

    from loguru import logger
    logger.remove()   # las reglas forenses registran cada correccion

    traza = json.loads((ROOT / args.traza).read_text(encoding="utf-8"))
    filas = traza["filas"]
    vigentes = ROOT / "models" / "meta_ensemble"

    # Importados, nunca copiados: es lo que mantiene el criterio previo.
    from decidir_adopcion import (
        TOL_FPR_SUBIDA, TOL_AUC_BAJADA, MEJORA_MIN_IA, TOL_IA_PLANA,
        MEJORA_MIN_FPR)

    variantes = [("V0 vigente", vigentes, "lineal"),
                 ("V1 vigente + mezcla o", vigentes, "o")]
    if args.cabezales_nuevos:
        nuevos = ROOT / args.cabezales_nuevos
        variantes += [("V2 cabezales nuevos", nuevos, "lineal"),
                      ("V3 cabezales nuevos + mezcla o", nuevos, "o")]

    resultados = {}
    extras = [f for f in filas if f["label"] not in (0, 1)]
    for nombre, directorio, mezcla in variantes:
        usar_cabezales(directorio)
        scores = puntuar(filas, mezcla)
        if nombre.startswith("V0"):
            dif = max(abs(s - f["final"]) for s, f in zip(scores, filas))
            print(f"  comprobacion: V0 reproduce produccion con diferencia "
                  f"maxima {dif:.2e} sobre {len(filas)} imagenes")
            if dif > 1e-6:
                raise SystemExit(
                    "ABORTA: la repeticion no reproduce el score de "
                    "produccion; lo que sigue no mediria el sistema.")
        r = resumen(filas, scores)
        r["extras"] = {f["archivo"]: round(s, 4)
                       for f, s in zip(filas, scores) if f["label"] not in (0, 1)}
        resultados[nombre] = r
    usar_cabezales(vigentes)

    base = resultados["V0 vigente"]
    print(f"\n  traza: {args.traza}  ({traza['n']} imagenes, "
          f"barajado[{traza['desde']}:{traza['desde'] + traza['n_por_fuente']}])\n")
    print(f"  {'variante':34s} {'falsas':>7s} {'IA sen.':>8s} {'AUC':>7s}   veredicto")
    print("  " + "-" * 74)
    for nombre, r in resultados.items():
        d_fa = r["falsas_alarmas_pct"] - base["falsas_alarmas_pct"]
        d_ia = r["ia_senalada_pct"] - base["ia_senalada_pct"]
        d_auc = (base["auc"] or 0) - (r["auc"] or 0)
        if nombre.startswith("V0"):
            ver = "(linea base)"
        elif d_fa > TOL_FPR_SUBIDA + 1e-9:
            ver = f"VETO falsas +{d_fa:.2f}"
        elif d_auc > TOL_AUC_BAJADA:
            ver = f"VETO AUC -{d_auc:.4f}"
        elif d_ia >= MEJORA_MIN_IA or (d_ia >= TOL_IA_PLANA and -d_fa >= MEJORA_MIN_FPR):
            ver = "PASA"
        else:
            ver = "sin mejora suficiente"
        r["veredicto"] = ver
        print(f"  {nombre:34s} {r['falsas_alarmas_pct']:6.2f}% "
              f"{r['ia_senalada_pct']:7.2f}% {r['auc']:7.4f}   {ver}")

    print("\n  senaladas por fuente")
    fuentes = sorted(base["por_fuente"])
    print(f"  {'variante':34s} " + " ".join(f"{f:>9s}" for f in fuentes))
    for nombre, r in resultados.items():
        print(f"  {nombre:34s} " + " ".join(
            f"{r['por_fuente'][f]['senaladas']:>9d}" for f in fuentes))
    if extras:
        print("\n  imagenes sueltas")
        for nombre, r in resultados.items():
            for a, s in r["extras"].items():
                print(f"  {nombre:34s} {a[:30]:30s} {s:.4f}")

    salida = ROOT / "reports" / f"repeticion_{Path(args.traza).stem.replace('traza_', '')}.json"
    salida.write_text(json.dumps({
        "generado": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "traza": args.traza, "n": traza["n"],
        "tramo": [traza["desde"], traza["desde"] + traza["n_por_fuente"]],
        "criterio": {"origen": "scripts/decidir_adopcion.py",
                     "tol_fpr_subida_pt": TOL_FPR_SUBIDA,
                     "tol_auc_bajada": TOL_AUC_BAJADA,
                     "mejora_min_ia_pt": MEJORA_MIN_IA},
        "variantes": resultados,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  -> {salida}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
