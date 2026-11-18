# -*- coding: utf-8 -*-
"""
El panel del worker (scripts/panel_worker.py) deduce su estado de la salida
real del worker. Estas lineas estan copiadas de reports/worker.log: si alguien
cambia el texto de un log del que depende el panel, esta prueba lo dice.
"""
import importlib.util
from pathlib import Path

RUTA = Path(__file__).resolve().parents[2] / "scripts" / "panel_worker.py"
_spec = importlib.util.spec_from_file_location("panel_worker", RUTA)
pw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw)

ARRANQUE = """\
2026-11-17 15:05:12.962 | INFO     | app.tasks.analysis_tasks:init_worker_models:64 - === Worker DeepScan: inicializando modelos GPU ===
2026-11-17 15:05:23.199 | SUCCESS  | app.models.deepfake_detector:load:138 - [face-deepfake-vit] prithivMLmods/Deep-Fake-Detector-v2-Model | labels={0: 'Realism', 1: 'Deepfake'}
2026-11-17 15:05:25.429 | SUCCESS  | app.models.deepfake_detector:load:138 - [sdxl-detector] Organika/sdxl-detector | labels={0: 'artificial', 1: 'human'}
2026-11-17 15:05:29.528 | SUCCESS  | app.models.deepfake_detector:load:328 - [CLIP-C] CLIP ViT-L/14 + mlp_256 | T=0.576
2026-11-17 15:05:32.602 | SUCCESS  | app.models.deepfake_detector:load:138 - [ai-art-detector] haywoodsloan/ai-image-detector-deploy | labels={0: 'artificial', 1: 'real'}
2026-11-17 15:05:34.621 | SUCCESS  | app.models.deepfake_detector:load:138 - [siglip-deepfake] prithivMLmods/Deepfake-Detect-Siglip2 | labels={0: 'Fake', 1: 'Real'}
2026-11-17 15:05:36.724 | SUCCESS  | app.models.deepfake_detector:load:138 - [ai-human-detector] umm-maybe/AI-image-detector | labels={0: 'artificial', 1: 'human'}
2026-11-17 15:05:37.358 | SUCCESS  | app.models.face_detector:load:43 - Face detector (MTCNN) loaded on cuda
2026-11-17 15:05:37.491 | SUCCESS  | app.models.meta_ensemble:load:235 - [meta:full] LGBMClassifier | T=0.950 | 7 features
2026-11-17 15:05:37.495 | SUCCESS  | app.models.meta_ensemble:load:235 - [meta:face] LGBMClassifier | T=0.894 | 5 features
2026-11-17 15:06:11.224 | SUCCESS  | app.services.semantic_inspection_service:load:189 - LLaVA listo: llava-hf/llava-1.5-7b-hf | Cuant.: 4-bit NF4 + bfloat16 | VRAM usada: 7.14GB
[2026-11-17 15:06:25,152: INFO/MainProcess] deepguard-worker@DESKTOP-RDABUG1 ready.
""".splitlines()

RECIBIDA = "[2026-11-17 15:06:47,752: INFO/MainProcess] Task app.tasks.analysis_tasks.analyze_image_task[0dca934d-364c-4bd1-a826-b185a0bff13a] received"
OK = ("[2026-11-17 15:07:12,985: INFO/MainProcess] Task app.tasks.analysis_tasks.analyze_image_task"
      "[0dca934d-364c-4bd1-a826-b185a0bff13a] succeeded in 25.230802899983246s: {'status': 'SUCCESS', "
      "'task_id': '0dca934d', 'file_type': 'image', 'fake_probability': 0.30, 'manipulation_probability': 30.0, "
      "'evidence_level': 'Low Evidence'}")
LATIDO = "2026-11-17 15:06:43.206 | DEBUG    | app.tasks.analysis_tasks:_heartbeat_loop:50 - Heartbeat escrito (TTL=90s)"


def test_el_arranque_completo_marca_todos_los_pasos_y_queda_listo():
    L = pw.Lector()
    pasos = []
    for linea in ARRANQUE:
        L.procesar(linea)
        pasos.append(L.paso_actual())
    assert L.hechos == set(pw.CLAVES)
    assert L.listo and L.paso_actual() is None
    # Durante la carga el paso activo avanza en orden.
    assert pasos[0] == "vit" and pasos[1] == "sdxl" and pasos[-2] == "cola"


def test_un_analisis_se_cuenta_con_duracion_y_resultado():
    L = pw.Lector()
    for linea in ARRANQUE:
        L.procesar(linea)
    L.procesar(RECIBIDA)
    assert len(L.en_curso) == 1
    L.procesar(OK)
    assert not L.en_curso and L.completados == 1
    a = L.actividad[0]
    assert a["estado"] == "ok" and round(a["dur"], 1) == 25.2 and a["pct"] == 30.0
    assert pw.banda(a["pct"]) == "baja"


def test_un_fallo_se_cuenta_como_error():
    L = pw.Lector()
    L.procesar(RECIBIDA)
    L.procesar(RECIBIDA.replace("received", "raised unexpected: RuntimeError('CUDA out of memory')"))
    assert L.errores == 1 and not L.en_curso
    assert "CUDA" in L.ultimo_error


def test_los_avisos_graves_se_detectan():
    L = pw.Lector()
    L.procesar("2026-11-17 15:05:37.495 | ERROR    | app.models.meta_ensemble:load:243 - "
               "[meta:face] CARGA FALLIDA, se usaran pesos fijos")
    L.procesar("2026-11-17 15:05:37.514 | WARNING  | app.services.semantic_inspection_service:load:166 - "
               "  VRAM INSUFICIENTE: LLaVA necesita ~6.5GB")
    assert {"meta", "llava"} <= L.fallidos and len(L.avisos) == 2


def test_la_vista_simple_oculta_el_ruido_y_resume_los_analisis():
    assert pw.resumen_simple(LATIDO) is None
    assert pw.resumen_simple("Loading weights: 100%|##########| 200/200") is None
    hora, nivel, msg = pw.resumen_simple(OK)
    assert hora == "15:07:12" and nivel == "SUCCESS"
    assert "25,2 s" in msg and "30 %" in msg and "baja" in msg and "{" not in msg


def test_las_bandas_coinciden_con_la_pagina():
    assert [pw.banda(x) for x in (5, 25, 50, 70, 95)] == [
        "muy baja", "baja", "inconclusa", "moderada", "fuerte"]
