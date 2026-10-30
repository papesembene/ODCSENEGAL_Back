#Requires -RunAsAdministrator
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskName = 'ODC-TEST-PROD-EMAIL-WORKER'
$apiTaskName = 'ODC-TEST-PROD-API'

$apiTask = Get-ScheduledTask -TaskName $apiTaskName -ErrorAction Stop
$apiAction = $apiTask.Actions | Select-Object -First 1
$runnerMatch = [regex]::Match($apiAction.Arguments, '-File\s+"([^"]+\.ps1)"')
if (-not $runnerMatch.Success) {
    throw "Impossible de trouver le lanceur de la tâche $apiTaskName."
}

$apiRunner = $runnerMatch.Groups[1].Value
$releaseRoot = Split-Path -Parent $apiRunner
if (-not (Test-Path -LiteralPath $apiRunner -PathType Leaf)) {
    throw "Lanceur de l'API introuvable: $apiRunner"
}

# The API runner may live in a release folder while its backend code lives
# elsewhere. Read the backend directory from that runner instead of guessing
# that it is a child of the release folder.
$apiRunnerText = Get-Content -LiteralPath $apiRunner -Raw
$backendMatch = [regex]::Match($apiRunnerText, "(?m)^\s*\`$backend\s*=\s*'([^']+)'\s*$")
if (-not $backendMatch.Success) {
    throw "Impossible de trouver le chemin `$backend dans le lanceur API: $apiRunner"
}
$backend = $backendMatch.Groups[1].Value
$python = Join-Path $backend '.venv\Scripts\python.exe'
$worker = Join-Path $backend 'email_worker.py'
$envFile = Join-Path $backend '.env.production'
foreach ($path in @($python, $worker, $envFile)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Fichier nécessaire introuvable: $path"
    }
}

$workerRunner = Join-Path $releaseRoot 'start-email-worker-production.ps1'
$log = Join-Path $backend 'email-worker-production.log'
$runnerText = @'
$ErrorActionPreference = 'Continue'
$backend = '__BACKEND__'
$python = '__PYTHON__'
$env:ODC_ENV_FILE = '__ENVFILE__'
Set-Location -LiteralPath $backend
while ($true) {
    "$(Get-Date -Format o) Worker email démarré" | Add-Content -LiteralPath '__LOG__'
    & $python (Join-Path $backend 'email_worker.py') *>> '__LOG__'
    "$(Get-Date -Format o) Worker arrêté (code $LASTEXITCODE), redémarrage dans 5 secondes" | Add-Content -LiteralPath '__LOG__'
    Start-Sleep -Seconds 5
}
'@
$runnerText = $runnerText.Replace('__BACKEND__', $backend).Replace('__PYTHON__', $python).
    Replace('__ENVFILE__', $envFile).Replace('__LOG__', $log)
[void][scriptblock]::Create($runnerText)
[System.IO.File]::WriteAllText($workerRunner, $runnerText, [System.Text.UTF8Encoding]::new($false))

$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action = New-ScheduledTaskAction -Execute $powershell -Argument (
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $workerRunner + '"'
)
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable -MultipleInstances IgnoreNew
$task = New-ScheduledTask -Action $action -Trigger $trigger `
    -Principal $apiTask.Principal -Settings $settings `
    -Description 'Worker email ODC: invitations, résultats et confirmations de candidature.'
Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3
$state = (Get-ScheduledTask -TaskName $taskName).State
if ($state -ne 'Running') {
    throw "La tâche $taskName ne tourne pas (état: $state). Consulter le journal: $log"
}

Write-Host "Worker email actif sur la release: $backend"
Write-Host "Tâche Windows: $taskName ($state)"
Write-Host "Journal: $log"
Write-Host 'Le worker n’envoie aucun message de test; il traite seulement la file MongoDB.'
