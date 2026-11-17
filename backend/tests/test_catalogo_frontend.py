# -*- coding: utf-8 -*-
"""
La copia del catalogo en el frontend debe coincidir con el backend.

frontend/src/components/Planes.tsx lleva una copia local de los planes para
que se vean al instante aunque la API este dormida. Si alguien cambia un precio
o una cuota en backend/app/billing/plans.py y no en la copia, la pagina
mostraria un precio y cobraria otro. Esta prueba lo impide.
"""
import re
from pathlib import Path

from app.billing import plans

TSX = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "Planes.tsx"
CAMPOS = ("analisis_por_dia", "analisis_por_mes", "prioridad", "historial_dias",
          "precio_clp", "precio_anual_clp", "informe_pdf_sellado", "acceso_api",
          "analisis_por_lote", "video")


def _copia_local() -> dict:
    t = TSX.read_text(encoding="utf-8")
    bloque = t[t.index("const CATALOGO_LOCAL"):]
    bloque = bloque[:bloque.index("\n};")]
    planes = {}
    for m in re.finditer(r"\{ id: '(\w+)'(.*?)\}", bloque, flags=re.S):
        datos = {}
        for campo in CAMPOS:
            v = re.search(rf"{campo}: ([\w.]+)", m.group(2)).group(1)
            datos[campo] = {"null": None, "true": True, "false": False}.get(v, v)
            if isinstance(datos[campo], str):
                datos[campo] = int(datos[campo])
        planes[m.group(1)] = datos
    return planes


def test_la_copia_local_tiene_los_mismos_planes():
    assert set(_copia_local()) == set(plans.PLANES)


def test_precios_y_cuotas_coinciden():
    local = _copia_local()
    for pid, p in plans.PLANES.items():
        for campo in CAMPOS:
            assert local[pid][campo] == getattr(p, campo), (
                f"{pid}.{campo}: frontend {local[pid][campo]!r} "
                f"vs backend {getattr(p, campo)!r}")


def test_las_descripciones_coinciden():
    """
    Tambien el texto: el 17 de noviembre la copia del backend decia "un ano de
    historial" (sin tilde) y la pagina lo mostraba tal cual.
    """
    t = TSX.read_text(encoding="utf-8")
    for pid, p in plans.PLANES.items():
        m = re.search(rf"\{{ id: '{pid}'.*?descripcion: '([^']*)'", t, flags=re.S)
        assert m and m.group(1) == p.descripcion, pid
