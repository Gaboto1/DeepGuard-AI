# ============================================================
# DeepGuard AI — Windows Setup Script (PowerShell)
# RTX 4070 SUPER + CUDA 12.1 + Python 3.11+
# Run: powershell -ExecutionPolicy Bypass -File setup.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "   DeepGuard AI - Setup Script" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# --- Check prerequisites ---
Write-Host "[1/7] Checking prerequisites..." -ForegroundColor Yellow

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Python not found. Install Python 3.11+ from https://python.org" -ForegroundColor Red
    exit 1
}

$pyVer = python --version 2>&1
Write-Host "  Python: $pyVer" -ForegroundColor Green

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Node.js not found. Install from https://nodejs.org (v18+)" -ForegroundColor Red
    exit 1
}
$nodeVer = node --version
Write-Host "  Node.js: $nodeVer" -ForegroundColor Green

# Check CUDA
$cudaAvailable = $false
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Host "  NVIDIA GPU detected:" -ForegroundColor Green
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | ForEach-Object {
        Write-Host "    $_" -ForegroundColor Green
    }
    $cudaAvailable = $true
} else {
    Write-Host "  WARNING: nvidia-smi not found. CPU mode will be used." -ForegroundColor Yellow
}

# --- Backend setup ---
Write-Host ""
Write-Host "[2/7] Setting up Python virtual environment..." -ForegroundColor Yellow

Set-Location "$Root\backend"
if (-not (Test-Path "venv")) {
    python -m venv venv
    Write-Host "  venv created" -ForegroundColor Green
} else {
    Write-Host "  venv already exists" -ForegroundColor Green
}

$activate = "$Root\backend\venv\Scripts\Activate.ps1"
& $activate

Write-Host ""
Write-Host "[3/7] Installing PyTorch with CUDA 12.1 support..." -ForegroundColor Yellow

if ($cudaAvailable) {
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet
    Write-Host "  PyTorch (CUDA 12.1) installed" -ForegroundColor Green
} else {
    pip install torch torchvision torchaudio --quiet
    Write-Host "  PyTorch (CPU) installed" -ForegroundColor Green
}

Write-Host ""
Write-Host "[4/7] Installing backend dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
Write-Host "  Backend dependencies installed" -ForegroundColor Green

# Setup .env
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    if (-not $cudaAvailable) {
        (Get-Content ".env") -replace "DEVICE=cuda", "DEVICE=cpu" | Set-Content ".env"
    }
    Write-Host "  .env created" -ForegroundColor Green
}

# Create dirs
New-Item -ItemType Directory -Force -Path "$Root\uploads" | Out-Null
New-Item -ItemType Directory -Force -Path "$Root\models" | Out-Null
New-Item -ItemType Directory -Force -Path "$Root\backend\logs" | Out-Null

# --- Frontend setup ---
Write-Host ""
Write-Host "[5/7] Installing frontend dependencies..." -ForegroundColor Yellow

Set-Location "$Root\frontend"
npm install --silent
Write-Host "  Frontend dependencies installed" -ForegroundColor Green

# .env.local
if (-not (Test-Path ".env.local")) {
    "NEXT_PUBLIC_API_URL=http://localhost:8000" | Out-File -FilePath ".env.local" -Encoding utf8
    Write-Host "  frontend .env.local created" -ForegroundColor Green
}

# --- Pre-download model ---
Write-Host ""
Write-Host "[6/7] Pre-downloading AI model (dima806/deepfake_vs_real_image_detection)..." -ForegroundColor Yellow
Write-Host "  This may take a few minutes (~350MB)..." -ForegroundColor Gray

Set-Location "$Root\backend"
& $activate

python -c @"
import os
os.environ['TRANSFORMERS_CACHE'] = r'$Root\models'
os.environ['HF_HOME'] = r'$Root\models'
from transformers import AutoImageProcessor, AutoModelForImageClassification
print('Downloading model...')
AutoImageProcessor.from_pretrained('dima806/deepfake_vs_real_image_detection', cache_dir=r'$Root\models')
AutoModelForImageClassification.from_pretrained('dima806/deepfake_vs_real_image_detection', cache_dir=r'$Root\models')
print('Model downloaded successfully!')
"@

Write-Host "  Model ready!" -ForegroundColor Green

# --- Launch scripts ---
Write-Host ""
Write-Host "[7/7] Creating launch scripts..." -ForegroundColor Yellow

$startBackend = @"
@echo off
cd /d "%~dp0backend"
call venv\Scripts\activate
set TRANSFORMERS_CACHE=%~dp0models
set HF_HOME=%~dp0models
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"@
$startBackend | Out-File -FilePath "$Root\start-backend.bat" -Encoding ascii

$startFrontend = @"
@echo off
cd /d "%~dp0frontend"
npm run dev
"@
$startFrontend | Out-File -FilePath "$Root\start-frontend.bat" -Encoding ascii

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "   Setup Complete!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start the application:" -ForegroundColor White
Write-Host ""
Write-Host "  Terminal 1 (Backend):" -ForegroundColor Cyan
Write-Host "    start-backend.bat" -ForegroundColor White
Write-Host "    OR: cd backend && venv\Scripts\activate && uvicorn app.main:app --port 8000" -ForegroundColor Gray
Write-Host ""
Write-Host "  Terminal 2 (Frontend):" -ForegroundColor Cyan
Write-Host "    start-frontend.bat" -ForegroundColor White
Write-Host "    OR: cd frontend && npm run dev" -ForegroundColor Gray
Write-Host ""
Write-Host "  Open: http://localhost:3000" -ForegroundColor Yellow
Write-Host "  API:  http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host ""
