<#
.SYNOPSIS
    Verifica que os tres servidores MCP iniciam corretamente.

.DESCRIPTION
    Em uso normal voce NAO precisa deste script: o Claude Desktop inicia os
    servidores sozinho, sob demanda, via stdio. Use aqui para diagnosticar
    quando o Claude nao enxergar as ferramentas.

.PARAMETER Server
    Inicia um servidor especifico em primeiro plano (career-agent,
    job-search ou career-files). Util para ver os logs ao vivo.
    Ctrl+C encerra. O servidor fica esperando JSON-RPC na entrada padrao -
    isso e o comportamento correto, nao um travamento.
#>
[CmdletBinding()]
param(
    [ValidateSet('career-agent', 'job-search', 'career-files')]
    [string]$Server
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

$paths = @{
    'career-agent' = Join-Path $ProjectRoot 'mcp-career\server.py'
    'job-search'   = Join-Path $ProjectRoot 'mcp-job-search\server.py'
    'career-files' = Join-Path $ProjectRoot 'mcp-career-files\server.py'
}

# --------------------------------------------------------------------------
# Modo primeiro plano
# --------------------------------------------------------------------------
if ($Server) {
    Write-Host ""
    Write-Host "Iniciando '$Server' em primeiro plano." -ForegroundColor Cyan
    Write-Info "O servidor vai aguardar mensagens JSON-RPC na entrada padrao."
    Write-Info "Ficar parado ai e o comportamento esperado. Ctrl+C para sair."
    Write-Host ""
    & $venvPython $paths[$Server]
    exit $LASTEXITCODE
}

# --------------------------------------------------------------------------
# Verificacao dos tres
# --------------------------------------------------------------------------
Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host " Career Agent - verificacao dos servidores MCP" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Info "Os servidores sao iniciados pelo Claude Desktop sob demanda."
Write-Info "Este script apenas confirma que eles carregam sem erro."
Write-Host ""

$failed = 0
foreach ($name in @('career-agent', 'job-search', 'career-files')) {
    $path = $paths[$name]

    $probe = @"
import importlib.util, sys, asyncio
spec = importlib.util.spec_from_file_location('probe', r'$path')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
tools = asyncio.run(module.mcp.list_tools())
print(len(tools))
"@
    $output = & $venvPython -c $probe
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "$name - carrega e expoe $($output.Trim()) ferramenta(s)"
    } else {
        Write-Fail "$name - falhou ao carregar"
        $failed++
    }
}

Write-Host ""
$logDir = Join-Path $ProjectRoot 'logs'
if (Test-Path $logDir) {
    Write-Info "Logs em: $logDir"
    Get-ChildItem $logDir -Filter '*.log' -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Info "  $($_.Name)  ($($_.Length) bytes)" }
}

Write-Host ""
if ($failed -gt 0) {
    Write-Fail "$failed servidor(es) com problema."
    exit 1
}

Write-Host "Os tres servidores estao prontos." -ForegroundColor Green
Write-Host ""
Write-Info "Se o Claude Desktop ainda nao mostra as ferramentas:"
Write-Info "  1. Rode .\scripts\configure-claude-desktop.ps1"
Write-Info "  2. Feche o Claude Desktop pela bandeja do sistema (Sair), nao so a janela."
Write-Info "  3. Abra de novo."
Write-Host ""
exit 0
