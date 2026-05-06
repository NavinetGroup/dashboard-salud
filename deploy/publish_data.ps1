# ============================================================
#  Informe Regional de Salud — Publicar nueva base de datos
# ============================================================
#  Ejecutar desde la maquina del desarrollador despues de
#  correr el pipeline y generar informe_regional.duckdb.
#
#  Requiere: gh CLI autenticado (gh auth login)
# ============================================================

$RepoRoot = Split-Path $PSScriptRoot -Parent
$DuckDb   = Join-Path $RepoRoot "data\informe_regional.duckdb"
$Repo     = "NavinetGroup/dashboard-salud"
$Tag      = "data-v1"

if (-not (Test-Path $DuckDb)) {
    Write-Host "ERROR: No se encontro la base de datos en:" -ForegroundColor Red
    Write-Host "  $DuckDb" -ForegroundColor Red
    Write-Host "Ejecute el pipeline primero para generar el archivo." -ForegroundColor Yellow
    exit 1
}

$mb = "{0:N0}" -f ((Get-Item $DuckDb).Length / 1MB)
Write-Host ""
Write-Host "  Publicando base de datos ($mb MB)..." -ForegroundColor Yellow
Write-Host "  Repositorio: $Repo" -ForegroundColor Gray
Write-Host "  Release:     $Tag" -ForegroundColor Gray
Write-Host ""

gh release upload $Tag $DuckDb --repo $Repo --clobber

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n  ERROR: Fallo la subida. Verifique que 'gh auth login' este completado." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  Base de datos publicada exitosamente." -ForegroundColor Green
Write-Host "  Los equipos de usuarios se actualizaran automaticamente" -ForegroundColor Gray
Write-Host "  el dia 1 del proximo mes a las 6am." -ForegroundColor Gray
Write-Host ""
Write-Host "  Para forzar actualizacion inmediata en un equipo, ejecutar:" -ForegroundColor Gray
Write-Host "  %LOCALAPPDATA%\InformeRegional\update_data.ps1" -ForegroundColor Gray
Write-Host ""
