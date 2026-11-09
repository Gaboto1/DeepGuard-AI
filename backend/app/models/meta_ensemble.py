"""
Meta-Ensemble Model — v3 (doble cabezal + compuerta de tipo de contenido)
=========================================================================

Cambios frente a v2
-------------------
1. **Carga corregida.** v2 leia ``data["model"]`` pero el artefacto se guarda
   bajo la clave ``"clf"``. El ``KeyError`` caia en el ``except``, dejaba
   ``_use_meta = False`` y el sistema corria SIEMPRE con los pesos fallback
   codificados a mano — el meta-modelo entrenado nunca llego a ejecutarse en
   produccion. Ahora se aceptan ambas claves.

2. **Features derivadas del artefacto.** v2 construia a mano un vector de 6
   posiciones que no coincidia ni en orden ni en contenido con las 7 columnas
   con las que se entreno el modelo. Ahora el vector se arma leyendo
   ``feature_cols`` del propio artefacto, asi que no puede volver a
   desalinearse: si el entrenamiento cambia, la inferencia lo sigue.

3. **Doble cabezal con compuerta de contenido.** El detector de arte IA
   concentraba el 91% de la importancia del meta-modelo: el porcentaje final
   era, en la practica, su sola opinion. Cuando la compuerta
   (``content_type_gate``) determina que el contenido es una obra grafica y no
   una fotografia, se usa un segundo cabezal entrenado SIN esas features, y el
   score de arte IA se reporta por separado sin afectar al porcentaje forense.

Cabezales
---------
    meta_classifier.joblib        con features de arte IA  -> contenido fotografico
    meta_classifier_noart.joblib  sin features de arte IA  -> obra grafica
"""
import json
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

from app.config import settings

_META_DIR = settings.MODELS_DIR / "meta_ensemble"
_MODEL_PATH = _META_DIR / "meta_classifier.joblib"
_NOART_PATH = _META_DIR / "meta_classifier_noart.joblib"
_FACE_PATH = _META_DIR / "meta_classifier_face.joblib"
_CONFIG_PATH = _META_DIR / "meta_config.json"

# Todos los modelos del ensemble (para metricas de incertidumbre)
BASE_FEATURES = [
    "face_deepfake_vit",
    "sdxl_detector",
    "efficientnet_ffpp",
    "ai_art_detector",
    "siglip_deepfake",
]

# Features usadas en el meta-modelo (solo detectores confiables — FPR < 15%)
RELIABLE_META_FEATURES = [
    "sdxl_detector",
    "ai_art_detector",
    "efficientnet_ffpp",
]

# Features atribuibles al detector de arte IA.
AI_ART_FEATURES = {"ai_art_detector", "sdxl_x_aiart"}

# ── Politica de participacion del detector de arte IA ────────────────────────
#
#   "always_separate"  (por defecto)
#       El detector de arte IA NUNCA entra en el porcentaje forense; se reporta
#       siempre como indicador independiente.
#
#   "gated"
#       Entra en el porcentaje solo cuando la compuerta clasifica el contenido
#       como fotografia; en obra grafica queda fuera.
#
# El valor por defecto fue "always_separate" y se cambio a "gated" tras medir su
# efecto sobre fotografia real recomprimida, que es el caso que mas aparece en
# uso real: una foto que paso por redes sociales.
#
# Medicion de extremo a extremo (245 imagenes, 7 grupos, pipeline completo):
#
#                                     always_separate      gated
#     AUC                                  0.734           0.808
#     Falsas alarmas (real >= 0.60)        17.1 %           4.3 %
#     Fotos reales bien clasificadas       42.9 %          92.9 %
#     coco recomprimida q=55 (media)        0.491           0.150
#     Deepfakes faciales detectados        25.7 %           8.6 %
#
# El motivo es que el detector de arte IA es la senal mas robusta a la
# compresion de todo el conjunto: sobre fotografia autentica se mantiene entre
# 0 % y 6 % aunque la imagen se recomprima, mientras los demas detectores se
# desplazan con los artefactos JPEG. Excluirlo del contenido fotografico
# eliminaba justamente la evidencia que sostenia el veredicto "es una foto
# real", y tambien desactivaba el Compression Veto, que depende de el.
#
# La separacion se mantiene donde estaba fundamentada: en obra grafica, donde el
# detector responde a otra pregunta ("¿genero una IA esta obra?") y concentraba
# el 91 % de la importancia del meta-modelo. Y en ambas politicas su puntuacion
# se reporta siempre como indicador independiente en la respuesta de la API.
#
# El coste es la deteccion de deepfakes faciales, que baja de 25.7 % a 8.6 %.
# Ninguna de las dos cifras es buena: es una limitacion conocida del conjunto de
# detectores, no de esta eleccion.
AI_ART_POLICY = "gated"


def ai_art_is_excluded(is_artwork: bool) -> bool:
    """
    ¿Queda el detector de arte IA fuera del porcentaje forense para este caso?

    Fuente unica de verdad de la politica: la usan tanto el meta-ensemble como
    las reglas de correccion forense, para que no puedan discrepar y reintroducir
    el score por una via lateral.
    """
    return AI_ART_POLICY == "always_separate" or is_artwork

# Claves sobre las que se calculan robust_mean / reliable_std cuando el
# artefacto no declara las suyas (modelos entrenados antes de la v3).
_DEFAULT_STAT_KEYS = [
    "sdxl_detector",
    "ai_art_detector",
    "efficientnet_ffpp",
    "ai_human_detector",
]

# Detectores robustos para el veto de consenso
ROBUST_KEYS = ["sdxl_detector", "ai_art_detector"]

# Robustos alternativos cuando el arte IA esta excluido del score
ROBUST_KEYS_NOART = ["sdxl_detector", "efficientnet_ffpp"]

# Umbral de consenso: si la media de robustos < esto, aplica el veto
VETO_THRESHOLD = 0.25

# Fuerza del veto (0=sin efecto, 1=veto total)
VETO_STRENGTH = 0.60

# Discrepancia minima para activar el veto
VETO_MIN_DISCREPANCY = 0.35

# Fallback weights (grid-search) si el meta-modelo no esta disponible
_FALLBACK_NO_FACE = [0.30, 0.20, 0.00, 0.20, 0.30]
_FALLBACK_FACE = [0.35, 0.25, 0.05, 0.25, 0.10]


# ── Construccion del vector de features ──────────────────────────────────────

def build_feature_vector(
    scores: dict[str, Optional[float]],
    feature_cols: list[str],
    stat_keys: Optional[list[str]] = None,
) -> np.ndarray:
    """
    Arma el vector de entrada del meta-modelo replicando exactamente el feature
    engineering del entrenamiento (``scripts/add_modelf_and_retrain.py``):

        sdxl_x_aiart = sdxl.fillna(0.5) * aiart.fillna(0.5)
        robust_mean  = nanmedian(stat_keys)
        reliable_std = nanstd(valores no-NaN de stat_keys), 0.0 si hay <= 1
        y al final, todo NaN restante -> 0.5

    El orden lo dicta ``feature_cols``, leido del artefacto entrenado.
    """
    stat_keys = stat_keys or _DEFAULT_STAT_KEYS

    def raw(key: str) -> float:
        v = scores.get(key)
        return float(v) if v is not None else np.nan

    derived: dict[str, float] = {}

    sdxl = raw("sdxl_detector")
    aiart = raw("ai_art_detector")
    derived["sdxl_x_aiart"] = (
        (0.5 if np.isnan(sdxl) else sdxl) * (0.5 if np.isnan(aiart) else aiart)
    )

    stat_vals = np.array([raw(k) for k in stat_keys], dtype=float)
    finite = stat_vals[~np.isnan(stat_vals)]
    derived["robust_mean"] = float(np.median(finite)) if finite.size else np.nan
    derived["reliable_std"] = float(np.std(finite)) if finite.size > 1 else 0.0

    vec = []
    for col in feature_cols:
        val = derived[col] if col in derived else raw(col)
        vec.append(0.5 if (val is None or np.isnan(val)) else val)
    return np.array([vec], dtype=float)


class _Head:
    """Un cabezal del meta-ensemble: clasificador + temperatura + features."""

    def __init__(self, path: Path, tag: str) -> None:
        self.path = path
        self.tag = tag
        self.clf = None
        self.temperature = 1.0
        self.feature_cols: list[str] = []
        self.stat_keys: Optional[list[str]] = None
        self.available = False

    def load(self) -> None:
        if not self.path.exists():
            logger.warning(f"[meta:{self.tag}] no encontrado en {self.path}")
            return
        try:
            import joblib

            data = joblib.load(str(self.path))
            # El artefacto guarda el estimador bajo "clf"; se acepta "model"
            # por compatibilidad con versiones antiguas.
            clf = data.get("clf", data.get("model"))
            if clf is None:
                logger.warning(f"[meta:{self.tag}] artefacto sin estimador")
                return
            cols = data.get("feature_cols") or data.get("features")
            if not cols:
                logger.warning(f"[meta:{self.tag}] artefacto sin feature_cols")
                return

            self.clf = clf
            self.feature_cols = list(cols)
            self.stat_keys = data.get("stat_keys")
            self.temperature = float(data.get("temperature", 1.0))
            self.available = True

            n_exp = getattr(clf, "n_features_in_", None)
            if n_exp is not None and n_exp != len(self.feature_cols):
                logger.error(
                    f"[meta:{self.tag}] DESALINEADO: el modelo espera {n_exp} "
                    f"features pero feature_cols tiene {len(self.feature_cols)}"
                )
                self.available = False
                return

            logger.success(
                f"[meta:{self.tag}] {type(clf).__name__} | "
                f"T={self.temperature:.3f} | {len(self.feature_cols)} features"
            )
        except Exception as e:
            logger.warning(f"[meta:{self.tag}] carga fallida: {e}")
            self.available = False

    def predict_proba(self, scores: dict[str, Optional[float]]) -> float:
        X = build_feature_vector(scores, self.feature_cols, self.stat_keys)
        return float(self.clf.predict_proba(X)[0, 1])


class MetaEnsemble:
    _instance: Optional["MetaEnsemble"] = None

    def __init__(self) -> None:
        self._full = _Head(_MODEL_PATH, "full")
        self._noart = _Head(_NOART_PATH, "noart")
        # Cabezal facial: en contenido con rostro solo el probe CLIP es
        # competente (AUC 0.976 dentro de ff++ frente a 0.48-0.58 de los otros
        # cinco). El cabezal general los pondera como iguales y dejaba los
        # deepfakes en la banda "inconcluyente"; este aprende esa jerarquia.
        self._face = _Head(_FACE_PATH, "face")
        self._config = {}
        self._loaded = False

    @classmethod
    def get_instance(cls) -> "MetaEnsemble":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self) -> None:
        if self._loaded:
            return
        self._full.load()
        self._noart.load()
        self._face.load()
        if not self._full.available:
            logger.warning("Meta-modelo principal no disponible — usando fallback")
        if not self._noart.available:
            logger.info(
                "Cabezal sin-arte no disponible — el contenido grafico usara el "
                "cabezal principal con el arte IA neutralizado"
            )
        if _CONFIG_PATH.exists():
            try:
                with open(_CONFIG_PATH) as f:
                    self._config = json.load(f)
            except Exception:
                self._config = {}
        self._loaded = True

    # ── calibracion ──────────────────────────────────────────────────────────
    @staticmethod
    def _apply_temperature(prob: float, temperature: float) -> float:
        if abs(temperature - 1.0) < 0.01:
            return prob
        eps = 1e-7
        logit = np.log(np.clip(prob, eps, 1 - eps) / np.clip(1 - prob, eps, 1 - eps))
        scaled = 1.0 / (1.0 + np.exp(-logit / temperature))
        return float(np.clip(scaled, 0, 1))

    # ── veto de consenso ─────────────────────────────────────────────────────
    def _consensus_veto(
        self,
        meta_prob: float,
        scores: dict[str, Optional[float]],
        robust_keys: Optional[list[str]] = None,
    ) -> tuple[float, bool]:
        """
        Si los detectores robustos coinciden en que la imagen es real con alta
        confianza, penaliza el resultado del meta-modelo.

        Retorna (prob_ajustada, veto_aplicado).
        """
        keys = robust_keys or ROBUST_KEYS
        robust_vals = [scores[k] for k in keys if scores.get(k) is not None]
        if not robust_vals:
            return meta_prob, False

        robust_mean = float(np.mean(robust_vals))
        if robust_mean >= VETO_THRESHOLD:
            return meta_prob, False

        discrepancy = meta_prob - robust_mean
        if discrepancy < VETO_MIN_DISCREPANCY:
            return meta_prob, False

        final = robust_mean * VETO_STRENGTH + meta_prob * (1.0 - VETO_STRENGTH)
        return float(np.clip(final, 0, 1)), True

    # ── prediccion ───────────────────────────────────────────────────────────
    def predict(
        self,
        scores: dict[str, Optional[float]],
        face: bool = False,
        is_artwork: bool = False,
    ) -> tuple[float, dict]:
        """
        Combina los scores de los detectores en una probabilidad forense.

        ``is_artwork``: cuando la compuerta de tipo de contenido determina que
        la imagen es una obra grafica (ilustracion, pintura, render) en lugar de
        una fotografia, el detector de arte IA queda FUERA del calculo y se
        reporta por separado. Su pregunta ("¿genero una IA esta obra?") no es la
        pregunta forense ("¿fue manipulada esta fotografia?"), y su peso
        dominante distorsionaba el porcentaje final.
        """
        self.load()

        head, ai_art_excluded, eff_scores = self._select_head(
            scores, is_artwork, face=face)

        if head is not None:
            try:
                prob = head.predict_proba(eff_scores)
                prob = self._apply_temperature(prob, head.temperature)
                robust_keys = ROBUST_KEYS_NOART if ai_art_excluded else ROBUST_KEYS
                prob, vetoed = self._consensus_veto(prob, eff_scores, robust_keys)
                model_tag = self._config.get("best_method", "meta").lower().replace(" ", "_")
                method = f"meta_{model_tag}"
                if head.tag != "full":
                    method += f"_{head.tag}"
                if vetoed:
                    method += "_vetoed"
            except Exception as e:
                logger.debug(f"Meta predict error: {e} — fallback")
                prob = self._fallback_from(scores, face)
                vetoed = False
                method = "fallback_weights"
        else:
            prob = self._fallback_from(scores, face)
            vetoed = False
            method = "fallback_weights"

        meta = self._uncertainty(scores, prob)
        meta.update({
            "method": method,
            "veto_applied": vetoed,
            "temperature": round(head.temperature, 3) if head else 1.0,
            "content_track": "artwork" if is_artwork else "photographic",
            "ai_art_excluded": ai_art_excluded,
            "head": head.tag if head else "fallback",
        })
        return float(np.clip(prob, 0, 1)), meta

    def _select_head(
        self, scores: dict[str, Optional[float]], is_artwork: bool,
        face: bool = False,
    ) -> tuple[Optional[_Head], bool, dict[str, Optional[float]]]:
        """
        Elige el cabezal y decide si el arte IA queda excluido del porcentaje.

        Orden de decision:

          1. Rostro detectado y contenido fotografico -> cabezal facial.
             Entrenado solo con rostros, porque ahi el probe CLIP es el unico
             detector competente y el cabezal general lo diluia con cinco
             detectores que estan al nivel del azar en ese caso.
          2. Si no, la politica ``AI_ART_POLICY`` decide si el arte IA
             participa (``gated``: solo en fotografia) y, cuando queda fuera,
             se usa el cabezal sin-arte. Si ese artefacto no existe, se recurre
             al completo con las features de arte neutralizadas a 0.5, de modo
             que el arte IA no pueda mover el resultado por ninguna via.

        El cabezal facial no se usa en obra grafica: un rostro dibujado no es
        una fotografia de rostro y el detector no fue entrenado para eso.
        """
        if face and not is_artwork and self._face.available:
            return self._face, True, scores

        exclude = ai_art_is_excluded(is_artwork)

        if not exclude:
            return (self._full if self._full.available else None), False, scores

        if self._noart.available:
            return self._noart, True, scores

        if self._full.available:
            neutral = dict(scores)
            for k in AI_ART_FEATURES:
                if k in neutral:
                    neutral[k] = None  # -> 0.5 al construir el vector
            neutral["ai_art_detector"] = None
            return self._full, True, neutral

        return None, True, scores

    # ── fallback y metricas ──────────────────────────────────────────────────
    def _fallback_from(self, scores: dict[str, Optional[float]], face: bool) -> float:
        filled = [
            scores.get(k) if scores.get(k) is not None else 0.5 for k in BASE_FEATURES
        ]
        return self._fallback(filled, face)

    def _fallback(self, scores: list[float], face: bool) -> float:
        w = _FALLBACK_FACE if face else _FALLBACK_NO_FACE
        total_w = sum(w)
        return float(np.clip(sum(wt * sc / total_w for wt, sc in zip(w, scores)), 0, 1))

    def _uncertainty(self, scores: dict[str, Optional[float]], prob: float) -> dict:
        available = [scores[k] for k in BASE_FEATURES if scores.get(k) is not None]
        std = float(np.std(available)) if len(available) > 1 else 0.5
        entropy = float(
            -prob * np.log(prob + 1e-8) - (1 - prob) * np.log(1 - prob + 1e-8)
        )
        ood_signal = (
            bool(available)
            and all(abs(s - 0.5) < 0.15 for s in available)
            and std < 0.10
        )
        robust_vals = [scores[k] for k in ROBUST_KEYS if scores.get(k) is not None]
        robust_mean = float(np.mean(robust_vals)) if robust_vals else None
        return {
            "models_avail": len(available),
            "std": round(std, 4),
            "entropy": round(entropy, 4),
            "ood_signal": ood_signal,
            "robust_mean": round(robust_mean, 4) if robust_mean is not None else None,
        }

    @property
    def is_meta(self) -> bool:
        return self._full.available or self._noart.available

    @property
    def has_noart_head(self) -> bool:
        return self._noart.available
