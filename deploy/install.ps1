# ============================================================
#  Informe Regional de Salud — Instalador
# ============================================================
#  Ejecutar en PowerShell con:
#    powershell -ExecutionPolicy Bypass -File install.ps1
#  O descargar, hacer clic derecho -> "Ejecutar con PowerShell"
# ============================================================

$ErrorActionPreference = 'Stop'

$InstallDir  = "$env:LOCALAPPDATA\InformeRegional"
$AppDir      = "$InstallDir\app"
$VenvDir     = "$AppDir\.venv"
$DataDir     = "$InstallDir\data"
$DataFile    = "$DataDir\informe_regional.duckdb"
$LauncherBat = "$InstallDir\Iniciar_Dashboard.bat"
$UpdatePs1   = "$InstallDir\update_data.ps1"
$LogFile     = "$InstallDir\install_log.txt"

$RepoZipUrl = "https://github.com/NavinetGroup/dashboard-salud/archive/refs/heads/main.zip"
$DataApiUrl = "https://api.github.com/repos/NavinetGroup/dashboard-salud/releases/latest"

# ── Helpers ──────────────────────────────────────────────────
function Write-Step($n, $msg) {
    Write-Host ""
    Write-Host "  [$n] $msg" -ForegroundColor Yellow
}
function Write-OK($msg)   { Write-Host "      OK  $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host "      ... $msg" -ForegroundColor Gray }
function Fail($msg) {
    Write-Host "`n  ERROR: $msg" -ForegroundColor Red
    Write-Host "  Revise $LogFile para mas detalles." -ForegroundColor Red
    exit 1
}
function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm') - $msg" | Add-Content $LogFile
}

# ── Inicio ───────────────────────────────────────────────────
Clear-Host
Write-Host ""
Write-Host "  ================================================" -ForegroundColor Cyan
Write-Host "    Informe Regional de Salud — Instalador" -ForegroundColor Cyan
Write-Host "  ================================================" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Log "=== Instalacion iniciada ==="

# ── 1. Python ─────────────────────────────────────────────────
Write-Step "1/6" "Verificando Python 3.12+..."

$python = $null
foreach ($cmd in @('python', 'python3', 'py -3.12', 'py')) {
    try {
        $ver = & $cmd.Split()[0] $cmd.Split()[1..99] --version 2>&1
        if ($ver -match 'Python (\d+)\.(\d+)') {
            if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 12) {
                $python = $cmd.Split()[0]
                if ($cmd -like 'py*') { $python = 'py'; $pyArgs = @('-3') } else { $pyArgs = @() }
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Info "Python 3.12+ no encontrado. Instalando via winget..."
    try {
        winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
        $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH','Machine') + ';' +
                    [System.Environment]::GetEnvironmentVariable('PATH','User')
        $python = 'python'; $pyArgs = @()
    } catch {
        Fail "No se pudo instalar Python automaticamente.`n  Descargue Python 3.12 desde https://www.python.org/downloads/`n  Asegurese de marcar 'Add Python to PATH'. Luego vuelva a ejecutar este script."
    }
}

$pyVer = & $python @pyArgs --version 2>&1
Write-OK $pyVer
Log "Python: $pyVer"

# ── 2. Descargar codigo ───────────────────────────────────────
Write-Step "2/6" "Descargando codigo de la aplicacion..."
Write-Info "Desde: $RepoZipUrl"

$zipPath = "$InstallDir\repo.zip"
try {
    if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
    Invoke-WebRequest -Uri $RepoZipUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $InstallDir -Force
    $extracted = Get-ChildItem $InstallDir -Directory |
                 Where-Object { $_.Name -like "dashboard-salud-*" } |
                 Select-Object -First 1 -ExpandProperty FullName
    if (-not $extracted) { Fail "No se encontro el directorio extraido del ZIP." }
    Move-Item $extracted $AppDir -Force
    Remove-Item $zipPath -Force
} catch { Fail "Error al descargar el codigo: $_" }

Write-OK "Codigo descargado en $AppDir"
Log "Codigo descargado."

# ── 3. Entorno virtual ────────────────────────────────────────
Write-Step "3/6" "Creando entorno virtual e instalando dependencias..."
Write-Info "Esto puede tardar 1-2 minutos..."

try {
    & $python @pyArgs -m venv $VenvDir
    $pip = "$VenvDir\Scripts\pip.exe"
    & $pip install --quiet --upgrade pip
    & $pip install --quiet -r "$AppDir\requirements.txt"
} catch { Fail "Error al instalar dependencias: $_" }

Write-OK "Dependencias instaladas."
Log "Dependencias instaladas."

# ── 4. Base de datos ──────────────────────────────────────────
Write-Step "4/6" "Descargando base de datos (~208 MB)..."
Write-Info "Esto puede tardar varios minutos segun la velocidad de su conexion..."

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

if (Test-Path $DataFile) {
    Write-OK "Base de datos existente conservada (omitiendo descarga)."
    Write-Info "Para forzar actualizacion ejecute: $UpdatePs1"
    Log "Base de datos existente conservada."
} else {
    try {
        $release = Invoke-RestMethod $DataApiUrl
        $asset = $release.assets | Where-Object { $_.name -like '*.duckdb' } | Select-Object -First 1
        if (-not $asset) { Fail "No se encontro el archivo .duckdb en GitHub Releases." }

        Write-Info "Descargando: $($asset.name)"
        $tmp = $DataFile + ".tmp"
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -UseBasicParsing
        Move-Item $tmp $DataFile -Force

        $mb = "{0:N0}" -f ((Get-Item $DataFile).Length / 1MB)
        Write-OK "Base de datos descargada ($mb MB)."
        Log "Base de datos descargada: $($asset.name) ($mb MB)."
    } catch { Fail "Error al descargar la base de datos: $_" }
}

# ── 5. Script de actualizacion mensual ───────────────────────
Write-Step "5/6" "Configurando actualizacion mensual automatica..."

Copy-Item "$AppDir\deploy\update_data.ps1" $UpdatePs1 -Force

$taskName = "InformeRegional_UpdateData"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action   = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$UpdatePs1`""
$trigger  = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At "06:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-OK "Tarea programada: dia 1 de cada mes a las 6:00 AM."
Log "Tarea programada registrada."

# ── 6. Acceso directo en el escritorio ───────────────────────
Write-Step "6/6" "Creando acceso directo en el escritorio..."

$streamlit = "$VenvDir\Scripts\streamlit.exe"

@"
@echo off
title Informe Regional de Salud
echo.
echo  Iniciando Informe Regional de Salud...
echo  No cierre esta ventana. Minimicela si lo desea.
echo.
set INFORME_DB_PATH=$DataFile
timeout /t 2 /nobreak > nul
start "" "http://localhost:8501"
"$streamlit" run "$AppDir\dashboard\app.py"
"@ | Set-Content $LauncherBat -Encoding ASCII

$WshShell = New-Object -ComObject WScript.Shell
$lnk = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\Informe Regional Salud.lnk")
$lnk.TargetPath       = $LauncherBat
$lnk.WorkingDirectory = $AppDir
$lnk.IconLocation     = "shell32.dll,14"
$lnk.Description      = "Abre el Informe Regional de Salud en el navegador"
$lnk.Save()

Write-OK "Acceso directo creado en el escritorio."
Log "Acceso directo creado."

# ── Resumen ───────────────────────────────────────────────────
Log "=== Instalacion completada exitosamente ==="
Write-Host ""
Write-Host "  ================================================" -ForegroundColor Cyan
Write-Host "    INSTALACION COMPLETA" -ForegroundColor Cyan
Write-Host "  ================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Para abrir la app:" -ForegroundColor White
Write-Host "    Doble clic en 'Informe Regional Salud' en el escritorio" -ForegroundColor White
Write-Host ""
Write-Host "  Datos:          $DataFile" -ForegroundColor Gray
Write-Host "  Actualizacion:  Automatica el dia 1 de cada mes a las 6am" -ForegroundColor Gray
Write-Host "  Log:            $LogFile" -ForegroundColor Gray
Write-Host ""
