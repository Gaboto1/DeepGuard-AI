"""
Servicio de Inspección Semántica — LLaVA-1.5-7b-hf (4-bit cuantizado)
=======================================================================
Añade una capa de análisis forense semántico que los modelos estadísticos
no pueden proporcionar: comprensión de anatomía, física y coherencia visual.

Arquitectura:
  LLaVA-1.5-7b-hf cuantizado en 4-bit (NF4 + bfloat16)
  VRAM estimada: ~4.5-5GB (compatible con RTX 4070 SUPER 12GB junto al ensemble)

Casos de uso críticos resueltos:
  1. Foto real comprimida (ej. Messi en redes sociales):
     → LLaVA confirma anatomía correcta → risk_score bajo (0-15)
     → Corrección descendente del ensemble que confundía la compresión JPEG

  2. Afiche híbrido IA (imagen de IA con diseño gráfico):
     → LLaVA detecta texto deforme o cara sospechosa → risk_score alto (60-90)
     → Corrección ascendente cuando el ensemble no captaba la manipulación

  3. Deepfake facial:
     → LLaVA detecta ojos asimétricos, dedos malformados → risk_score 70-95
     → Refuerza la señal del ensemble

Integración con el Meta-Ensemble:
  El risk_score semántico se fusiona mediante reglas calibradas empíricamente
  (no reentrenamiento de XGBoost) para máxima transparencia y controlabilidad.
"""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import torch
from PIL import Image
from loguru import logger

from app.config import settings

# ─── Constantes ───────────────────────────────────────────────────────────────

MODEL_ID    = "llava-hf/llava-1.5-7b-hf"
QUANT_DESC  = "4-bit NF4 + bfloat16"
MAX_TOKENS  = 300   # suficiente para JSON + descripción forense
TEMPERATURE = 0.05  # muy baja para respuestas reproducibles y estructuradas

# System prompt forense en español — instrucciones estrictas de formato JSON
FORENSIC_PROMPT = """Actúa como un perito forense digital de élite especializado en detección de imágenes manipuladas o generadas por inteligencia artificial.

Analiza esta imagen minuciosamente en busca de:
1) Incoherencias anatómicas: dedos extra o faltantes, ojos asimétricos o de tamaño distinto, proporciones corporales incorrectas, orejas malformadas, dientes irregulares.
2) Inconsistencias físicas: sombras que no coinciden con la fuente de luz, reflejos imposibles, perspectiva errónea entre elementos del fondo y del sujeto.
3) Artefactos de generación IA: bordes con halos o sangrado de color, texturas con patrones repetitivos, piel excesivamente lisa sin poros ni arrugas naturales, cabello con fusiones anómalas.
4) Texto deformado: letras ilegibles, palabras mezcladas, fuentes inconsistentes dentro de la misma imagen.
5) Coherencia general: ¿La escena es físicamente posible? ¿Los elementos son consistentes entre sí?

Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional antes ni después:
{"risk_score": <entero 0-100>, "semantic_observations": "<descripción forense detallada en español de máximo 200 palabras>"}

Donde risk_score=0 significa imagen completamente auténtica sin anomalías detectables, y risk_score=100 significa manipulación artificial evidente en múltiples dimensiones."""


# ─── Singleton del servicio ───────────────────────────────────────────────────

class _SemanticInspector:
    """
    Singleton que gestiona la carga y el ciclo de vida del modelo LLaVA.
    Se inicializa una sola vez en el worker Celery (worker_init signal).
    """
    _instance: Optional["_SemanticInspector"] = None

    def __init__(self) -> None:
        self._model     = None
        self._processor = None
        self._loaded    = False
        self._available = True
        self.device     = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    @classmethod
    def get_instance(cls) -> "_SemanticInspector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self) -> None:
        """
        Carga LLaVA-1.5-7b-hf con cuantización 4-bit (NF4 + bfloat16).
        Descarga automática en el directorio local de caché (≈14GB FP16 → ~5GB 4-bit).
        """
        if self._loaded or not self._available:
            return

        os.environ["TRANSFORMERS_CACHE"]              = str(settings.MODELS_DIR)
        os.environ["HF_HOME"]                         = str(settings.MODELS_DIR)
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

        try:
            from transformers import LlavaForConditionalGeneration, AutoProcessor, BitsAndBytesConfig

            total_vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
            logger.info(f"Cargando {MODEL_ID} con cuantización {QUANT_DESC}...")
            logger.info(f"  VRAM total: {total_vram_gb:.1f}GB")

            bnb_config = BitsAndBytesConfig(
                load_in_4bit                     = True,
                bnb_4bit_quant_type              = "nf4",
                bnb_4bit_compute_dtype           = torch.bfloat16,
                bnb_4bit_use_double_quant        = True,
                # Permite que los módulos que no caben en VRAM usen FP32 en CPU
                # en lugar de lanzar "Some modules are dispatched on the CPU or the disk"
                llm_int8_enable_fp32_cpu_offload = True,
            )

            # Reservar VRAM para el ensemble de 5 modelos (~6.5GB usados previamente)
            # LLaVA toma lo que quede, con overflow a RAM del sistema
            llava_vram_gb = max(3.0, total_vram_gb - 7.0)
            max_memory = {
                0:     f"{llava_vram_gb:.1f}GiB",  # GPU: VRAM disponible para LLaVA
                "cpu": "12GiB",                     # CPU RAM: overflow sin errores
            }
            logger.info(f"  Asignando LLaVA: GPU={llava_vram_gb:.1f}GiB, CPU=12GiB overflow")

            self._processor = AutoProcessor.from_pretrained(
                MODEL_ID,
                cache_dir=str(settings.MODELS_DIR),
            )
            self._model = LlavaForConditionalGeneration.from_pretrained(
                MODEL_ID,
                quantization_config = bnb_config,
                device_map          = "auto",
                max_memory          = max_memory,
                cache_dir           = str(settings.MODELS_DIR),
            )
            self._model.eval()
            self._loaded = True

            used_vram = torch.cuda.memory_allocated(0) / 1e9
            logger.success(
                f"LLaVA listo: {MODEL_ID} | "
                f"Cuant.: {QUANT_DESC} | "
                f"VRAM usada: {used_vram:.2f}GB"
            )

        except ImportError as e:
            logger.warning(
                f"bitsandbytes/transformers no disponible — LLaVA desactivado: {e}. "
                "Instale con: pip install bitsandbytes accelerate"
            )
            self._available = False
        except Exception as e:
            logger.error(f"Error al cargar LLaVA: {e}")
            self._available = False

    def analyze(self, image_path: Path) -> dict:
        """
        Analiza una imagen con el prompt forense y retorna risk_score + observaciones.
        Retorna un dict vacío/neutro si el modelo no está disponible.
        """
        if not self._loaded:
            return _neutral_result("LLaVA no cargado")

        t0 = time.time()
        try:
            image = Image.open(image_path).convert("RGB")

            # Formato de conversación estándar LLaVA-1.5
            conversation = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": FORENSIC_PROMPT},
                    ],
                }
            ]

            prompt_text = self._processor.apply_chat_template(
                conversation, add_generation_prompt=True
            )
            inputs = self._processor(
                images=image,
                text=prompt_text,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                output_ids = self._model.generate(
                    **inputs,
                    max_new_tokens  = MAX_TOKENS,
                    temperature     = TEMPERATURE,
                    do_sample       = False,
                    repetition_penalty = 1.1,
                )

            # Decodificar solo los tokens nuevos (excluir el prompt)
            new_tokens = output_ids[0, inputs["input_ids"].shape[1]:]
            raw_text   = self._processor.decode(new_tokens, skip_special_tokens=True).strip()

            risk_score, observations = _parse_llava_response(raw_text)

            elapsed = time.time() - t0
            logger.debug(
                f"LLaVA: risk_score={risk_score} | "
                f"observaciones={len(observations)} chars | "
                f"tiempo={elapsed:.2f}s"
            )

            return {
                "risk_score":             risk_score,
                "risk_score_normalized":  round(risk_score / 100.0, 4),
                "semantic_observations":  observations,
                "model_used":             MODEL_ID,
                "quantization":           QUANT_DESC,
                "analysis_time":          round(elapsed, 3),
                "raw_response":           raw_text[:300],  # para debugging
            }

        except Exception as e:
            logger.error(f"Error en análisis semántico LLaVA: {e}")
            return _neutral_result(f"Error de inferencia: {type(e).__name__}")


# ─── Parseador de respuesta JSON ──────────────────────────────────────────────

def _parse_llava_response(raw: str) -> tuple[int, str]:
    """
    Extrae risk_score y semantic_observations del texto generado por LLaVA.
    Robusto a texto extra antes/después del JSON.
    Fallback a análisis de texto libre si el JSON es inválido.
    """
    # Intento 1: JSON puro en la respuesta
    try:
        data = json.loads(raw)
        score = int(data.get("risk_score", 50))
        obs   = str(data.get("semantic_observations", "Sin observaciones."))
        return min(max(score, 0), 100), obs
    except (json.JSONDecodeError, ValueError):
        pass

    # Intento 2: Extraer bloque JSON con regex (modelo añadió texto extra)
    json_match = re.search(r'\{[^{}]*"risk_score"[^{}]*\}', raw, re.DOTALL)
    if json_match:
        try:
            data  = json.loads(json_match.group())
            score = int(data.get("risk_score", 50))
            obs   = str(data.get("semantic_observations", raw[:200]))
            return min(max(score, 0), 100), obs
        except Exception:
            pass

    # Intento 3: Extraer score numérico del texto libre
    score_match = re.search(r'"risk_score"\s*:\s*(\d+)', raw)
    score = int(score_match.group(1)) if score_match else 50

    # Usar todo el texto como observación si no hay JSON válido
    obs = raw[:300] if raw else "El modelo no generó una respuesta JSON válida."
    return min(max(score, 0), 100), obs


def _neutral_result(reason: str) -> dict:
    """Score neutro cuando LLaVA no está disponible — no penaliza ni beneficia."""
    return {
        "risk_score":             -1,    # -1 indica "no disponible"
        "risk_score_normalized":  None,
        "semantic_observations":  f"Análisis semántico no disponible: {reason}",
        "model_used":             MODEL_ID,
        "quantization":           QUANT_DESC,
        "analysis_time":          0.0,
        "raw_response":           "",
    }


# ─── API pública ──────────────────────────────────────────────────────────────

def analyze_semantic_coherence(image_path: Path) -> dict:
    """
    Función principal de análisis semántico forense.
    Usa el singleton _SemanticInspector para evitar recargas del modelo.
    """
    inspector = _SemanticInspector.get_instance()
    if not inspector._loaded:
        inspector.load()
    return inspector.analyze(image_path)


# ─── Fusión semántica con el ensemble ─────────────────────────────────────────

# Pesos de fusión calibrados empíricamente (sin reentrenar XGBoost)
_LLAVA_WEIGHT_WITH_FACE    = 0.30   # LLaVA puede verificar anatomía directamente
_LLAVA_WEIGHT_WITHOUT_FACE = 0.18   # Verifica coherencia física general
_ENSEMBLE_WEIGHT_WITH_FACE    = 0.70
_ENSEMBLE_WEIGHT_WITHOUT_FACE = 0.82

# Umbrales para correcciones en casos críticos
_CORRECTION_LLAVA_HIGH = 0.65   # LLaVA detecta alta anomalía
_CORRECTION_LLAVA_LOW  = 0.20   # LLaVA confirma autenticidad
_CORRECTION_ENS_LOW    = 0.35   # Ensemble dice "real"
_CORRECTION_ENS_HIGH   = 0.65   # Ensemble dice "manipulado"


def apply_semantic_fusion(
    ensemble_score: float,
    semantic_result: dict,
    faces_detected: bool,
) -> tuple[float, Optional[str], Optional[str]]:
    """
    Fusiona el score del ensemble con el análisis semántico de LLaVA.

    Lógica de fusión (3 casos):
      1. Corrección ascendente: ensemble dice REAL pero LLaVA detecta anomalías
         → Foto o video con manipulación sutil que el ensemble no captó
      2. Corrección descendente: ensemble dice FAKE pero LLaVA confirma autenticidad
         → Foto real comprimida donde compresión JPEG confundió al ensemble
      3. Blend normal: casos sin discrepancia fuerte entre modelos

    Retorna (score_final, tipo_corrección, nota_corrección).
    """
    llava_norm = semantic_result.get("risk_score_normalized")

    # LLaVA no disponible — devolver ensemble sin modificar
    if llava_norm is None or semantic_result.get("risk_score", -1) < 0:
        return ensemble_score, None, None

    w_llava = _LLAVA_WEIGHT_WITH_FACE if faces_detected else _LLAVA_WEIGHT_WITHOUT_FACE
    w_ens   = 1.0 - w_llava

    # ── Caso 1: Corrección ascendente ─────────────────────────────────────────
    # Ensemble dice imagen limpia (<35%), pero LLaVA detecta anomalías claras (>65%)
    if ensemble_score < _CORRECTION_ENS_LOW and llava_norm > _CORRECTION_LLAVA_HIGH:
        # Factor 1.40 para correccion más fuerte; mínimo garantizado en 0.40
        delta     = (llava_norm - ensemble_score) * w_llava * 1.40
        corrected = float(min(0.65, max(0.40, ensemble_score + delta)))
        note      = (
            f"Corrección semántica ascendente: LLaVA detectó anomalías visuales "
            f"(score semántico: {llava_norm*100:.0f}%) no capturadas por el ensemble estadístico. "
            f"Score ajustado: {ensemble_score*100:.1f}% → {corrected*100:.1f}%."
        )
        return corrected, "semantic_correction_up", note

    # ── Caso 2a: Corrección descendente fuerte ────────────────────────────────
    # Ensemble dice manipulado (>65%), pero LLaVA confirma autenticidad (<20%)
    elif ensemble_score > _CORRECTION_ENS_HIGH and llava_norm < _CORRECTION_LLAVA_LOW:
        delta     = (ensemble_score - llava_norm) * w_llava * 0.90
        corrected = float(max(0.15, ensemble_score - delta))
        note      = (
            f"Corrección semántica descendente: LLaVA confirmó coherencia anatómica y física "
            f"(score semántico: {llava_norm*100:.0f}%). Probable artefacto de compresión o procesamiento. "
            f"Score ajustado: {ensemble_score*100:.1f}% → {corrected*100:.1f}%."
        )
        return corrected, "semantic_correction_down", note

    # ── Caso 2b: Zona de confusión por compresión ─────────────────────────────
    # Ensemble incierto (35-55%) + LLaVA muy seguro que es real (<10%)
    # Patrón característico de fotos reales comprimidas por redes sociales
    elif llava_norm < 0.10 and 0.35 <= ensemble_score <= 0.55:
        corrected = float(max(0.12, ensemble_score - (0.50 - llava_norm) * 0.50))
        note      = (
            f"Corrección por zona de compresión: LLaVA muy seguro de autenticidad "
            f"({llava_norm*100:.0f}%) con ensemble incierto ({ensemble_score*100:.0f}%). "
            f"Probable compresión JPEG agresiva. Score: {ensemble_score*100:.1f}% → {corrected*100:.1f}%."
        )
        return corrected, "semantic_compression_zone", note

    # ── Caso 3: Blend ponderado normal ────────────────────────────────────────
    fused = w_ens * ensemble_score + w_llava * llava_norm
    fused = float(min(1.0, max(0.0, fused)))
    return fused, "semantic_blend", None
