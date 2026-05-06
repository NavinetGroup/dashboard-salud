# ============================================================
#  Informe Regional de Salud — Actualizador de datos
# ============================================================
#  Ejecutado automaticamente el dia 1 de cada mes.
#  Tambien puede ejecutarse manualmente en cualquier momento.
# ============================================================

$DataFile = "$env:LOCALAPPDATA\InformeRegional\data\informe_regional.duckdb"
$LogFile  = "$env:LOCALAPPDATA\InformeRegional\update_log.txt"
$ApiUrl   = "https://api.github.com/repos/NavinetGroup/dashboard-salud/releases/latest"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm') - $msg" | Add-Content $LogFile
}

Log "=== Actualizacion de datos iniciada ==="

try {
    if (-not (Test-Path (Split-Path $DataFile))) {
        Log "ERROR: Directorio de datos no encontrado. Ejecute install.ps1 primero."
        exit 1
    }

    $release = Invoke-RestMethod $ApiUrl
    $asset   = $release.assets | Where-Object { $_.name -like '*.duckdb' } | Select-Object -First 1

    if (-not $asset) {
        Log "ERROR: No se encontro .duckdb en GitHub Releases."
        exit 1
    }

    Log "Descargando: $($asset.name) ($([math]::Round($asset.size/1MB)) MB)..."

    $tmp = $DataFile + ".tmp"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -UseBasicParsing
    Move-Item $tmp $DataFile -Force

    $mb = "{0:N0}" -f ((Get-Item $DataFile).Length / 1MB)
    Log "OK: Base de datos actualizada ($mb MB)."

} catch {
    Log "ERROR: $_"
    exit 1
}
