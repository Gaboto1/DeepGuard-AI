"""
Reexpresa una medicion del retenido en terminos de BANDAS DE EVIDENCIA.

Por que esta es la metrica que corresponde al producto
-----------------------------------------------------
DeepScan no emite un veredicto binario: muestra una banda. El informe lo dice
explicitamente —"el sistema no acusa: informa bandas de evidencia"— y el guion
de la defensa sostiene el mismo argumento. Medir con un umbral unico (p >= T)
responde a una pregunta que la interfaz nunca le plantea al usuario, y maltrata
al sistema en los dos sentidos:

  - Una imagen de IA en 0.82 cuenta como fallo contra el umbral 0.8764, cuando
    en pantalla sale como "Moderate Evidence", es decir sospecha declarada.
  - Una fotografia autentica en 0.45 cuenta como acierto, cuando en pantalla
    sale "Inconclusive" y el usuario se queda sin respuesta.

Aqui se cuentan dos cosas distintas, que es lo que un uso forense necesita:

    senalada     banda >= Moderate Evidence (p >= 0.60)
                 el sistema se pronuncia a favor de la manipulacion.
    descartada   banda <= Low Evidence (p < 0.40)
                 el sistema se pronuncia a favor de la autenticidad.

Entre ambas queda "Inconclusive", que no es un error: es el sistema diciendo
que no sabe. Contarla como acierto o como fallo seria inventar una decision
que el producto no toma.

Uso
---
    python scripts/kpi_por_bandas.py                       # heldout_eval.json
    python scripts/kpi_por_bandas.py reports/otro.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Fronteras de app/utils/helpers.get_evidence_level
ORDEN = ["Very Low Evidence", "Low Evidence", "Inconclusive",
         "Moderate Evidence", "Strong Evidence"]
SENALADA = {"Moderate Evidence", "Strong Evidence"}
DESCARTADA = {"Very Low Evidence", "Low Evidence"}


def main() -> int:
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "reports" / "heldout_eval.json"
    if not ruta.exists():
        print(f"ERROR: falta {ruta}")
        return 1
    rep = json.loads(ruta.read_text(encoding="utf-8"))
    pf = rep.get("por_fuente") or {}
    if not pf:
        print(f"ERROR: {ruta.name} no trae 'por_fuente'")
        return 1

    print(f"Fuente de datos: {ruta.name}")
    print(f"Generado: {rep.get('generado')}   umbral binario: "
          f"{rep.get('umbral')}\n")

    print("=== DISTRIBUCION DE BANDAS POR FUENTE ===")
    cab = f"{'fuente':12s} {'clase':5s} {'n':>5s} " + \
        " ".join(f"{b.replace(' Evidence','').replace('Inconclusive','Inconcl'):>9s}"
                 for b in ORDEN)
    print(cab)
    print("-" * len(cab))
    agreg = {"real": {}, "IA": {}}
    for fuente, v in sorted(pf.items(), key=lambda kv: kv[1]["clase"]):
        bandas = v.get("bandas") or {}
        n = v["n"]
        fila = " ".join(f"{bandas.get(b, 0):9d}" for b in ORDEN)
        print(f"{fuente:12s} {v['clase']:5s} {n:5d} {fila}")
        acc = agreg.setdefault(v["clase"], {})
        for b in ORDEN:
            acc[b] = acc.get(b, 0) + bandas.get(b, 0)

    print("\n=== KPI EN TERMINOS DE LO QUE VE EL USUARIO ===")
    salida = {}
    for clase, acc in agreg.items():
        n = sum(acc.values())
        if not n:
            continue
        sen = sum(acc.get(b, 0) for b in SENALADA)
        des = sum(acc.get(b, 0) for b in DESCARTADA)
        inc = acc.get("Inconclusive", 0)
        salida[clase] = {"n": n,
                         "senalada_pct": round(100 * sen / n, 2),
                         "descartada_pct": round(100 * des / n, 2),
                         "inconclusive_pct": round(100 * inc / n, 2)}
        print(f"  {clase:5s} n={n:5d}   senalada {100*sen/n:6.2f} %   "
              f"inconclusive {100*inc/n:6.2f} %   "
              f"descartada {100*des/n:6.2f} %")

    # La clase positiva no siempre se llama igual: heldout_eval la etiqueta "IA"
    # y produccion_ffpp "deepfake". Se toma como positiva cualquier clase que no
    # sea "real", para que el bloque comparativo no se pierda en silencio segun
    # el fichero de origen.
    positivas = [c for c in salida if c != "real"]
    if "real" in salida and len(positivas) == 1:
        pos = positivas[0]
        print()
        print(f"  Deteccion de {pos} (se pronuncia)      "
              f"{salida[pos]['senalada_pct']:6.2f} %")
        print(f"  Falsa alarma sobre foto autentica     "
              f"{salida['real']['senalada_pct']:6.2f} %")
        print(f"  Autentico correctamente descartado    "
              f"{salida['real']['descartada_pct']:6.2f} %")
        print(f"  {pos} erroneamente descartada          "
              f"{salida[pos]['descartada_pct']:6.2f} %")
    elif len(positivas) > 1:
        print(f"\n  [!] mas de una clase positiva ({positivas}): se omite el "
              f"resumen comparativo.")
        print("\n  'Inconclusive' no se cuenta ni a favor ni en contra: es el")
        print("  sistema declarando que no sabe, que es la respuesta correcta")
        print("  cuando no sabe.")

    destino = ruta.with_name(ruta.stem + "_bandas.json")
    destino.write_text(json.dumps(
        {"origen": ruta.name, "generado": rep.get("generado"),
         "por_clase": salida,
         "nota": ("Banda >= Moderate Evidence cuenta como senalada; "
                  "<= Low Evidence como descartada; Inconclusive no cuenta "
                  "en ninguna direccion.")},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
