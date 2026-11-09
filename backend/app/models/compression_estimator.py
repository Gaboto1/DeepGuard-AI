"""
Estimador del nivel de compresión de una imagen
================================================

Por qué existe
--------------
Se detectó que recomprimir una fotografía auténtica elevaba su puntuación:
una foto de COCO pasaba de 0,33 a 0,50 con sólo guardarla en JPEG de calidad 55.
La causa no está en el meta-modelo sino en los detectores base, que reaccionan a
los artefactos de compresión. El detector de SDXL, por ejemplo, pasaba de 0 % a
40 % sobre la misma escena sólo por recomprimirla.

Reentrenar añadiendo fotografía recomprimida no bastó: el meta-modelo sólo ve
las salidas de los detectores, y si todas se desplazan con la compresión, no
tiene forma de saber que el desplazamiento se debe a eso y no a síntesis.

Este módulo aporta la variable que faltaba. Al conocer cuánto está comprimida la
imagen, el meta-modelo puede aprender la interacción: "con estos niveles de
compresión, estas puntuaciones siguen siendo compatibles con una foto auténtica".

Las tres señales se calculan en CPU en pocos milisegundos y no dependen de que
el archivo sea JPEG.
"""
from typing import Optional

import numpy as np
from PIL import Image
from loguru import logger


def _blockiness(gray: np.ndarray) -> float:
    """
    Intensidad de los bordes de bloque 8x8 propios de JPEG.

    Compara el salto medio de intensidad al cruzar una frontera de bloque con el
    salto medio en el interior. Una imagen sin comprimir no distingue ambas
    posiciones (razón ~1); una muy comprimida acentúa las fronteras (razón > 1).
    """
    h, w = gray.shape
    if h < 24 or w < 24:
        return 0.0

    col = np.abs(np.diff(gray.astype(np.float32), axis=1))
    idx = np.arange(col.shape[1])
    frontera_v = col[:, idx % 8 == 7]
    interior_v = col[:, idx % 8 != 7]

    fil = np.abs(np.diff(gray.astype(np.float32), axis=0))
    idy = np.arange(fil.shape[0])
    frontera_h = fil[idy % 8 == 7, :]
    interior_h = fil[idy % 8 != 7, :]

    f = float(np.mean(frontera_v) + np.mean(frontera_h))
    i = float(np.mean(interior_v) + np.mean(interior_h))
    if i < 1e-6:
        return 0.0
    razon = f / i
    # razón 1.0 -> sin bloques; 2.0 o más -> compresión agresiva
    return float(np.clip((razon - 1.0), 0.0, 1.5) / 1.5)


def _calidad_jpeg(image: Image.Image) -> Optional[float]:
    """
    Calidad aproximada a partir de las tablas de cuantización, si las hay.

    Devuelve un valor en [0,1] donde 1 es calidad máxima. None si la imagen no
    trae tablas (PNG, WEBP o JPEG ya decodificado sin metadatos).
    """
    tablas = getattr(image, "quantization", None)
    if not tablas:
        return None
    try:
        valores = np.concatenate([np.asarray(t, dtype=np.float64).ravel()
                                  for t in tablas.values()])
    except Exception:
        return None
    if valores.size == 0:
        return None
    # Cuantizadores pequeños = poca pérdida. El rango útil va de 1 a ~60.
    medio = float(np.mean(valores))
    return float(np.clip(1.0 - (medio - 1.0) / 60.0, 0.0, 1.0))


def _detalle_alta_frecuencia(gray: np.ndarray) -> float:
    """
    Proporción de energía en altas frecuencias. La compresión la destruye, así
    que un valor bajo indica una imagen muy procesada con independencia del
    formato en que llegue.
    """
    g = gray.astype(np.float32)
    if min(g.shape) < 16:
        return 0.5
    lap = (
        -4 * g[1:-1, 1:-1]
        + g[:-2, 1:-1] + g[2:, 1:-1]
        + g[1:-1, :-2] + g[1:-1, 2:]
    )
    energia = float(np.mean(np.abs(lap)))
    # 0 -> plano; 12 o más -> muy detallado
    return float(np.clip(energia / 12.0, 0.0, 1.0))


def estimate_compression(image: Image.Image) -> dict:
    """
    Devuelve el nivel de compresión estimado.

    {"compression_level": float 0-1,   0 = sin comprimir, 1 = muy comprimida
     "blockiness": float,
     "jpeg_quality": float | None,
     "hf_detail": float}
    """
    try:
        gris = np.asarray(image.convert("L"))
        blk = _blockiness(gris)
        hf = _detalle_alta_frecuencia(gris)
        q = _calidad_jpeg(image)

        # La bloquosidad es la señal directa; la falta de detalle la respalda.
        nivel = 0.65 * blk + 0.35 * (1.0 - hf)
        if q is not None:
            # Si hay tablas de cuantización, pesan: son evidencia de primera mano.
            nivel = 0.55 * nivel + 0.45 * (1.0 - q)

        return {
            "compression_level": float(np.clip(nivel, 0.0, 1.0)),
            "blockiness": round(blk, 4),
            "jpeg_quality": round(q, 4) if q is not None else None,
            "hf_detail": round(hf, 4),
        }
    except Exception as e:
        logger.debug(f"[compresion] estimacion fallida: {e}")
        return {"compression_level": 0.5, "blockiness": None,
                "jpeg_quality": None, "hf_detail": None}


def compression_level(image: Image.Image) -> float:
    return estimate_compression(image)["compression_level"]
