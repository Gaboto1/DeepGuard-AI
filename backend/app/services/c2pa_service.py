"""
C2PA Provenance Service
=======================
Lee manifiestos C2PA (Coalition for Content Provenance and Authenticity)
incrustados en imágenes y videos.

C2PA es el estándar criptográfico de la industria para procedencia de contenido:
  - Fabricantes de cámaras: Sony, Canon, Nikon, Leica (CAI — Content Authenticity Initiative)
  - Agencias de prensa:     Reuters, AP, Getty (firman con SIGMA/C2PA)
  - Generadores IA:         Adobe Firefly, DALL·E 3, Stability AI (embed C2PA)
  - Redes sociales:         LinkedIn, TikTok, Meta (en proceso de adopción)

Un manifiesto C2PA válido demuestra:
  1. El archivo no fue modificado desde que fue firmado
  2. El firmante (issuer) es una autoridad conocida y de confianza
  3. La cadena de edición (ingredientes) está vinculada criptográficamente

Señal forense para DeepGuard:
  verified=True  + emisor reconocido → señal fuerte de autenticidad
  has_c2pa=True  pero verified=False → ALTERADO → señal de alta manipulación
  has_c2pa=False → sin señal (la mayoría de archivos no tienen C2PA)

VRAM: 0 bytes — Rust + numpy, sin redes neuronales
Latencia: ~5-50 ms según complejidad del manifiesto
"""
from __future__ import annotations

import json
from typing import Optional

from loguru import logger


# ── Autoridades firmantes C2PA conocidas ─────────────────────────────────────
_TRUSTED_ISSUERS = frozenset({
    "adobe", "sigma", "leica", "nikon", "canon", "sony", "panasonic",
    "contentauthenticity", "content credentials", "truepic", "attestiv",
    "openai", "stability", "stability ai", "midjourney",
    "reuters", "ap ", "associated press", "getty", "shutterstock",
    "news agency", "axel springer",
})


def _is_trusted_issuer(issuer: Optional[str]) -> bool:
    if not issuer:
        return False
    lower = issuer.lower()
    return any(t in lower for t in _TRUSTED_ISSUERS)


def _mime_from_filename(filename: str) -> str:
    """Infiere el tipo MIME desde la extensión del archivo."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return {
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "png":  "image/png",
        "webp": "image/webp",
        "gif":  "image/gif",
        "tiff": "image/tiff",
        "tif":  "image/tiff",
        "avif": "image/avif",
        "heic": "image/heic",
        "mp4":  "video/mp4",
        "mov":  "video/quicktime",
        "mkv":  "video/x-matroska",
        "webm": "video/webm",
        "avi":  "video/avi",
    }.get(ext, "image/jpeg")


def _extract_cn(dn: str) -> str:
    """Extrae el CN (Common Name) de un Distinguished Name X.509."""
    for part in dn.split(","):
        part = part.strip()
        if part.upper().startswith("CN="):
            return part[3:].strip()
    return dn


def _parse_actions(assertions: list) -> list[dict]:
    """Extrae la lista de acciones del assertion c2pa.actions."""
    actions: list[dict] = []
    for assertion in assertions:
        if assertion.get("label") == "c2pa.actions":
            for act in assertion.get("data", {}).get("actions", []):
                actions.append({
                    "action":         act.get("action", ""),
                    "when":           act.get("when"),
                    "software_agent": act.get("softwareAgent", ""),
                })
    return actions


def read_c2pa_provenance(file_bytes: bytes, filename: str = "") -> dict:
    """
    Lee metadatos de procedencia C2PA desde los bytes crudos del archivo.

    Retorna siempre un dict con la estructura completa — nunca lanza excepciones:

      has_c2pa        bool  — el archivo porta un manifiesto C2PA
      active          bool  — existe un manifiesto activo no expirado
      verified        bool  — la firma criptográfica es válida
      signed_by       str?  — CN del certificado firmante (ej. "Adobe Content Credentials")
      claim_generator str?  — software que generó el manifiesto (ej. "Adobe Firefly")
      issued_at       str?  — timestamp ISO 8601 de la firma
      history_log     list  — cadena cronológica de edición (ingredientes C2PA)
      error           str?  — descripción del error si la lectura falló
    """
    result: dict = {
        "has_c2pa":        False,
        "active":          False,
        "verified":        False,
        "signed_by":       None,
        "claim_generator": None,
        "issued_at":       None,
        "history_log":     [],
        "error":           None,
    }

    if not file_bytes:
        return result

    # ── Import lazy — la librería es opcional (no disponible en Python 3.13) ──
    try:
        import c2pa  # type: ignore[import]
    except ImportError:
        logger.debug("C2PA: c2pa-python no instalado — omitiendo análisis de procedencia")
        return result

    mime = _mime_from_filename(filename)

    # ── Lectura del manifiesto ────────────────────────────────────────────────
    try:
        reader   = c2pa.Reader(mime, file_bytes)
        raw_json = reader.json()
    except Exception as exc:
        msg = str(exc)
        # Ausencia de JUMBF es el caso normal para archivos sin C2PA
        no_manifest_signals = ("no manifest", "not found", "missing", "jumbf",
                               "no active manifest", "unsupported", "invalid")
        if any(kw in msg.lower() for kw in no_manifest_signals):
            logger.debug(f"C2PA: sin manifiesto en '{filename}' — normal")
        else:
            result["error"] = msg
            logger.debug(f"C2PA read error ({filename!r}): {msg}")
        return result

    # ── Parse del JSON del store ──────────────────────────────────────────────
    try:
        store = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        result["error"] = f"JSON parse: {exc}"
        return result

    active_id = store.get("active_manifest")
    if not active_id:
        logger.debug(f"C2PA: store presente pero sin manifiesto activo en '{filename}'")
        return result

    result["has_c2pa"] = True
    result["active"]   = True

    manifests       = store.get("manifests", {})
    active_manifest = manifests.get(active_id, {})

    # ── Validación criptográfica ──────────────────────────────────────────────
    # validation_status vacío = sin errores = firma válida
    # Ignoramos los códigos que terminan en ".validated" (son informativos)
    val_status = store.get("validation_status", [])
    hard_errors = [
        s for s in val_status
        if not str(s.get("code", "")).endswith(".validated")
    ]
    result["verified"] = len(hard_errors) == 0

    # ── Información del firmante ──────────────────────────────────────────────
    sig_info                = active_manifest.get("signature_info", {})
    raw_issuer              = sig_info.get("issuer", "")
    result["signed_by"]     = _extract_cn(raw_issuer) if raw_issuer else None
    result["issued_at"]     = sig_info.get("time")
    result["claim_generator"] = (
        active_manifest.get("claim_generator", "").split("/")[0].strip() or None
    )

    # ── Historial de procedencia (cadena de ingredientes) ────────────────────
    history: list[dict] = []

    # Procesar ingredientes del manifiesto activo
    for ingredient in active_manifest.get("ingredients", []):
        ing_active_id = ingredient.get("active_manifest")
        rel           = ingredient.get("relationship", "")
        ing_title     = ingredient.get("title", "")
        ing_format    = ingredient.get("format", "")

        if ing_active_id and ing_active_id in manifests:
            ing_mani    = manifests[ing_active_id]
            ing_sig     = ing_mani.get("signature_info", {})
            ing_actions = _parse_actions(ing_mani.get("assertions", []))
            history.append({
                "title":        ing_title or ing_mani.get("title", ""),
                "format":       ing_format or ing_mani.get("format", ""),
                "relationship": rel,
                "date":         ing_sig.get("time"),
                "tool":         (
                    ing_mani.get("claim_generator", "").split("/")[0].strip() or None
                ),
                "actions":      ing_actions,
            })
        elif ing_title or ing_format:
            # Ingrediente sin manifiesto anidado (referencia externa)
            history.append({
                "title":        ing_title,
                "format":       ing_format,
                "relationship": rel,
                "date":         None,
                "tool":         None,
                "actions":      [],
            })

    # La versión activa (más reciente) siempre va al final
    active_actions = _parse_actions(active_manifest.get("assertions", []))
    if active_actions or result["claim_generator"] or result["issued_at"]:
        history.append({
            "title":        active_manifest.get("title", filename or "Versión actual"),
            "format":       active_manifest.get("format", ""),
            "relationship": "active",
            "date":         result["issued_at"],
            "tool":         result["claim_generator"],
            "actions":      active_actions,
        })

    result["history_log"] = history

    logger.info(
        f"C2PA: manifiesto encontrado en '{filename}' — "
        f"verified={result['verified']}, "
        f"signed_by={result['signed_by']!r}, "
        f"history={len(history)} etapas"
    )
    return result
