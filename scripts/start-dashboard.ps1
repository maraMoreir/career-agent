<#
.SYNOPSIS
    Inicia o dashboard local do Career Agent.

.DESCRIPTION
    Servidor FastAPI preso a 127.0.0.1 - nao aceita conexao de fora da
    maquina. Somente leitura: o dashboard mostra o catalogo e o historico,
    mas nao altera nada. As acoes que mudam estado continuam no Claude
    Desktop, onde existe a aprovacao humana.

    Ctrl+C encerra.

.PARAMETER Port
    Porta local. Padrao 8787.

.PARAMETER NoBrowser
    Nao abre o navegador automaticamente.
#>
[CmdletBinding()]
param(
    [int]$Port = 8787,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Write-Ok   { param([string]$m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Fail { param([string]$m) Write-Host "  [ERRO]  $m" -ForegroundColor Red }
function Write-Info { param([string]$m) Write-Host "  $m" -ForegroundColor Gray }

$venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Fail "Ambiente virtual nao encontrado. Rode .\scripts\install.ps1 primeiro."
    exit 1
}

& $venvPython -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Info "Instalando as dependencias do dashboard..."
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    Push-Location $ProjectRoot
    if ($uv) { & uv pip install -e ".[dashboard]" }
    else     { & $venvPython -m pip install --quiet fastapi uvicorn }
    Pop-Location
    if ($LASTEXITCODE -ne 0) { Write-Fail "Falha ao instalar fastapi/uvicorn."; exit 1 }
}

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try {
    $listener.Start(); $listener.Stop()
} catch {
    Write-Fail "A porta $Port ja esta em uso. Use -Port com outro valor."
    exit 1
}

$url = "http://127.0.0.1:$Port"

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host " Career Agent - Dashboard" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Ok "Endereco: $url"
Write-Info "Preso a 127.0.0.1 - ninguem na rede alcanca."
Write-Info "Somente leitura - nada e alterado por aqui."
Write-Info "Ctrl+C encerra."
Write-Host ""

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        Start-Sleep -Seconds 2
        Start-Process $using:url
    } | Out-Null
}

Push-Location $ProjectRoot
try {
    & $venvPython -m uvicorn dashboard.app:app --host 127.0.0.1 --port $Port --log-level warning
} finally {
    Pop-Location
}
