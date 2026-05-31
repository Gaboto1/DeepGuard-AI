import sys, io, requests, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from PIL import Image, ImageDraw, ImageFilter
from io import BytesIO
import numpy as np

API = "http://localhost:8000"

print()
print("=" * 65)
print("  DEEPGUARD ENTERPRISE — Test End-to-End API v1")
print("=" * 65)

# 1. v1/health
print("\n[1/4] GET /api/v1/health")
h1 = requests.get(f"{API}/api/v1/health", timeout=8).json()
print(f"  version: {h1['version']}")
print(f"  cuda: {h1['cuda']} | gpu: {h1.get('gpu','?')}")
print(f"  redis: {h1.get('redis_info','?')}")
print(f"  workers: {h1.get('workers_status','?')}")

# 2. POST /api/v1/analyze -> 202
print("\n[2/4] POST /api/v1/analyze -> 202 Accepted")
img = Image.new("RGB",(640,480)); px=img.load()
rng=np.random.default_rng(42)
for y in range(480):
    for x in range(640):
        n=int(rng.integers(-6,7))
        if y>288: px[x,y]=(55+n,95+n,38+n)
        else: px[x,y]=(max(0,min(255,int(120-30*(y/480))+n)),max(0,min(255,int(160-20*(y/480))+n)),max(0,min(255,int(210-10*(y/480))+n)))
buf=BytesIO(); img.filter(ImageFilter.GaussianBlur(0.5)).save(buf,"JPEG",quality=90); buf.seek(0)
r = requests.post(f"{API}/api/v1/analyze", files={"file":("real.jpg",buf,"image/jpeg")}, timeout=30)
print(f"  HTTP: {r.status_code} {'OK' if r.status_code==202 else 'FAIL'}")
d = r.json()
task_id = d["task_id"]
print(f"  task_id:   {task_id}")
print(f"  dispatch:  {d.get('dispatch_mode')}")
print(f"  est_secs:  {d.get('estimated_seconds')}s")

# 3. Poll /api/v1/tasks/{id}
print(f"\n[3/4] Polling /api/v1/tasks/{task_id[:8]}...")
for i in range(90):
    time.sleep(0.8)
    r2 = requests.get(f"{API}/api/v1/tasks/{task_id}", timeout=10).json()
    st = r2.get("status","?")
    if st in ("SUCCESS","FAILED"):
        print(f"  Completado en ~{(i+1)*0.8:.0f}s: status={st}")
        break
    if i % 5 == 0:
        print(f"  [{(i+1)*0.8:.0f}s] {st} progress={r2.get('progress',0):.0%}")

res = r2.get("result", r2)
print(f"\n  Resultado:")
print(f"    manipulation_probability : {res.get('manipulation_probability')}%")
print(f"    evidence_level           : {res.get('evidence_level')}")
print(f"    forensic_metadata:")
fm = res.get("forensic_metadata", {})
print(f"      ai_generator_detected  : {fm.get('ai_generator_detected')}")
print(f"      missing_exif           : {fm.get('missing_exif')}")
print(f"      risk_signal            : {fm.get('risk_signal')}")
print(f"    chain_of_custody         : {'PRESENTE' if res.get('chain_of_custody') else 'AUSENTE'}")
cod = res.get("chain_of_custody", {})
if cod:
    print(f"      sha256               : {cod.get('file_sha256','?')[:20]}...")
    print(f"      custody_token        : {cod.get('custody_token','?')[:20]}...")
    print(f"      timestamp_utc        : {cod.get('timestamp_utc','?')}")

# 4. Custody verification
print(f"\n[4/4] GET /api/v1/tasks/{task_id[:8]}.../custody")
if res.get("chain_of_custody"):
    r3 = requests.get(f"{API}/api/v1/tasks/{task_id}/custody", timeout=10)
    if r3.status_code == 200:
        c = r3.json()
        print(f"  integrity_valid : {c.get('integrity_valid')}")
        print(f"  message         : {c.get('verification_message','')[:80]}")
    else:
        print(f"  Status {r3.status_code}: {r3.text[:80]}")
else:
    print("  Sello no disponible (análisis en modo sync fallback)")

print()
print("=" * 65)
print("  ENTERPRISE API v1: TODAS LAS PRUEBAS COMPLETADAS")
print("=" * 65)
