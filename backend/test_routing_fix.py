# -*- coding: utf-8 -*-
"""
Test de corrección de enrutamiento:
  1. Verifica que el frontend usa /api/v1/ (no /api/)
  2. Verifica normalización de estados Celery -> frontend
  3. Verifica que get_task_status devuelva lowercase status
  4. Verifica que el sync_fallback produce campos completos

Ejecutar: python test_routing_fix.py
"""
import sys
import os
import json
import ast
import re

# Proveer clave de test antes de importar custody_service (CRÍTICO-01 fix)
os.environ.setdefault("DEEPGUARD_SIGNING_KEY", "test-key-for-unit-tests-only-not-for-production-use")
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))
FRONTEND_ROOT = Path(__file__).parent.parent / "frontend" / "src"

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


# ─── Test 1: Frontend uploadFile usa /api/v1/analyze ──────────────────────────

def test_frontend_upload_url():
    api_ts = (FRONTEND_ROOT / "lib" / "api.ts").read_text(encoding="utf-8")
    # Debe tener /api/v1/analyze y NO /api/analyze (sin v1) en el upload
    has_v1  = "/api/v1/analyze" in api_ts
    # Verificar que el POST no apunte al legacy sin v1
    legacy  = bool(re.search(r"post\(['\"]\/api\/analyze['\"]", api_ts, re.IGNORECASE))
    ok = has_v1 and not legacy
    print(
        f"  {PASS if ok else FAIL} [TEST 1] uploadFile -> /api/v1/analyze "
        f"(v1={has_v1}, legacy_sin_v1={legacy})"
    )
    results.append(ok)


# ─── Test 2: Frontend getTask usa /api/v1/tasks ────────────────────────────────

def test_frontend_polling_url():
    api_ts = (FRONTEND_ROOT / "lib" / "api.ts").read_text(encoding="utf-8")
    has_v1_tasks = "/api/v1/tasks/" in api_ts
    legacy_tasks = bool(re.search(r"get\(['\"`]\/api\/tasks\/", api_ts, re.IGNORECASE))
    ok = has_v1_tasks and not legacy_tasks
    print(
        f"  {PASS if ok else FAIL} [TEST 2] getTask -> /api/v1/tasks/{{id}} "
        f"(v1={has_v1_tasks}, legacy={legacy_tasks})"
    )
    results.append(ok)


# ─── Test 3: Frontend normaliza estados Celery -> frontend ────────────────────

def test_frontend_status_normalization():
    api_ts = (FRONTEND_ROOT / "lib" / "api.ts").read_text(encoding="utf-8")
    # En TypeScript las claves de objetos no llevan comillas, buscar el patrón clave:valor
    # SUCCESS: 'completed' o SUCCESS:    'completed'
    has_success_map = bool(re.search(r"SUCCESS\s*:\s*['\"]completed['\"]", api_ts))
    has_completed   = "completed" in api_ts
    has_failed      = bool(re.search(r"FAILED\s*:\s*['\"]failed['\"]", api_ts))
    ok = has_success_map and has_completed and has_failed
    print(
        f"  {PASS if ok else FAIL} [TEST 3] Mapa de normalizacion de estados presente "
        f"(SUCCESS->completed={has_success_map}, completed={has_completed}, FAILED->failed={has_failed})"
    )
    results.append(ok)


# ─── Test 4: Backend v1 get_task_status normaliza status a minuscula ──────────

def test_backend_status_normalization():
    routes_src = Path(__file__).parent / "app" / "api" / "v1" / "routes.py"
    src = routes_src.read_text(encoding="utf-8")
    # Debe asignar "completed" (minúscula) en la respuesta
    has_completed = '"completed"' in src
    has_frontend  = "_STATUS_FRONTEND" in src
    has_normalize = "frontend_status" in src
    ok = has_completed and has_frontend and has_normalize
    print(
        f"  {PASS if ok else FAIL} [TEST 4] Backend v1 normaliza status a minuscula "
        f"(completed={has_completed}, _STATUS_FRONTEND={has_frontend}, frontend_status={has_normalize})"
    )
    results.append(ok)


# ─── Test 5: sync_fallback incluye LLaVA, semantic_analysis, chain_of_custody ─

def test_sync_fallback_completeness():
    routes_src = Path(__file__).parent / "app" / "api" / "v1" / "routes.py"
    src = routes_src.read_text(encoding="utf-8")

    required_fields = [
        "analyze_semantic_coherence",   # LLaVA call
        "apply_semantic_fusion",        # fusion
        '"semantic_analysis"',          # campo resultado
        '"chain_of_custody"',           # sello de custodia
        '"manipulation_probability"',   # campo requerido por frontend
        '"evidence_level"',             # campo requerido por frontend
        '"explanation"',                # campo requerido por frontend
        '"progress"',                    # campo de progreso presente
        '"status":                  "completed"',  # minúscula para frontend
    ]

    missing = [f for f in required_fields if f not in src]
    ok = len(missing) == 0

    if ok:
        print(f"  {PASS} [TEST 5] sync_fallback completo: todos los campos requeridos presentes")
    else:
        print(f"  {FAIL} [TEST 5] sync_fallback incompleto — faltan: {missing}")
    results.append(ok)


# ─── Test 6: custody_service.generate_custody_seal acepta semantic_score ──────

def test_custody_seal_api():
    try:
        from app.services.custody_service import generate_custody_seal, verify_custody_seal
        seal = generate_custody_seal(
            task_id="test-routing-uuid-0001",
            file_sha256="b" * 64,
            filename="routing_test.jpg",
            file_type="image",
            final_score=0.19,
            evidence_level="Low Evidence",
            semantic_score=8,
        )
        assert seal["seal_version"] == "DG-CUSTODY-v2"
        assert verify_custody_seal(seal), "Sello invalido"
        print(f"  {PASS} [TEST 6] generate_custody_seal v2 funciona con semantic_score=8")
        results.append(True)
    except Exception as e:
        print(f"  {FAIL} [TEST 6] custody_service error: {type(e).__name__}: {e}")
        results.append(False)


# ─── Test 7: resultado JSON del sync_fallback tiene status=completed ───────────

def test_sync_fallback_status_value():
    """Analiza el AST del sync_fallback para confirmar que status='completed'."""
    routes_src = Path(__file__).parent / "app" / "api" / "v1" / "routes.py"
    src = routes_src.read_text(encoding="utf-8")

    # Buscar el dict del resultado en _run() con status "completed"
    # Patron: '"status": "completed"' dentro de la funcion _run
    has_completed_status = re.search(
        r'"status"\s*:\s*"completed"', src
    ) is not None
    has_failed_status = re.search(
        r'"status"\s*:\s*"failed"', src
    ) is not None

    ok = has_completed_status and has_failed_status
    print(
        f"  {PASS if ok else FAIL} [TEST 7] sync_fallback devuelve status en minusculas "
        f"(completed={has_completed_status}, failed={has_failed_status})"
    )
    results.append(ok)


# ─── Test 8: frontend validateStatus acepta 202 ────────────────────────────────

def test_frontend_accepts_202():
    api_ts = (FRONTEND_ROOT / "lib" / "api.ts").read_text(encoding="utf-8")
    # El cliente axios debe aceptar 202 via validateStatus
    has_validate_status = "validateStatus" in api_ts
    has_202 = "< 300" in api_ts or "202" in api_ts
    ok = has_validate_status and has_202
    print(
        f"  {PASS if ok else FAIL} [TEST 8] axios acepta 202 via validateStatus "
        f"(validateStatus={has_validate_status}, 202_range={has_202})"
    )
    results.append(ok)


# ─── Ejecucion ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Test de corrección de enrutamiento v1 ===\n")

    test_frontend_upload_url()
    test_frontend_polling_url()
    test_frontend_status_normalization()
    test_backend_status_normalization()
    test_sync_fallback_completeness()
    test_custody_seal_api()
    test_sync_fallback_status_value()
    test_frontend_accepts_202()

    total  = len(results)
    passed = sum(results)
    print(f"\n=== {passed}/{total} tests pasaron ===\n")
    sys.exit(0 if all(results) else 1)
