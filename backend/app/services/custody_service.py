"""
Forensic Chain of Custody Service
==================================
Genera un Sello Criptográfico de Cadena de Custodia para cada análisis.

Garantía forense:
  El sello vincula criptográficamente el hash del archivo original con el
  score final y el timestamp del análisis, haciendo imposible alterar
  retroactivamente cualquier resultado sin invalidar el sello.

Componentes del sello:
  1. SHA-256 del archivo original (inmutabilidad del input)
  2. Task UUID (trazabilidad de la sesión de análisis)
  3. Score final (resultado auditado)
  4. Timestamp ISO 8601 UTC (cuando se realizó el análisis)
  5. HMAC-SHA256 del bundle (integridad del sello mismo)

Uso en auditorías judiciales:
  Cualquier auditor puede verificar que el archivo X (hash conocido)
  produjo el score Y en la fecha Z ejecutando:
    hmac.new(SIGNING_KEY, f"{task_id}:{sha256}:{score:.8f}:{ts}".encode(), sha256).hexdigest()
  y comparando contra el custody_token del reporte.
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from app.config import settings

# ── Clave de firma HMAC ───────────────────────────────────────────────────────
# OBLIGATORIA: si DEEPGUARD_SIGNING_KEY no está definida —o es uno de los
# valores de ejemplo/placeholder conocidos que aparecen en los .env.example
# y en docker-compose.prod.yml—, el servicio falla inmediatamente en lugar
# de firmar la cadena de custodia con una clave pública/adivinable (CRÍTICO-01).
# Generar clave segura: python -c "import secrets; print(secrets.token_hex(32))"
_INSECURE_PLACEHOLDERS = {
    "change-me-in-production",
    "cambia-esto-por-una-clave-aleatoria-larga",
    "reemplazar-con-output-de-secrets.token_hex(32)",
}
_raw_key = settings.DEEPGUARD_SIGNING_KEY or os.getenv("DEEPGUARD_SIGNING_KEY", "")
if not _raw_key or _raw_key.strip().lower() in _INSECURE_PLACEHOLDERS:
    # En modo API_ONLY (Render) no se generan sellos, por lo que no es crítico.
    # En modo worker (local con GPU) sí es obligatoria.
    if not settings.API_ONLY:
        raise RuntimeError(
            "DEEPGUARD_SIGNING_KEY no está definida o usa un valor de ejemplo "
            "inseguro (p. ej. 'change-me-in-production'). "
            "La cadena de custodia forense requiere una clave secreta real. "
            "Generar con: python -c \"import secrets; print(secrets.token_hex(32))\" "
            "y definirla como variable de entorno DEEPGUARD_SIGNING_KEY."
        )
    # En API_ONLY se usa placeholder — los sellos no se generan en la nube
    _raw_key = "api-only-placeholder-no-seals-generated-here"

_SIGNING_KEY: bytes = _raw_key.encode()

CUSTODY_REPORTS_DIR = settings.CUSTODY_DIR
CUSTODY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── SHA-256 del archivo ──────────────────────────────────────────────────────

def compute_file_sha256(file_path: Path, chunk_size: int = 65536) -> str:
    """
    Calcula SHA-256 en chunks para no cargar archivos grandes en memoria.
    Lanza OSError/IOError si el archivo no puede leerse (ALTO-03):
    retornar un string de error silencioso comprometería la cadena de custodia.
    El caller debe manejar la excepción explícitamente.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:   # Propaga IOError/PermissionError al caller
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


# ─── Sello de cadena de custodia ─────────────────────────────────────────────

def generate_custody_seal(
    task_id: str,
    file_sha256: str,
    filename: str,
    file_type: str,
    final_score: float,
    evidence_level: str,
    analyst_note: str = "Análisis automatizado DeepGuard AI",
    semantic_score: Optional[int] = None,
) -> dict:
    """
    Genera el sello criptográfico de cadena de custodia.

    El token HMAC-SHA256 vincula criptográficamente:
      - Hash SHA-256 del archivo original
      - Score final del ensemble
      - Score semántico de LLaVA (si disponible) — añadido en v2
      - Timestamp UTC
    Cualquier alteración de estos valores invalida el token.
    """
    timestamp_utc   = datetime.now(timezone.utc)
    timestamp_iso   = timestamp_utc.isoformat()
    timestamp_unix  = timestamp_utc.timestamp()
    seal_version    = "DG-CUSTODY-v2"  # v2 incluye score semántico

    # Score semántico para el canonical string (-1 si no disponible)
    sem_score_val = int(semantic_score) if semantic_score is not None else -1

    # String canónico para firmar (v2: incluye score semántico)
    canonical = (
        f"{seal_version}:{task_id}:{file_sha256}:"
        f"{final_score:.8f}:{timestamp_unix:.3f}:sem={sem_score_val}"
    )

    # HMAC-SHA256
    custody_token = hmac.new(
        _SIGNING_KEY,
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    seal = {
        "seal_version":  seal_version,
        "task_id":       task_id,
        "file_sha256":   file_sha256,
        "filename":      filename,
        "file_type":     file_type,
        "final_score":   round(final_score, 8),
        "evidence_level":  evidence_level,
        "semantic_score":  sem_score_val,
        "timestamp_utc":   timestamp_iso,
        "timestamp_unix":  round(timestamp_unix, 3),
        "custody_token":   custody_token,
        "analyst_note":    analyst_note,
    }

    logger.info(
        f"Custody seal generated: task={task_id[:8]}... "
        f"sha256={file_sha256[:16]}... "
        f"token={custody_token[:16]}..."
    )
    return seal


def verify_custody_seal(seal: dict) -> bool:
    """
    Verifica la integridad de un sello de custodia.

    CRÍTICO: recomputa el canonical string desde los campos individuales
    (no desde el campo canonical_string almacenado). Esto garantiza que
    cualquier alteración de task_id, file_sha256, final_score o timestamp
    invalide el sello, incluso si el atacante actualiza canonical_string.
    """
    try:
        token = seal.get("custody_token", "")
        if not token:
            return False

        version = seal.get("seal_version", "DG-CUSTODY-v1")

        # v2: incluye semantic_score en el canonical string
        if version == "DG-CUSTODY-v2":
            sem = int(seal.get("semantic_score", -1))
            canonical_recomputed = (
                f"{version}:{seal['task_id']}:{seal['file_sha256']}:"
                f"{seal['final_score']:.8f}:{seal['timestamp_unix']:.3f}:sem={sem}"
            )
        else:
            # v1 backward-compatible
            canonical_recomputed = (
                f"{version}:{seal['task_id']}:{seal['file_sha256']}:"
                f"{seal['final_score']:.8f}:{seal['timestamp_unix']:.3f}"
            )

        expected = hmac.new(
            _SIGNING_KEY, canonical_recomputed.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, token)
    except (KeyError, TypeError, ValueError):
        return False


# ─── Persistencia del reporte de custodia ─────────────────────────────────────

def persist_custody_report(
    seal: dict,
    analysis_result: dict,
) -> Path:
    """
    Guarda el reporte completo de custodia en disco como JSON inmutable.
    El filename incluye el task_id y el hash para trazabilidad.
    """
    task_id   = seal["task_id"]
    sha256    = seal["file_sha256"][:12]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_filename = f"custody_{task_id[:8]}_{sha256}_{timestamp}.json"
    report_path     = CUSTODY_REPORTS_DIR / report_filename

    report = {
        "chain_of_custody": seal,
        "analysis_summary": {
            "manipulation_probability": analysis_result.get("manipulation_probability"),
            "evidence_level":           analysis_result.get("evidence_level"),
            "model_agreement":          analysis_result.get("model_agreement"),
            "model_used":               analysis_result.get("model_used"),
            "device_used":              analysis_result.get("device_used"),
            "analysis_time_seconds":    analysis_result.get("analysis_time"),
            "forensic_correction_type": analysis_result.get("forensic_correction_type"),
        },
        "integrity_verified": verify_custody_seal(seal),
    }

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        # Hacer el archivo de reporte de solo lectura (protección adicional)
        report_path.chmod(0o444)
        logger.info(f"Custody report persisted: {report_path.name}")
    except Exception as e:
        logger.error(f"Failed to persist custody report: {e}")

    return report_path
