# -*- coding: utf-8 -*-
"""
Tests de la resolucion del backbone ViT para Grad-CAM.

La ruta a los bloques transformer cambia entre versiones de transformers
(``vit.encoder.layer`` en las antiguas, ``vit.layers`` en las nuevas). El codigo
fijaba la primera, de modo que al actualizar la libreria TODOS los mapas de
calor empezaron a fallar en silencio: la excepcion se capturaba y grad_cam
devolvia None sin que nada lo reportase.

No requieren GPU ni pesos: se usan dobles con la forma estructural de cada
version.
"""
import types

from app.models.deepfake_detector import _HFModel


def _make(model_obj) -> _HFModel:
    m = _HFModel([], "test")
    m.model = model_obj
    return m


def test_ruta_nueva_vit_layers():
    """transformers reciente: los bloques cuelgan de vit.layers."""
    bloques = ["b0", "b1", "b2"]
    modelo = types.SimpleNamespace(vit=types.SimpleNamespace(layers=bloques))
    assert _make(modelo)._vit_blocks() == bloques


def test_ruta_antigua_vit_encoder_layer():
    """transformers antiguo: los bloques cuelgan de vit.encoder.layer."""
    bloques = ["b0", "b1"]
    modelo = types.SimpleNamespace(
        vit=types.SimpleNamespace(encoder=types.SimpleNamespace(layer=bloques))
    )
    assert _make(modelo)._vit_blocks() == bloques


def test_la_ruta_antigua_tiene_prioridad_si_ambas_existen():
    antigua = ["viejo"]
    modelo = types.SimpleNamespace(
        vit=types.SimpleNamespace(
            encoder=types.SimpleNamespace(layer=antigua), layers=["nuevo"]
        )
    )
    assert _make(modelo)._vit_blocks() == antigua


def test_modelo_sin_backbone_vit_devuelve_none():
    """Un backbone Swin o EfficientNet no expone .vit — no hay mapa de calor."""
    modelo = types.SimpleNamespace(swin=object())
    assert _make(modelo)._vit_blocks() is None


def test_vit_sin_bloques_reconocibles_devuelve_none():
    modelo = types.SimpleNamespace(vit=types.SimpleNamespace(embeddings=object()))
    assert _make(modelo)._vit_blocks() is None


def test_grad_cam_sin_cargar_devuelve_none():
    """Sin modelo cargado no se intenta generar nada."""
    m = _HFModel([], "test")
    assert m._loaded is False
    assert m.grad_cam(image=None) is None
