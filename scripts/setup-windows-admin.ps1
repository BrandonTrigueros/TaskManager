# Setup nativo de TaskManager en Windows. Ejecutar COMO ADMINISTRADOR.
#   powershell -ExecutionPolicy Bypass -File setup-windows-admin.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$pg   = "C:\Program Files\PostgreSQL\16"
$psql = Join-Path $pg "bin\psql.exe"
$src  = Join-Path $PSScriptRoot "pgvector-win"

Write-Host "== 1/4  pgvector ==" -ForegroundColor Cyan
if (Test-Path $src) {
    Copy-Item (Join-Path $src "lib\vector.dll") (Join-Path $pg "lib\vector.dll") -Force
    Copy-Item (Join-Path $src "share\extension\vector*") (Join-Path $pg "share\extension\") -Force
    Write-Host "   pgvector copiado" -ForegroundColor Green
} else {
    Write-Host "   WARN: no está $src (¿ya lo instalaste?)" -ForegroundColor Yellow
}

Write-Host "== 2/4  Servicio PostgreSQL ==" -ForegroundColor Cyan
Set-Service -Name postgresql-x64-16 -StartupType Automatic
Start-Service postgresql-x64-16 -ErrorAction SilentlyContinue
Start-Sleep 3
$svc = Get-Service postgresql-x64-16
Write-Host "   $($svc.Name): $($svc.Status)" -ForegroundColor Green

Write-Host "== 3/4  Rol y base ==" -ForegroundColor Cyan
$env:PGPASSWORD = "postgres"
$role = & $psql -U postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='hb_admin'"
if (-not $role) {
    & $psql -U postgres -c "CREATE ROLE hb_admin LOGIN PASSWORD 'dev_password_local'"
    Write-Host "   rol hb_admin creado" -ForegroundColor Green
}
$db = & $psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='heartbeat'"
if (-not $db) {
    & $psql -U postgres -c "CREATE DATABASE heartbeat OWNER hb_admin"
    Write-Host "   base heartbeat creada" -ForegroundColor Green
}

Write-Host "== 4/4  Schema + extensiones ==" -ForegroundColor Cyan
& $psql -U postgres -d heartbeat -c "CREATE EXTENSION IF NOT EXISTS vector"
& $psql -U postgres -d heartbeat -c "CREATE EXTENSION IF NOT EXISTS pg_trgm"
& $psql -U postgres -d heartbeat -c "GRANT ALL ON SCHEMA public TO hb_admin"
$env:PGPASSWORD = "dev_password_local"
Get-Content (Join-Path $root "db\schema.sql") -Raw | & $psql -U hb_admin -d heartbeat -v ON_ERROR_STOP=1
Write-Host "   schema aplicado" -ForegroundColor Green

Write-Host ""
Write-Host "Listo. Siguiente:" -ForegroundColor Cyan
Write-Host "  cd $root"
Write-Host "  .\.venv\Scripts\python.exe -m src.ingest.heartbeat --action graph"
Write-Host "  .\.venv\Scripts\python.exe -m src.api.server"
