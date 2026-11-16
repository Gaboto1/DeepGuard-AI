# -*- coding: utf-8 -*-
"""
Aplica el criterio de adopcion a un cambio de CODIGO, no de modelo.

Por que un guion aparte
-----------------------
`scripts/decidir_adopcion.py` decide sobre reentrenamientos: compara contra el
respaldo de `reports/.snapshot_actual` y, si procede, restaura los `.joblib`.
Aqui los modelos no se tocan: lo que cambia es una regla forense. El respaldo
no son pesos sino la medicion anterior, y revertir es `git revert`, no copiar
archivos.

**Los umbrales no se redefinen: se importan de `decidir_adopcion.py`.** Esto
no es una comodidad, es la unica forma de que el criterio siga siendo previo.
Si se copiaran aqui a mano, nada impediria ajustarlos despues de ver el
resultado, que es exactamente el sesgo que el criterio existe para evitar.
Fueron fijados el 9 de noviembre de 2026, antes de esta medicion.

Uso
---
    python scripts/decidir_adopcion_codigo.py \
        --antes reports/linea_base_pre_r1 \
        --cambio "R1 solo puede elevar"
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
sys.path.insert(0, str(ROOT / "scripts"))

# Importados, nunca copiados. Ver la nota de arriba.
from decidir_adopcion import (  # noqa: E402
    TOL_FPR_SUBIDA, TOL_AUC_BAJADA, MEJORA_MIN_IA, TOL_IA_PLANA, MEJORA_MIN_FPR,
)


def _bandas(p: Path):
    d = json.loads(p.read_text(encoding="utf-8"))["por_clase"]
    return d["real"]["senalada_pct"], d["IA"]["senalada_pct"]


def _auc(p: Path):
    d = json.loads(p.read_text(encoding="utf-8"))
    return float((d.get("global") or {}).get("auc") or d.get("auc"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--antes", required=True,
                    help="carpeta con heldout_eval.json y heldout_eval_bandas.json previos")
    ap.add_argument("--cambio", default="(sin describir)",
                    help="que se cambio, para el registro")
    args = ap.parse_args()

    antes = ROOT / args.antes
    faltan = [p for p in (antes / "heldout_eval_bandas.json",
                          antes / "heldout_eval.json",
                          REPORTS / "heldout_eval_bandas.json",
                          REPORTS / "heldout_eval.json") if not p.exists()]
    if faltan:
        for p in faltan:
            print(f"ERROR: falta {p}")
        return 1

    fpr0, ia0 = _bandas(antes / "heldout_eval_bandas.json")
    fpr1, ia1 = _bandas(REPORTS / "heldout_eval_bandas.json")
    auc0 = _auc(antes / "heldout_eval.json")
    auc1 = _auc(REPORTS / "heldout_eval.json")

    print("\n" + "=" * 68)
    print("  DECISION DE ADOPCION — cambio de codigo")
    print("=" * 68)
    print(f"  cambio: {args.cambio}")
    print(f"  linea base: {args.antes}\n")
    print(f"  {'metrica':34s} {'antes':>9s} {'ahora':>9s} {'delta':>9s}")
    print("  " + "-" * 64)
    print(f"  {'falsas alarmas (real senalada) %':34s} {fpr0:>9.2f} {fpr1:>9.2f} {fpr1-fpr0:>+9.2f}")
    print(f"  {'IA senalada %':34s} {ia0:>9.2f} {ia1:>9.2f} {ia1-ia0:>+9.2f}")
    print(f"  {'AUC fuera de muestra':34s} {auc0:>9.4f} {auc1:>9.4f} {auc1-auc0:>+9.4f}")

    vetos = []
    if fpr1 - fpr0 > TOL_FPR_SUBIDA:
        vetos.append(f"las falsas alarmas suben {fpr1-fpr0:+.2f} pt "
                     f"(tolerancia {TOL_FPR_SUBIDA})")
    if auc0 - auc1 > TOL_AUC_BAJADA:
        vetos.append(f"el AUC baja {auc0-auc1:.4f} (tolerancia {TOL_AUC_BAJADA})")

    d_ia, d_fpr = ia1 - ia0, fpr1 - fpr0
    mejora = (d_ia >= MEJORA_MIN_IA
              or (d_ia >= TOL_IA_PLANA and -d_fpr >= MEJORA_MIN_FPR))

    print()
    if vetos:
        for v in vetos:
            print(f"  VETO: {v}")
        veredicto = "REVERTIR"
    elif not mejora:
        print(f"  Sin mejora suficiente: IA senalada {d_ia:+.2f} pt "
              f"(hace falta {MEJORA_MIN_IA:+.1f}), falsas alarmas {d_fpr:+.2f} pt.")
        veredicto = "REVERTIR"
    else:
        print("  Los dos vetos se superan y hay mejora medible.")
        veredicto = "ADOPTAR"

    print(f"\n  >>> {veredicto} <<<\n")
    salida = REPORTS / "decision_adopcion_codigo.json"
    salida.write_text(json.dumps({
        "generado": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "cambio": args.cambio,
        "linea_base": args.antes,
        "veredicto": veredicto,
        "vetos": vetos,
        "antes": {"falsas_alarmas_pct": fpr0, "ia_senalada_pct": ia0, "auc": auc0},
        "ahora": {"falsas_alarmas_pct": fpr1, "ia_senalada_pct": ia1, "auc": auc1},
        "criterio": {
            "origen": "importado de scripts/decidir_adopcion.py, fijado el 2026-11-09",
            "tol_fpr_subida_pt": TOL_FPR_SUBIDA,
            "tol_auc_bajada": TOL_AUC_BAJADA,
            "mejora_min_ia_pt": MEJORA_MIN_IA,
            "tol_ia_plana_pt": TOL_IA_PLANA,
            "mejora_min_fpr_pt": MEJORA_MIN_FPR,
        },
        "nota": ("Revertir aqui es `git revert`, no restaurar pesos: este "
                 "guion decide sobre cambios de codigo y no toca modelos."),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {salida}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
