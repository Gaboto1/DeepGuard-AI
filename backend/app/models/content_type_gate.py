"""
Content-Type Gate — clasificacion fotografia vs. obra grafica
==============================================================

Determina si una imagen es una *fotografia* (captura optica de una escena real,
o una manipulacion de una) o una *obra grafica* (ilustracion, pintura, render
3D, anime, concept art), usando CLIP ViT-L/14 en modo zero-shot con un ensemble
de prompts por clase.

Por que existe
--------------
El detector de arte IA (modelo D, ``haywoodsloan/ai-image-detector-deploy``)
esta entrenado sobre plataformas de arte generativo. Su pregunta es "¿esta obra
la genero una IA?", que NO es la pregunta forense "¿esta fotografia fue
manipulada?".

Cuando el contenido es una obra grafica, ese modelo:
  1. Responde a una pregunta distinta de la que reporta el veredicto forense.
  2. Penaliza ilustracion digital hecha por humanos (falso positivo).
  3. Domina el meta-ensemble — concentraba el 91% de la importancia del modelo,
     con lo que el porcentaje final era, en la practica, su sola opinion.

Esta compuerta permite excluirlo del score forense cuando el contenido no es
fotografico, reportandolo por separado como indicador independiente.

Validacion (150 img/grupo, CLIP ViT-L/14 zero-shot):
    coco (foto natural)          artwork_p = 0.097
    ff++ real (rostro video)     artwork_p = 0.028
    ff++ fake (deepfake)         artwork_p = 0.046
    diffusiondb (arte IA)        artwork_p = 0.881
    sdturbo_sports (IA fotorrea) artwork_p = 0.103
    AUC foto-vs-arte = 0.973

Notese que el deepfake facial y la imagen IA fotorrealista quedan del lado
"fotografia": la compuerta separa por *tipo de contenido*, no por autoria.

Coste: reutiliza el CLIP ViT-L/14 que ya carga el modelo C. 0 VRAM adicional
cuando ese modelo esta disponible.
"""
from typing import Optional

import numpy as np
import torch
from PIL import Image
from loguru import logger

from app.config import settings

# ── Bancos de prompts ────────────────────────────────────────────────────────
PHOTO_PROMPTS = [
    "a photograph taken with a camera",
    "a real photo of a person",
    "a candid photograph",
    "a photojournalism photograph",
    "a snapshot from a digital camera",
    "a real-world photograph of a scene",
]
ART_PROMPTS = [
    "a digital illustration",
    "a painting",
    "a drawing",
    "digital art",
    "an anime illustration",
    "a 3d rendered image",
    "concept art",
    "a fantasy artwork",
]

# Umbral por encima del cual el contenido se considera obra grafica.
# Elegido sobre la curva de validacion: a 0.55 se captura ~91% del arte IA
# marcando erroneamente solo ~2% de las fotografias.
ARTWORK_THRESHOLD = 0.55

_CLIP_ID = "openai/clip-vit-large-patch14"


class ContentTypeGate:
    """Singleton. Devuelve P(obra grafica) para una imagen."""

    _instance: Optional["ContentTypeGate"] = None

    def __init__(self) -> None:
        self.device = torch.device(
            "cuda" if settings.DEVICE == "cuda" and torch.cuda.is_available() else "cpu"
        )
        self._model = None
        self._proc = None
        self._text_feat: Optional[torch.Tensor] = None
        self._n_photo = len(PHOTO_PROMPTS)
        self._loaded = False
        self._available = True

    @classmethod
    def get_instance(cls) -> "ContentTypeGate":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── carga ────────────────────────────────────────────────────────────────
    def load(self) -> None:
        if self._loaded or not self._available:
            return
        try:
            from transformers import CLIPModel, CLIPProcessor

            # Reutiliza el CLIP del modelo C si ya esta en memoria
            shared = self._borrow_model_c_clip()
            if shared is not None:
                self._model, self._proc = shared
                logger.info("[gate] CLIP reutilizado del modelo C (0 VRAM extra)")
            else:
                dtype = torch.float16 if self.device.type == "cuda" else torch.float32
                self._model = CLIPModel.from_pretrained(
                    _CLIP_ID, cache_dir=str(settings.MODELS_DIR), torch_dtype=dtype
                )
                self._proc = CLIPProcessor.from_pretrained(
                    _CLIP_ID, cache_dir=str(settings.MODELS_DIR)
                )
                self._model.to(self.device).eval()
                logger.info("[gate] CLIP ViT-L/14 cargado para la compuerta")

            self._build_text_bank()
            self._loaded = True
            logger.success(
                f"[gate] Content-Type Gate listo | umbral={ARTWORK_THRESHOLD}"
            )
        except Exception as e:
            logger.warning(f"[gate] Carga fallida: {e} — compuerta deshabilitada")
            self._available = False

    def _borrow_model_c_clip(self):
        """Toma prestado el CLIP ya cargado por el modelo C, si existe."""
        try:
            from app.models.deepfake_detector import _model_c
            if getattr(_model_c, "_loaded", False):
                m = getattr(_model_c, "_clip_model", None)
                p = getattr(_model_c, "_clip_proc", None)
                if m is not None and p is not None:
                    return m, p
        except Exception:
            pass
        return None

    @torch.no_grad()
    def _build_text_bank(self) -> None:
        tok = self._proc(
            text=PHOTO_PROMPTS + ART_PROMPTS, return_tensors="pt", padding=True
        ).to(self.device)
        pooled = self._model.text_model(**tok).pooler_output
        feat = self._model.text_projection(pooled).float()
        self._text_feat = feat / feat.norm(dim=-1, keepdim=True)

    # ── inferencia ───────────────────────────────────────────────────────────
    @torch.no_grad()
    def _image_feat(self, images: list[Image.Image]) -> torch.Tensor:
        inp = self._proc(
            images=[im.convert("RGB") for im in images],
            return_tensors="pt", padding=True,
        )
        px = inp["pixel_values"].to(self.device)
        if self.device.type == "cuda":
            px = px.half()
        pooled = self._model.vision_model(pixel_values=px).pooler_output
        f = self._model.visual_projection(pooled).float()
        return f / f.norm(dim=-1, keepdim=True)

    def artwork_probability_batch(self, images: list[Image.Image]) -> list[float]:
        """P(obra grafica) para cada imagen. 0.0 si la compuerta no esta activa."""
        if not self._loaded:
            self.load()
        if not self._loaded or not images:
            return [0.0] * len(images)
        try:
            with torch.no_grad():
                f = self._image_feat(images)
                scale = self._model.logit_scale.exp().float()
                sim = (f @ self._text_feat.T) * scale
                # max-pool dentro de cada banco, softmax entre los dos
                photo_s = sim[:, : self._n_photo].max(dim=1).values
                art_s = sim[:, self._n_photo :].max(dim=1).values
                pr = torch.softmax(torch.stack([photo_s, art_s], dim=1), dim=1)[:, 1]
            return [float(x) for x in pr.cpu().numpy()]
        except Exception as e:
            logger.debug(f"[gate] batch fallido: {e}")
            return [0.0] * len(images)

    def artwork_probability(self, image: Image.Image) -> float:
        return self.artwork_probability_batch([image])[0]

    def classify(self, image: Image.Image) -> dict:
        """
        Devuelve el veredicto de tipo de contenido.

        {"artwork_probability": float,
         "is_artwork": bool,
         "content_type": "artwork" | "photographic",
         "gate_available": bool}
        """
        if not self._loaded:
            self.load()
        if not self._loaded:
            return {
                "artwork_probability": None,
                "is_artwork": False,
                "content_type": "photographic",
                "gate_available": False,
            }
        p = self.artwork_probability(image)
        is_art = p >= ARTWORK_THRESHOLD
        return {
            "artwork_probability": round(p, 4),
            "is_artwork": is_art,
            "content_type": "artwork" if is_art else "photographic",
            "gate_available": True,
        }

    @property
    def is_available(self) -> bool:
        return self._loaded
