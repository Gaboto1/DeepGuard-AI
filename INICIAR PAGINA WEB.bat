@echo off
title DEEPGUARD - Worker GPU (hace funcionar la pagina)
cd /d "%~dp0"

REM Este archivo arranca el WORKER GPU, que es lo que hace que la pagina
REM funcione: la web vive en GitHub Pages y la API en Render, pero el analisis
REM corre aqui, en esta maquina, con la GPU. Sin este worker la pagina acepta
REM la imagen y se queda esperando para siempre.

REM Comprobacion previa: entorno, worker duplicado y VRAM libre.
REM Ahi se decide si merece la pena arrancar ahora o cerrar aplicaciones antes.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\preparar_worker.ps1"
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

cd /d "%~dp0backend"

echo ============================================================
echo   DeepScan - Worker GPU local
echo   Broker : Upstash Redis TLS (rediss, puerto 6379)
echo   Colas  : images, videos, default    Pool: threads, 2 hilos
echo ============================================================
echo.
echo [INFO] Cargando los seis detectores, el meta-ensemble y LLaVA.
echo        Tarda entre 2 y 4 minutos. La pagina NO procesa cargas
echo        hasta que aparezca la linea "ready".
echo.
echo [INFO] Si en el log sale "VRAM INSUFICIENTE", LLaVA esta corriendo
echo        en CPU y cada analisis tardara decenas de minutos. Cierra
echo        navegadores y juegos, y reinicia este worker.
echo.

REM Cache de modelos HuggingFace dentro del proyecto, no en el perfil.
set TRANSFORMERS_CACHE=%~dp0models
set HF_HOME=%~dp0models
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

venv\Scripts\celery.exe -A app.celery_app worker --loglevel=info -P threads -Q images,videos,default -c 2 -n deepguard-worker@%%h

echo.
echo [INFO] El worker se detuvo. La pagina ya no procesa cargas.
pause
