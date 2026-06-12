@echo off
cd /d "%~dp0backend"
call venv\Scripts\activate
set TRANSFORMERS_CACHE=%~dp0models
set HF_HOME=%~dp0models
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
