# -*- coding: utf-8 -*-
"""
El historial global no debe exponer los analisis de todos los usuarios.

/api/v1/history devolvia, sin pedir identidad, los resultados de cualquiera
que hubiera analizado algo. Desde la auditoria del 17 de noviembre de 2026
queda desactivado salvo que se active a proposito para depurar en local.
"""
import asyncio

import httpx

from app.main import app


def _get(path):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as c:
            return await c.get(path)
    return asyncio.run(run())


def test_el_historial_global_esta_desactivado_por_defecto(monkeypatch):
    monkeypatch.delenv("HISTORIAL_PUBLICO", raising=False)
    r = _get("/api/v1/history")
    assert r.status_code == 404
    assert r.json()["error"] == "no_disponible"


def test_se_puede_activar_a_proposito_para_depurar(monkeypatch):
    monkeypatch.setenv("HISTORIAL_PUBLICO", "true")
    r = _get("/api/v1/history?limit=1")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
