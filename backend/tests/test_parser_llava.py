# -*- coding: utf-8 -*-
"""
El interprete de la respuesta de LLaVA debe leer el score aunque las claves
vengan escapadas al estilo Markdown.

Caso real del 17 de noviembre de 2026: LLaVA devolvio
{"risk\_score": 80, "semantic\_observations": "..."} y el sistema uso 50, el
valor por defecto, ademas de mostrar el JSON crudo como observaciones.
"""
import warnings

from app.services.semantic_inspection_service import _parse_llava_response


def test_claves_escapadas_al_estilo_markdown():
    raw = ('{"risk\_score": 80, "semantic\_observations": '
           '"El personaje tiene una apariencia animada."}')
    score, obs = _parse_llava_response(raw)
    assert score == 80
    assert obs == "El personaje tiene una apariencia animada."
    assert "\\" not in obs and "risk" not in obs


def test_json_limpio_sigue_funcionando():
    score, obs = _parse_llava_response(
        '{"risk_score": 15, "semantic_observations": "Escena coherente."}')
    assert (score, obs) == (15, "Escena coherente.")


def test_texto_extra_alrededor_del_json():
    score, _ = _parse_llava_response(
        'Respuesta: {"risk\_score": 64, "semantic\_observations": "x"} fin')
    assert score == 64


def test_el_modulo_no_tiene_escapes_invalidos():
    """El arreglo no debe introducir avisos de escape invalido."""
    import importlib, app.services.semantic_inspection_service as m
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        importlib.reload(m)
