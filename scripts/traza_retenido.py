# -*- coding: utf-8 -*-
"""
Graba, imagen a imagen, todo lo que entra a la fusion del sistema.

Para que sirve
--------------
Cada idea sobre la fusion -otra mezcla de ramas, otros cabezales, otra regla
forense- costaba una pasada de 17 minutos de GPU sobre el retenido. Pero lo
caro de esa pasada son los seis detectores, que NO cambian entre una idea y la
siguiente: lo que cambia es la aritmetica que viene despues.

Este guion hace la pasada cara una sola vez y guarda, por imagen, las entradas
exactas de cada funcion de la fusion: los argumentos de cada llamada a
`_calibrated_combine` (imagen completa y recorte de rostro), el resultado del
detector OOD y lo que recibe `apply_forensic_corrections`. Con esa traza,
`scripts/repetir_fusion.py` reevalua cualquier variante en segundos y de forma
EXACTA, porque no reimplementa nada: vuelve a llamar a las mismas funciones de
produccion con las entradas grabadas.

Que conjunto se traza, y por que importa
----------------------------------------
`--desde` y `--n` eligen el tramo del barajado con semilla 13, el mismo que usa
`scripts/eval_heldout.py`. La medicion oficial toma los 500 primeros de cada
fuente. Trazando a partir del 500 se obtiene un tramo **disjunto**: archivos
del retenido que la medicion oficial nunca toca.

Ese tramo es el conjunto de DESARROLLO. Poder evaluar variantes al instante
multiplica la tentacion de ajustar contra el test, que es el defecto que este
proyecto lleva documentado desde la seccion 4 del informe v4. La disciplina es:
las variantes se comparan sobre desarrollo, y la muestra oficial se mira UNA
vez, con el criterio de adopcion, para la variante ya elegida.

Limite que hay que declarar: el tramo de desarrollo comparte *generadores* con
el de test (FLUX, DALL-E 3). Los detectores siguen sin haber visto ninguno,
pero la logica de fusion elegida asi ya no es ciega a ellos.

Salida: reports/traza_<nombre>.json  (no se versiona: se regenera con esto)

Uso
---
    python scripts/traza_retenido.py --desde 500 --n 400 --nombre dev
    python scripts/traza_retenido.py --desde 0   --n 500 --nombre oficial
"""
import argparse
import inspect
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "models"))
os.environ.setdefault("HF_HOME", str(ROOT / "models"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(str(BACKEND))

HELDOUT = ROOT / "data" / "heldout"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
BOOLEANOS = {"face", "is_artwork"}


def tramo(base: Path, desde: int, n: int, seed: int = 13) -> list[Path]:
    """El mismo barajado que eval_heldout.recoger, pero desde un desplazamiento."""
    import random
    files = sorted(p for p in base.rglob("*") if p.suffix.lower() in EXTS)
    random.Random(seed).shuffle(files)
    return files[desde:desde + n]


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=500)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--nombre", default="dev")
    ap.add_argument("--extra", action="append", default=[],
                    help="imagen suelta que se traza aparte (fuente 'extra')")
    args = ap.parse_args()

    tareas = []
    for clase_dir in sorted(HELDOUT.iterdir()):
        if not clase_dir.is_dir():
            continue
        label = 0 if clase_dir.name == "real" else 1
        for fuente_dir in sorted(clase_dir.iterdir()):
            if not fuente_dir.is_dir():
                continue
            got = tramo(fuente_dir, args.desde, args.n)
            tareas.extend((fuente_dir.name, label, p) for p in got)
            print(f"  {fuente_dir.name:12s} label={label}  {len(got):5d}  "
                  f"(barajado[{args.desde}:{args.desde + args.n}])")
    for e in args.extra:
        tareas.append(("extra", -1, Path(e)))

    print("\nCargando el sistema completo (via de produccion)...")
    from app.models.deepfake_detector import DeepfakeDetector
    from app.models.face_detector import FaceDetector
    from app.models.meta_ensemble import MetaEnsemble
    det = DeepfakeDetector.get_instance()
    det.load()
    FaceDetector.get_instance().load()
    MetaEnsemble.get_instance().load()
    from app.models.deepfake_detector import (
        _model_a, _model_b, _model_c, _model_d, _model_e, _model_f)
    faltan = [n for n, m in zip("ABCDEF",
              (_model_a, _model_b, _model_c, _model_d, _model_e, _model_f))
              if not getattr(m, "_loaded", False)]
    if faltan:
        raise SystemExit(f"ABORTA: detectores sin cargar: {faltan}")

    from app.services import image_service
    from app.utils.helpers import get_evidence_level

    # ── Espias sobre las referencias que image_service ya importo ───────────
    cc_orig = image_service._calibrated_combine
    ood_orig = image_service.apply_ood_penalty
    corr_orig = image_service.apply_forensic_corrections
    firma = inspect.signature(cc_orig)
    buf = {"llamadas": [], "ood": None, "corr": None}

    def espia_cc(*a, **k):
        out = cc_orig(*a, **k)
        b = firma.bind(*a, **k)
        b.apply_defaults()
        d = {kk: (bool(v) if kk in BOOLEANOS else _num(v))
             for kk, v in b.arguments.items()}
        d["ens"] = float(out[0])
        buf["llamadas"].append(d)
        return out

    def espia_ood(score, ood_result):
        out = ood_orig(score, ood_result)
        buf["ood"] = {
            "is_ood": bool(ood_result.get("is_ood", False)),
            "penalty_alpha": float(ood_result.get("penalty_alpha", 0.0) or 0.0),
            "entra": float(score), "sale": float(out),
        }
        return out

    def espia_corr(final_score, model_scores, ood_result, ai_art_excluded=False):
        out = corr_orig(final_score, model_scores, ood_result,
                        ai_art_excluded=ai_art_excluded)
        buf["corr"] = {
            "entra": float(final_score),
            "model_scores": {k: _num(v) for k, v in model_scores.items()},
            "ai_art_excluded": bool(ai_art_excluded),
            "sale": float(out[0]), "regla": out[1],
        }
        return out

    image_service._calibrated_combine = espia_cc
    image_service.apply_ood_penalty = espia_ood
    image_service.apply_forensic_corrections = espia_corr
    print(f"Listo -- 6/6 detectores en {det.device_name}.\n")

    filas, fallos = [], 0
    t0 = time.time()
    for i, (fuente, label, ruta) in enumerate(tareas, 1):
        buf["llamadas"], buf["ood"], buf["corr"] = [], None, None
        try:
            res = image_service._run_image_analysis(ruta)
        except Exception as e:
            fallos += 1
            print(f"  fallo {ruta.name}: {type(e).__name__}: {e}")
            continue
        p = res.get("fake_probability")
        if p is None or not buf["llamadas"] or buf["corr"] is None:
            fallos += 1
            continue
        # Orden de las llamadas a _calibrated_combine dentro de
        # _run_image_analysis: [imagen completa] [recorte de rostro, si lo hay]
        # [meta-info final, que no decide nada]. La ultima se descarta.
        ll = buf["llamadas"]
        completa = ll[0]
        rostro = ll[1] if len(ll) >= 3 and ll[1]["face"] else None
        filas.append({
            "fuente": fuente, "label": label, "archivo": ruta.name,
            "completa": completa, "rostro": rostro,
            "ood": buf["ood"], "corr": buf["corr"],
            "final": float(p),
            "banda": str(res.get("evidence_level") or get_evidence_level(p)),
            "rostros": int(res.get("faces_detected") or 0),
        })
        if i % 50 == 0:
            m = (time.time() - t0) / 60
            print(f"  [{i}/{len(tareas)}] {m:.1f}min  "
                  f"ETA {m / i * (len(tareas) - i):.1f}min", flush=True)

    image_service._calibrated_combine = cc_orig
    image_service.apply_ood_penalty = ood_orig
    image_service.apply_forensic_corrections = corr_orig

    salida = ROOT / "reports" / f"traza_{args.nombre}.json"
    salida.write_text(json.dumps({
        "generado": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "desde": args.desde, "n_por_fuente": args.n,
        "semilla_barajado": 13, "n": len(filas), "fallos": fallos,
        "nota": ("Entradas exactas de la fusion por imagen. 'completa' y "
                 "'rostro' son los argumentos de _calibrated_combine; 'corr' "
                 "lo que recibio apply_forensic_corrections."),
        "filas": filas,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"\n  {len(filas)} imagenes trazadas, {fallos} fallos, "
          f"{(time.time() - t0) / 60:.1f} min")
    print(f"  -> {salida}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
