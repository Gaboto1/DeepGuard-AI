@echo off
title DEEPGUARD - Celery GPU Worker
cd /d "%~dp0backend"

echo.
echo ============================================================
echo   DeepGuard AI - Worker GPU Local
echo   Broker: Aiven Valkey TLS (puerto 13419)
echo ============================================================
echo.

REM Verificar que el entorno virtual existe
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] No se encontro el entorno virtual en backend\venv\
    echo         Ejecuta primero: python -m venv venv
    echo         Luego: venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

REM Verificar que el .env existe
if not exist ".env" (
    echo [ERROR] Archivo .env no encontrado en backend\.env
    echo         Copia backend\.env.worker.example como .env
    pause
    exit /b 1
)

REM Variables de entorno para modelos HuggingFace
set TRANSFORMERS_CACHE=%~dp0models
set HF_HOME=%~dp0models
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

echo [INFO] Iniciando Celery Worker...
echo        Pool    : threads (compatible Windows)
echo        Colas   : images, videos, default
echo        Workers : 2 hilos concurrentes
echo.
echo [INFO] Cargando modelos GPU... esto tarda ~90 segundos la primera vez.
echo.

venv\Scripts\celery.exe -A app.celery_app worker --loglevel=info -P threads -Q images,videos,default -c 2 -n deepguard-worker@%%h

echo.
echo [INFO] El worker se detuvo.
pause
