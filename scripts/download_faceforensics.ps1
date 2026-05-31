# ============================================================
# FaceForensics++ Dataset Download Script
# Downloads the c0 (lossless ~300GB) version
#
# USAGE:
#   powershell -ExecutionPolicy Bypass -File download_faceforensics.ps1
#
# REQUIREMENTS:
#   - The faceforensics_download_v4.py script in this folder
#   - Python + pip installed
#   - ~400GB free disk space
# ============================================================

$Root       = "C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL"
$ScriptPath = "$Root\scripts\faceforensics_download_v4.py"
$DataDir    = "E:\faceforensics_data"   # Using E: drive (481GB free)
$PythonExe  = "$Root\backend\venv\Scripts\python.exe"

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  FaceForensics++ Dataset Download" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Download destination: $DataDir"
Write-Host "  Estimated size: ~300GB (c0/lossless)"
Write-Host "  Estimated time: 6-24h depending on connection"
Write-Host ""

# Check script exists
if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: Download script not found at: $ScriptPath" -ForegroundColor Red
    Write-Host "Please save the faceforensics_download_v4.py file to the scripts/ folder." -ForegroundColor Yellow
    exit 1
}

# Check python
if (-not (Test-Path $PythonExe)) {
    Write-Host "ERROR: Python venv not found. Run setup.ps1 first." -ForegroundColor Red
    exit 1
}

# Check disk space on E:
$drive = Get-PSDrive E -ErrorAction SilentlyContinue
if ($drive) {
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    Write-Host "  Drive E: free space: ${freeGB}GB"
    if ($freeGB -lt 350) {
        Write-Host "  WARNING: Less than 350GB free. May run out of space." -ForegroundColor Yellow
    }
} else {
    Write-Host "  Drive E: not found. Change DataDir variable to an available drive." -ForegroundColor Yellow
}

# Create destination
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path "$DataDir\original_sequences" | Out-Null
New-Item -ItemType Directory -Force -Path "$DataDir\manipulated_sequences" | Out-Null

Write-Host ""
Write-Host "Starting download..." -ForegroundColor Yellow
Write-Host "  Run this in a terminal that won't be closed:" -ForegroundColor Gray
Write-Host ""

# Full command for 300GB (c0 = lossless compression)
$cmd = @"
& "$PythonExe" "$ScriptPath" "$DataDir" -d all -c c0 -t videos
"@

Write-Host $cmd -ForegroundColor White
Write-Host ""
Write-Host "For c23 version (~60GB, faster, still research-quality):" -ForegroundColor Gray
Write-Host "  $PythonExe `"$ScriptPath`" `"$DataDir`" -d all -c c23 -t videos" -ForegroundColor Gray
Write-Host ""

# Confirm and run
$confirm = Read-Host "Start download now? (y/n)"
if ($confirm -eq 'y') {
    Write-Host "Downloading... (this will take many hours, do not close this window)"
    & $PythonExe $ScriptPath $DataDir -d all -c c0 -t videos
} else {
    Write-Host "Download not started. Run the command above manually when ready." -ForegroundColor Yellow
}
