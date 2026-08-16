<#
.SYNOPSIS
    Registra os tres MCPs do Career Agent no claude_desktop_config.json.

.DESCRIPTION
    Faz backup do arquivo existente e PRESERVA todas as configuracoes e MCPs
    que ja estiverem la. Apenas as tres entradas do Career Agent sao
    adicionadas/atualizadas.

.PARAMETER ConfigPath
    Caminho alternativo do claude_desktop_config.json.

.PARAMETER WhatIf
    Mostra o que seria gravado, sem gravar.
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = "$env:APPDATA\Claude\claude_desktop_config.json",
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Write-Ok   { param([string]$m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "  [AVISO] $m" -ForegroundColor Yellow }
function Write-Fail { param([string]$m) Write-Host "  [ERRO]  $m" -ForegroundColor Red }
function Write-Info { param([string]$m) Write-Host "  $m" -ForegroundColor Gray }

Write-Host ""
Write-Host "Configurando o Claude Desktop" -ForegroundColor Cyan
Write-Host "-------------------------------------------------------------" -ForegroundColor Cyan

# --------------------------------------------------------------------------
# Interpretador
# --------------------------------------------------------------------------
$venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Fail "Ambiente virtual nao encontrado: $venvPython"
    Write-Info "Rode primeiro: .\scripts\install.ps1"
    exit 1
}
Write-Ok "Interpretador: $venvPython"

foreach ($server in @('mcp-career', 'mcp-job-search', 'mcp-career-files')) {
    $path = Join-Path $ProjectRoot "$server\server.py"
    if (-not (Test-Path $path)) { Write-Fail "Servidor ausente: $path"; exit 1 }
}
Write-Ok "Os tres servidores foram encontrados."

# --------------------------------------------------------------------------
# Diretorio de configuracao
# --------------------------------------------------------------------------
$configDir = Split-Path -Parent $ConfigPath
if (-not (Test-Path $configDir)) {
    Write-Warn "Diretorio de configuracao do Claude nao existe: $configDir"
    Write-Info "O Claude Desktop parece nao estar instalado. Criando mesmo assim -"
    Write-Info "a configuracao sera lida quando voce instalar o app."
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

# --------------------------------------------------------------------------
# Backup + leitura do existente
# --------------------------------------------------------------------------
$config = $null

if (Test-Path $ConfigPath) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupPath = "$ConfigPath.backup-$stamp"
    Copy-Item $ConfigPath $backupPath -Force
    Write-Ok "Backup criado: $backupPath"

    try {
        $raw = Get-Content $ConfigPath -Raw -Encoding UTF8
        if ($raw.Trim()) {
            $config = $raw | ConvertFrom-Json
            Write-Ok "Configuracao existente lida e preservada."
        }
    } catch {
        Write-Fail "O JSON existente esta invalido: $($_.Exception.Message)"
        Write-Info "Seu arquivo original esta intacto no backup acima."
        Write-Info "Corrija o JSON ou apague o arquivo e rode este script de novo."
        exit 1
    }
} else {
    Write-Info "Nenhuma configuracao previa - um arquivo novo sera criado."
}

if (-not $config) { $config = [PSCustomObject]@{} }

# --------------------------------------------------------------------------
# Preserva MCPs de terceiros
# --------------------------------------------------------------------------
$ourServers = @('career-agent', 'job-search', 'career-files')

if (-not $config.PSObject.Properties.Name.Contains('mcpServers')) {
    $config | Add-Member -MemberType NoteProperty -Name 'mcpServers' -Value ([PSCustomObject]@{})
}

$existingNames = @($config.mcpServers.PSObject.Properties.Name)
$foreign = @($existingNames | Where-Object { $ourServers -notcontains $_ })
if ($foreign.Count -gt 0) {
    Write-Ok "MCPs de terceiros preservados: $($foreign -join ', ')"
}
$replaced = @($existingNames | Where-Object { $ourServers -contains $_ })
if ($replaced.Count -gt 0) {
    Write-Info "Entradas do Career Agent que serao atualizadas: $($replaced -join ', ')"
}

# --------------------------------------------------------------------------
# Escreve as tres entradas
# --------------------------------------------------------------------------
$entries = @{
    'career-agent' = Join-Path $ProjectRoot 'mcp-career\server.py'
    'job-search'   = Join-Path $ProjectRoot 'mcp-job-search\server.py'
    'career-files' = Join-Path $ProjectRoot 'mcp-career-files\server.py'
}

foreach ($name in $ourServers) {
    $entry = [PSCustomObject]@{
        command = $venvPython
        args    = @($entries[$name])
    }
    if ($config.mcpServers.PSObject.Properties.Name -contains $name) {
        $config.mcpServers.PSObject.Properties.Remove($name)
    }
    $config.mcpServers | Add-Member -MemberType NoteProperty -Name $name -Value $entry
    Write-Ok "MCP configurado: $name"
}

$json = $config | ConvertTo-Json -Depth 12

if ($WhatIf) {
    Write-Host ""
    Write-Host "-- Conteudo que SERIA gravado em $ConfigPath --" -ForegroundColor Yellow
    Write-Host $json
    Write-Host "-- nada foi gravado (-WhatIf) --" -ForegroundColor Yellow
    exit 0
}

# Sem BOM: o Claude Desktop e mais tolerante, mas JSON puro e o correto.
[System.IO.File]::WriteAllText($ConfigPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Ok "Gravado: $ConfigPath"

# --------------------------------------------------------------------------
# Verificacao
# --------------------------------------------------------------------------
try {
    $check = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $configured = @($check.mcpServers.PSObject.Properties.Name)
    foreach ($name in $ourServers) {
        if ($configured -contains $name) { Write-Ok "verificado: $name" }
        else { Write-Fail "nao encontrado apos gravar: $name"; exit 1 }
    }
} catch {
    Write-Fail "O arquivo gravado nao e um JSON valido: $($_.Exception.Message)"
    exit 1
}

Write-Host ""
Write-Host "Configuracao aplicada." -ForegroundColor Green
Write-Host ""
Write-Host "PARA CONCLUIR - reinicie o Claude Desktop:" -ForegroundColor Yellow
Write-Host "  1. Feche a janela do Claude Desktop." -ForegroundColor Gray
Write-Host "  2. Na bandeja do sistema (ao lado do relogio), clique com o botao" -ForegroundColor Gray
Write-Host "     direito no icone do Claude e escolha Sair/Quit." -ForegroundColor Gray
Write-Host "     Fechar so a janela NAO encerra o processo - os MCPs nao recarregam." -ForegroundColor Gray
Write-Host "  3. Abra o Claude Desktop novamente." -ForegroundColor Gray
Write-Host ""
Write-Host "Para confirmar, pergunte no chat:" -ForegroundColor White
Write-Host '  "Quais ferramentas de career voce tem?"' -ForegroundColor Gray
Write-Host ""
exit 0
