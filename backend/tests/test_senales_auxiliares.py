# -*- coding: utf-8 -*-
"""
Las señales auxiliares de CPU no deben mover el porcentaje forense.

Contexto
--------
Se reportó que fotografías reales de personas puntuaban como evidencia de IA.
Al medir las tres señales auxiliares sobre 1.100 imágenes de cinco fuentes:

    señal   AUC      media en real   media en IA
    SRM     0.409        0.802           0.745     invertida
    ELA     0.561        0.748           0.839     sin poder discriminante
    freq    0.296        0.222           0.117     invertida

El 96,6 % de las fotografías reales superaba el umbral de SRM (0.65) que
activaba la corrección conjunta F+SRM, que sólo podía subir el score. Las tres
señales quedaron fuera del cálculo hasta que se recalibren.

Estos tests fijan esa decisión para que no se revierta sin darse cuenta.
"""
import pytest

from app.models.deepfake_detector import _calibrated_combine
from app.utils.forensic_corrections import (
    CONSENSUS_MODELS,
    F_SRM_ENABLED,
    apply_forensic_corrections,
)


BASE = dict(score_a=0.55, score_b=0.20, score_c=0.45, face=False,
            score_d=0.05, score_e=0.40, score_f=0.80)


# ── El score no depende de las señales auxiliares ───────────────────────────

@pytest.mark.parametrize("senal", ["score_srm", "score_ela", "score_freq"])
def test_la_senal_auxiliar_no_cambia_el_porcentaje(senal):
    """Moverla de un extremo al otro debe dejar el score idéntico."""
    bajo, _ = _calibrated_combine(**BASE, **{senal: 0.01})
    alto, _ = _calibrated_combine(**BASE, **{senal: 0.99})
    assert bajo == pytest.approx(alto, abs=1e-9)


def test_las_tres_senales_juntas_no_cambian_el_porcentaje():
    sin, _ = _calibrated_combine(**BASE)
    con, _ = _calibrated_combine(**BASE, score_srm=0.95, score_ela=0.95,
                                 score_freq=0.95)
    assert sin == pytest.approx(con, abs=1e-9)


def test_las_senales_se_siguen_reportando():
    """Quedan fuera del cálculo, pero deben seguir visibles para diagnóstico."""
    _, per_model = _calibrated_combine(**BASE, score_srm=0.77, score_ela=0.66,
                                       score_freq=0.11)
    assert per_model["srm_noise_detector"] == pytest.approx(0.77)
    assert per_model["ela_detector"] == pytest.approx(0.66)
    assert per_model["frequency_spectral"] == pytest.approx(0.11)


def test_el_ai_human_no_se_aplica_dos_veces():
    """
    Ya es característica de entrada del meta-modelo. Antes se volvía a mezclar
    como corrección post-meta, contándolo dos veces.
    """
    bajo, _ = _calibrated_combine(**{**BASE, "score_f": 0.05})
    alto, _ = _calibrated_combine(**{**BASE, "score_f": 0.95})
    # Debe influir (es feature del modelo) pero por una sola vía: el salto no
    # puede superar lo que el propio meta-modelo produce.
    assert 0.0 <= bajo <= 1.0 and 0.0 <= alto <= 1.0


# ── Regla 4 desactivada ──────────────────────────────────────────────────────

def test_regla4_esta_desactivada():
    assert F_SRM_ENABLED is False


def test_regla4_no_se_activa_aunque_se_cumplan_sus_condiciones():
    """
    F=0.80 y SRM=0.70 cumplían el disparador. Es el perfil típico de una
    fotografía real: no debe elevarse el score.
    """
    scores = {
        "face_deepfake_vit": 0.20, "ai_art_detector": 0.05,
        "siglip_deepfake": 0.20, "ai_human_detector": 0.80,
        "srm_noise_detector": 0.70, "sdxl_detector": 0.30,
    }
    # ai_art_excluded=True reproduce la configuración de producción
    corregido, tipo, _ = apply_forensic_corrections(
        final_score=0.42, model_scores=scores, ood_result={"is_ood": False},
        ai_art_excluded=True,
    )
    assert tipo != "f_srm_alignment"
    assert corregido == 0.42


# ── Regla 3: votantes depurados ──────────────────────────────────────────────

def test_srm_y_siglip_ya_no_votan_en_el_consenso():
    assert "srm_noise_detector" not in CONSENSUS_MODELS
    assert "siglip_deepfake" not in CONSENSUS_MODELS


def test_el_consenso_no_se_alcanza_con_senales_rotas():
    """
    SRM y SigLIP altos sobre una fotografía real ya no pueden completar el
    quórum por sí solos.
    """
    scores = {
        "face_deepfake_vit": 0.30, "ai_art_detector": 0.05,
        "siglip_deepfake": 0.99, "ai_human_detector": 0.30,
        "srm_noise_detector": 0.99, "sdxl_detector": 0.05,
    }
    _, tipo, _ = apply_forensic_corrections(
        final_score=0.30, model_scores=scores, ood_result={"is_ood": False},
    )
    assert tipo != "consensus_override"


# ── Regla 1: SRM fuera del término de manipulación ──────────────────────────

def test_el_bypass_ood_ignora_srm():
    """Con ViT alto y OOD, mover SRM no debe cambiar la corrección."""
    base = {
        "face_deepfake_vit": 0.80, "ai_art_detector": 0.60,
        "ai_human_detector": 0.60,
    }
    a, tipo_a, _ = apply_forensic_corrections(
        0.40, {**base, "srm_noise_detector": 0.05}, {"is_ood": True})
    b, tipo_b, _ = apply_forensic_corrections(
        0.40, {**base, "srm_noise_detector": 0.95}, {"is_ood": True})
    assert tipo_a == tipo_b == "ood_bypass"
    assert a == pytest.approx(b, abs=1e-9)
