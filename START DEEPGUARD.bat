@echo off
title DeepGuard AI - Launcher
cls
echo.
echo  ========================================================
echo    DeepGuard AI - Starting all services
echo  ========================================================
echo.

REM Kill any existing instances
taskkill /f /im uvicorn.exe >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq DeepGuard*" >nul 2>&1
timeout /t 2 /nobreak >nul

REM Start backend
echo  [1/2] Starting backend (Triple Ensemble AI)...
start "DeepGuard Backend" /min cmd /k "cd /d "%~dp0backend" && set TRANSFORMERS_CACHE=%~dp0models && set HF_HOME=%~dp0models && set HF_HUB_DISABLE_SYMLINKS_WARNING=1 && venv\Scripts\activate && uvicorn app.main:app --host 0.0.0.0 --port 8000"

REM Wait for backend
echo  Waiting for models to load (30s)...
timeout /t 30 /nobreak >nul

REM Start frontend
echo  [2/2] Starting frontend...
start "DeepGuard Frontend" /min cmd /k "cd /d "%~dp0frontend" && npm run dev"

timeout /t 12 /nobreak >nul

echo.
echo  ========================================================
echo    DeepGuard AI is running!
echo.
echo    Web:    http://localhost:3000
echo    API:    http://localhost:8000
echo    Docs:   http://localhost:8000/docs
echo  ========================================================
echo.
start "" http://localhost:3000
echo  Press any key to stop all services...
pause >nul

taskkill /f /im uvicorn.exe >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq DeepGuard*" >nul 2>&1
echo  Services stopped.
