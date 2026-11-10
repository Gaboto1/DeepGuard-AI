# Comprobacion previa al arranque del worker GPU de DeepScan.
# Devuelve 0 para seguir, distinto de 0 para abortar. No arranca nada: solo mira.

$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RAIZ    = Split-Path -Parent $PSScriptRoot
$BACKEND = Join-Path $RAIZ "backend"

# VRAM libre que conviene tener ANTES de arrancar. El worker llega a ~7,7GB
# con todo residente y analizando, y LLaVA necesita 4,5GB de esos en GPU.
# El resto es holgura para que otras aplicaciones crezcan: el consumo de un
# navegador o un juego fluctua mientras el worker ya esta arriba.
$VRAM_MINIMA_MIB = 9500

# Procesos que suelen llevarse VRAM en este equipo, para poder nombrarlos.
$GOLOSOS = 'opera|chrome|msedge|firefox|League|RiotClient|wallpaper|Discord|' +
           'Spotify|Overwolf|BlueStacks|Genesis|ChatGPT|copilot|ms-teams|steamwebhelper'

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor DarkCyan
Write-Host "   DeepScan - comprobacion previa del worker" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor DarkCyan
Write-Host ""

# ---- 1. El entorno existe -------------------------------------------------
if (-not (Test-Path (Join-Path $BACKEND "venv\Scripts\celery.exe"))) {
    Write-Host "   [ERROR] No hay entorno virtual en backend\venv" -ForegroundColor Red
    Write-Host "           Crealo con:  python -m venv venv" -ForegroundColor Gray
    Write-Host "           y luego:     venv\Scripts\pip install -r requirements.txt" -ForegroundColor Gray
    exit 1
}
if (-not (Test-Path (Join-Path $BACKEND ".env"))) {
    Write-Host "   [ERROR] Falta backend\.env" -ForegroundColor Red
    Write-Host "           Sin el, la configuracion cae en sus valores por" -ForegroundColor Gray
    Write-Host "           defecto: broker en redis://localhost en vez de" -ForegroundColor Gray
    Write-Host "           Upstash, y el worker no recibe ninguna tarea." -ForegroundColor Gray
    exit 1
}
Write-Host "   [ ok ]  entorno virtual y backend\.env en su sitio" -ForegroundColor Green

# ---- 2. No hay ya un worker arriba ---------------------------------------
# Dos workers sobre una sola GPU se pelean la VRAM y los dos van lentos.
$yaArriba = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -like "*celery*" -and $_.CommandLine -like "*worker*" }
if ($yaArriba) {
    Write-Host ""
    Write-Host "   [ALTO]  Ya hay un worker en marcha:" -ForegroundColor Yellow
    foreach ($w in $yaArriba) { Write-Host ("           PID {0}" -f $w.ProcessId) -ForegroundColor Gray }
    Write-Host ""
    Write-Host "   Arrancar otro no duplica la capacidad: los dos se pelean la" -ForegroundColor Gray
    Write-Host "   misma GPU y ambos van lentos. Si el que hay esta colgado," -ForegroundColor Gray
    Write-Host "   cierra su ventana primero y vuelve a ejecutar esto." -ForegroundColor Gray
    Write-Host ""
    exit 2
}
Write-Host "   [ ok ]  no hay otro worker compitiendo por la GPU" -ForegroundColor Green

# ---- 3. VRAM libre -------------------------------------------------------
$g = & nvidia-smi --query-gpu=memory.free,memory.total --format=csv,noheader,nounits 2>$null
if (-not $g) {
    Write-Host "   [aviso] nvidia-smi no responde; no puedo comprobar la VRAM" -ForegroundColor DarkYellow
    Write-Host ""
    exit 0
}
$c = ($g -split ",") | ForEach-Object { [int]($_.Trim()) }
$libre = $c[0]; $total = $c[1]

if ($libre -ge $VRAM_MINIMA_MIB) {
    Write-Host ("   [ ok ]  VRAM libre {0} MiB de {1}" -f $libre, $total) -ForegroundColor Green
    Write-Host ""
    exit 0
}

# Por debajo del minimo: nombrar a los culpables y dejar decidir.
Write-Host ""
Write-Host ("   [ALTO]  VRAM libre {0} MiB de {1}. Hacen falta {2}." -f `
            $libre, $total, $VRAM_MINIMA_MIB) -ForegroundColor Yellow
Write-Host ""
Write-Host "   Con menos VRAM, LLaVA no cabe entero en la GPU y parte del" -ForegroundColor Gray
Write-Host "   modelo corre en CPU. Entonces cada analisis tarda DECENAS DE" -ForegroundColor Gray
Write-Host "   MINUTOS en vez de ~30 segundos, y la pagina parece colgada." -ForegroundColor Gray
Write-Host "   Medido el 9/11/2026: dos analisis de 38 y 39 minutos con la" -ForegroundColor Gray
Write-Host "   VRAM saturada, y 25-62 segundos los nueve siguientes." -ForegroundColor Gray
Write-Host ""

$apps = Get-Process | Where-Object { $_.Name -match $GOLOSOS } |
        Group-Object Name |
        Sort-Object { ($_.Group | Measure-Object WorkingSet64 -Sum).Sum } -Descending
if ($apps) {
    Write-Host "   Cierra estas antes de seguir (de mayor a menor):" -ForegroundColor White
    foreach ($a in ($apps | Select-Object -First 8)) {
        $ram = [math]::Round((($a.Group | Measure-Object WorkingSet64 -Sum).Sum)/1GB, 2)
        Write-Host ("      {0,-22} x{1,-3} RAM {2} GB" -f $a.Name, $a.Count, $ram) -ForegroundColor Gray
    }
    Write-Host ""
}

Write-Host "   Puedes arrancar igual: el worker funcionara, solo sera lento," -ForegroundColor DarkGray
Write-Host "   y el log te dira el presupuesto que LLaVA consiguio." -ForegroundColor DarkGray
Write-Host ""
$r = Read-Host "   Arrancar de todas formas? (s/N)"
if ($r -match '^[sSyY]') { Write-Host ""; exit 0 }
Write-Host ""
Write-Host "   Cancelado. Cierra lo que puedas y vuelve a ejecutarlo." -ForegroundColor Cyan
Write-Host ""
exit 3
