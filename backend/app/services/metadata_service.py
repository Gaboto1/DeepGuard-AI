"""
Metadata extraction service — EXIF and forensic hints.
Never modifies the manipulation probability score.
Purely informational evidence.
"""
from pathlib import Path
from typing import Optional

from PIL import Image
from loguru import logger

from app.api.schemas import MetadataAnalysis


def _rational_to_float(rational) -> Optional[float]:
    try:
        if hasattr(rational, 'numerator'):
            return rational.numerator / rational.denominator if rational.denominator else None
        if isinstance(rational, tuple) and len(rational) == 2:
            return rational[0] / rational[1] if rational[1] else None
        return float(rational)
    except Exception:
        return None


def _gps_to_decimal(gps_data: tuple, ref: str) -> Optional[float]:
    try:
        degrees = _rational_to_float(gps_data[0]) or 0
        minutes = _rational_to_float(gps_data[1]) or 0
        seconds = _rational_to_float(gps_data[2]) or 0
        decimal = degrees + minutes / 60 + seconds / 3600
        if ref in ('S', 'W'):
            decimal = -decimal
        return round(decimal, 6)
    except Exception:
        return None


def extract_metadata(image_path: Path) -> MetadataAnalysis:
    """
    Extract EXIF metadata and generate forensic notes.
    Does NOT modify analysis scores.
    """
    forensic_notes = []

    try:
        img = Image.open(image_path)
        w, h = img.size

        exif_data = {}
        try:
            raw_exif = img._getexif()
            if raw_exif:
                from PIL.ExifTags import TAGS, GPSTAGS
                for tag_id, value in raw_exif.items():
                    tag = TAGS.get(tag_id, str(tag_id))
                    exif_data[tag] = value
        except Exception:
            raw_exif = None

        has_exif = bool(exif_data)

        if not has_exif:
            forensic_notes.append(
                "No EXIF metadata found. This is common in screenshots, "
                "re-saved images, social media uploads, and some AI-generated content."
            )

        # Camera
        make  = str(exif_data.get("Make", "")).strip() or None
        model = str(exif_data.get("Model", "")).strip() or None

        if make and model:
            forensic_notes.append(f"Camera metadata present: {make} {model}.")
        elif has_exif and not make and not model:
            forensic_notes.append(
                "EXIF present but no camera make/model — possible software generation or metadata stripping."
            )

        # Software
        software = str(exif_data.get("Software", "")).strip() or None
        if software:
            sw_lower = software.lower()
            if any(s in sw_lower for s in ["photoshop", "lightroom", "gimp", "capture", "affinity"]):
                forensic_notes.append(f"Post-processing software detected: {software}.")
            elif any(s in sw_lower for s in ["stable diffusion", "midjourney", "dall-e", "ai", "generative"]):
                forensic_notes.append(f"AI generation software referenced in metadata: {software}.")
            else:
                forensic_notes.append(f"Software tag: {software}.")

        # DateTime
        dt_orig = str(exif_data.get("DateTimeOriginal", "")).strip() or None
        if not dt_orig:
            dt_orig = str(exif_data.get("DateTime", "")).strip() or None

        # GPS
        lat = lon = None
        gps_info = exif_data.get("GPSInfo")
        if gps_info and isinstance(gps_info, dict):
            try:
                from PIL.ExifTags import GPSTAGS
                gps = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
                if "GPSLatitude" in gps and "GPSLatitudeRef" in gps:
                    lat = _gps_to_decimal(gps["GPSLatitude"], gps["GPSLatitudeRef"])
                if "GPSLongitude" in gps and "GPSLongitudeRef" in gps:
                    lon = _gps_to_decimal(gps["GPSLongitude"], gps["GPSLongitudeRef"])
                if lat is not None and lon is not None:
                    forensic_notes.append(f"GPS coordinates embedded: {lat:.4f}, {lon:.4f}.")
            except Exception:
                pass

        # Color space
        color_space_map = {1: "sRGB", 65535: "Uncalibrated"}
        cs_raw = exif_data.get("ColorSpace")
        color_space = color_space_map.get(cs_raw) if cs_raw else str(img.mode)

        # Compression
        fmt = img.format or "Unknown"
        comp = f"{fmt}"
        if "JpegIF" in str(exif_data.get("Compression", "")):
            comp += " (JPEG)"

        # Camera settings
        iso_val = exif_data.get("ISOSpeedRatings") or exif_data.get("ISO")
        try:
            iso = int(iso_val) if iso_val else None
        except Exception:
            iso = None

        focal_raw = exif_data.get("FocalLength")
        focal = f"{_rational_to_float(focal_raw):.1f}mm" if focal_raw else None

        exp_raw = exif_data.get("ExposureTime")
        exp_f   = _rational_to_float(exp_raw)
        exp     = f"1/{int(1/exp_f)}s" if exp_f and exp_f < 1 else (f"{exp_f}s" if exp_f else None)

        fn_raw = exif_data.get("FNumber")
        fn_f   = _rational_to_float(fn_raw)
        f_num  = f"f/{fn_f:.1f}" if fn_f else None

        flash_raw = exif_data.get("Flash")
        flash     = str(flash_raw) if flash_raw is not None else None

        return MetadataAnalysis(
            has_exif=has_exif,
            camera_make=make,
            camera_model=model,
            software=software,
            datetime_original=dt_orig,
            gps_latitude=lat,
            gps_longitude=lon,
            color_space=color_space,
            image_width=w,
            image_height=h,
            compression=comp,
            iso=iso,
            focal_length=focal,
            exposure_time=exp,
            f_number=f_num,
            flash=flash,
            forensic_notes=forensic_notes,
        )

    except Exception as e:
        logger.debug(f"Metadata extraction failed: {e}")
        return MetadataAnalysis(
            has_exif=False,
            image_width=None,
            image_height=None,
            forensic_notes=["Metadata extraction failed or file format not supported."],
        )
