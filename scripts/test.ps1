<#
.SYNOPSIS
    Roda a suite de testes e a validacao funcional dos MCPs.

.DESCRIPTION
    Duas camadas:
      1. pytest  - logica de dominio (score, duplicidade, seguranca, sandbox,
                   perfil, curriculo, candidatura, historico).
      2. validate_mcp.py - fluxo real atravessando a camada MCP:
                   perfil -> vaga -> score -> candidatura -> aprovacao -> historico.

    A validacao copia seu perfil real para uma raiz temporaria. Seu historico
    de candidaturas NAO e alterado.

.PARAMETER UnitOnly
    Roda apenas o pytest.

.PARAMETER McpOnly
    Roda apenas a validacao funcional dos MCPs.

.PARAMETER Verbose
    Saida detalhada do pytest.
#>
[CmdletBinding()]
param(
    [switch]$UnitOnly,
    [switch]$McpOnly
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Write-Step { param([string]$m) Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Fail { param([string]$m) Write-Host "  [ERRO]  $m" -ForegroundColor Red }
function Write-Info { param([string]$m) Write-Host "  $m" -ForegroundColor Gray }

$venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Fail "Ambiente virtual nao encontrado. Rode .\scripts\install.ps1 primeiro."
    exit 1
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host " Career Agent - Testes" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan

$failures = 0

# --------------------------------------------------------------------------
# 1. pytest
# --------------------------------------------------------------------------
if (-not $McpOnly) {
    Write-Step "1/2 Testes automatizados (pytest)"
    Write-Info "Cobrindo: score, classificacao, duplicidade, validacao de vaga,"
    Write-Info "historico, regras de seguranca e geracao de candidatura."
    Write-Host ""

    Push-Location $ProjectRoot
    $pytestArgs = @('-m', 'pytest', 'tests')
    if ($VerbosePreference -eq 'Continue') { $pytestArgs += '-v' } else { $pytestArgs += '-q' }

    & $venvPython @pytestArgs
    $pytestExit = $LASTEXITCODE
    Pop-Location

    Write-Host ""
    if ($pytestExit -eq 0) { Write-Ok "pytest: todos os testes passaram" }
    else { Write-Fail "pytest: falhou (codigo $pytestExit)"; $failures++ }
}

# --------------------------------------------------------------------------
# 2. Validacao funcional dos MCPs
# --------------------------------------------------------------------------
if (-not $UnitOnly) {
    Write-Step "2/2 Validacao funcional dos MCPs"
    Write-Info "Importacao, execucao dos 3 MCPs, leitura de perfil, calculo de"
    Write-Info "score, registro de candidatura, historico e duplicidade."
    Write-Host ""

    & $venvPython (Join-Path $ProjectRoot 'scripts\validate_mcp.py')
    $mcpExit = $LASTEXITCODE

    if ($mcpExit -eq 0) { Write-Ok "validacao funcional: tudo passou" }
    else { Write-Fail "validacao funcional: falhou (codigo $mcpExit)"; $failures++ }
}

# --------------------------------------------------------------------------
# 3. Sanidade da configuracao do Claude Desktop (informativo)
# --------------------------------------------------------------------------
Write-Step "Configuracao do Claude Desktop"

$configPath = "$env:APPDATA\Claude\claude_desktop_config.json"
if (-not (Test-Path $configPath)) {
    Write-Info "Ainda nao configurado. Rode .\scripts\configure-claude-desktop.ps1"
} else {
    try {
        $config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $names = @($config.mcpServers.PSObject.Properties.Name)
        foreach ($expected in @('career-agent', 'job-search', 'career-files')) {
            if ($names -contains $expected) {
                $entry = $config.mcpServers.$expected
                $script = $entry.args[0]
                if ((Test-Path $entry.command) -and (Test-Path $script)) {
                    Write-Ok "$expected - configurado, caminhos existem"
                } else {
                    Write-Fail "$expected - caminho invalido no config"
                    $failures++
                }
            } else {
                Write-Info "$expected - ausente do claude_desktop_config.json"
            }
        }
    } catch {
        Write-Fail "claude_desktop_config.json invalido: $($_.Exception.Message)"
        $failures++
    }
}

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "==============================================================" -ForegroundColor $(if ($failures -eq 0) { 'Green' } else { 'Red' })
if ($failures -eq 0) {
    Write-Host " TUDO PASSOU" -ForegroundColor Green
} else {
    Write-Host " $failures ETAPA(S) COM FALHA" -ForegroundColor Red
}
Write-Host "==============================================================" -ForegroundColor $(if ($failures -eq 0) { 'Green' } else { 'Red' })
Write-Host ""

exit $failures
