"""
Decide si el modelo reentrenado se adopta o se revierte, segun un criterio
escrito ANTES de ver el resultado.

Por que un guion y no un juicio a mano
--------------------------------------
Si el criterio se decide despues de ver las cifras, siempre hay una lectura que
favorece al modelo nuevo: basta elegir la metrica en la que gano. Este guion fija
el criterio por adelantado y lo aplica mecanicamente.

Criterio (en bandas de evidencia sobre el conjunto retenido, que es lo que la
pagina muestra; ver reports/MEJORA_ENSEMBLE_v4.md seccion 8):

  1. VETO  — las falsas alarmas sobre fotografia autentica no pueden subir mas
             de 0,3 puntos sobre la linea base. Una acusacion infundada es el
             error de mayor costo del sistema; ninguna mejora en deteccion la
             compensa.
  2. VETO  — el AUC fuera de muestra no puede bajar mas de 0,005.
  3. MEJORA— con los dos vetos superados, se adopta si la IA señalada sube al
             menos 1,0 punto, o si se mantiene (-0,5 pt de tolerancia) y las
             falsas alarmas bajan al menos 0,2 puntos.

Uso
---
    python scripts/decidir_adopcion.py              # informa
    python scripts/decidir_adopcion.py --aplicar    # revierte si procede
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"

TOL_FPR_SUBIDA   = 0.3   # puntos porcentuales
TOL_AUC_BAJADA   = 0.005
MEJORA_MIN_IA    = 1.0
TOL_IA_PLANA     = -0.5
MEJORA_MIN_FPR   = 0.2


def bandas(p: Path):
    d = json.loads(p.read_text(encoding="utf-8"))
    pc = d["por_clase"]
    return (pc["real"]["senalada_pct"], pc["IA"]["senalada_pct"])


def auc(p: Path):
    d = json.loads(p.read_text(encoding="utf-8"))
    for k in ("auc", "auc_global", "AUC"):
        if k in d:
            return float(d[k])
    g = d.get("global") or d.get("agregado") or {}
    for k in ("auc", "AUC"):
        if k in g:
            return float(g[k])
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true",
                    help="restaura el respaldo si el criterio dice REVERTIR")
    args = ap.parse_args()

    marca = REPORTS / ".snapshot_actual"
    if not marca.exists():
        print("ERROR: no hay reports/.snapshot_actual — sin respaldo no se "
              "puede decidir ni revertir.")
        return 1
    snap = ROOT / marca.read_text(encoding="utf-8").strip()
    if not snap.is_dir():
        print(f"ERROR: el respaldo {snap} no existe.")
        return 1

    base_b = snap / "mediciones" / "heldout_eval_bandas.json"
    nuevo_b = REPORTS / "heldout_eval_bandas.json"
    base_e = snap / "mediciones" / "heldout_eval.json"
    nuevo_e = REPORTS / "heldout_eval.json"
    for p in (base_b, nuevo_b, base_e, nuevo_e):
        if not p.exists():
            print(f"ERROR: falta {p}. Hay que medir antes de decidir: "
                  f"scripts/eval_heldout.py y scripts/kpi_por_bandas.py")
            return 1

    fpr0, ia0 = bandas(base_b)
    fpr1, ia1 = bandas(nuevo_b)
    auc0, auc1 = auc(base_e), auc(nuevo_e)

    print("\n" + "=" * 66)
    print("  DECISION DE ADOPCION — criterio fijado antes de medir")
    print("=" * 66)
    print(f"  respaldo: {snap.name}\n")
    print(f"  {'metrica':34s} {'antes':>9s} {'ahora':>9s} {'delta':>8s}")
    print("  " + "-" * 62)
    print(f"  {'falsas alarmas (real señalada) %':34s} {fpr0:>9.2f} "
          f"{fpr1:>9.2f} {fpr1-fpr0:>+8.2f}")
    print(f"  {'IA señalada %':34s} {ia0:>9.2f} {ia1:>9.2f} "
          f"{ia1-ia0:>+8.2f}")
    if auc0 is not None and auc1 is not None:
        print(f"  {'AUC fuera de muestra':34s} {auc0:>9.4f} {auc1:>9.4f} "
              f"{auc1-auc0:>+8.4f}")
    else:
        print(f"  {'AUC fuera de muestra':34s} {'(no legible en el JSON)':>27s}")

    vetos = []
    if fpr1 - fpr0 > TOL_FPR_SUBIDA:
        vetos.append(f"las falsas alarmas suben {fpr1-fpr0:+.2f} pt "
                     f"(tolerancia {TOL_FPR_SUBIDA})")
    if auc0 is not None and auc1 is not None and auc0 - auc1 > TOL_AUC_BAJADA:
        vetos.append(f"el AUC baja {auc0-auc1:.4f} "
                     f"(tolerancia {TOL_AUC_BAJADA})")

    d_ia, d_fpr = ia1 - ia0, fpr1 - fpr0
    mejora = (d_ia >= MEJORA_MIN_IA
              or (d_ia >= TOL_IA_PLANA and -d_fpr >= MEJORA_MIN_FPR))

    print()
    if vetos:
        for v in vetos:
            print(f"  VETO: {v}")
        veredicto = "REVERTIR"
    elif not mejora:
        print(f"  Sin mejora suficiente: IA señalada {d_ia:+.2f} pt "
              f"(hace falta {MEJORA_MIN_IA:+.1f}), falsas alarmas "
              f"{d_fpr:+.2f} pt.")
        veredicto = "REVERTIR"
    else:
        print("  Los dos vetos se superan y hay mejora medible.")
        veredicto = "ADOPTAR"

    print(f"\n  >>> {veredicto} <<<\n")

    salida = REPORTS / "decision_adopcion.json"
    salida.write_text(json.dumps({
        "respaldo": snap.name, "veredicto": veredicto, "vetos": vetos,
        "antes": {"falsas_alarmas_pct": fpr0, "ia_senalada_pct": ia0,
                  "auc": auc0},
        "ahora": {"falsas_alarmas_pct": fpr1, "ia_senalada_pct": ia1,
                  "auc": auc1},
        "criterio": {"tol_fpr_subida_pt": TOL_FPR_SUBIDA,
                     "tol_auc_bajada": TOL_AUC_BAJADA,
                     "mejora_min_ia_pt": MEJORA_MIN_IA,
                     "tol_ia_plana_pt": TOL_IA_PLANA,
                     "mejora_min_fpr_pt": MEJORA_MIN_FPR},
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {salida}")

    if veredicto == "REVERTIR" and args.aplicar:
        print("\n  Restaurando el respaldo...")
        for sub, destino in (("meta_ensemble", ROOT / "models" / "meta_ensemble"),
                             ("advanced_detector",
                              ROOT / "models" / "advanced_detector")):
            for f in (snap / sub).glob("*"):
                shutil.copy(f, destino / f.name)
                print(f"    restaurado {sub}/{f.name}")
        print("\n  OJO: hay que REINICIAR EL WORKER para que la pagina vuelva "
              "a servir estos modelos (reports/REANUDAR_WORKER.txt).")
    elif veredicto == "REVERTIR":
        print("\n  (no se restauro nada: ejecuta con --aplicar)")

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
