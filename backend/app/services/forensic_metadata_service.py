"""
Forensic Metadata Service — EXIF / XMP / IPTC
===============================================
Detecta firmas de software IA generativo, inconsistencias de fechas/lentes,
y metadatos inyectados por generadores. Produce una señal de riesgo adicional.

Señales de riesgo que modula el score forense global:
  +40% → Software de generación IA detectado (Midjourney, DALL-E, SD, FLUX...)
  +12% → Software de edición profesional (Photoshop, GIMP, Lightroom...)
  +08% → Ausencia total de EXIF (frecuente en imágenes sintéticas)
  +06% × n → Inconsistencias de metadatos (fechas, lentes imposibles...)
  Cap: 55% máximo para no dominar el score del ensemble de IA
"""
from __future__ import annotations
from pathlib import Path
from loguru import logger

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

try:
    import piexif
    _PIEXIF_OK = True
except ImportError:
    _PIEXIF_OK = False

try:
    import exifread
    _EXIFREAD_OK = True
except ImportError:
    _EXIFREAD_OK = False


# ─── Firmas de software ───────────────────────────────────────────────────────

AI_GENERATOR_SIGNATURES: dict[str, list[str]] = {
    "Midjourney":       ["midjourney", "mj ", "nijijourney"],
    "DALL-E":           ["dall-e", "dall·e", "openai", "dalle"],
    "Stable Diffusion": ["stable diffusion", "automatic1111", "comfyui", "a1111",
                         "sd-webui", "stability ai", "dreamstudio"],
    "FLUX":             ["flux.1", "black forest labs"],
    "Ideogram":         ["ideogram"],
    "Adobe Firefly":    ["firefly", "adobe generative"],
    "Runway":           ["runway", "gen-2", "gen-3"],
    "GPT Image":        ["gpt-image", "gpt image", "chatgpt image"],
    "Bing Image":       ["bing image creator", "designer.microsoft"],
}

EDITING_SOFTWARE_SIGNATURES: list[str] = [
    "adobe photoshop", "photoshop", "lightroom", "capture one",
    "affinity photo", "gimp", "darktable", "rawtherapee",
    "luminar", "on1 photo",
]


# ─── Extractor principal ──────────────────────────────────────────────────────

def extract_forensic_metadata(file_path: Path) -> dict:
    """
    Retorna dict con:
      ai_generator_detected, ai_generator_name,
      editing_software_detected, editing_software_name,
      missing_exif, inconsistencies, risk_signal, risk_reasons,
      raw_software_tag, xmp_ai_hints, has_gps, color_space
    """
    result: dict = {
        "exif_fields":               {},
        "ai_generator_detected":     False,
        "ai_generator_name":         None,
        "editing_software_detected": False,
        "editing_software_name":     None,
        "missing_exif":              False,
        "inconsistencies":           [],
        "risk_signal":               0.0,
        "risk_reasons":              [],
        "raw_software_tag":          None,
        "xmp_ai_hints":              [],
        "has_gps":                   False,
        "color_space":               None,
        "thumbnail_present":         False,
    }

    try:
        ext = file_path.suffix.lower()
        if ext in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
            _analyze_video(file_path, result)
        else:
            _analyze_image(file_path, result)
    except Exception as e:
        logger.debug(f"Forensic metadata error: {e}")
        result["inconsistencies"].append(f"Error leyendo metadatos: {type(e).__name__}")

    _compute_risk_signal(result)
    return result


def _analyze_image(file_path: Path, result: dict) -> None:
    if not _PIL_OK:
        return

    img = Image.open(file_path)
    result["color_space"] = img.mode

    # ── EXIF vía Pillow ────────────────────────────────────────────────────────
    raw_exif: dict = {}
    try:
        raw_exif = img._getexif() or {}
    except Exception:
        pass

    if not raw_exif:
        result["missing_exif"] = True
        result["inconsistencies"].append(
            "Ausencia de bloques EXIF estándar — comportamiento frecuente "
            "en imágenes generadas artificialmente o procesadas por software de edición."
        )
    else:
        exif_named = {TAGS.get(k, str(k)): v for k, v in raw_exif.items()}
        _parse_basic_exif(exif_named, result)

    # ── ExifRead (más completo, captura XMP embedded) ─────────────────────────
    if _EXIFREAD_OK:
        try:
            with open(file_path, "rb") as f:
                tags = exifread.process_file(f, details=False, strict=False)
            for tag_name, tag_val in tags.items():
                val_lower = str(tag_val).lower()
                _check_for_ai_signatures(tag_name, val_lower, str(tag_val), result)
        except Exception:
            pass

    # ── Piexif: lectura directa del archivo (más fiable que img.info.get("exif"))
    if _PIEXIF_OK and not result.get("ai_generator_detected"):
        for piexif_source in [str(file_path), img.info.get("exif")]:
            if piexif_source is None:
                continue
            try:
                ed     = piexif.load(piexif_source)
                zeroth = ed.get("0th", {})
                for fid in [piexif.ImageIFD.Software,
                             piexif.ImageIFD.Artist,
                             piexif.ImageIFD.Copyright,
                             piexif.ImageIFD.ImageDescription]:
                    val = zeroth.get(fid, b"")
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="replace").strip("\x00").strip()
                    if val:
                        result["raw_software_tag"] = val
                        _classify_software(val.lower(), result)
                        break
                if result.get("ai_generator_detected"):
                    break
            except Exception:
                continue


def _parse_basic_exif(exif: dict, result: dict) -> None:
    fields = result["exif_fields"]
    for field in ["Make", "Model", "DateTimeOriginal", "DateTime",
                  "FocalLength", "FNumber", "ISOSpeedRatings", "ColorSpace"]:
        if field in exif:
            try:
                fields[field] = str(exif[field])
            except Exception:
                pass

    software = str(exif.get("Software", "")).strip()
    if software:
        result["raw_software_tag"] = software
        _classify_software(software.lower(), result)

    if "GPSInfo" in exif:
        result["has_gps"] = True

    # Inconsistencia de fechas
    dt_orig = str(exif.get("DateTimeOriginal", ""))
    dt_mod  = str(exif.get("DateTime", ""))
    if dt_orig and dt_mod and dt_orig != dt_mod:
        result["inconsistencies"].append(
            f"Inconsistencia de fechas detectada: fecha original={dt_orig} "
            f"difiere de la fecha de modificación={dt_mod}. "
            "Posible edición posterior a la captura."
        )

    # Lente imposible
    focal = str(exif.get("FocalLength", ""))
    if focal in ("0", "0/0", "(0, 0)"):
        result["inconsistencies"].append(
            "Parámetro óptico imposible: longitud focal = 0 mm. "
            "Ninguna cámara física produce este valor; indica probable origen sintético."
        )


def _check_for_ai_signatures(tag_name: str, val_lower: str, val_raw: str, result: dict) -> None:
    for gen_name, sigs in AI_GENERATOR_SIGNATURES.items():
        if any(s in val_lower for s in sigs):
            if not result["ai_generator_detected"]:
                result["ai_generator_detected"] = True
                result["ai_generator_name"]     = gen_name
                result["xmp_ai_hints"].append(f"{tag_name}: '{val_raw[:80]}'")
            return
    # Guardar campos de texto relevantes como pistas
    if any(k in tag_name.lower() for k in ("comment", "description", "usercomment")):
        if len(val_raw) > 20:
            result["xmp_ai_hints"].append(f"{tag_name}: '{val_raw[:120]}'")


def _analyze_video(file_path: Path, result: dict) -> None:
    try:
        with open(file_path, "rb") as f:
            header_bytes = f.read(4096)
        header_text = header_bytes.decode("latin-1", errors="replace").lower()
        for gen_name, sigs in AI_GENERATOR_SIGNATURES.items():
            if any(s in header_text for s in sigs):
                result["ai_generator_detected"] = True
                result["ai_generator_name"]     = gen_name
                result["xmp_ai_hints"].append(f"Firma IA en container: {gen_name}")
                break
    except Exception as e:
        logger.debug(f"Video metadata read error: {e}")


def _classify_software(software_lower: str, result: dict) -> None:
    for gen_name, sigs in AI_GENERATOR_SIGNATURES.items():
        if any(s in software_lower for s in sigs):
            result["ai_generator_detected"] = True
            result["ai_generator_name"]     = gen_name
            return
    for editor_sig in EDITING_SOFTWARE_SIGNATURES:
        if editor_sig in software_lower:
            result["editing_software_detected"] = True
            result["editing_software_name"]     = editor_sig.title()
            return


def _compute_risk_signal(result: dict) -> None:
    boost   = 0.0
    reasons = []

    if result["ai_generator_detected"]:
        boost  += 0.40
        gen     = result["ai_generator_name"] or "desconocido"
        reasons.append(
            f"Generador IA detectado en metadatos: '{gen}' — señal de riesgo forense alta (+40%)."
        )
    if result["editing_software_detected"]:
        boost  += 0.12
        editor  = result["editing_software_name"] or "desconocido"
        reasons.append(
            f"Software de edición profesional detectado en metadatos: '{editor}' (+12%)."
        )
    if result["missing_exif"] and not result["ai_generator_detected"]:
        boost  += 0.08
        reasons.append(
            "Ausencia de bloques EXIF estándar en el archivo — señal indicativa de "
            "imagen sintética o procesada (+8%)."
        )

    n_incons = len(result["inconsistencies"])
    if n_incons >= 2:
        inc_boost = 0.06 * (n_incons - 1)
        boost    += inc_boost
        reasons.append(
            f"Se detectaron {n_incons} inconsistencias en los metadatos del archivo "
            f"(+{inc_boost*100:.0f}% señal de riesgo)."
        )

    result["risk_signal"]  = round(min(boost, 0.55), 4)
    result["risk_reasons"] = reasons


def apply_metadata_risk_to_score(
    base_score: float,
    forensic_meta: dict,
    max_boost_fraction: float = 0.50,
) -> tuple[float, str | None]:
    """
    Aplica la señal de riesgo de metadatos al score del ensemble.

    La señal de metadatos complementa el score de IA — no lo reemplaza.
    Usa una función de mezcla suave: el boost se aplica proporcionalmente
    al "espacio disponible" hasta el máximo (1.0), evitando saltos bruscos.

    Retorna (adjusted_score, correction_note | None).
    """
    risk_signal = forensic_meta.get("risk_signal", 0.0)
    if risk_signal <= 0.0:
        return base_score, None

    # Boost suave: llena el espacio disponible proporcionalmente
    available = 1.0 - base_score
    boost     = available * risk_signal * max_boost_fraction
    adjusted  = float(min(1.0, base_score + boost))

    if abs(adjusted - base_score) < 0.005:
        return base_score, None

    reasons   = forensic_meta.get("risk_reasons", [])
    note      = f"Señal forense de metadatos: {'; '.join(reasons[:2])}" if reasons else None

    return adjusted, note
