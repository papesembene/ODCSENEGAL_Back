#Requires -RunAsAdministrator
[CmdletBinding()]
param([switch]$PreservePausedState)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'BackendService.Common.ps1')
$context=Get-PublishedBackendNssmContext
if (-not (Test-BackendHealth $context.Port).Healthy) { throw 'Published API is not healthy.' }
$backend=$context.Backend
$requiresHeartbeat=[IO.File]::ReadAllText((Join-Path $backend 'email_worker.py')).Contains('ODC_EMAIL_HEARTBEAT_FILE')
$runner=Join-Path (Split-Path -Parent $backend) 'start-email-worker-production.ps1'
$logs=Join-Path $backend 'ops-logs'
$null=New-Item -ItemType Directory -Path $logs -Force
$taskName='ODC-TEST-PROD-EMAIL-WORKER'
$oldTask=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$wasPaused=$PreservePausedState -and $oldTask -and $oldTask.State -ne 'Running'
$oldXml=if ($oldTask) { Export-ScheduledTask -TaskName $taskName } else { $null }
$oldRunner=if (Test-Path -LiteralPath $runner) { [IO.File]::ReadAllText($runner) } else { $null }
$snapshot=@(Get-CimInstance Win32_Process -ErrorAction Stop)
$wrappers=@($snapshot | Where-Object { $_.Name -ieq 'powershell.exe' -and $_.CommandLine -match '-File\s+"(C:\\Orange Digital Center\\[^\"]+\\start-email-worker-production\.ps1)"' })
$owned=@{}
foreach ($wrapper in $wrappers) {
    $owned[[string]$wrapper.ProcessId]=$wrapper
    $pending=[Collections.Generic.Queue[uint32]]::new()
    $pending.Enqueue([uint32]$wrapper.ProcessId)
    while ($pending.Count) {
        $parent=$pending.Dequeue()
        foreach ($child in @($snapshot | Where-Object { $_.ParentProcessId -eq $parent })) {
            if ($child.Name -ieq 'conhost.exe' -and $child.ExecutablePath -ieq (Join-Path $env:SystemRoot 'System32\conhost.exe')) { continue }
            if ($child.Name -ine 'python.exe' -or $child.CommandLine -notmatch 'email_worker\.py') { throw 'Unexpected process in production worker tree.' }
            $owned[[string]$child.ProcessId]=$child
            $pending.Enqueue([uint32]$child.ProcessId)
        }
    }
}
$unknown=@($snapshot | Where-Object { $_.Name -ieq 'python.exe' -and $_.CommandLine -match 'email_worker\.py' -and $_.CommandLine -like '*C:\Orange Digital Center\*' -and -not $owned.ContainsKey([string]$_.ProcessId) })
if ($unknown.Count) { throw 'Unrecognized email worker process; task unchanged.' }
$template=@'
$ErrorActionPreference='Stop'
$backend='__BACKEND__'
$env:ODC_ENV_FILE='__ENV__'
$env:FLASK_ENV='production'
$env:ODC_EMAIL_STOP_FILE='C:\Orange Digital Center\ops\backend-recovery\state\email-worker.stop'
$env:ODC_EMAIL_HEARTBEAT_FILE='__HEARTBEAT__'
while (-not (Test-Path -LiteralPath $env:ODC_EMAIL_STOP_FILE)) {
    $child=Start-Process -FilePath '__PYTHON__' -ArgumentList ('"'+(Join-Path $backend 'email_worker.py')+'"') -WorkingDirectory $backend -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput '__STDOUT__' -RedirectStandardError '__STDERR__'
    if (-not (Test-Path -LiteralPath $env:ODC_EMAIL_STOP_FILE)) { Start-Sleep -Seconds 5 }
}
'@
$text=$template.Replace('__BACKEND__',$backend).Replace('__ENV__',$context.EnvFile).Replace('__PYTHON__',$context.Python).Replace('__STDOUT__',(Join-Path $logs 'email-worker.stdout.log')).Replace('__STDERR__',(Join-Path $logs 'email-worker.stderr.log'))
$heartbeat=Join-Path $logs 'email-worker.heartbeat'
$text=$text.Replace('__HEARTBEAT__',$heartbeat)
$null=[scriptblock]::Create($text)
$stopFile='C:\Orange Digital Center\ops\backend-recovery\state\email-worker.stop'
$hadStopFile=Test-Path -LiteralPath $stopFile
$null=New-Item -ItemType Directory -Path (Split-Path -Parent $stopFile) -Force
$touched=$false
try {
    # New workers finish their current job before exiting; legacy workers get
    # a bounded grace period before their verified process tree is stopped.
    $null=New-Item -ItemType File -Path $stopFile -Force
    $touched=$true
    if ($oldTask) { Disable-ScheduledTask -TaskName $taskName | Out-Null }
    $deadline=[DateTime]::UtcNow.AddSeconds(60)
    while ($owned.Count -and [DateTime]::UtcNow -lt $deadline) {
        $alive=@(Get-CimInstance Win32_Process | Where-Object { $owned.ContainsKey([string]$_.ProcessId) -and $_.CreationDate -eq $owned[[string]$_.ProcessId].CreationDate })
        if (-not $alive.Count) { break }
        Start-Sleep -Seconds 2
    }
    if ($oldTask -and (Get-ScheduledTask -TaskName $taskName).State -eq 'Running') { Stop-ScheduledTask -TaskName $taskName }
    foreach ($captured in @($wrappers)+@($owned.Values | Where-Object { $_.Name -ieq 'python.exe' })) {
        $current=Get-CimInstance Win32_Process -Filter "ProcessId=$($captured.ProcessId)" -ErrorAction SilentlyContinue
        if ($current -and $current.CreationDate -eq $captured.CreationDate -and $current.ExecutablePath -eq $captured.ExecutablePath) { Stop-Process -Id $current.ProcessId -ErrorAction Stop }
    }
    if (-not $wasPaused) { Remove-Item -LiteralPath $stopFile -Force }
    [IO.File]::WriteAllText($runner,$text,[Text.UTF8Encoding]::new($false))
    $powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $action=New-ScheduledTaskAction -Execute $powershell -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$runner+'"') -WorkingDirectory $backend
    $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew
    $principal=New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
    $definition=New-ScheduledTask -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $settings -Principal $principal
    Register-ScheduledTask -TaskName $taskName -InputObject $definition -Force | Out-Null
    if ($wasPaused) {
        if (-not $oldTask.Settings.Enabled) { Disable-ScheduledTask -TaskName $taskName | Out-Null }
        Write-Output ('Worker email aligne, pause conservee: '+$backend)
        return
    }
    $started=[DateTime]::UtcNow
    Start-ScheduledTask -TaskName $taskName
    $ready=$false
    for ($attempt=0;$attempt -lt 20;$attempt++) {
        Start-Sleep -Seconds 1
        $running=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -ieq 'python.exe' -and $_.CommandLine -and $_.CommandLine.IndexOf((Join-Path $backend 'email_worker.py'),[StringComparison]::OrdinalIgnoreCase) -ge 0 })
        $heartbeatReady=if ($requiresHeartbeat) { (Test-Path -LiteralPath $heartbeat) -and (Get-Item -LiteralPath $heartbeat).LastWriteTimeUtc -ge $started } else { ([DateTime]::UtcNow-$started).TotalSeconds -ge 3 }
        if ($running.Count -gt 0 -and $heartbeatReady -and (Get-ScheduledTask -TaskName $taskName).State -eq 'Running') { $ready=$true; break }
    }
    if (-not $ready) { throw 'New email worker did not start.' }
    Write-Output ('Worker email aligne et redemarre: '+$backend)
} catch {
    if ($touched) {
        if ($hadStopFile) { $null=New-Item -ItemType File -Path $stopFile -Force }
        else { Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue }
        $currentTask=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        $newProcesses=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -ieq 'python.exe' -and $_.CommandLine -and $_.CommandLine.IndexOf((Join-Path $backend 'email_worker.py'),[StringComparison]::OrdinalIgnoreCase) -ge 0 })
        if ($currentTask -and $currentTask.State -eq 'Running') { Stop-ScheduledTask -TaskName $taskName }
        foreach ($captured in $newProcesses) {
            $current=Get-CimInstance Win32_Process -Filter "ProcessId=$($captured.ProcessId)" -ErrorAction SilentlyContinue
            if ($current -and $current.CreationDate -eq $captured.CreationDate -and $current.ExecutablePath -eq $captured.ExecutablePath) { Stop-Process -Id $current.ProcessId -ErrorAction Stop }
        }
        if ($null -ne $oldRunner) { [IO.File]::WriteAllText($runner,$oldRunner,[Text.UTF8Encoding]::new($false)) }
        if ($oldXml) {
            Register-ScheduledTask -TaskName $taskName -Xml $oldXml -Force | Out-Null
            if (-not $oldTask.Settings.Enabled) { Disable-ScheduledTask -TaskName $taskName | Out-Null }
            elseif (-not $wasPaused) { Start-ScheduledTask -TaskName $taskName }
        } elseif ($currentTask) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
    }
    throw
}
