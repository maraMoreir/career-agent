<#
.SYNOPSIS
    Instala o Career Agent: verifica pre-requisitos, cria o ambiente,
    instala dependencias, cria diretorios e arquivos iniciais e valida os MCPs.

.PARAMETER ConfigureClaude
    Tambem grava a configuracao no claude_desktop_config.json (com backup).

.PARAMETER SkipValidation
    Pula a validacao funcional dos MCPs ao final (mais rapido).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
    powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -ConfigureClaude
#>
[CmdletBinding()]
param(
    [switch]$ConfigureClaude,
    [switch]$SkipValidation
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# --------------------------------------------------------------------------
# Saida
# --------------------------------------------------------------------------
function Write-Step   { param([string]$m) Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok     { param([string]$m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Warn   { param([string]$m) Write-Host "  [AVISO] $m" -ForegroundColor Yellow }
function Write-Fail   { param([string]$m) Write-Host "  [ERRO]  $m" -ForegroundColor Red }
function Write-Info   { param([string]$m) Write-Host "  $m" -ForegroundColor Gray }

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host " Career Agent - Instalacao" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Info "Projeto: $ProjectRoot"

# --------------------------------------------------------------------------
# 1. Python
# --------------------------------------------------------------------------
Write-Step "1/7 Verificando Python"

$pythonCmd = $null
foreach ($candidate in @('python', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $pythonCmd = $cmd.Source; break }
}
if (-not $pythonCmd) {
    Write-Fail "Python nao encontrado no PATH."
    Write-Info "Instale em https://www.python.org/downloads/ (marque 'Add to PATH')."
    exit 1
}

$pythonVersion = (& $pythonCmd --version) 2>&1 | Select-Object -First 1
Write-Ok "$pythonVersion  ($pythonCmd)"

$versionOk = & $pythonCmd -c "import sys; print(1 if sys.version_info >= (3,11) else 0)"
if ($versionOk.Trim() -ne '1') {
    Write-Fail "Python 3.11 ou superior e necessario."
    exit 1
}

# --------------------------------------------------------------------------
# 2. uv
# --------------------------------------------------------------------------
Write-Step "2/7 Verificando uv"

function Resolve-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # uv instalado via pip nao entra no PATH automaticamente.
    try {
        $viaPip = & $script:pythonCmd -c "import uv; print(uv.find_uv_bin())" 2>$null
        if ($LASTEXITCODE -eq 0 -and $viaPip -and (Test-Path $viaPip.Trim())) {
            return $viaPip.Trim()
        }
    } catch { }
    foreach ($guess in @(
        "$env:USERPROFILE\.local\bin\uv.exe",
        "$env:LOCALAPPDATA\Programs\uv\uv.exe"
    )) {
        if (Test-Path $guess) { return $guess }
    }
    return $null
}

$script:pythonCmd = $pythonCmd
$uvPath = Resolve-Uv

if (-not $uvPath) {
    Write-Warn "uv nao encontrado. Instalando via pip (fonte: PyPI)..."
    & $pythonCmd -m pip install --quiet --upgrade uv
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Falha ao instalar uv."
        Write-Info "Alternativa oficial: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    }
    $uvPath = Resolve-Uv
}

if (-not $uvPath) {
    Write-Fail "uv instalado, mas nao foi possivel localizar o executavel."
    exit 1
}
Write-Ok "uv: $((& $uvPath --version) 2>&1 | Select-Object -First 1)"
Write-Info "Caminho: $uvPath"

# --------------------------------------------------------------------------
# 3. Git (opcional)
# --------------------------------------------------------------------------
Write-Step "3/7 Verificando Git (opcional)"

$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    Write-Ok "$((& git --version) 2>&1 | Select-Object -First 1)"
    if (-not (Test-Path (Join-Path $ProjectRoot '.git'))) {
        Write-Info "Repositorio ainda nao inicializado. Para versionar:"
        Write-Info "  cd $ProjectRoot; git init; git add .; git commit -m 'Career Agent v1'"
    } else {
        Write-Ok "Repositorio Git ja inicializado."
    }
} else {
    Write-Warn "Git nao encontrado. O projeto funciona sem ele (sem versionamento)."
}

# --------------------------------------------------------------------------
# 4. Diretorios e arquivos iniciais
# --------------------------------------------------------------------------
Write-Step "4/7 Criando diretorios e arquivos iniciais"

$directories = @(
    'data', 'data\profile', 'data\resumes', 'data\applications', 'logs'
)
foreach ($relative in $directories) {
    $full = Join-Path $ProjectRoot $relative
    if (-not (Test-Path $full)) {
        New-Item -ItemType Directory -Path $full -Force | Out-Null
        Write-Ok "criado: $relative"
    } else {
        Write-Info "ja existe: $relative"
    }
}

$envPath = Join-Path $ProjectRoot '.env'
$envExample = Join-Path $ProjectRoot '.env.example'
if (-not (Test-Path $envPath)) {
    Copy-Item $envExample $envPath
    Write-Ok "criado: .env (a partir de .env.example)"
} else {
    Write-Info "ja existe: .env (preservado)"
}

$historyPath = Join-Path $ProjectRoot 'data\applications\applications.json'
if (-not (Test-Path $historyPath)) {
    $seed = @{
        _comment     = 'ARQUIVO GERADO AUTOMATICAMENTE. Fonte de verdade: applications.db (SQLite).'
        generated_at = ''
        count        = 0
        applications = @()
    } | ConvertTo-Json -Depth 5
    $seed | Out-File -FilePath $historyPath -Encoding utf8
    Write-Ok "criado: data\applications\applications.json"
}

foreach ($required in @(
    'data\profile\profile.md',
    'data\profile\skills.md',
    'data\profile\preferences.md',
    'data\resumes\curriculo-principal.md'
)) {
    if (Test-Path (Join-Path $ProjectRoot $required)) {
        Write-Ok "presente: $required"
    } else {
        Write-Warn "AUSENTE: $required - o agente nao conseguira ler seu perfil."
    }
}

# --------------------------------------------------------------------------
# 5. Ambiente virtual e dependencias
# --------------------------------------------------------------------------
Write-Step "5/7 Criando ambiente virtual e instalando dependencias"

Push-Location $ProjectRoot
try {
    $venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        & $uvPath venv
        if ($LASTEXITCODE -ne 0) { throw "falha ao criar o ambiente virtual" }
        Write-Ok "ambiente virtual criado em .venv"
    } else {
        Write-Info ".venv ja existe (reutilizando)"
    }

    Write-Info "Instalando dependencias (pode demorar na primeira vez)..."
    & $uvPath pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { throw "falha ao instalar dependencias" }
    Write-Ok "dependencias instaladas"
} catch {
    Write-Fail $_.Exception.Message
    Pop-Location
    exit 1
}
Pop-Location

# --------------------------------------------------------------------------
# 6. Validacao dos MCPs
# --------------------------------------------------------------------------
Write-Step "6/7 Validando os servidores MCP"

$venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Fail "python do ambiente virtual nao encontrado: $venvPython"
    exit 1
}

foreach ($server in @('mcp-career', 'mcp-job-search', 'mcp-career-files')) {
    $serverPath = Join-Path $ProjectRoot "$server\server.py"
    & $venvPython -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" $serverPath
    if ($LASTEXITCODE -eq 0) { Write-Ok "$server\server.py - sintaxe valida" }
    else { Write-Fail "$server\server.py - erro de sintaxe"; exit 1 }
}

if ($SkipValidation) {
    Write-Info "Validacao funcional pulada (-SkipValidation)."
} else {
    & $venvPython (Join-Path $ProjectRoot 'scripts\validate_mcp.py')
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "A validacao funcional falhou. Veja a saida acima."
        exit 1
    }
    Write-Ok "validacao funcional dos 3 MCPs concluida"
}

# --------------------------------------------------------------------------
# 7. Claude Desktop
# --------------------------------------------------------------------------
Write-Step "7/7 Configuracao do Claude Desktop"

if ($ConfigureClaude) {
    & (Join-Path $PSScriptRoot 'configure-claude-desktop.ps1')
    if ($LASTEXITCODE -ne 0) { Write-Warn "a configuracao do Claude Desktop falhou." }
} else {
    Write-Info "Nao aplicada (use -ConfigureClaude para aplicar automaticamente)."
    Write-Info "Ou rode: powershell -ExecutionPolicy Bypass -File .\scripts\configure-claude-desktop.ps1"
}

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "==============================================================" -ForegroundColor Green
Write-Host " Instalacao concluida" -ForegroundColor Green
Write-Host "==============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Proximos passos:" -ForegroundColor White
Write-Host "  1. Preencha os campos [PREENCHER] em:" -ForegroundColor Gray
Write-Host "       data\profile\profile.md" -ForegroundColor Gray
Write-Host "       data\profile\preferences.md   (salario minimo / alvo)" -ForegroundColor Gray
Write-Host "       data\resumes\curriculo-principal.md   (suas experiencias)" -ForegroundColor Gray
if (-not $ConfigureClaude) {
    Write-Host "  2. Configure o Claude Desktop:" -ForegroundColor Gray
    Write-Host "       .\scripts\configure-claude-desktop.ps1" -ForegroundColor Gray
    Write-Host "  3. Feche o Claude Desktop COMPLETAMENTE (inclusive o icone na" -ForegroundColor Gray
    Write-Host "     bandeja do sistema) e abra de novo." -ForegroundColor Gray
} else {
    Write-Host "  2. Feche o Claude Desktop COMPLETAMENTE (inclusive o icone na" -ForegroundColor Gray
    Write-Host "     bandeja do sistema) e abra de novo." -ForegroundColor Gray
}
Write-Host ""
Write-Host "Depois, no Claude Desktop, tente:" -ForegroundColor White
Write-Host '  "Procure vagas Backend .NET compativeis com meu perfil."' -ForegroundColor Gray
Write-Host ""
exit 0
