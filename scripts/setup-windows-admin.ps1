# Setup nativo de TaskManager en Windows. Ejecutar COMO ADMINISTRADOR.
#   powershell -ExecutionPolicy Bypass -File setup-windows-admin.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$pg   = "C:\Program Files\PostgreSQL\16"
$psql = Join-Path $pg "bin\psql.exe"
$src  = Join-Path $PSScriptRoot "pgvector-win"

function Die($msg) { Write-Host "`n[FATAL] $msg" -ForegroundColor Red; exit 1 }
function Ok($msg)  { Write-Host "   $msg" -ForegroundColor Green }

# Ejecuta psql y aborta si falla. Sin esto el script reporta exito falso.
function Invoke-Psql {
    param([string]$Db = "postgres", [string]$Sql, [switch]$Scalar)
    $out = if ($Scalar) { & $psql -U postgres -d $Db -tAc $Sql 2>&1 }
           else        { & $psql -U postgres -d $Db -c  $Sql 2>&1 }
    if ($LASTEXITCODE -ne 0) {
        Write-Host ($out | Out-String) -ForegroundColor Red
        Die "psql fallo (exit $LASTEXITCODE). SQL: $Sql"
    }
    if ($Scalar) { return ($out | Out-String).Trim() }
}

Write-Host "== 1/5  pgvector ==" -ForegroundColor Cyan
if (Test-Path $src) {
    Copy-Item (Join-Path $src "lib\vector.dll") (Join-Path $pg "lib\vector.dll") -Force
    Copy-Item (Join-Path $src "share\extension\vector*") (Join-Path $pg "share\extension\") -Force
    Ok "pgvector copiado"
} else {
    Write-Host "   WARN: no esta $src (¿ya lo instalaste?)" -ForegroundColor Yellow
}

Write-Host "== 2/5  Servicio PostgreSQL ==" -ForegroundColor Cyan
Set-Service -Name postgresql-x64-16 -StartupType Automatic
$svc = Get-Service postgresql-x64-16
if ($svc.Status -ne "Running") {
    try { Start-Service postgresql-x64-16 -ErrorAction Stop }
    catch {
        Write-Host "`n   No arranco via SCM. Diagnosticando..." -ForegroundColor Yellow
        & (Join-Path $pg "bin\pg_ctl.exe") start -D (Join-Path $pg "data") -w -t 20
        Write-Host "`n   Si pg_ctl funciono, el problema es como el SCM lanza el servicio." -ForegroundColor Yellow
        Write-Host "   Revisar: Get-EventLog -LogName Application -Source 'PostgreSQL*' -Newest 5" -ForegroundColor Yellow
        Die "El servicio postgresql-x64-16 no arranca. Ver el log de arriba."
    }
    Start-Sleep 2
    $svc = Get-Service postgresql-x64-16
}
if ($svc.Status -ne "Running") { Die "Servicio en estado '$($svc.Status)'" }
Ok "$($svc.Name): $($svc.Status)"

Write-Host "== 3/5  Verificar conexion ==" -ForegroundColor Cyan
$env:PGPASSWORD = "postgres"
# Espera activa: el servicio puede estar "Running" antes de aceptar conexiones
$ready = $false
foreach ($i in 1..15) {
    $out = & $psql -U postgres -h 127.0.0.1 -tAc "SELECT 1" 2>&1
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep 1
}
if (-not $ready) {
    Write-Host ($out | Out-String) -ForegroundColor Red
    Write-Host "   Si dice 'password authentication failed', la contrasena de postgres no es 'postgres'." -ForegroundColor Yellow
    Write-Host "   Probar:  `$env:PGPASSWORD='<tu_pass>'; .\setup-windows-admin.ps1" -ForegroundColor Yellow
    Die "No hay conexion a 127.0.0.1:5432 tras 15s"
}
Ok "conexion OK"

Write-Host "== 4/5  Rol y base ==" -ForegroundColor Cyan
$role = Invoke-Psql -Scalar "SELECT 1 FROM pg_roles WHERE rolname='hb_admin'"
if ($role -ne "1") {
    Invoke-Psql "CREATE ROLE hb_admin LOGIN PASSWORD 'dev_password_local'"
    Ok "rol hb_admin creado"
} else { Ok "rol hb_admin ya existia" }

$db = Invoke-Psql -Scalar "SELECT 1 FROM pg_database WHERE datname='heartbeat'"
if ($db -ne "1") {
    Invoke-Psql "CREATE DATABASE heartbeat OWNER hb_admin"
    Ok "base heartbeat creada"
} else { Ok "base heartbeat ya existia" }

Write-Host "== 5/5  Schema + extensiones ==" -ForegroundColor Cyan
Invoke-Psql -Db heartbeat "CREATE EXTENSION IF NOT EXISTS vector"
Invoke-Psql -Db heartbeat "CREATE EXTENSION IF NOT EXISTS pg_trgm"
Invoke-Psql -Db heartbeat "GRANT ALL ON SCHEMA public TO hb_admin"

$env:PGPASSWORD = "dev_password_local"
$schemaOk = & $psql -U hb_admin -h 127.0.0.1 -d heartbeat -v ON_ERROR_STOP=1 -f (Join-Path $root "db\schema.sql") 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ($schemaOk | Out-String) -ForegroundColor Red
    Die "db\schema.sql fallo (exit $LASTEXITCODE)"
}
Ok "schema aplicado"

# Verificacion real: contar tablas
$tables = & $psql -U hb_admin -h 127.0.0.1 -d heartbeat -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>&1
$nTables = ($tables | Out-String).Trim()
Ok "tablas en public: $nTables"
if ($nTables -match '^\d+$' -and [int]$nTables -lt 3) { Die "Solo $nTables tablas: el schema no se aplico bien" }

Write-Host "`nListo. Siguiente:" -ForegroundColor Cyan
Write-Host "  cd $root"
Write-Host "  .\.venv\Scripts\python.exe -m src.ingest.heartbeat --action graph"
Write-Host "  .\.venv\Scripts\python.exe -m src.api.server"
