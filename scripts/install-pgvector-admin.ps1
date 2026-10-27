# Instala pgvector 0.8.7 en PostgreSQL 16 (Windows). Ejecutar COMO ADMINISTRADOR.
$ErrorActionPreference = "Stop"
$pg  = "C:\Program Files\PostgreSQL\16"
$src = Join-Path $PSScriptRoot "pgvector-win"

if (-not (Test-Path $src)) { throw "No se encontró $src" }

Copy-Item (Join-Path $src "lib\vector.dll") (Join-Path $pg "lib\vector.dll") -Force
Copy-Item (Join-Path $src "share\extension\vector*") (Join-Path $pg "share\extension\") -Force

Write-Host "pgvector instalado en $pg" -ForegroundColor Green
Write-Host "Ahora ejecuta:" -ForegroundColor Yellow
Write-Host "  & '$pg\bin\psql.exe' -U postgres -c `"CREATE EXTENSION IF NOT EXISTS vector`" -d heartbeat"
