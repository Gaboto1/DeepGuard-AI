"""
Orquestador del conjunto v3: descarga, reentrenamiento y evaluacion.

Se ejecuta sin intervencion. Cada etapa deja su propio registro y el
orquestador continua aunque una falle, para que un fallo tardio no invalide
el trabajo ya hecho. Todas las etapas son reanudables.

    1. Descarga      151.000 imagenes nuevas (4 fuentes)
    2. Embeddings    CLIP sobre el conjunto ampliado  -> probe
    3. Probe         reentrena el detector C
    4. Scoring       6 detectores sobre una muestra   -> meta-ensemble
    5. Meta          reentrena los tres cabezales
    6. Evaluacion    medicion end-to-end

Uso:  python scripts/pipeline_v3.py [--desde N]
"""
import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "backend" / "venv" / "Scripts" / "python.exe"
REPORTS = ROOT / "reports"
REGISTRO = REPORTS / "pipeline_v3.log"


def log(msg):
    linea = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(linea, flush=True)
    with open(REGISTRO, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


def etapa(num, nombre, cmd, timeout_min=600):
    log("=" * 68)
    log(f"ETAPA {num}: {nombre}")
    log("=" * 68)
    t0 = time.time()
    salida = REPORTS / f"pipeline_v3_etapa{num}.log"
    try:
        with open(salida, "w", encoding="utf-8") as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                               cwd=str(ROOT), timeout=timeout_min * 60)
        ok = r.returncode == 0
    except subprocess.TimeoutExpired:
        log(f"ETAPA {num}: AGOTO EL TIEMPO ({timeout_min} min)")
        return False
    except Exception as e:
        log(f"ETAPA {num}: ERROR {type(e).__name__}: {e}")
        return False
    mins = (time.time() - t0) / 60
    log(f"ETAPA {num}: {'OK' if ok else 'FALLO (codigo %d)' % r.returncode} "
        f"en {mins:.1f} min  -> {salida.name}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=1)
    args = ap.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    log("")
    log("#" * 68)
    log(f"#  PIPELINE v3 — inicio {datetime.now():%Y-%m-%d %H:%M}")
    log("#" * 68)
    t_total = time.time()

    etapas = [
        (1, "Descarga del conjunto v3 (63.000 imagenes nuevas)",
         [str(PY), "scripts/download_dataset_v3.py"], 420),
        (2, "Embeddings CLIP del conjunto ampliado",
         [str(PY), "scripts/extract_clip_embeddings.py", "--batch", "48"], 240),
        (3, "Dominio webcam (rostros y degradacion de captura)",
         [str(PY), "scripts/add_webcam_domain.py"], 120),
        (4, "Reentrenamiento del probe CLIP (detector C)",
         [str(PY), "scripts/train_clip_probe.py"], 180),
        (5, "Scoring con los 6 detectores (40.000 imagenes)",
         [str(PY), "scripts/score_dataset_v2.py", "--batch", "16"], 300),
        (6, "Variantes de compresion para el meta-ensemble",
         [str(PY), "scripts/augment_compresion.py", "--por-clase", "2000"], 180),
        (7, "Caracteristica de nivel de compresion",
         [str(PY), "scripts/add_compression_feature.py"], 120),
        (8, "Recalculo del detector C en los conjuntos del meta",
         [str(PY), "scripts/rescore_model_c.py"], 180),
        (9, "Reentrenamiento de los cabezales del meta-ensemble",
         [str(PY), "scripts/train_meta_dual_head.py"], 120),
        (10, "Bateria de pruebas",
         [str(PY), "-m", "pytest", "backend/tests/", "-q"], 30),
    ]

    # Las etapas 2 y 4 son criticas: sin embeddings ni probe no tiene sentido
    # seguir. La 1 no lo es — si la descarga falla a medias, el resto del
    # encadenamiento todavia mejora el modelo con lo que haya llegado.
    CRITICAS = {2, 4}

    resultados = {}
    for num, nombre, cmd, tmo in etapas:
        if num < args.desde:
            log(f"ETAPA {num}: omitida por --desde")
            continue
        resultados[num] = etapa(num, nombre, cmd, tmo)
        if num in CRITICAS and not resultados[num]:
            log("Etapa critica fallida: se detiene el encadenamiento")
            break

    log("")
    log("#" * 68)
    log(f"#  RESUMEN  ({(time.time()-t_total)/60:.0f} min en total)")
    for num, ok in resultados.items():
        log(f"#    etapa {num}: {'OK' if ok else 'FALLO'}")
    log("#" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
