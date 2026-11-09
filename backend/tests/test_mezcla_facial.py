# -*- coding: utf-8 -*-
"""
El track facial no debe quedar vetado por el de imagen completa.

Contexto
--------
Cuando se detecta un rostro, el resultado final mezcla dos pasadas:

    final = PESO_TRACK_FACIAL * facial + (1 - PESO_TRACK_FACIAL) * completa

El peso estaba en 0.60 desde el release v6.0, ANTERIOR al cabezal facial del
meta-ensemble. Al entrenar un cabezal especifico para rostro (validado por
identidad, AUC 0.9968) el peso no se movio, y el track de imagen completa
—que esta calibrado para imagen de difusion y promedia 0.476 ante un
intercambio de rostro— conservaba el 40 % del voto sobre el caso para el que
el otro cabezal fue construido.

Medido sobre las 60.000 filas de reports/dataset_v2_scores.csv:

    peso facial   deteccion IA      FPR     error ff_fake
    0.60               80.41 %   0.030 %         88.70 %
    0.80               93.23 %   0.027 %         11.74 %
    1.00               94.30 %   0.067 %          5.32 %

Estos tests fijan la decision. El primero falla con el peso antiguo: es el que
evita que el 0.60 vuelva sin que nadie lo note.
"""
import json
from pathlib import Path

import pytest

from app.services.image_service import (
    PESO_TRACK_FACIAL, PESO_TRACK_FACIAL_OBRA)

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "models" / "meta_ensemble" / "meta_config.json"


def mezcla(facial: float, completa: float, obra: bool = False) -> float:
    """Reproduce la mezcla de image_service._run_image_analysis."""
    w = PESO_TRACK_FACIAL_OBRA if obra else PESO_TRACK_FACIAL
    return w * facial + (1.0 - w) * completa


def umbral() -> float:
    if not CONFIG.exists():
        pytest.skip(f"falta {CONFIG.name}")
    T = (json.loads(CONFIG.read_text(encoding="utf-8"))
         .get("full_head", {}).get("cv", {}).get("T"))
    if T is None:
        pytest.skip("el config no trae full_head.cv.T")
    return float(T)


def test_peso_facial_es_mayoritario():
    """El cabezal entrenado para rostro debe pesar mas que el generico."""
    assert 0.75 <= PESO_TRACK_FACIAL <= 1.0, (
        f"PESO_TRACK_FACIAL={PESO_TRACK_FACIAL}: por debajo de 0.75 el track "
        f"de imagen completa puede vetar al facial sobre intercambio de "
        f"rostro, que es el caso forense central del proyecto."
    )


def test_veredicto_facial_firme_sobrevive_a_un_track_completo_sin_opinion():
    """
    Un deepfake que el cabezal facial declara con firmeza (0.99) debe seguir
    por encima del umbral cuando el track de imagen completa no opina (0.50,
    el neutro que usa el ensemble para un detector ausente).

    Con el peso antiguo de 0.60 la mezcla daba 0.794 y el umbral estaba en
    0.8764: el deepfake se reportaba como autentico.
    """
    T = umbral()
    p = mezcla(facial=0.99, completa=0.50)
    assert p >= T, (
        f"mezcla(0.99, 0.50) = {p:.4f} < T = {T:.4f}. Un veredicto facial "
        f"firme esta quedando por debajo del umbral porque el track de imagen "
        f"completa pesa demasiado."
    )


def test_fotografia_autentica_sigue_abajo():
    """
    La correccion no debe comprarse con falsas alarmas: si ambos tracks ven
    una fotografia autentica, el resultado tiene que quedar muy por debajo del
    umbral. Es el error de mayor costo en uso forense.
    """
    T = umbral()
    p = mezcla(facial=0.02, completa=0.02)
    assert p < 0.10, f"mezcla(0.02, 0.02) = {p:.4f}: demasiado alto"
    assert p < T


def test_el_track_completo_conserva_voz():
    """
    No se apaga el track de imagen completa. El cabezal facial se entreno solo
    con intercambio de rostro (ff++) y queda fuera de dominio ante un rostro
    enteramente sintetico dentro de una imagen generada; ahi el track completo
    es el que acierta, y debe poder mover el resultado.
    """
    assert PESO_TRACK_FACIAL < 1.0, (
        "con peso 1.0 el track de imagen completa no influye y un retrato "
        "enteramente sintetico queda a merced de un cabezal fuera de dominio."
    )
    sin_opinion = mezcla(facial=0.50, completa=0.50)
    con_alarma = mezcla(facial=0.50, completa=1.00)
    salto = con_alarma - sin_opinion
    # El margen va con tolerancia: con peso 0.80 el salto es exactamente 0.10 y
    # en coma flotante sale 0.09999999999999998.
    assert salto >= 0.10 - 1e-9, (
        f"el track completo solo mueve el resultado {salto:.3f}: su voz es "
        f"testimonial."
    )


def test_sobre_obra_grafica_manda_el_track_completo():
    """
    En obra grafica el cabezal facial esta fuera de dominio: se entreno con
    intercambio de rostro sobre fotografia y nunca vio un rostro enteramente
    sintetico, de modo que ante un retrato generado lo declara autentico.

    Un retrato de IA en el que el track completo acierta con firmeza (0,95) y
    el facial se equivoca (0,05) debe quedar del lado correcto. Con el peso de
    fotografia aplicado a obra grafica daba 0,23 —"Low Evidence", es decir el
    sistema declarandolo autentico— que es la regresion medida sobre FLUX.
    """
    p = mezcla(facial=0.05, completa=0.95, obra=True)
    assert p >= 0.60, (
        f"mezcla(0.05, 0.95, obra=True) = {p:.4f} < 0.60: un retrato "
        f"sintetico que el track competente detecta queda por debajo de "
        f"'Moderate Evidence' porque el cabezal facial, fuera de su dominio, "
        f"pesa demasiado sobre obra grafica."
    )
    assert PESO_TRACK_FACIAL_OBRA < PESO_TRACK_FACIAL, (
        "el peso facial sobre obra grafica debe ser MENOR que sobre "
        "fotografia: es el unico caso en que el cabezal opera fuera del "
        "dominio en que fue entrenado."
    )


def test_el_cabezal_facial_no_se_apaga_en_obra_grafica():
    """
    No se lleva a cero: un intercambio de rostro dentro de una ilustracion es
    concebible, y el cabezal facial es la unica pieza entrenada para verlo.
    """
    assert PESO_TRACK_FACIAL_OBRA > 0.0
    sin_opinion = mezcla(0.50, 0.50, obra=True)
    con_alarma = mezcla(1.00, 0.50, obra=True)
    assert con_alarma - sin_opinion >= 0.10 - 1e-9, (
        f"el cabezal facial solo mueve el resultado "
        f"{con_alarma - sin_opinion:.3f} sobre obra grafica: esta apagado "
        f"de hecho."
    )


def test_el_deepfake_facial_conserva_el_peso_alto():
    """
    La compuerta clasifica ff++ como fotografia en el 99 % de los casos
    (reports/diagnostico_compuerta_rostro.json), de modo que el caso forense
    central del proyecto sigue recibiendo el peso alto. Este test fija esa
    condicion: si alguien invirtiera la rama, el deepfake facial volveria a
    caer por debajo del umbral.
    """
    T = umbral()
    assert mezcla(0.99, 0.50, obra=False) >= T
    assert mezcla(0.99, 0.50, obra=False) > mezcla(0.99, 0.50, obra=True)


def test_mezcla_es_monotona_y_acotada():
    """Propiedades basicas: convexa en ambos argumentos y dentro de [0, 1]."""
    assert mezcla(0.0, 0.0) == pytest.approx(0.0)
    assert mezcla(1.0, 1.0) == pytest.approx(1.0)
    anterior = -1.0
    for f in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = mezcla(f, 0.5)
        assert 0.0 <= v <= 1.0
        assert v > anterior, "la mezcla debe crecer con el veredicto facial"
        anterior = v
