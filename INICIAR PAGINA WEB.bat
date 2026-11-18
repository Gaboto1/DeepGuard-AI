@echo off
REM Arranca el WORKER GPU, que es lo que hace funcionar la pagina: la web vive
REM en GitHub Pages y la API en Render, pero el analisis corre en este equipo.
REM
REM Abre el panel de control (scripts\panel_worker.py): comprueba el equipo,
REM arranca el worker, muestra la carga de cada modelo, la GPU y los analisis,
REM y guarda toda la salida en reports\worker.log. Cerrar el panel detiene el
REM worker.
REM
REM Version de consola, de respaldo: scripts\worker_consola.bat
cd /d "%~dp0"
if not exist "backend\venv\Scripts\pythonw.exe" (
    echo [ERROR] No hay entorno virtual en backend\venv
    echo         Crealo con: python -m venv backend\venv
    echo         y luego:    backend\venv\Scripts\pip install -r backend\requirements.txt
    pause
    exit /b 1
)
start "" "backend\venv\Scripts\pythonw.exe" "scripts\panel_worker.py"
