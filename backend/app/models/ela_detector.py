"""
ELA (Error Level Analysis) Detector
=====================================
Fundamento forense (Krawetz 2007, Zhao et al. 2015):

  ELA re-comprime una imagen JPEG a calidad conocida y mide la diferencia
  pixel a pixel entre original y re-comprimida.

  CLAVE: La compresion JPEG introduce errores proporcionales a la variacion
  de la region. Si toda la imagen tiene el MISMO historial de compresion,
  los errores ELA son uniformes. Si hay regiones con distinto historial
  (copia-pega, composicion), las diferencias son significativas.

  Para imagenes AI-generadas:
    - Toda la imagen se genera en un solo paso de inferencia → mismo historial
    - ELA es MUY UNIFORME (desviacion estandar muy baja del mapa ELA)
    - Media ELA BAJA (la imagen es "fresca", sin compresion acumulada)

  Para fotos reales autenticas:
    - Tienen historial de compresion variable por region (textura, bordes, etc.)
    - ELA es HETEROGENEA (mayor desviacion estandar)
    - Bordes y texturas tienen mayor ELA; areas planas tienen menor ELA

  Señal ORTOGONAL a FFT (espectral global) y SRM (residuos locales):
    - FFT: analiza distribucion de frecuencias globales
    - SRM: analiza residuos de filtros de prediccion lineal
    - ELA: analiza uniformidad del historial de compresion

Sin PyTorch ni modelos — solo PIL + NumPy.
VRAM: 0 bytes.
Latencia: ~15-40ms/imagen en CPU (incluye re-compresion).
"""
from __future__ import annotations

import io
import numpy as np
from PIL import Image
from loguru import logger


class ELADetector:
    """
    Detector singleton de artefactos por Error Level Analysis.

    Tres señales estadisticas del mapa ELA:
      1. Uniformidad de la media ELA  — AI baja + uniforme
      2. Uniformidad de la std ELA    — AI muy baja varianza
      3. Consistencia de parches locales — AI: parches similares entre si

    Calibracion (empirica, JPEG q75 re-compresion):
      Reales: ela_mean ≈ 0.022-0.038, ela_std ≈ 0.018-0.030
      AI:     ela_mean ≈ 0.006-0.016, ela_std ≈ 0.003-0.010
    """

    _instance: "ELADetector | None" = None

    # Calidad de re-compresion para ELA
    _ELA_QUALITY = 75

    # Calibracion: valores de referencia para normalizar las señales
    # Imágenes reales autenticas (media y std del mapa ELA):
    _MEAN_REAL = 0.030    # media ELA tipica de foto real
    _MEAN_AI   = 0.010    # media ELA tipica de imagen IA (mas baja)

    _STD_REAL  = 0.024    # desviacion de ELA: fotos reales son heterogeneas
    _STD_AI    = 0.006    # desviacion de ELA: imagenes IA son uniformes

    _PATCH_CV_REAL = 0.60  # coeficiente de variacion entre parches (real=alto)
    _PATCH_CV_AI   = 0.18  # coeficiente de variacion entre parches (IA=bajo)

    # Pesos de la combinacion interna
    _W_MEAN_INV  = 0.35   # media ELA baja → más IA
    _W_STD_INV   = 0.50   # std ELA baja → más IA (señal más discriminativa)
    _W_PATCH     = 0.15   # uniformidad entre parches → más IA

    @classmethod
    def get_instance(cls) -> "ELADetector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _compute_ela_map(self, image: Image.Image) -> np.ndarray:
        """Re-comprime la imagen y retorna el mapa de diferencias normalizadas."""
        img_rgb = image.convert("RGB")

        buf = io.BytesIO()
        img_rgb.save(buf, format="JPEG", quality=self._ELA_QUALITY, optimize=True)
        buf.seek(0)
        recompressed = Image.open(buf).convert("RGB")

        orig_arr   = np.array(img_rgb, dtype=np.float32) / 255.0
        recomp_arr = np.array(recompressed, dtype=np.float32) / 255.0

        # Mapa ELA: diferencia absoluta promediada sobre canales RGB
        ela = np.abs(orig_arr - recomp_arr).mean(axis=2)
        return ela

    def _patch_cv(self, ela: np.ndarray, n_patches: int = 12) -> float:
        """
        Coeficiente de variacion entre medias de parches locales.
        Bajo CV → parches similares entre si → más uniforme → más IA.
        """
        h, w       = ela.shape
        patch_h    = max(8, h // n_patches)
        patch_w    = max(8, w // n_patches)
        patch_means = []

        for py in range(0, h - patch_h + 1, patch_h):
            for px in range(0, w - patch_w + 1, patch_w):
                patch = ela[py:py + patch_h, px:px + patch_w]
                patch_means.append(float(patch.mean()))

        if len(patch_means) < 4:
            return (self._PATCH_CV_REAL + self._PATCH_CV_AI) / 2.0

        mean_of_means = float(np.mean(patch_means))
        if mean_of_means < 1e-8:
            return self._PATCH_CV_AI  # imagen totalmente plana → IA-like

        return float(np.std(patch_means) / (mean_of_means + 1e-8))

    def predict(self, image: Image.Image) -> dict:
        """
        Retorna dict con fake_probability y metricas ELA.
        fake_probability alta → imagen mas probablemente sintetica.
        """
        try:
            ela = self._compute_ela_map(image)

            ela_mean = float(ela.mean())
            ela_std  = float(ela.std())
            patch_cv = self._patch_cv(ela)

            # Score 1: media ELA baja → más IA (inverted)
            mean_score = float(np.clip(
                (self._MEAN_REAL - ela_mean) / (self._MEAN_REAL - self._MEAN_AI),
                0.0, 1.0,
            ))

            # Score 2: std ELA baja → más uniforme → más IA (inverted)
            std_score = float(np.clip(
                (self._STD_REAL - ela_std) / (self._STD_REAL - self._STD_AI),
                0.0, 1.0,
            ))

            # Score 3: bajo CV entre parches → más uniforme → más IA (inverted)
            patch_score = float(np.clip(
                (self._PATCH_CV_REAL - patch_cv) / (self._PATCH_CV_REAL - self._PATCH_CV_AI),
                0.0, 1.0,
            ))

            fake_prob = (
                self._W_MEAN_INV  * mean_score
                + self._W_STD_INV   * std_score
                + self._W_PATCH     * patch_score
            )
            fake_prob = float(np.clip(fake_prob, 0.0, 1.0))

            return {
                "fake_probability": fake_prob,
                "real_probability": 1.0 - fake_prob,
                "ela_mean":         round(ela_mean, 5),
                "ela_std":          round(ela_std, 5),
                "ela_patch_cv":     round(patch_cv, 4),
            }

        except Exception as e:
            logger.debug(f"ELADetector failed: {e}")
            return {
                "fake_probability": 0.5,
                "real_probability": 0.5,
            }


# ── Singleton global ──────────────────────────────────────────────────────────
_ela_detector = ELADetector()


def predict_ela(image: Image.Image) -> dict:
    """Funcion publica para obtener el score ELA de una imagen."""
    return _ela_detector.predict(image)
