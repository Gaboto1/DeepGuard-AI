# -*- coding: utf-8 -*-
"""
Tests del veto de consenso del meta-ensemble (MetaEnsemble._consensus_veto).

La funcion es pura respecto a sus parametros (no requiere cargar el modelo
.joblib ni GPU), por lo que se instancia MetaEnsemble() directamente sin
llamar a .load().
"""
import pytest

from app.models.meta_ensemble import MetaEnsemble, VETO_STRENGTH


@pytest.fixture
def meta():
    return MetaEnsemble()


def test_veto_aplica_caso_documentado(meta):
    """SDXL/AI Art muy bajos pero el meta-modelo dice 68% -> el veto corrige."""
    final, applied = meta._consensus_veto(
        meta_prob=0.68,
        scores={"sdxl_detector": 0.01, "ai_art_detector": 0.10},
    )
    expected = 0.055 * VETO_STRENGTH + 0.68 * (1 - VETO_STRENGTH)
    assert applied is True
    assert final == pytest.approx(expected, abs=0.001)
    assert final == pytest.approx(0.305, abs=0.01)


def test_veto_no_aplica_si_robustos_no_son_muy_seguros(meta):
    """Si la media robusta ya supera VETO_THRESHOLD, no hay veto."""
    final, applied = meta._consensus_veto(
        meta_prob=0.68,
        scores={"sdxl_detector": 0.30, "ai_art_detector": 0.40},
    )
    assert applied is False
    assert final == 0.68


def test_veto_no_aplica_si_discrepancia_es_pequena(meta):
    """Meta y robustos coinciden en que es probablemente real -> sin veto."""
    final, applied = meta._consensus_veto(
        meta_prob=0.30,
        scores={"sdxl_detector": 0.10, "ai_art_detector": 0.05},
    )
    assert applied is False
    assert final == 0.30


def test_veto_sin_scores_robustos_disponibles(meta):
    """Si no hay scores de los modelos robustos, no se puede vetar."""
    final, applied = meta._consensus_veto(meta_prob=0.55, scores={})
    assert applied is False
    assert final == 0.55
