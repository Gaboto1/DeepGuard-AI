# -*- coding: utf-8 -*-
"""
Tests del meta-ensemble v3: construccion del vector de features y enrutamiento
de cabezales segun el tipo de contenido.

Son funciones puras (no cargan el .joblib ni la GPU), salvo los tests marcados
que construyen un MetaEnsemble con cabezales simulados.
"""
import numpy as np
import pytest

import app.models.meta_ensemble as me
from app.models.meta_ensemble import (
    MetaEnsemble,
    build_feature_vector,
)


# ── build_feature_vector ─────────────────────────────────────────────────────

def test_vector_respeta_el_orden_de_feature_cols():
    """El orden lo dicta feature_cols, no el orden del diccionario de scores."""
    scores = {"sdxl_detector": 0.10, "ai_art_detector": 0.90, "efficientnet_ffpp": 0.50}
    v = build_feature_vector(
        scores, ["ai_art_detector", "sdxl_detector", "efficientnet_ffpp"]
    )
    assert v.shape == (1, 3)
    assert list(v[0]) == [0.90, 0.10, 0.50]


def test_score_ausente_se_rellena_con_medio():
    """Un detector sin score entra como 0.5 (no informativo), igual que en training."""
    v = build_feature_vector({"sdxl_detector": 0.8}, ["sdxl_detector", "siglip_deepfake"])
    assert list(v[0]) == [0.8, 0.5]


def test_score_none_se_trata_como_ausente():
    v = build_feature_vector(
        {"sdxl_detector": 0.8, "ai_art_detector": None}, ["sdxl_detector", "ai_art_detector"]
    )
    assert list(v[0]) == [0.8, 0.5]


def test_sdxl_x_aiart_replica_el_entrenamiento():
    """sdxl_x_aiart = sdxl.fillna(0.5) * aiart.fillna(0.5)"""
    v = build_feature_vector(
        {"sdxl_detector": 0.4, "ai_art_detector": 0.5}, ["sdxl_x_aiart"]
    )
    assert v[0][0] == pytest.approx(0.20)

    # con el arte ausente, el factor es 0.5
    v2 = build_feature_vector({"sdxl_detector": 0.4}, ["sdxl_x_aiart"])
    assert v2[0][0] == pytest.approx(0.20)


def test_robust_mean_es_la_mediana_de_stat_keys():
    """
    robust_mean se calcula como nanmedian sobre stat_keys — pese al nombre, el
    entrenamiento usa la mediana, no la media.
    """
    scores = {
        "sdxl_detector": 0.10, "ai_art_detector": 0.20,
        "efficientnet_ffpp": 0.30, "ai_human_detector": 0.90,
    }
    v = build_feature_vector(scores, ["robust_mean"])
    assert v[0][0] == pytest.approx(np.median([0.10, 0.20, 0.30, 0.90]))


def test_robust_mean_ignora_los_ausentes():
    scores = {"sdxl_detector": 0.10, "efficientnet_ffpp": 0.30}
    v = build_feature_vector(
        scores, ["robust_mean"],
        stat_keys=["sdxl_detector", "ai_art_detector", "efficientnet_ffpp"],
    )
    assert v[0][0] == pytest.approx(0.20)  # mediana de [0.10, 0.30]


def test_reliable_std_es_cero_con_un_solo_valor():
    v = build_feature_vector(
        {"sdxl_detector": 0.7}, ["reliable_std"],
        stat_keys=["sdxl_detector", "ai_art_detector"],
    )
    assert v[0][0] == 0.0


def test_stat_keys_personalizadas_cambian_las_derivadas():
    """El cabezal sin-arte usa otras stat_keys; el vector debe reflejarlo."""
    scores = {
        "sdxl_detector": 0.10, "ai_art_detector": 0.99,
        "efficientnet_ffpp": 0.30, "ai_human_detector": 0.50,
    }
    con_arte = build_feature_vector(
        scores, ["robust_mean"],
        stat_keys=["sdxl_detector", "ai_art_detector", "efficientnet_ffpp", "ai_human_detector"],
    )
    sin_arte = build_feature_vector(
        scores, ["robust_mean"],
        stat_keys=["sdxl_detector", "efficientnet_ffpp", "ai_human_detector"],
    )
    assert con_arte[0][0] != sin_arte[0][0]
    assert sin_arte[0][0] == pytest.approx(0.30)  # mediana de [0.10, 0.30, 0.50]


# ── enrutamiento de cabezales ────────────────────────────────────────────────

class _FakeHead:
    """Cabezal simulado que devuelve un valor fijo y registra lo que recibio."""

    def __init__(self, tag, value=0.5, available=True):
        self.tag = tag
        self.temperature = 1.0
        self.available = available
        self._value = value
        self.last_scores = None

    def predict_proba(self, scores):
        self.last_scores = scores
        return self._value


@pytest.fixture
def meta():
    m = MetaEnsemble()
    m._loaded = True  # evita tocar el disco
    return m


def test_la_politica_por_defecto_es_gated(meta):
    """
    El valor por defecto es "gated": el arte IA participa en contenido
    fotografico y queda fuera en obra grafica.

    Fue "always_separate" hasta que se midio su efecto sobre fotografia real
    recomprimida: las falsas alarmas pasaban del 4,3 % al 17,1 % porque el
    detector de arte IA es la senal mas robusta a la compresion del conjunto.
    Ver el comentario de AI_ART_POLICY en meta_ensemble.py.
    """
    assert me.AI_ART_POLICY == "gated"
    meta._full = _FakeHead("full", 0.80)
    meta._noart = _FakeHead("noart", 0.20)

    prob_foto, info_foto = meta.predict({"sdxl_detector": 0.8}, is_artwork=False)
    assert info_foto["head"] == "full"
    assert info_foto["ai_art_excluded"] is False
    assert info_foto["content_track"] == "photographic"
    assert prob_foto == pytest.approx(0.80)

    prob_arte, info_arte = meta.predict({"sdxl_detector": 0.8}, is_artwork=True)
    assert info_arte["head"] == "noart"
    assert info_arte["ai_art_excluded"] is True
    assert info_arte["content_track"] == "artwork"
    assert prob_arte == pytest.approx(0.20)


def test_politica_always_separate_excluye_tambien_en_fotografia(meta, monkeypatch):
    """La politica alternativa sigue disponible y deja el arte IA siempre fuera."""
    monkeypatch.setattr(me, "AI_ART_POLICY", "always_separate")
    meta._full = _FakeHead("full", 0.80)
    meta._noart = _FakeHead("noart", 0.20)

    _, info_foto = meta.predict({"sdxl_detector": 0.8}, is_artwork=False)
    assert info_foto["head"] == "noart"
    assert info_foto["ai_art_excluded"] is True


def test_ai_art_is_excluded_refleja_la_politica(monkeypatch):
    """Las correcciones forenses y el meta-ensemble leen la misma fuente."""
    monkeypatch.setattr(me, "AI_ART_POLICY", "always_separate")
    assert me.ai_art_is_excluded(is_artwork=False) is True
    assert me.ai_art_is_excluded(is_artwork=True) is True

    monkeypatch.setattr(me, "AI_ART_POLICY", "gated")
    assert me.ai_art_is_excluded(is_artwork=False) is False
    assert me.ai_art_is_excluded(is_artwork=True) is True


def test_obra_grafica_usa_el_cabezal_sin_arte(meta):
    meta._full = _FakeHead("full", 0.80)
    meta._noart = _FakeHead("noart", 0.20)
    prob, info = meta.predict({"sdxl_detector": 0.8}, is_artwork=True)
    assert info["head"] == "noart"
    assert info["ai_art_excluded"] is True
    assert info["content_track"] == "artwork"
    assert prob == pytest.approx(0.20)


def test_sin_cabezal_sin_arte_el_completo_recibe_el_arte_neutralizado(meta):
    """
    Si no existe el cabezal especializado, se usa el completo pero el score de
    arte IA entra como ausente (-> 0.5), de modo que no influye en el resultado.
    """
    meta._full = _FakeHead("full", 0.70)
    meta._noart = _FakeHead("noart", available=False)
    _, info = meta.predict(
        {"sdxl_detector": 0.8, "ai_art_detector": 0.99}, is_artwork=True
    )
    assert info["head"] == "full"
    assert info["ai_art_excluded"] is True
    assert meta._full.last_scores["ai_art_detector"] is None


def test_sin_ningun_cabezal_cae_al_fallback(meta):
    meta._full = _FakeHead("full", available=False)
    meta._noart = _FakeHead("noart", available=False)
    prob, info = meta.predict({"sdxl_detector": 0.8, "ai_art_detector": 0.9})
    assert info["method"] == "fallback_weights"
    assert 0.0 <= prob <= 1.0


def test_el_arte_ia_no_cambia_el_score_en_obra_grafica(meta):
    """
    Garantia central del requisito: con el contenido marcado como obra grafica,
    mover el score de arte IA de un extremo al otro no altera el porcentaje.
    """
    meta._full = _FakeHead("full", 0.70)
    meta._noart = _FakeHead("noart", available=False)
    bajo, _ = meta.predict(
        {"sdxl_detector": 0.3, "ai_art_detector": 0.01}, is_artwork=True
    )
    alto, _ = meta.predict(
        {"sdxl_detector": 0.3, "ai_art_detector": 0.99}, is_artwork=True
    )
    assert bajo == pytest.approx(alto)
