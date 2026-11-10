# -*- coding: utf-8 -*-
"""
Mide la latencia REAL de los analisis, separando el ensemble de la parte
semantica, y la escribe en reports/latencia_medida.json.

Por que hace falta
------------------
El KPI-04 del informe declaraba "< 3 s" como valor actual y "<= 5 s en el
percentil 95" como meta, y decia medirse con el "campo de tiempo de analisis".
Ese campo es `analysis_time`, y sobre 49 analisis reales nunca bajo de 17,3 s:
incluye el analisis semantico con LLaVA, que es la parte lenta.

El detalle SMART del KPI dice explicitamente que excluye el analisis semantico.
El resultado trae el desglose (`semantic_analysis.analysis_time`), de modo que
esa resta se puede hacer y el KPI se puede medir como esta definido. Hecha la
resta, el valor tampoco es "< 3 s".

De donde salen los datos
------------------------
Del backend de resultados de Celery en Redis, es decir de analisis que de
verdad pasaron por la via de produccion: la pagina, la API, el broker y el
worker. No se reconstruye ningun tiempo aqui. `result_expires` son 24 h, asi
que esto mide la ventana reciente, y conviene ejecutarlo tras una tanda de
pruebas (scripts/prueba_extremo_a_extremo.py).

La VRAM separa dos regimenes
----------------------------
Con la GPU dedicada un analisis tarda decenas de segundos; con la VRAM
saturada por otras aplicaciones, decenas de minutos. Mezclarlos da un
percentil 95 sin sentido fisico, asi que se informan por separado y el umbral
se declara aqui en vez de elegirse despues de ver los datos.

Uso
---
    python scripts/medir_latencia.py
"""
import json
import math
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

SALIDA = ROOT / "reports" / "latencia_medida.json"

# Umbral que separa los dos regimenes, fijado ANTES de mirar los datos. Un
# analisis con la GPU dedicada no llego nunca a 120 s en ninguna medicion.
UMBRAL_REGIMEN_S = 120.0


def percentil(valores, p):
    v = sorted(valores)
    i = min(len(v) - 1, max(0, math.ceil(p / 100 * len(v)) - 1))
    return v[i]


def resumen(valores):
    if not valores:
        return None
    return {
        "n": len(valores),
        "minimo_s": round(min(valores), 2),
        "mediana_s": round(st.median(valores), 2),
        "p95_s": round(percentil(valores, 95), 2),
        "maximo_s": round(max(valores), 2),
    }


def main() -> int:
    from app.celery_app import celery_app

    total, semantico, ensemble = [], [], []
    with celery_app.connection_or_acquire() as conn:
        cli = conn.default_channel.client
        for clave in cli.keys("celery-task-meta-*"):
            try:
                d = json.loads(cli.get(clave))
                if d.get("status") != "SUCCESS":
                    continue
                r = d.get("result") or {}
                res = r.get("result", r)
                a = res.get("analysis_time")
                if a is None:
                    continue
                s = (res.get("semantic_analysis") or {}).get("analysis_time")
                total.append(float(a))
                if s is not None:
                    semantico.append(float(s))
                    ensemble.append(float(a) - float(s))
            except Exception:
                continue

    if not total:
        print("No hay resultados en el backend. Ejecuta antes algunos "
              "analisis: scripts/prueba_extremo_a_extremo.py")
        return 1

    pares = list(zip(ensemble, total)) if len(ensemble) == len(total) else []
    ens_gpu = [e for e, t in pares if t < UMBRAL_REGIMEN_S]
    tot_gpu = [t for t in total if t < UMBRAL_REGIMEN_S]
    tot_sat = [t for t in total if t >= UMBRAL_REGIMEN_S]

    datos = {
        "generado": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "origen": "backend de resultados de Celery en Redis (via de produccion)",
        "umbral_regimen_s": UMBRAL_REGIMEN_S,
        "nota": (
            "total = lo que espera el usuario, incluido el analisis semantico. "
            "ensemble = total menos semantic_analysis.analysis_time, que es lo "
            "que el KPI-04 dice medir. 'gpu_dedicada' excluye los analisis "
            "corridos con la VRAM saturada por otras aplicaciones."
        ),
        "total_todos": resumen(total),
        "total_gpu_dedicada": resumen(tot_gpu),
        "total_vram_saturada": resumen(tot_sat),
        "semantico_todos": resumen(semantico),
        "ensemble_sin_semantica_todos": resumen(ensemble),
        "ensemble_sin_semantica_gpu_dedicada": resumen(ens_gpu),
    }
    SALIDA.write_text(json.dumps(datos, indent=2, ensure_ascii=False),
                      encoding="utf-8")

    def linea(etiqueta, r):
        if not r:
            return
        print(f"  {etiqueta:44s} n={r['n']:3d}  mediana {r['mediana_s']:8.2f}s"
              f"  p95 {r['p95_s']:9.2f}s  max {r['maximo_s']:9.2f}s")

    print("\n  LATENCIA MEDIDA POR LA VIA DE PRODUCCION")
    print("  " + "-" * 86)
    linea("total (lo que espera el usuario)", datos["total_todos"])
    linea("total, solo GPU dedicada", datos["total_gpu_dedicada"])
    linea("total, VRAM saturada", datos["total_vram_saturada"])
    print()
    linea("solo la parte semantica (LLaVA)", datos["semantico_todos"])
    linea("ensemble sin semantica (KPI-04)",
          datos["ensemble_sin_semantica_todos"])
    linea("ensemble sin semantica, GPU dedicada",
          datos["ensemble_sin_semantica_gpu_dedicada"])
    print(f"\n  -> {SALIDA}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
