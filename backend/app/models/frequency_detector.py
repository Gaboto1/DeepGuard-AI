"""
Detector de Artefactos de Frecuencia para Imágenes IA
======================================================
Fundamento científico (Wang et al. 2020, Dzanic et al. 2019):

  Las imágenes naturales siguen una ley de potencia en el espectro:
      S(f) ∝ f^(-α)   con α ≈ 2.0  (caída pronunciada)

  Las imágenes generadas por IA tienen distribuciones anómalas:
    - GANs:       α < 1.8  (más energía en altas frecuencias por upsampling)
    - Difusión:   picos en frecuencias específicas + ratio HF anómalo
    - Face-swap:  inconsistencias espectrales en bordes faciales

  Esta señal es ORTOGONAL al espacio de píxeles → complementa el ensemble
  existente (ViT, SDXL, CLIP, AiArt, SigLIP) capturando artefactos
  invisibles en RGB.

Sin PyTorch ni modelos — solo numpy/scipy.
Latencia: ~10ms/imagen en CPU.
VRAM: 0 bytes.
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from loguru import logger


class FrequencyArtifactDetector:
    """
    Detector singleton de artefactos de frecuencia.
    Combina tres señales complementarias:
      1. Exponent espectral (pendiente log-log del espectro radial)
      2. Ratio de energía en altas frecuencias
      3. Asimetría del espectro 2D (anisotropía artificial)
    """

    _instance: "FrequencyArtifactDetector | None" = None

    # Calibración ajustada para imágenes comprimidas (JPEG/WEBP/PNG):
    # La compresión JPEG reduce el α real de ~2.0 a ~1.4-1.6.
    # Imágenes reales comprimidas:  α_mean=1.50, HF_ratio_mean=0.52
    # Imágenes IA comprimidas:      α_mean=1.20, HF_ratio_mean=0.62
    # Pendiente de recalibración con golden set propio cuando haya más datos.
    _ALPHA_REAL   = 1.55    # alpha real ajustado para compresión
    _ALPHA_AI     = 1.15    # alpha IA ajustado
    _HF_RATIO_REAL = 0.52   # HF ratio ajustado
    _HF_RATIO_AI   = 0.65   # HF ratio IA ajustado

    # Pesos conservadores — señal auxiliar, no dominante
    _W_ALPHA  = 0.50
    _W_HF     = 0.35
    _W_ANISO  = 0.15

    @classmethod
    def get_instance(cls) -> "FrequencyArtifactDetector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Señal 1: Exponent espectral (caída del espectro radial) ───────────────

    def _spectral_exponent(self, magnitude: np.ndarray) -> float:
        """
        Calcula el exponent α de la ley de potencia S(f) ∝ f^(-α).
        Valor bajo α → más plano → más probable imagen IA.
        """
        h, w    = magnitude.shape
        cy, cx  = h // 2, w // 2
        max_r   = min(cy, cx)

        # Promedio azimutal (radial)
        y, x    = np.mgrid[0:h, 0:w]
        r       = np.sqrt((x - cx)**2 + (y - cy)**2).astype(int)
        r_flat  = r.ravel()
        m_flat  = magnitude.ravel()

        radial_sum   = np.bincount(r_flat, weights=m_flat, minlength=max_r + 1)
        radial_count = np.bincount(r_flat, minlength=max_r + 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            radial_mean = np.where(radial_count > 0, radial_sum / radial_count, 0)

        # Usar frecuencias medias (evitar DC y Nyquist)
        lo = max(2, max_r // 8)
        hi = max_r * 3 // 4
        freqs = np.arange(lo, hi)
        power = radial_mean[lo:hi]
        valid = power > 0

        if valid.sum() < 10:
            return self._ALPHA_REAL  # fallback neutral

        lf  = np.log(freqs[valid].astype(float) + 1)
        lp  = np.log(power[valid] + 1e-12)
        try:
            slope = float(np.polyfit(lf, lp, 1)[0])
        except Exception:
            return self._ALPHA_REAL

        return max(0.0, -slope)   # α positivo

    # ── Señal 2: Ratio de energía en altas frecuencias ────────────────────────

    def _hf_ratio(self, magnitude: np.ndarray) -> float:
        """
        Proporción de energía en el 30% superior de frecuencias.
        Imágenes IA tienen más energía HF por artefactos de upsampling.
        """
        h, w    = magnitude.shape
        cy, cx  = h // 2, w // 2
        max_r   = min(cy, cx)
        y, x    = np.mgrid[0:h, 0:w]
        dist    = np.sqrt((x - cx)**2 + (y - cy)**2)

        total  = magnitude.sum()
        if total < 1e-8:
            return self._HF_RATIO_REAL

        hf_thresh  = max_r * 0.70
        hf_energy  = magnitude[dist > hf_thresh].sum()
        return float(hf_energy / total)

    # ── Señal 3: Anisotropía espectral ────────────────────────────────────────

    def _spectral_anisotropy(self, magnitude: np.ndarray) -> float:
        """
        Detecta asimetría artificial en el espectro 2D.
        Los artefactos de upsampling crean picos en direcciones específicas.
        Score alto → espectro más anisótropo → más probable IA.
        """
        h, w  = magnitude.shape
        cy, cx = h // 2, w // 2

        # Cuadrantes
        q1 = magnitude[:cy, :cx]
        q2 = magnitude[:cy, cx:]
        q3 = magnitude[cy:, :cx]
        q4 = magnitude[cy:, cx:]

        means = np.array([q.mean() for q in [q1, q2, q3, q4]])
        if means.mean() < 1e-8:
            return 0.0
        # Coeficiente de variación entre cuadrantes
        cv = float(means.std() / (means.mean() + 1e-8))
        return float(np.clip(cv / 0.5, 0.0, 1.0))

    # ── API pública ───────────────────────────────────────────────────────────

    def predict(self, image: Image.Image) -> dict:
        """
        Retorna un dict con fake_probability y señales individuales.
        """
        try:
            # Usar canal de luminancia (más informativo que RGB promediado)
            gray = np.array(image.convert("L")).astype(np.float32)

            # FFT 2D + centrado + magnitud
            fft       = np.fft.fft2(gray)
            fft_shift = np.fft.fftshift(fft)
            magnitude = np.abs(fft_shift)

            # Las 3 señales
            alpha      = self._spectral_exponent(magnitude)
            hf_r       = self._hf_ratio(magnitude)
            aniso      = self._spectral_anisotropy(magnitude)

            # Normalizar cada señal a [0, 1] donde 1 = más probable IA
            #   alpha: real=2.05, IA=1.62 → score sube cuando alpha baja
            alpha_score = float(np.clip(
                (self._ALPHA_REAL - alpha) / (self._ALPHA_REAL - self._ALPHA_AI),
                0.0, 1.0
            ))
            #   hf_ratio: real=0.31, IA=0.41 → score sube cuando ratio sube
            hf_score = float(np.clip(
                (hf_r - self._HF_RATIO_REAL) / (self._HF_RATIO_AI - self._HF_RATIO_REAL),
                0.0, 1.0
            ))
            aniso_score = float(np.clip(aniso, 0.0, 1.0))

            fake_prob = (
                self._W_ALPHA * alpha_score
                + self._W_HF   * hf_score
                + self._W_ANISO * aniso_score
            )
            fake_prob = float(np.clip(fake_prob, 0.0, 1.0))

            return {
                "fake_probability":  fake_prob,
                "real_probability":  1.0 - fake_prob,
                "spectral_alpha":    round(alpha, 4),
                "hf_ratio":          round(hf_r, 4),
                "aniso_score":       round(aniso_score, 4),
            }

        except Exception as e:
            logger.debug(f"FrequencyDetector failed: {e}")
            return {
                "fake_probability": 0.5,
                "real_probability": 0.5,
            }


# ── Singleton global ──────────────────────────────────────────────────────────
_frequency_detector = FrequencyArtifactDetector()


def predict_frequency(image: Image.Image) -> dict:
    """Función pública para obtener el score de frecuencia."""
    return _frequency_detector.predict(image)
