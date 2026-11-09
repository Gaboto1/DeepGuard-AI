# Panel de progreso del pipeline v3 de DeepScan.
# Se refresca solo. Ctrl+C para salir. No toca nada: solo lee.

$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RAIZ = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RAIZ "reports"))) { $RAIZ = $PSScriptRoot }
$LOG  = Join-Path $RAIZ "reports\pipeline_v3_etapas2a10.log"

# Tope de minutos por etapa, igual que en scripts/pipeline_v3.py
$TOPE = @{ 2=240; 3=120; 4=180; 5=300; 6=180; 7=120; 8=180; 9=120; 10=30 }

# Nombres por adelantado, para que las etapas pendientes se vean antes de
# empezar en vez de salir como "(pendiente)".
$NOMBRE = @{
    2="Embeddings CLIP del conjunto ampliado"; 3="Dominio webcam"
    4="Reentrenamiento del probe CLIP (detector C)"
    5="Scoring con los 6 detectores"; 6="Variantes de compresion"
    7="Caracteristica de nivel de compresion"
    8="Recalculo del detector C"; 9="Reentrenamiento de los cabezales"
    10="Bateria de pruebas"
}

# Las etapas que no vuelcan su salida: ahi no habra linea de progreso y el
# panel lo dice en vez de parecer que no avanza.
$CIEGAS = @(4)

function Leer-Etapas {
    $iniciadas = @{}; $hechas = @{}; $nombres = @{}
    if (-not (Test-Path $LOG)) { return @($iniciadas, $hechas, $nombres) }
    foreach ($l in Get-Content $LOG) {
        if ($l -match '^\[(\d\d:\d\d:\d\d)\] ETAPA (\d+): (.+)$') {
            $hora = $matches[1]; $n = [int]$matches[2]; $resto = $matches[3]
            if ($resto -match '^(OK|FALLO|AGOTO)') {
                $hechas[$n] = $resto
            } elseif ($resto -match '^omitida') {
                $hechas[$n] = "omitida"
            } else {
                $iniciadas[$n] = $hora; $nombres[$n] = $resto
            }
        }
    }
    return @($iniciadas, $hechas, $nombres)
}

while ($true) {
    $r = Leer-Etapas
    $iniciadas = $r[0]; $hechas = $r[1]; $nombres = $r[2]

    $actual = $null
    foreach ($n in ($iniciadas.Keys | Sort-Object)) {
        if (-not $hechas.ContainsKey($n)) { $actual = $n }
    }

    $arranque = "?"
    if (Test-Path $LOG) {
        $p = Get-Content $LOG | Select-String -Pattern 'PIPELINE v3' | Select-Object -First 1
        if ($p -and $p.Line -match '^\[(\d\d:\d\d:\d\d)\]') { $arranque = $matches[1] }
    }

    Clear-Host
    Write-Host ""
    Write-Host "  ================================================================" -ForegroundColor DarkCyan
    Write-Host ("   DeepScan - PIPELINE v3        {0}    (arranco {1})" -f (Get-Date -Format "HH:mm:ss"), $arranque) -ForegroundColor Cyan
    Write-Host "  ================================================================" -ForegroundColor DarkCyan
    Write-Host ""
    Write-Host "   ETAPAS" -ForegroundColor White

    foreach ($n in 2..10) {
        $nom = $nombres[$n]
        if (-not $nom) { $nom = $NOMBRE[$n] }
        if (-not $nom) { $nom = "(pendiente)" }
        if ($nom.Length -gt 42) { $nom = $nom.Substring(0, 42) }
        if ($hechas.ContainsKey($n)) {
            $d = $hechas[$n]
            $col = if ($d -match '^OK') { "Green" } elseif ($d -match '^omitida') { "DarkGray" } else { "Red" }
            $et  = if ($d -match '^OK') { "[ OK ]" } elseif ($d -match '^omitida') { "[ -- ]" } else { "[FALLO]" }
            $ext = ""
            if ($d -match 'en ([0-9.]+) min') { $ext = ("{0,8} min" -f $matches[1]) }
            Write-Host ("     {0} {1,2}  {2,-42} {3}" -f $et, $n, $nom, $ext) -ForegroundColor $col
        } elseif ($n -eq $actual) {
            $min = ""
            if ($iniciadas[$n]) {
                $t0 = [datetime]::ParseExact($iniciadas[$n], "HH:mm:ss", $null)
                $mins = ((Get-Date) - $t0).TotalMinutes
                if ($mins -lt 0) { $mins += 1440 }
                $min = ("{0,8:N1} min  (tope {1})" -f $mins, $TOPE[$n])
            }
            Write-Host ("     [ >> ] {0,2}  {1,-42} {2}" -f $n, $nom, $min) -ForegroundColor Yellow
        } else {
            Write-Host ("            {0,2}  {1,-42}" -f $n, $nom) -ForegroundColor DarkGray
        }
    }

    Write-Host ""
    if ($actual) {
        Write-Host ("   PROGRESO DE LA ETAPA {0}" -f $actual) -ForegroundColor White
        $le = Join-Path $RAIZ ("reports\pipeline_v3_etapa{0}.log" -f $actual)
        $lineas = @()
        if (Test-Path $le) {
            $lineas = Get-Content $le -Tail 4 | Where-Object { $_.Trim() -ne "" }
        }
        if ($lineas.Count -gt 0) {
            foreach ($l in $lineas) {
                $t = $l.Trim(); if ($t.Length -gt 60) { $t = $t.Substring(0, 60) }
                Write-Host ("     {0}" -f $t) -ForegroundColor Gray
            }
        } elseif ($CIEGAS -contains $actual) {
            Write-Host "     Esta etapa no vuelca su salida mientras corre: el log" -ForegroundColor DarkYellow
            Write-Host "     queda vacio aunque este trabajando. Mirar el CPU de" -ForegroundColor DarkYellow
            Write-Host "     abajo, que es la senal de vida de verdad." -ForegroundColor DarkYellow
        } else {
            Write-Host "     (sin linea de progreso todavia)" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "   PIPELINE TERMINADO (o detenido)" -ForegroundColor Magenta
    }

    Write-Host ""
    Write-Host "   SENALES DE VIDA" -ForegroundColor White
    $g = & nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>$null
    if ($g) {
        $c = ($g -split ",") | ForEach-Object { $_.Trim() }
        Write-Host ("     GPU        {0} MiB de {1}     uso {2} %" -f $c[0], $c[1], $c[2]) -ForegroundColor Gray
    } else {
        Write-Host "     GPU        (nvidia-smi no responde)" -ForegroundColor DarkGray
    }

    $hijos = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
             Where-Object { $_.CommandLine -like "*scripts*" -and $_.CommandLine -notlike "*pipeline_v3.py*" }
    if ($hijos) {
        foreach ($h in $hijos) {
            $pr = Get-Process -Id $h.ProcessId
            if (-not $pr -or $pr.CPU -lt 1) { continue }
            $nm = "?"
            if ($h.CommandLine -match 'scripts[\/]([a-zA-Z0-9_]+\.py)') { $nm = $matches[1] }
            Write-Host ("     proceso    {0,-28} CPU {1,6:N0} min de nucleo   RAM {2,5:N0} MB" -f $nm, ($pr.CPU/60), ($pr.WorkingSet64/1MB)) -ForegroundColor Gray
        }
    } else {
        Write-Host "     proceso    (ninguna etapa ejecutandose)" -ForegroundColor DarkGray
    }

    if ($actual) {
        $le = Join-Path $RAIZ ("reports\pipeline_v3_etapa{0}.log" -f $actual)
        if (Test-Path $le) {
            $m = (Get-Item $le).LastWriteTime
            $seg = ((Get-Date) - $m).TotalSeconds
            $col = if ($seg -gt 600) { "DarkYellow" } else { "Gray" }
            $edad = if ($seg -lt 90) { "{0:N0} s" -f $seg } else { "{0:N1} min" -f ($seg/60) }
            Write-Host ("     log etapa  ultima escritura {0:HH:mm:ss}  (hace {1})" -f $m, $edad) -ForegroundColor $col
        }
    }

    # ---- FASE 2: lo que de verdad decide. El pipeline solo deja los modelos
    # nuevos en disco; hasta que el retenido se mide y se aplica el criterio,
    # el reentrenamiento no significa nada. Un archivo cuenta como recien
    # hecho solo si es posterior al fin del pipeline: asi una medicion vieja
    # no se hace pasar por la de ahora.
    Write-Host ""
    Write-Host "   FASE 2 - MEDICION Y DECISION" -ForegroundColor White

    $corte = (Get-Date).AddDays(-1)
    if (Test-Path $LOG) { $corte = (Get-Item $LOG).LastWriteTime }

    $pasos = @(
        @{ etiqueta = "Medir el retenido (2.000 imagenes, ~17 min)"
           ruta     = "reports\heldout_eval.json" }
        @{ etiqueta = "Bandas de evidencia"
           ruta     = "reports\heldout_eval_bandas.json" }
        @{ etiqueta = "Decision de adopcion"
           ruta     = "reports\decision_adopcion.json" }
    )
    foreach ($ps in $pasos) {
        $ruta  = Join-Path $RAIZ $ps.ruta
        $listo = (Test-Path $ruta) -and ((Get-Item $ruta).LastWriteTime -gt $corte)
        if ($listo) {
            Write-Host ("     [ OK ]  {0}" -f $ps.etiqueta) -ForegroundColor Green
        } else {
            Write-Host ("             {0}" -f $ps.etiqueta) -ForegroundColor DarkGray
        }
    }

    $logMed = Join-Path $RAIZ "reports\heldout_run_post_v3.log"
    if (Test-Path $logMed) {
        # -Tail 400 y no 4: el log de la medicion lleva varias lineas de
        # DEBUG por imagen, asi que la linea de avance queda sepultada muy
        # por encima del final. Con 4 el panel no mostraba nada.
        $ult = Get-Content $logMed -Tail 400 |
               Where-Object { $_ -match '\[\d+/\d+\]' } |
               Select-Object -Last 1
        if ($ult) {
            Write-Host ("     avance     {0}" -f $ult.Trim()) -ForegroundColor Gray
        }
    }

    $dj = Join-Path $RAIZ "reports\decision_adopcion.json"
    if ((Test-Path $dj) -and ((Get-Item $dj).LastWriteTime -gt $corte)) {
        $d = Get-Content $dj -Raw | ConvertFrom-Json
        $colv = if ($d.veredicto -eq "ADOPTAR") { "Green" } else { "DarkYellow" }
        Write-Host ""
        Write-Host ("     VEREDICTO  {0}" -f $d.veredicto) -ForegroundColor $colv
        Write-Host ("        falsas alarmas {0:N2} -> {1:N2} %" -f `
                    $d.antes.falsas_alarmas_pct, $d.ahora.falsas_alarmas_pct) -ForegroundColor Gray
        Write-Host ("        IA senalada    {0:N1} -> {1:N1} %" -f `
                    $d.antes.ia_senalada_pct, $d.ahora.ia_senalada_pct) -ForegroundColor Gray
        if ($d.antes.auc -and $d.ahora.auc) {
            Write-Host ("        AUC retenido   {0:N4} -> {1:N4}" -f `
                        $d.antes.auc, $d.ahora.auc) -ForegroundColor Gray
        }
    }

    # El worker carga los modelos una sola vez al arrancar: mientras este
    # detenido, la pagina no procesa nada, por buenos que sean los .joblib.
    $wk = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
          Where-Object { $_.CommandLine -like "*celery*" }
    if ($wk) {
        Write-Host "     worker     en marcha: la pagina procesa cargas" -ForegroundColor Green
    } else {
        Write-Host "     worker     DETENIDO: la pagina no procesa cargas" -ForegroundColor DarkYellow
    }

    Write-Host ""
    Write-Host "   Refresca cada 15 s. Ctrl+C para salir." -ForegroundColor DarkCyan
    Start-Sleep -Seconds 15
}
