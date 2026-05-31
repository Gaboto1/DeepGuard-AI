import sys, os
sys.path.insert(0, '.')
os.environ['TRANSFORMERS_CACHE'] = r'C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\models'
os.environ['HF_HOME'] = r'C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\models'
os.chdir(r'C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\backend')

print('=== Enterprise Module Check ===')
errors = []

# 1. Celery app
try:
    from app.celery_app import celery_app
    print(f'  [OK] celery_app (broker={celery_app.conf.broker_url})')
except Exception as e:
    errors.append(f'celery_app: {e}'); print(f'  [FAIL] celery_app: {e}')

# 2. Custody service
try:
    from app.services.custody_service import compute_file_sha256, generate_custody_seal, verify_custody_seal
    import tempfile, pathlib
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
        f.write(b'test content deepguard v1')
        tmp = pathlib.Path(f.name)
    sha  = compute_file_sha256(tmp)
    seal = generate_custody_seal('test-uuid-1234', sha, 'test.jpg', 'image', 0.75, 'Moderate Evidence')
    ok   = verify_custody_seal(seal)
    tmp.unlink(missing_ok=True)
    print(f'  [OK] custody_service | sha={sha[:12]}... | verify={ok}')
    assert ok, "Seal verification failed!"
except Exception as e:
    errors.append(f'custody: {e}'); print(f'  [FAIL] custody: {e}')

# 3. Forensic metadata service
try:
    from app.services.forensic_metadata_service import (
        extract_forensic_metadata, apply_metadata_risk_to_score
    )
    adj, note = apply_metadata_risk_to_score(0.50, {'risk_signal': 0.40, 'risk_reasons': ['IA detectada (+40%)']})
    print(f'  [OK] forensic_metadata | 0.50 + risk(0.40) -> {adj:.3f} | note={bool(note)}')
    assert 0.50 < adj <= 0.60, f"Unexpected adjusted score: {adj}"
except Exception as e:
    errors.append(f'metadata: {e}'); print(f'  [FAIL] metadata: {e}')

# 4. Syntax check tasks
try:
    with open(r'C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\backend\app\tasks\analysis_tasks.py') as f:
        compile(f.read(), 'analysis_tasks.py', 'exec')
    print('  [OK] analysis_tasks.py syntax valid')
except Exception as e:
    errors.append(f'tasks syntax: {e}'); print(f'  [FAIL] tasks syntax: {e}')

# 5. Syntax check v1 routes
try:
    with open(r'C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\backend\app\api\v1\routes.py') as f:
        compile(f.read(), 'routes_v1.py', 'exec')
    print('  [OK] api/v1/routes.py syntax valid')
except Exception as e:
    errors.append(f'routes syntax: {e}'); print(f'  [FAIL] routes syntax: {e}')

# 6. Full app import (includes router_v1)
try:
    import app.main
    print('  [OK] app.main imports + v1 router registered')
except Exception as e:
    errors.append(f'app.main: {e}'); print(f'  [FAIL] app.main: {e}')

print()
if errors:
    print(f'FAILED ({len(errors)} errors): {errors}')
else:
    print('ALL ENTERPRISE MODULES: OK')
