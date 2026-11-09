# -*- coding: utf-8 -*-
"""
Tests de las 4 reglas de correccion forense post-hoc (forensic_corrections.py).

Cada caso replica, con tolerancia numerica, los ejemplos reales documentados
en el docstring del modulo (Cobreloa, Messi, Midjourney portrait, F+SRM),
mas un caso negativo por regla para confirmar que NO se activa fuera de su
condicion. No requieren GPU ni modelos — son funciones puras de dominio.
"""
import pytest

from app.utils.forensic_corrections import (
    OOD_BYPASS_MAX,
    apply_forensic_corrections,
)


def test_regla1_ood_bypass_cobreloa():
    """
    Poster IA deportivo: las senales presentes activan el bypass OOD.

    El probe CLIP entra con el mayor peso (0.45) desde que se reentreno: es el
    unico detector con AUC alto en todas las pistas. Con las cuatro senales
    altas la correccion llega al tope de la regla.
    """
    scores = {
        "face_deepfake_vit":  0.795,
        "ai_art_detector":    0.594,
        "ai_human_detector":  0.612,
        "efficientnet_ffpp":  0.95,
        "srm_noise_detector": 0.726,
        "sdxl_detector":      0.10,
    }
    corrected, ctype, details = apply_forensic_corrections(
        final_score=0.50, model_scores=scores, ood_result={"is_ood": True},
    )
    assert ctype == "ood_bypass"
    assert corrected == pytest.approx(OOD_BYPASS_MAX, abs=0.001)
    assert details


def test_regla1_el_probe_clip_domina_la_senal():
    """
    Si el probe CLIP no ve sintesis, el bypass no puede elevarse tanto como
    cuando si la ve. Antes la regla lo ignoraba por completo y reemplazaba una
    deteccion correcta del probe por la media de detectores que no veian nada.
    """
    base = {
        "face_deepfake_vit": 0.795,
        "ai_art_detector":   0.594,
        "ai_human_detector": 0.612,
        "sdxl_detector":     0.10,
    }
    bajo, _, _ = apply_forensic_corrections(
        0.50, {**base, "efficientnet_ffpp": 0.02}, {"is_ood": True})
    alto, _, _ = apply_forensic_corrections(
        0.50, {**base, "efficientnet_ffpp": 0.98}, {"is_ood": True})
    assert alto > bajo + 0.15


def test_regla1_no_activa_en_afiche_real():
    """Diseno grafico con foto real: ViT y AI Art bajos -> no hay bypass.

    El score si baja, pero por el Compression Veto (regla 2), no por el bypass:
    con todos los detectores de generacion IA en minimos, la lectura correcta es
    "foto real con artefactos de compresion".
    """
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
    assert ctype != "ood_bypass"
    assert corrected <= 0.50


def test_regla2_compression_veto_messi():
    """Foto real comprimida por redes sociales: SDXL/AI Art confirman autenticidad."""
    scores = {
        "face_deepfake_vit": 0.10,
        "ai_art_detector":   0.12,
        "sdxl_detector":     0.40,
        "ai_human_detector": 0.0,
        "srm_noise_detector":0.0,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.46, model_scores=scores, ood_result={"is_ood": False},
    )
    assert ctype == "compression_veto"
    # 8% + 12% x 35% = 12.2%, el caso documentado en el docstring del modulo
    assert corrected == pytest.approx(0.122, abs=0.005)


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
    """
    Los tres votantes que quedan (ViT, AI Art, AI-Human) coinciden en fake pero
    SDXL falla, porque no reconoce el estilo Midjourney.

    SRM y SigLIP salieron de la lista de votantes: medidos sobre conjunto
    multifuente dan AUC 0.409 y 0.227, y votaban fake en fotografia autentica.
    Con tres votantes el floor base es 50 % (sin votos extra).
    """
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
    assert corrected == pytest.approx(0.50, abs=0.001)


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
    assert ctype != "consensus_override"
    assert corrected <= 0.30


def test_regla4_desactivada_no_eleva_el_score():
    """
    La regla 4 (F+SRM Alignment) esta desactivada: se midio que SRM tiene
    AUC 0.409 (invertido) y que el 96,6 % de las fotografias reales supera su
    umbral de 0.65, de modo que la regla se activaba sobre material autentico
    y solo podia subir el score. Ver test_senales_auxiliares.py.
    """
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
        ai_art_excluded=True,
    )
    assert ctype != "f_srm_alignment"
    assert corrected == pytest.approx(0.419, abs=0.001)


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
    assert ctype != "f_srm_alignment"
    assert corrected <= 0.30


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


# ── Disponibilidad de scores: ausente != 0.0 ─────────────────────────────────

def test_score_ausente_no_dispara_compression_veto():
    """
    Un detector que no reporto score no es evidencia de autenticidad.

    Antes, `scores.get(k, 0) or 0` convertia un None en 0.0, el veto veia
    "AI Art = 0% < 20%" y hundia el score a ~8%: si el modelo de arte IA
    fallaba al cargar, el sistema declaraba autentica cualquier imagen.
    """
    scores = {
        "face_deepfake_vit": 0.60,
        "ai_art_detector":   None,   # el modelo no pudo puntuar
        "sdxl_detector":     0.30,
        "ai_human_detector": 0.55,
        "srm_noise_detector":0.50,
    }
    corrected, ctype, _ = apply_forensic_corrections(
        final_score=0.45, model_scores=scores, ood_result={"is_ood": False},
    )
    assert ctype != "compression_veto"
    assert corrected == 0.45


def test_score_ausente_no_cuenta_como_voto_en_consenso():
    """Un modelo sin score no vota; no puede completar el quorum de la regla 3."""
    scores = {
        "face_deepfake_vit": 0.75,
        "ai_art_detector":   None,
        "siglip_deepfake":   None,
        "ai_human_detector": 0.80,
        "srm_noise_detector":0.70,
        "sdxl_detector":     0.12,
    }
    _, ctype, _ = apply_forensic_corrections(
        final_score=0.38, model_scores=scores, ood_result={"is_ood": False},
    )
    # Solo 3 votantes disponibles: no se alcanza CONSENSUS_MIN_VOTES = 4
    assert ctype != "consensus_override"


# ── Exclusion del arte IA por la compuerta de tipo de contenido ──────────────

def test_ai_art_excluido_no_activa_compression_veto():
    """
    Con el arte IA excluido (obra grafica), la regla 2 no puede usarlo.

    Es la garantia de que el score de arte IA no reentra al porcentaje final
    por la puerta de atras cuando la compuerta lo dejo fuera.
    """
    scores = {
        "face_deepfake_vit": 0.55,
        "ai_art_detector":   0.05,   # bajo: activaria el veto si se usara
        "sdxl_detector":     0.30,
        "ai_human_detector": 0.60,
        "srm_noise_detector":0.50,
    }
    sin_excluir, ctype_incl, _ = apply_forensic_corrections(
        final_score=0.45, model_scores=scores, ood_result={"is_ood": False},
    )
    excluido, ctype_excl, _ = apply_forensic_corrections(
        final_score=0.45, model_scores=scores, ood_result={"is_ood": False},
        ai_art_excluded=True,
    )
    assert ctype_incl == "compression_veto"
    assert sin_excluir < 0.25
    assert ctype_excl != "compression_veto"
    assert excluido == 0.45


def test_ai_art_excluido_renormaliza_pesos_del_bypass():
    """
    En el bypass OOD, excluir el arte IA redistribuye su peso entre las señales
    restantes en vez de restar magnitud a la señal combinada.
    """
    scores = {
        "face_deepfake_vit": 0.80,
        "ai_art_detector":   0.00,   # excluido: no debe arrastrar la señal a la baja
        "ai_human_detector": 0.80,
        "srm_noise_detector":0.80,
    }
    _, _, _ = apply_forensic_corrections(
        final_score=0.40, model_scores=scores, ood_result={"is_ood": True},
    )
    excluido, ctype, _ = apply_forensic_corrections(
        final_score=0.40, model_scores=scores, ood_result={"is_ood": True},
        ai_art_excluded=True,
    )
    assert ctype == "ood_bypass"
    # Las tres señales restantes valen 0.80. Renormalizadas, la señal combinada
    # es 0.80 (no 0.80 x (1 - peso_arte) = 0.56). El damper baja a 0.82 porque
    # con el arte excluido quedan 3 señales y el bonus exige 4.
    assert excluido == pytest.approx(0.8 * 0.82, abs=0.02)
