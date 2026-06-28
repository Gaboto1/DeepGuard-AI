# -*- coding: utf-8 -*-
"""
Tests de las 4 reglas de correccion forense post-hoc (forensic_corrections.py).

Cada caso replica, con tolerancia numerica, los ejemplos reales documentados
en el docstring del modulo (Cobreloa, Messi, Midjourney portrait, F+SRM),
mas un caso negativo por regla para confirmar que NO se activa fuera de su
condicion. No requieren GPU ni modelos — son funciones puras de dominio.
"""
import pytest

from app.utils.forensic_corrections import apply_forensic_corrections


def test_regla1_ood_bypass_cobreloa():
    """Poster IA deportivo: las 4 senales presentes activan el bypass OOD."""
    scores = {
        "face_deepfake_vit": 0.795,
        "ai_art_detector":   0.594,
        "ai_human_detector": 0.612,
        "srm_noise_detector":0.726,
        "sdxl_detector":     0.10,
    }
    corrected, ctype, details = apply_forensic_corrections(
        final_score=0.50, model_scores=scores, ood_result={"is_ood": True},
    )
    assert ctype == "ood_bypass"
    assert corrected == pytest.approx(0.605, abs=0.01)
    assert details


def test_regla1_no_activa_en_afiche_real():
    """Diseno grafico con foto real: ViT y AI Art bajos -> no hay bypass."""
    scores = {
        "face_deepfake_vit": 0.15,
        "ai_art_detector":   0.08,
        "ai_human_detector": 0.05,
        "srm_noise_detector":0.05,
        "sdxl_detector":     0.10,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.50, model_scores=scores, ood_result={"is_ood": True},
    )
    assert ctype is None
    assert corrected == 0.50


def test_regla2_compression_veto_messi():
    """Foto real comprimida por redes sociales: SDXL/AI Art confirman autenticidad."""
    scores = {
        "face_deepfake_vit": 0.10,
        "ai_art_detector":   0.005,
        "sdxl_detector":     0.40,
        "ai_human_detector": 0.0,
        "srm_noise_detector":0.0,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.46, model_scores=scores, ood_result={"is_ood": False},
    )
    assert ctype == "compression_veto"
    assert corrected == pytest.approx(0.102, abs=0.005)


def test_regla2_no_activa_si_score_bajo():
    """Si el score ya esta bajo el umbral de 20%, el veto de compresion no aplica."""
    scores = {
        "face_deepfake_vit": 0.10,
        "ai_art_detector":   0.08,
        "sdxl_detector":     0.15,
        "ai_human_detector": 0.05,
        "srm_noise_detector":0.05,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.12, model_scores=scores, ood_result={"is_ood": False},
    )
    assert ctype is None
    assert corrected == 0.12


def test_regla3_consensus_override_midjourney():
    """5 de 5 modelos votan fake pero SDXL falla (no detecta el estilo Midjourney)."""
    scores = {
        "face_deepfake_vit": 0.75,
        "ai_art_detector":   0.60,
        "siglip_deepfake":   0.65,
        "ai_human_detector": 0.80,
        "srm_noise_detector":0.70,
        "sdxl_detector":     0.12,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.38, model_scores=scores, ood_result={"is_ood": False},
    )
    assert ctype == "consensus_override"
    assert corrected == pytest.approx(0.54, abs=0.001)


def test_regla3_no_activa_sin_consenso():
    """Foto real: ningun modelo supera el umbral de voto -> sin correccion."""
    scores = {
        "face_deepfake_vit": 0.35,
        "ai_art_detector":   0.08,
        "siglip_deepfake":   0.30,
        "ai_human_detector": 0.25,
        "srm_noise_detector":0.20,
        "sdxl_detector":     0.10,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.30, model_scores=scores, ood_result={"is_ood": False},
    )
    assert ctype is None
    assert corrected == 0.30


def test_regla4_f_srm_alignment():
    """AI-Human y SRM Noise concuerdan en imagen sintetica; XGBoost no las usa."""
    scores = {
        "face_deepfake_vit": 0.20,
        "ai_art_detector":   0.50,
        "siglip_deepfake":   0.20,
        "ai_human_detector": 0.82,
        "srm_noise_detector":0.75,
        "sdxl_detector":     0.30,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.419, model_scores=scores, ood_result={"is_ood": False},
    )
    assert ctype == "f_srm_alignment"
    assert corrected == pytest.approx(0.536, abs=0.005)


def test_regla4_no_activa_con_senales_bajas():
    """F y SRM bajos (foto real): la regla 4 no se activa."""
    scores = {
        "face_deepfake_vit": 0.10,
        "ai_art_detector":   0.08,
        "siglip_deepfake":   0.10,
        "ai_human_detector": 0.25,
        "srm_noise_detector":0.20,
        "sdxl_detector":     0.15,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.30, model_scores=scores, ood_result={"is_ood": False},
    )
    assert ctype is None
    assert corrected == 0.30


def test_reglas_son_mutuamente_excluyentes():
    """Solo una regla puede aplicarse por llamada (la primera que matchea)."""
    # Construido para cumplir simultaneamente Regla 1 (is_ood + ViT alto) y,
    # de no existir el bypass, tambien Regla 3 (consenso) — Regla 1 debe ganar.
    scores = {
        "face_deepfake_vit": 0.80,
        "ai_art_detector":   0.60,
        "siglip_deepfake":   0.65,
        "ai_human_detector": 0.70,
        "srm_noise_detector":0.70,
        "sdxl_detector":     0.10,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.38, model_scores=scores, ood_result={"is_ood": True},
    )
    assert ctype == "ood_bypass"
