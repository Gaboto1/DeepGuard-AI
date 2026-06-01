# -*- coding: utf-8 -*-
"""Debug completo del sistema de health check. python debug_health.py"""
import os, sys, json
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Cargar .env
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

REDIS_URL = os.environ.get("REDIS_URL", "")
print(f"REDIS_URL (primeros 40 chars): {REDIS_URL[:40]}...")

sys.path.insert(0, ".")
from app.config import make_redis_client

print("\n=== TEST 1: Conectar a Redis con make_redis_client() ===")
try:
    r = make_redis_client(socket_connect_timeout=6, socket_timeout=6, decode_responses=True)
    r.ping()
    print("Redis PING: OK")
except Exception as e:
    print(f"Redis PING FAIL: {type(e).__name__}: {e}")
    sys.exit(1)

print("\n=== TEST 2: Heartbeat key ===")
val = r.get("deepguard:worker:heartbeat")
ttl = r.ttl("deepguard:worker:heartbeat")
print(f"deepguard:worker:heartbeat = {val}")
print(f"TTL = {ttl}s")
if val:
    print("RESULTADO: Worker DETECTADO via heartbeat")
else:
    print("RESULTADO: Heartbeat NO encontrado — worker no lo escribio todavia")
    print("  -> Espera 30s despues de que el worker arranque")

print("\n=== TEST 3: Todas las claves en Aiven ===")
try:
    keys = r.keys("*")
    print(f"Total de claves: {len(keys)}")
    for k in sorted(keys)[:30]:
        ttl_k = r.ttl(k)
        print(f"  {k}  (TTL={ttl_k}s)")
except Exception as e:
    print(f"Error listando claves: {e}")

print("\n=== TEST 4: ¿Celery worker activo? (via inspect.ping, timeout=10s) ===")
try:
    from app.celery_app import celery_app
    inspect = celery_app.control.inspect(timeout=10)
    result  = inspect.ping()
    print(f"inspect.ping() result: {result}")
    if result:
        print("RESULTADO: Worker DETECTADO via inspect.ping")
    else:
        print("RESULTADO: inspect.ping devolvio None/vacio — no detectado")
except Exception as e:
    print(f"inspect.ping EXCEPCION: {type(e).__name__}: {e}")

print("\n=== TEST 5: Simular health endpoint completo ===")
HEARTBEAT_KEY = "deepguard:worker:heartbeat"
hb_value = r.get(HEARTBEAT_KEY)
hb_ttl   = r.ttl(HEARTBEAT_KEY) if hb_value else -1
workers_online = hb_value is not None
print(f"workers_online = {workers_online}")
print(f"hb_value = {hb_value}")
print(f"hb_ttl = {hb_ttl}")
payload = {
    "workers_online": workers_online,
    "workers_status": f"Worker activo (TTL={hb_ttl}s)" if workers_online else "Sin workers",
}
print(f"JSON que devolveria el endpoint: {json.dumps(payload)}")
