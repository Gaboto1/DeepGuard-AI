"""
Meta-Ensemble Model — v2 (con Temperature Scaling + Veto de Consenso)
======================================================================
Correcciones vs v1:
  1. Temperature Scaling aplicado usando el T guardado en training
  2. Veto de consenso: si los detectores ROBUSTOS (SDXL + AI Art) concuerdan
     en que la imagen es real (ambos < umbral), el meta-modelo no puede elevar
     el resultado por encima de ese consenso.
  3. Feature engineering aplicado en inferencia (mismo que en entrenamiento)

Lógica del Veto de Consenso:
  Los modelos "robustos" son aquellos con bajo FPR en el benchmark:
    - SDXL Detector:    FPR = 0.8%  (muy confiable para fotos reales)
    - AI Art Detector:  FPR = 8.6%  (confiable para fotos reales)
  Si ambos dan < VETO_THRESHOLD, la media robusta veta el score del meta-modelo:
    final = interp(meta_score, robust_mean, weight=VETO_STRENGTH)
"""
import json
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

from app.config import settings

_META_DIR    = settings.MODELS_DIR / "meta_ensemble"
_MODEL_PATH  = _META_DIR / "meta_classifier.joblib"
_CONFIG_PATH = _META_DIR / "meta_config.json"

# Todos los modelos del ensemble (para calcular incertidumbre)
BASE_FEATURES = [
    "face_deepfake_vit",
    "sdxl_detector",
    "efficientnet_ffpp",
    "ai_art_detector",
    "siglip_deepfake",
]

# Features usadas en el meta-modelo (solo detectores confiables — FPR < 15%)
# ViT (FPR=96%) y SigLIP (FPR=100%) excluidos del meta-modelo deliberadamente
RELIABLE_META_FEATURES = [
    "sdxl_detector",
    "ai_art_detector",
    "efficientnet_ffpp",
]

# Detectores robustos para el veto de consenso
ROBUST_KEYS = ["sdxl_detector", "ai_art_detector"]

# Umbral de consenso: si la media de robustos < esto, aplica el veto
VETO_THRESHOLD = 0.25   # reducido: solo veta cuando robustos son MUY seguros que es real

# Fuerza del veto (0=sin efecto, 1=veto total)
# Reducido de 0.65 a 0.50 para no suprimir demasiado los verdaderos positivos
VETO_STRENGTH  = 0.60

# Discrepancia mínima para activar el veto:
# Solo veta si meta dice ≥ VETO_MIN_DISCREPANCY más que los modelos robustos
# Esto evita vetar casos donde meta y robustos están de acuerdo (ambos bajos o altos)
VETO_MIN_DISCREPANCY = 0.35

# Fallback weights (grid-search) si el meta-modelo no está disponible
_FALLBACK_NO_FACE = [0.30, 0.20, 0.00, 0.20, 0.30]
_FALLBACK_FACE    = [0.35, 0.25, 0.05, 0.25, 0.10]


class MetaEnsemble:
    _instance: Optional["MetaEnsemble"] = None

    def __init__(self) -> None:
        self._model       = None
        self._config      = {}
        self._loaded      = False
        self._use_meta    = False
        self._temperature = 1.0
        self._has_eng     = False  # si el modelo usa features engineered

    @classmethod
    def get_instance(cls) -> "MetaEnsemble":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self) -> None:
        if self._loaded:
            return
        try:
            import joblib
            if _MODEL_PATH.exists():
                data = joblib.load(str(_MODEL_PATH))
                self._model       = data["model"]
                self._temperature = float(data.get("temperature", 1.0))
                saved_features    = data.get("features", BASE_FEATURES)
                self._has_eng     = len(saved_features) > len(BASE_FEATURES)
                self._use_meta    = True
                self._loaded      = True
                logger.success(
                    f"MetaEnsemble v2 cargado: {data.get('name','?')} | "
                    f"T={self._temperature:.3f} | eng_features={self._has_eng}"
                )
            else:
                logger.warning(f"Meta-model no encontrado en {_MODEL_PATH} — usando fallback")
                self._use_meta = False
                self._loaded   = True
        except Exception as e:
            logger.warning(f"MetaEnsemble carga fallida: {e} — usando fallback")
            self._use_meta = False
            self._loaded   = True

        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH) as f:
                self._config = json.load(f)

    def _apply_temperature(self, prob: float) -> float:
        """Escala la probabilidad con la temperatura calibrada."""
        if abs(self._temperature - 1.0) < 0.01:
            return prob
        eps    = 1e-7
        logit  = np.log(np.clip(prob, eps, 1-eps) / np.clip(1-prob, eps, 1-eps))
        scaled = 1.0 / (1.0 + np.exp(-logit / self._temperature))
        return float(np.clip(scaled, 0, 1))

    def _consensus_veto(
        self,
        meta_prob: float,
        scores: dict[str, Optional[float]],
    ) -> tuple[float, bool]:
        """
        Si los detectores robustos coinciden en que la imagen es real
        con alta confianza, penaliza el resultado del meta-modelo.

        Retorna (prob_ajustada, veto_aplicado).

        Ejemplo que provocaba el bug:
          SDXL=0.01, AI_Art=0.10 → robust_mean=0.055
          Meta-LightGBM dice 0.68 (por SigLIP=0.96 + ViT=0.65)
          Con VETO_STRENGTH=0.60 (valor actual):
            final = 0.055 * 0.60 + 0.68 * 0.40 = 0.033 + 0.272 = 0.305
        """
        robust_vals = [
            scores[k] for k in ROBUST_KEYS if scores.get(k) is not None
        ]
        if not robust_vals:
            return meta_prob, False

        robust_mean = float(np.mean(robust_vals))

        if robust_mean >= VETO_THRESHOLD:
            return meta_prob, False  # robustos no descartan — no vetar

        # Solo veta si hay una discrepancia GRANDE entre meta y robustos
        # Esto evita suprimir imágenes IA donde SDXL también da score bajo
        discrepancy = meta_prob - robust_mean
        if discrepancy < VETO_MIN_DISCREPANCY:
            return meta_prob, False  # meta y robustos coinciden en el orden — no vetar

        # Veto: meta dice fake con mucha confianza pero robustos dicen real
        final = robust_mean * VETO_STRENGTH + meta_prob * (1.0 - VETO_STRENGTH)
        return float(np.clip(final, 0, 1)), True

    def predict(
        self,
        scores: dict[str, Optional[float]],
        face: bool = False,
    ) -> tuple[float, dict]:
        self.load()

        filled = [scores.get(k) or 0.5 for k in BASE_FEATURES]
        valid_mask = [scores.get(k) is not None for k in BASE_FEATURES]

        if self._use_meta and self._model is not None:
            try:
                # Extraer solo los features confiables (en el orden correcto)
                sdxl  = scores.get("sdxl_detector")   or 0.5
                aiart = scores.get("ai_art_detector")  or 0.5
                effnet= scores.get("efficientnet_ffpp") or 0.5

                # Base confiables + engineered
                feat_vec = [sdxl, aiart, effnet]
                if self._has_eng:
                    reliable_scores = [sdxl, aiart, effnet]
                    std_r = float(np.std(reliable_scores))
                    feat_vec += [sdxl * aiart, (sdxl + aiart) / 2, std_r]

                X    = np.array([feat_vec])
                prob = float(self._model.predict_proba(X)[0, 1])

                # 1. Temperature Scaling
                prob = self._apply_temperature(prob)

                # 2. Veto de consenso
                prob, vetoed = self._consensus_veto(prob, scores)

                model_tag = self._config.get("best_method", "meta").lower().replace(" ", "_")
                method = f"meta_{model_tag}" + ("_vetoed" if vetoed else "")

            except Exception as e:
                logger.debug(f"Meta predict error: {e} — fallback")
                prob   = self._fallback(filled, face)
                vetoed = False
                method = "fallback_weights"
        else:
            prob   = self._fallback(filled, face)
            vetoed = False
            method = "fallback_weights"

        # Métricas de incertidumbre
        available  = [scores[k] for k in BASE_FEATURES if scores.get(k) is not None]
        std        = float(np.std(available)) if len(available) > 1 else 0.5
        entropy    = float(
            -prob * np.log(prob + 1e-8) - (1-prob) * np.log(1-prob + 1e-8)
        )
        ood_signal = all(abs(s - 0.5) < 0.15 for s in available) and std < 0.10

        # Info adicional del veto (para debugging y transparencia)
        robust_vals = [scores[k] for k in ROBUST_KEYS if scores.get(k) is not None]
        robust_mean = float(np.mean(robust_vals)) if robust_vals else None

        meta = {
            "method":        method,
            "models_avail":  sum(valid_mask),
            "std":           round(std,     4),
            "entropy":       round(entropy, 4),
            "ood_signal":    ood_signal,
            "temperature":   round(self._temperature, 3),
            "robust_mean":   round(robust_mean, 4) if robust_mean is not None else None,
            "veto_applied":  vetoed,
        }
        return float(np.clip(prob, 0, 1)), meta

    def _fallback(self, scores: list[float], face: bool) -> float:
        w       = _FALLBACK_FACE if face else _FALLBACK_NO_FACE
        total_w = sum(w)
        return float(np.clip(sum(wt*sc/total_w for wt, sc in zip(w, scores)), 0, 1))

    @property
    def is_meta(self) -> bool:
        return self._use_meta and self._model is not None
