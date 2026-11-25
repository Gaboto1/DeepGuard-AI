# -*- coding: utf-8 -*-
"""
El archivo del usuario no se conserva: ni en disco ni dentro del resultado en
Redis. La PPT, el informe y la pagina lo afirman; hasta el 25 nov 2026 no era
cierto (mas de cien originales en disco y la imagen en base64 en cada
resultado por `result_extended`).
"""
import os
import time

import pytest
from celery.exceptions import Retry

from app.celery_app import celery_app
from app.services import retencion
from app.tasks import analysis_tasks as at

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def test_redis_no_guarda_los_argumentos_de_la_tarea():
    assert not celery_app.conf.result_extended

    class Peticion:
        task, args, hostname, retries, delivery_info = "t", [], "h", 0, None
        group = parent_id = stamps = None
        kwargs = {"file_content_b64": "IMAGEN"}
        children = []
    meta = celery_app.backend._get_result_meta({"ok": 1}, "SUCCESS", None, Peticion())
    assert "IMAGEN" not in str(meta)


def test_el_original_se_borra_aunque_el_analisis_falle(tmp_path, monkeypatch):
    f = tmp_path / "x.png"
    visto = {}

    def explota(path):
        visto["existia"] = path.exists()
        raise RuntimeError("fallo durante el analisis")

    monkeypatch.setattr("app.services.custody_service.compute_file_sha256", explota)
    monkeypatch.setattr(at.analyze_image_task, "update_state", lambda *a, **k: None)
    monkeypatch.setattr(at.analyze_image_task, "retry",
                        lambda *a, **k: Retry("reintento"))
    with pytest.raises(Retry):
        at.analyze_image_task.run("t", str(f), "x.png", file_content_b64=PNG)
    assert visto["existia"] and not f.exists()


def test_se_conserva_si_el_reintento_no_podria_reconstruirlo(tmp_path):
    f = tmp_path / "x.png"
    f.write_bytes(b"x")
    at._liberar_original(f, terminado=False, reconstruible=False)
    assert f.exists()
    at._liberar_original(f, terminado=True, reconstruible=False)
    assert not f.exists()


def test_el_barrido_solo_toca_lo_vencido_y_lo_que_le_corresponde(tmp_path):
    viejo, nuevo, ajeno = tmp_path / "a.PNG", tmp_path / "b.png", tmp_path / ".gitkeep"
    for p in (viejo, nuevo, ajeno):
        p.write_bytes(b"x")
    hace_2h = time.time() - 7200
    os.utime(viejo, (hace_2h, hace_2h))
    os.utime(ajeno, (hace_2h, hace_2h))
    assert retencion.purgar_vencidos(tmp_path, 3600, retencion._EXT_ORIGINALES) == 1
    assert not viejo.exists() and nuevo.exists() and ajeno.exists()


def test_borrar_nunca_lanza(tmp_path):
    assert retencion.borrar_original(tmp_path / "no_existe.png")
