# -*- coding: utf-8 -*-
"""
Como se combinan la rama de rostro y la de imagen completa.

Estas pruebas no fijan cual de los dos modos esta activo -eso lo decide el
criterio de adopcion y puede cambiar- sino lo que cada modo garantiza. Asi
siguen valiendo antes y despues de cualquier decision.

El caso que las motiva: un retrato fotorrealista generado por IA que el
sistema puntuo en 18 %. La rama de rostro decia 0,00 -no es un intercambio de
rostro, lo cual es cierto- y con peso 0,80 eso imponia un techo de 0,20 al
resultado, dijera lo que dijera la rama de imagen completa.
"""
import pytest

from app.services import image_service as isv
from app.services.image_service import (
    PESO_TRACK_FACIAL, PESO_TRACK_FACIAL_OBRA, mezclar_ramas)


def test_el_modo_lineal_es_la_formula_de_siempre():
    assert mezclar_ramas(0.9, 0.1, False, modo="lineal") == pytest.approx(
        PESO_TRACK_FACIAL * 0.9 + (1 - PESO_TRACK_FACIAL) * 0.1)
    assert mezclar_ramas(0.9, 0.1, True, modo="lineal") == pytest.approx(
        PESO_TRACK_FACIAL_OBRA * 0.9 + (1 - PESO_TRACK_FACIAL_OBRA) * 0.1)


def test_el_modo_lineal_impone_un_techo_cuando_el_rostro_dice_cero():
    """
    Documenta el defecto, no lo celebra: con la rama de rostro en 0 y la
    completa TOTALMENTE segura, la mezcla lineal no puede pasar de 1 - w.
    Con w = 0,80 eso es 0,20, banda 'Low Evidence'. Ninguna imagen sintetica
    con un rostro que no sea un intercambio puede senalarse en ese modo.
    """
    techo = mezclar_ramas(0.0, 1.0, False, modo="lineal")
    assert techo == pytest.approx(1 - PESO_TRACK_FACIAL)
    assert techo < 0.60, "por debajo de la banda 'Moderate Evidence'"


def test_el_modo_o_no_deja_que_una_rama_anule_a_la_otra():
    # Rostro enteramente sintetico: el cabezal facial calla, la completa lo ve.
    assert mezclar_ramas(0.0, 0.95, False, modo="o") == pytest.approx(0.95)
    # Intercambio de rostro: la completa no ve nada, el cabezal facial si.
    assert mezclar_ramas(0.95, 0.05, False, modo="o") == pytest.approx(0.95)


def test_el_modo_o_nunca_baja_respecto_del_lineal():
    """max(a, b) >= cualquier media ponderada de a y b."""
    for rostro in (0.0, 0.2, 0.5, 0.8, 1.0):
        for completa in (0.0, 0.3, 0.6, 0.9, 1.0):
            assert (mezclar_ramas(rostro, completa, False, modo="o")
                    >= mezclar_ramas(rostro, completa, False, modo="lineal") - 1e-12)


def test_en_fotografia_autentica_el_modo_o_no_inventa_nada():
    """Si las dos ramas dicen 'real', el resultado sigue siendo 'real'."""
    assert mezclar_ramas(0.02, 0.05, False, modo="o") == pytest.approx(0.05)


def test_en_obra_grafica_el_modo_o_conserva_la_mezcla_lineal():
    """
    El cabezal facial se entreno con fotogramas y ante un rostro dibujado opina
    fuera de dominio. Un maximo dejaria pasar sus falsos positivos; por eso en
    obra grafica se mantiene el peso 0,30 aunque el modo sea 'o'.
    """
    assert mezclar_ramas(0.95, 0.10, True, modo="o") == pytest.approx(
        mezclar_ramas(0.95, 0.10, True, modo="lineal"))
    assert mezclar_ramas(0.95, 0.10, True, modo="o") < 0.60


def test_sin_modo_explicito_se_usa_el_de_produccion():
    assert mezclar_ramas(0.3, 0.7, False) == pytest.approx(
        mezclar_ramas(0.3, 0.7, False, modo=isv.MEZCLA_RAMAS))
    assert isv.MEZCLA_RAMAS in ("lineal", "o")
