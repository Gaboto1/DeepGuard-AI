# -*- coding: utf-8 -*-
"""
Las bibliotecas que necesitan los cabezales en produccion deben estar en
requirements.txt, con la version con que se serializaron.

Hasta el 17 nov 2026 no estaban scikit-learn, joblib ni lightgbm: el worker
funcionaba porque estaban instaladas a mano, pero una instalacion nueva no
cargaba ningun cabezal y caia en silencio a pesos fijos.
"""
import re
from importlib.metadata import version
from pathlib import Path

import joblib

RAIZ = Path(__file__).resolve().parents[1]
REQ = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
META = RAIZ.parent / "models" / "meta_ensemble"

# Modulo raiz del estimador -> paquete de pip que lo provee.
PAQUETE = {"sklearn": "scikit-learn", "lightgbm": "lightgbm", "xgboost": "xgboost"}


def _pin(paquete):
    m = re.search(rf"^{re.escape(paquete)}==([\w.]+)", REQ, flags=re.M | re.I)
    return m.group(1) if m else None


def test_joblib_esta_fijado():
    assert _pin("joblib") == version("joblib")


def test_cada_cabezal_de_produccion_tiene_su_biblioteca_fijada():
    for nombre in ("meta_classifier", "meta_classifier_noart", "meta_classifier_face"):
        d = joblib.load(META / f"{nombre}.joblib")
        clf = d.get("clf", d.get("model"))
        raiz = type(clf).__module__.split(".")[0]
        paquete = PAQUETE.get(raiz, raiz)
        assert _pin(paquete) is not None, f"{nombre}: falta {paquete} en requirements.txt"
        assert _pin(paquete) == version(paquete), (
            f"{nombre}: requirements fija {paquete}=={_pin(paquete)} pero el "
            f"entorno que lo serializo tiene {version(paquete)}")
    # Los estimadores de LightGBM y XGBoost usan la interfaz de scikit-learn.
    assert _pin("scikit-learn") == version("scikit-learn")
