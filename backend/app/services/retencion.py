# -*- coding: utf-8 -*-
"""
Retencion de archivos: que se borra, cuando y quien lo garantiza.

Hasta el 25 nov 2026 el original se borraba desde un hilo `daemon` que dormia
una hora. Si el worker se cerraba antes -lo normal en un equipo de escritorio-
el hilo moria con el y el archivo se quedaba para siempre. Habia mas de cien.

Ahora:
  - el original se borra AL TERMINAR el analisis (borrar_original);
  - un barrido al arrancar y cada 30 minutos elimina lo que dejara un corte
    (purgar_vencidos) y los resultados en disco con mas de 24 horas.

Los sellos de custodia NO se borran: contienen la huella, el nombre del
archivo y el resultado, nunca la imagen, y son lo que acredita la integridad.
"""
import threading
import time
from pathlib import Path

from loguru import logger

from app.config import settings

RESULTADOS_TTL_S = 24 * 3600        # igual que result_expires en Redis
BARRIDO_CADA_S = 30 * 60

# Solo se tocan archivos con estas extensiones: un .gitkeep o cualquier otra
# cosa que alguien deje en la carpeta no se borra.
_EXT_ORIGINALES = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".heic", ".avif",
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".mpeg", ".mpg",
}


def borrar_original(path: Path) -> bool:
    """Borra el archivo analizado. Nunca lanza: no puede tumbar un analisis."""
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError as e:
        # En Windows otro proceso puede tenerlo abierto: lo recoge el barrido.
        logger.warning(f"No se pudo borrar {path.name} ahora ({type(e).__name__}); "
                       "lo eliminara el barrido")
        return False


def purgar_vencidos(carpeta: Path, edad_max_s: float, extensiones: set[str],
                    ahora: float | None = None) -> int:
    """Elimina de `carpeta` (sin recursion) lo que supere la edad maxima."""
    ahora = time.time() if ahora is None else ahora
    n = 0
    if not carpeta.is_dir():
        return 0
    for p in carpeta.iterdir():
        try:
            if (p.is_file() and p.suffix.lower() in extensiones
                    and ahora - p.stat().st_mtime > edad_max_s):
                p.unlink()
                n += 1
        except OSError:
            continue
    return n


def barrer() -> tuple[int, int]:
    originales = purgar_vencidos(settings.UPLOAD_DIR, settings.FILE_CLEANUP_DELAY, _EXT_ORIGINALES)
    resultados = purgar_vencidos(settings.RESULTS_DIR, RESULTADOS_TTL_S, {".json"})
    if originales or resultados:
        logger.info(f"Retencion: {originales} originales y {resultados} resultados vencidos eliminados")
    return originales, resultados


def iniciar_barrido() -> None:
    """Barre ya y despues periodicamente mientras viva el proceso."""
    def _bucle():
        while True:
            try:
                barrer()
            except Exception as e:
                logger.warning(f"Retencion: el barrido fallo ({type(e).__name__})")
            time.sleep(BARRIDO_CADA_S)

    threading.Thread(target=_bucle, daemon=True, name="ds-retencion").start()
