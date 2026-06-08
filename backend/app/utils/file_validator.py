"""
Validación de archivos — mensajes de error 100% en español técnico.
"""
from pathlib import Path
from fastapi import HTTPException
from loguru import logger

from app.config import settings


ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".mpeg", ".mpg"}

ALLOWED_IMAGE_MIMES = {
    "image/jpeg", "image/png", "image/webp", "image/bmp",
}
ALLOWED_VIDEO_MIMES = {
    "video/mp4", "video/quicktime", "video/x-matroska",
    "video/webm", "video/x-msvideo", "video/mpeg",
}

# Límite adicional para el endpoint asíncrono v1 (videos grandes)
MAX_VIDEO_SIZE_ASYNC_MB = 500

try:
    import magic as _magic
    _MAGIC_AVAILABLE = True
except Exception:
    _MAGIC_AVAILABLE = False
    logger.warning(
        "python-magic no disponible. La validación de archivos usará solo la extensión. "
        "En Windows ejecute: pip install python-magic-bin"
    )


def get_file_type(filename: str) -> str:
    """
    Retorna 'image' o 'video'.
    Lanza HTTP 415 si la extensión no está soportada.
    """
    ext = Path(filename).suffix.lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return "video"

    exts_img = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
    exts_vid = ", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))
    raise HTTPException(
        status_code=415,
        detail={
            "error":   "formato_no_soportado",
            "mensaje": (
                f"El tipo de archivo '{ext}' no está soportado. "
                f"Imágenes admitidas: {exts_img}. "
                f"Videos admitidos: {exts_vid}."
            ),
            "extension_recibida":    ext,
            "extensiones_imagen":    sorted(ALLOWED_IMAGE_EXTENSIONS),
            "extensiones_video":     sorted(ALLOWED_VIDEO_EXTENSIONS),
        },
    )


def validate_file_size(file_size: int) -> None:
    """
    Valida que el archivo no supere el límite máximo global.
    """
    max_bytes = settings.max_file_size_bytes
    if file_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "error":   "archivo_demasiado_grande",
                "mensaje": (
                    f"El archivo supera el tamaño máximo permitido de "
                    f"{settings.MAX_FILE_SIZE_MB} MB. "
                    f"Tamaño recibido: {file_size / 1_048_576:.1f} MB."
                ),
                "limite_mb":   settings.MAX_FILE_SIZE_MB,
                "recibido_mb": round(file_size / 1_048_576, 1),
            },
        )


def validate_video_size_async(file_size: int) -> None:
    """
    Validación adicional para el endpoint asíncrono v1.
    Los videos grandes pueden procesarse pero requieren workers dedicados.
    """
    max_bytes = MAX_VIDEO_SIZE_ASYNC_MB * 1_048_576
    if file_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "error":   "video_excede_limite_asincrono",
                "mensaje": (
                    f"El archivo de video excede el límite máximo permitido de "
                    f"{MAX_VIDEO_SIZE_ASYNC_MB} MB para procesamiento asíncrono. "
                    f"Tamaño recibido: {file_size / 1_048_576:.1f} MB. "
                    "Considere comprimir el video antes de subirlo."
                ),
                "limite_mb":   MAX_VIDEO_SIZE_ASYNC_MB,
                "recibido_mb": round(file_size / 1_048_576, 1),
            },
        )


def validate_not_empty(file_size: int, filename: str) -> None:
    """Rechaza archivos vacíos o de 0 bytes."""
    if file_size == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "error":   "archivo_vacio",
                "mensaje": (
                    f"El archivo '{filename}' está vacío (0 bytes). "
                    "Asegúrese de subir un archivo válido con contenido."
                ),
            },
        )


def validate_mime_type(file_path: Path, expected_type: str) -> None:
    """
    Validación profunda mediante magic bytes.
    Detecta archivos renombrados (ej. un ejecutable .py con extensión .jpg).
    Usa python-magic si está disponible; si no, aplica validación de magic bytes
    manual para los formatos más comunes (no requiere dependencias extra).
    """
    mime: str | None = None

    if _MAGIC_AVAILABLE:
        try:
            mime = _magic.from_file(str(file_path), mime=True)
        except Exception as e:
            logger.warning(f"python-magic falló, usando fallback de magic bytes: {e}")

    # Fallback sin python-magic: verificar magic bytes manuales
    if mime is None:
        try:
            with open(file_path, "rb") as fh:
                header = fh.read(12)
            # JPEG: FF D8 FF
            if header[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            # PNG: 89 50 4E 47
            elif header[:4] == b"\x89PNG":
                mime = "image/png"
            # WEBP: RIFF????WEBP
            elif header[:4] == b"RIFF" and header[8:12] == b"WEBP":
                mime = "image/webp"
            # BMP: 42 4D ("BM")
            elif header[:2] == b"BM":
                mime = "image/bmp"
            # MP4/MOV: ftyp box en posición 4
            elif header[4:8] in (b"ftyp", b"moov", b"mdat"):
                mime = "video/mp4"
            # MKV y WEBM comparten el mismo header EBML (1A 45 DF A3).
            # Los diferenciamos leyendo el DocType del segmento EBML:
            # "webm" → video/webm, "matroska" o ausente → video/x-matroska
            elif header[:4] == b"\x1a\x45\xdf\xa3":
                try:
                    with open(file_path, "rb") as fh2:
                        ebml_header = fh2.read(64)
                    mime = "video/webm" if b"webm" in ebml_header else "video/x-matroska"
                except Exception:
                    mime = "video/x-matroska"
        except Exception as e:
            logger.warning(f"Validación MIME manual omitida: {e}")

    if mime is None:
        logger.debug(f"MIME no determinado para {file_path.name} — omitiendo validación")
        return

    logger.debug(f"MIME detectado: {mime} para {file_path.name}")

    if expected_type == "image" and mime not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(
            status_code=415,
            detail={
                "error":   "contenido_no_coincide",
                "mensaje": (
                    f"El contenido del archivo es '{mime}', "
                    "pero se esperaba una imagen válida. "
                    "El archivo podría estar corrupto o su extensión ser incorrecta."
                ),
                "mime_detectado": mime,
                "tipo_esperado":  "imagen",
            },
        )
    if expected_type == "video" and mime not in ALLOWED_VIDEO_MIMES:
        raise HTTPException(
            status_code=415,
            detail={
                "error":   "contenido_no_coincide",
                "mensaje": (
                    f"El contenido del archivo es '{mime}', "
                    "pero se esperaba un video válido. "
                    "El archivo podría estar corrupto o su extensión ser incorrecta."
                ),
                "mime_detectado": mime,
                "tipo_esperado":  "video",
            },
        )
