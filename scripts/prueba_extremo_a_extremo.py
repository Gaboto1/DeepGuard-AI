"""
Encola tareas REALES en el broker y comprueba lo que la pagina devolveria.

Por que no basta con llamar a las funciones
-------------------------------------------
El worker de Celery carga los seis detectores y el meta-ensemble una sola vez
al arrancar (`worker_init`). Llamar a `_run_image_analysis` desde un proceso
suelto no prueba nada sobre lo que recibe el usuario: ese proceso carga —o no
carga— sus propios modelos. El 9 de noviembre de 2026 eso produjo un AUC de
0,525 con aspecto de medicion valida, porque los seis detectores devolvian
None y el score salia de dos heuristicas de CPU.

Este guion recorre el mismo camino que una carga desde la web: envia la tarea
por el broker de Upstash, el worker la toma con los modelos que tenga en
memoria, y aqui se lee el resultado. Si el worker sirve modelos viejos, se ve.

Uso
---
    python scripts/prueba_extremo_a_extremo.py            # 10 imagenes
    python scripts/prueba_extremo_a_extremo.py --n 4
"""
import argparse
import base64
import json
import random
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# (etiqueta, clase esperada, patron)
FUENTES = [
    ("lfw (rostro real)",        "real", "data/heldout/real/lfw/*"),
    ("imagenet (foto real)",     "real", "data/heldout/real/imagenet/*"),
    ("ff++ real (rostro real)",  "real", "data/ff++_faces/real/*"),
    ("flux (IA)",                "ia",   "data/heldout/ai/flux/*"),
    ("dalle3 (IA)",              "ia",   "data/heldout/ai/dalle3/*"),
    ("ff++ Deepfakes (deepfake)", "ia",  "data/ff++_faces/fake/Deepfakes/*/*"),
]
EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def elegir(n_por_fuente: int, semilla: int = 20261109):
    rnd = random.Random(semilla)
    elegidas = []
    for etiqueta, clase, patron in FUENTES:
        cand = [p for p in ROOT.glob(patron)
                if p.is_file() and p.suffix.lower() in EXT]
        if not cand:
            print(f"  aviso: sin imagenes para {etiqueta} ({patron})")
            continue
        for p in rnd.sample(cand, min(n_por_fuente, len(cand))):
            elegidas.append((etiqueta, clase, p))
    return elegidas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2,
                    help="imagenes por fuente (6 fuentes)")
    ap.add_argument("--espera", type=int, default=900,
                    help="segundos maximos de espera por tarea")
    args = ap.parse_args()

    from app.celery_app import celery_app

    imagenes = elegir(args.n)
    print(f"\nEncolando {len(imagenes)} tareas en el broker...\n")

    enviados = []
    for etiqueta, clase, p in imagenes:
        b64 = base64.b64encode(p.read_bytes()).decode()
        tid = str(uuid.uuid4())
        r = celery_app.send_task(
            "app.tasks.analysis_tasks.analyze_image_task",
            args=[tid, str(p), p.name],
            kwargs={"include_heatmap": True, "file_content_b64": b64},
            queue="images",
        )
        enviados.append((etiqueta, clase, p.name, r))
        print(f"  -> {etiqueta:27s} {p.name[:34]:34s} id={r.id[:8]}")

    print(f"\nEsperando resultados (hasta {args.espera}s por tarea)...\n")
    print(f"  {'fuente':27s} {'archivo':26s} {'score':>7s} "
          f"{'banda':22s} {'veredicto':10s}")
    print("  " + "-" * 96)

    filas, fallos = [], 0
    for etiqueta, clase, nombre, r in enviados:
        try:
            res = r.get(timeout=args.espera)
        except Exception as e:
            print(f"  {etiqueta:27s} {nombre[:26]:26s} FALLO: {e}")
            fallos += 1
            continue
        # Se lee la banda QUE EMITE EL SISTEMA, no una recalculada aqui: si el
        # worker aplicara otro umbral, recalcular la banda lo ocultaria.
        score = res.get("fake_probability") if isinstance(res, dict) else None
        banda = res.get("evidence_level", "?") if isinstance(res, dict) else "?"
        rostros = res.get("faces_detected") if isinstance(res, dict) else None
        tipo = res.get("content_type") if isinstance(res, dict) else None
        # Señalada = la pagina muestra evidencia de IA en banda alta
        senala = banda in ("Moderate Evidence", "Strong Evidence")
        correcto = (senala and clase == "ia") or (not senala and clase == "real")
        ver = "ok" if correcto else ("FALSA ALARMA" if clase == "real"
                                     else "no senala")
        if banda == "Inconclusive Evidence":
            ver = "inconcluso"
        print(f"  {etiqueta:27s} {nombre[:26]:26s} "
              f"{score if score is None else round(score, 4)!s:>7s} "
              f"{banda:22s} {ver:10s}")
        filas.append({"fuente": etiqueta, "clase": clase, "archivo": nombre,
                      "score": score, "banda": banda, "veredicto": ver,
                      "rostros": rostros, "content_type": tipo})

    salida = ROOT / "reports" / "prueba_extremo_a_extremo.json"
    salida.write_text(json.dumps(
        {"generado": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "n": len(filas), "fallos": fallos, "filas": filas},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  tareas fallidas: {fallos}")
    print(f"  -> {salida}")
    return 0 if fallos == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
