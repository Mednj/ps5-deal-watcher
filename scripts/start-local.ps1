$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed. Make sure Docker Desktop is running.' }
Write-Output 'Dashboard: http://127.0.0.1:8765'
