# -*- coding: utf-8 -*-
"""
Coherencia entre el score mostrado y todo lo que se deriva de el.

El informe de una imagen mostraba un titular de 58.5% mientras el texto del
analisis decia 62%, y la cabecera "Resultado no concluyente" convivia con la
etiqueta "Evidencia Moderada". La causa: el nivel de evidencia, la
incertidumbre y la explicacion se calculaban ANTES de la fusion semantica
(LLaVA), que es el ultimo paso que modifica el score.

Estos tests fijan la invariante: cuanto se deriva del score se deriva del
score definitivo.
"""
import re

import pytest

from app.api.schemas import EvidenceLevel
from app.utils.helpers import (
    get_evidence_level,
    generate_forensic_explanation,
    get_model_agreement,
)


# ── El porcentaje del texto coincide con el del titular ──────────────────────

def _pct_en_texto(texto: str) -> float:
    m = re.search(r"probabilidad de manipulación del ([\d.]+)%", texto)
    assert m, f"no se encontro el porcentaje en: {texto[:120]}"
    return float(m.group(1))


@pytest.mark.parametrize("prob", [0.585, 0.62, 0.331, 0.854, 0.075, 0.5])
def test_el_texto_reporta_el_mismo_porcentaje_que_el_titular(prob):
    """
    `manipulation_probability` de la tarea es round(prob * 100, 1).
    El texto del analisis debe decir exactamente ese numero.
    """
    titular = round(prob * 100, 1)
    texto = generate_forensic_explanation(
        probability=prob,
        evidence_level=get_evidence_level(prob),
        model_agreement=get_model_agreement([prob])[0],
        file_type="image",
    )
    assert _pct_en_texto(texto) == pytest.approx(titular, abs=0.05)


def test_el_caso_reportado_58_5_no_dice_58():
    """Con round() a entero, 0.585 salia como '58%' junto a un titular '58.5%'."""
    texto = generate_forensic_explanation(
        probability=0.585,
        evidence_level=get_evidence_level(0.585),
        model_agreement=get_model_agreement([0.585])[0],
        file_type="image",
    )
    assert "58.5%" in texto


# ── El nivel de evidencia corresponde a la banda del score ───────────────────

@pytest.mark.parametrize("prob,esperado", [
    (0.585, EvidenceLevel.INCONCLUSIVE),   # el caso reportado
    (0.62,  EvidenceLevel.MODERATE),       # lo que se mostraba por error
    (0.10,  EvidenceLevel.VERY_LOW),
    (0.30,  EvidenceLevel.LOW),
    (0.85,  EvidenceLevel.STRONG),
])
def test_banda_de_evidencia_por_score(prob, esperado):
    assert get_evidence_level(prob) is esperado


def test_58_5_y_62_caen_en_bandas_distintas():
    """
    Justo lo que hacia visible el desfase: el score final (58.5%) es
    inconcluyente, pero el nivel se habia calculado sobre 62%, que es moderado.
    """
    assert get_evidence_level(0.585) is not get_evidence_level(0.62)


# ── Orden de las fases en la tarea de imagen ─────────────────────────────────

def test_la_fusion_semantica_precede_a_la_derivacion_del_informe():
    """
    Comprueba en el fuente que `apply_semantic_fusion` (ultimo paso que cambia
    `prob`) ocurre ANTES de calcular nivel de evidencia y explicacion.

    Es una verificacion estructural: reproducir la tarea completa exigiria GPU,
    Redis y los pesos de LLaVA.
    """
    from pathlib import Path
    import app.tasks.analysis_tasks as tasks

    fuente = Path(tasks.__file__).read_text(encoding="utf-8")
    inicio = fuente.index("def analyze_image_task")
    fin = fuente.index("def analyze_video_task")
    bloque = fuente[inicio:fin]

    i_fusion = bloque.index("apply_semantic_fusion(prob")
    i_nivel = bloque.index("ev_level         = get_evidence_level(prob)")
    i_expl = bloque.index("explanation = generate_forensic_explanation")

    assert i_fusion < i_nivel, "el nivel de evidencia se deriva antes de la fusion"
    assert i_fusion < i_expl, "la explicacion se genera antes de la fusion"


def test_el_sello_de_custodia_se_emite_tras_la_derivacion():
    """El sello firma score y nivel de evidencia: ambos deben ser los finales."""
    from pathlib import Path
    import app.tasks.analysis_tasks as tasks

    fuente = Path(tasks.__file__).read_text(encoding="utf-8")
    inicio = fuente.index("def analyze_image_task")
    fin = fuente.index("def analyze_video_task")
    bloque = fuente[inicio:fin]

    i_nivel = bloque.index("ev_level         = get_evidence_level(prob)")
    i_sello = bloque.index("seal = generate_custody_seal")
    assert i_nivel < i_sello
