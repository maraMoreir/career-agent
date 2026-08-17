<#
.SYNOPSIS
    Agenda a busca automatica de vagas no Agendador de Tarefas do Windows.

.DESCRIPTION
    Nao ha processo residente. O Agendador do Windows ja resolve retomada
    apos reboot, execucao com a maquina bloqueada e registro de falhas -
    reimplementar isso num daemon proprio seria pior e mais fragil.

.PARAMETER IntervalHours
    Intervalo entre execucoes, em horas. Padrao 2.

.PARAMETER Keywords
    Termos de busca.

.PARAMETER MinScore
    Score minimo para considerar a vaga relevante.

.PARAMETER Remove
    Remove o agendamento.

.PARAMETER Status
    Mostra o agendamento atual e a ultima execucao.

.EXAMPLE
    .\scripts\schedule.ps1
    .\scripts\schedule.ps1 -IntervalHours 4 -MinScore 80
    .\scripts\schedule.ps1 -Status
    .\scripts\schedule.ps1 -Remove
#>
[CmdletBinding()]
param(
    [int]$IntervalHours = 2,
    [string]$Keywords = "backend .net c#",
    [double]$MinScore = 75,
    [switch]$Remove,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TaskName = 'CareerAgent-BuscaDeVagas'

function Write-Ok   { param([string]$m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Fail { param([string]$m) Write-Host "  [ERRO]  $m" -ForegroundColor Red }
function Write-Info { param([string]$m) Write-Host "  $m" -ForegroundColor Gray }

Write-Host ""
Write-Host "Agendamento da busca de vagas" -ForegroundColor Cyan
Write-Host "-------------------------------------------------------------" -ForegroundColor Cyan

# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------
if ($Status) {
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Ok "Tarefa registrada: $TaskName"
        Write-Info "Estado.............: $($task.State)"
        Write-Info "Ultima execucao....: $($info.LastRunTime)"
        Write-Info "Ultimo resultado...: $($info.LastTaskResult) (0 = sucesso)"
        Write-Info "Proxima execucao...: $($info.NextRunTime)"
    } catch {
        Write-Info "Nenhum agendamento registrado. Rode .\scripts\schedule.ps1 para criar."
    }

    $logPath = Join-Path $ProjectRoot 'logs\busca-agendada.log'
    if (Test-Path $logPath) {
        Write-Host ""
        Write-Info "Ultimas linhas de logs\busca-agendada.log:"
        Get-Content $logPath -Tail 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    exit 0
}

# --------------------------------------------------------------------------
# Remocao
# --------------------------------------------------------------------------
if ($Remove) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Ok "Agendamento removido."
    } catch {
        Write-Info "Nao havia agendamento para remover."
    }
    exit 0
}

# --------------------------------------------------------------------------
# Criacao
# --------------------------------------------------------------------------
$venvPython = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $venvPython)) {
    # pythonw evita piscar janela de console a cada execucao.
    $venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path $venvPython)) {
    Write-Fail "Ambiente virtual nao encontrado. Rode .\scripts\install.ps1 primeiro."
    exit 1
}

if ($IntervalHours -lt 1 -or $IntervalHours -gt 24) {
    Write-Fail "IntervalHours precisa estar entre 1 e 24."
    exit 1
}

$runner = Join-Path $ProjectRoot 'scripts\run_search.py'
$logFile = Join-Path $ProjectRoot 'logs\busca-agendada.log'
New-Item -ItemType Directory -Path (Split-Path $logFile) -Force | Out-Null

# cmd /c redireciona a saida para o log, preservando o historico.
$arguments = "/c `"`"$venvPython`" `"$runner`" --keywords `"$Keywords`" --min-score $MinScore --quiet >> `"$logFile`" 2>&1`""

$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $arguments -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
} catch { }

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Career Agent - coleta vagas a cada $IntervalHours h e registra no catalogo." `
        -ErrorAction Stop | Out-Null
} catch {
    Write-Fail "Falha ao registrar a tarefa: $($_.Exception.Message)"
    Write-Info "Se o erro for de permissao, abra o PowerShell como Administrador."
    exit 1
}

Write-Ok "Agendamento criado: $TaskName"
Write-Info "Intervalo....: a cada $IntervalHours hora(s)"
Write-Info "Termos.......: $Keywords"
Write-Info "Score minimo.: $MinScore"
Write-Info "Log..........: $logFile"
Write-Info "Primeira execucao em ~2 minutos."
Write-Host ""
Write-Info "Ver status:  .\scripts\schedule.ps1 -Status"
Write-Info "Remover:     .\scripts\schedule.ps1 -Remove"
Write-Host ""
Write-Info "As vagas coletadas ficam disponiveis no Claude Desktop via"
Write-Info "`list_matching_jobs` e no dashboard (.\scripts\start-dashboard.ps1)."
Write-Host ""
exit 0
