"""
OSINT module — External verification infrastructure.

DESIGN PRINCIPLES:
  - Never modifies the manipulation probability score
  - Never makes definitive claims about authenticity
  - Provides search links for manual investigation
  - Generates a perceptual hash for future deduplication

AUTOMATED SEARCH: Not implemented without API keys.
Future integration: SerpAPI, TinEye API, Bing Image Search API.
Current behavior: Generates manual search links + infrastructure.
"""
from pathlib import Path
from typing import Optional
import base64
from io import BytesIO

from PIL import Image
from loguru import logger

from app.api.schemas import OsintResult, OsintSearchLink

# Trusted news/media sources to check manually
TRUSTED_SOURCES = [
    ("Reuters", "https://www.reuters.com"),
    ("Associated Press", "https://www.apnews.com"),
    ("Getty Images", "https://www.gettyimages.com"),
    ("AFP", "https://www.afp.com"),
    ("BBC", "https://www.bbc.com"),
    ("Wikimedia Commons", "https://commons.wikimedia.org"),
]


def _compute_perceptual_hash(image_path: Path) -> Optional[str]:
    """Perceptual hash for deduplication — robust to minor edits."""
    try:
        import imagehash
        img = Image.open(image_path).convert("RGB")
        phash = str(imagehash.phash(img))
        dhash = str(imagehash.dhash(img))
        return f"phash:{phash} dhash:{dhash}"
    except ImportError:
        logger.debug("imagehash not installed — skipping perceptual hash")
        return None
    except Exception as e:
        logger.debug(f"Perceptual hash failed: {e}")
        return None


def _image_to_data_url(image_path: Path, max_size: int = 400) -> Optional[str]:
    """Generate a small data URL for embedding in search links."""
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((max_size, max_size))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=75)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


def build_osint_result(image_path: Path) -> OsintResult:
    """
    Build OSINT evidence structure.
    Provides search links and perceptual hash.
    Does NOT make claims about authenticity.
    """
    phash = _compute_perceptual_hash(image_path)

    # Reverse image search links (manual)
    links = [
        OsintSearchLink(
            engine="TinEye",
            url="https://tineye.com/",
            note="Upload image manually to search for prior appearances",
        ),
        OsintSearchLink(
            engine="Google Lens",
            url="https://lens.google.com/",
            note="Drag and drop image for visual search",
        ),
        OsintSearchLink(
            engine="Bing Visual Search",
            url="https://www.bing.com/visualsearch",
            note="Upload image for Bing visual search",
        ),
        OsintSearchLink(
            engine="Yandex Images",
            url="https://yandex.com/images/",
            note="Often finds images not in Google/Bing indexes",
        ),
    ]

    return OsintResult(
        status="manual_review_required",
        note=(
            "Automated external search was not performed. "
            "Manual reverse image search is recommended using the links below. "
            "Priority sources: Reuters, Associated Press, Getty Images, AFP, BBC, Wikimedia Commons."
        ),
        search_links=links,
        perceptual_hash=phash,
        disclaimer=(
            "Finding this image in a trusted source does NOT confirm authenticity — "
            "manipulated images can be republished. "
            "Not finding this image does NOT confirm manipulation — "
            "original content may not be indexed."
        ),
    )
