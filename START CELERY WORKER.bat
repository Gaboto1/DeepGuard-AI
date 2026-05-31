@echo off
title DEEPGUARD - Celery GPU Worker ^| Aiven Valkey
cd /d "%~dp0backend"

echo.
echo ============================================================
echo   DeepGuard AI - Heavy Worker GPU Local
echo   Broker: Aiven Valkey (Valkey 7.2.4 / TLS puerto 13419)
echo ============================================================
echo.

REM Verificar que el .env existe
if not exist ".env" (
    echo [ERROR] Archivo .env no encontrado en backend\.env
    pause
    exit /b 1
)

REM Verificar conexion con Aiven Valkey antes de lanzar
echo [INFO] Verificando conexion con Aiven Valkey...
venv\Scripts\python.exe -c "
import redis, sys, os
from pathlib import Path

for line in Path('.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip())

url = os.environ.get('REDIS_URL', '')
if not url:
    print('[ERROR] REDIS_URL no definida en .env')
    sys.exit(1)

try:
    r = redis.from_url(url, socket_connect_timeout=6, socket_timeout=6, decode_responses=True)
    pong = r.ping()
    info = r.info('server')
    print('[OK] Aiven Valkey', info.get('redis_version'), '- PING:', pong)
    sys.exit(0)
except Exception as e:
    print('[ERROR]', type(e).__name__, str(e)[:100])
    sys.exit(1)
" 2>&1

if errorlevel 1 (
    echo.
    echo [ERROR] No se pudo conectar a Aiven Valkey.
    echo         Verifica las credenciales en backend\.env
    pause
    exit /b 1
)

echo.
echo [OK] Lanzando worker Celery...
echo      Colas   : images, videos, default
echo      Pool    : threads (compatible Windows)
echo      Workers : 2 hilos concurrentes
echo.

set TRANSFORMERS_CACHE=%~dp0models
set HF_HOME=%~dp0models
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

venv\Scripts\celery.exe -A app.celery_app worker ^
    --loglevel=info ^
    -P threads ^
    -Q images,videos,default ^
    -c 2 ^
    -n deepguard-worker@%%h
