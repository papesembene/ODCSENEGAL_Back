#Requires -RunAsAdministrator
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'BackendService.Common.ps1')
$siteConfig='C:\inetpub\wwwroot\web.config'
$apiConfig='C:\inetpub\api\web.config'
$backend='C:\Orange Digital Center\odc-test\backend'
$serviceName='ODC-PROD-API'
$taskName='ODC-TEST-PROD-API'
$mutex=[Threading.Mutex]::new($false,'Global\ODC-Production-Deployment')
$locked=$false
$siteChanged=$false; $apiChanged=$false; $created=$false; $disabled=$false; $committed=$false
try {
    try { $locked=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked=$true }
    if (-not $locked) { throw 'Another deployment is running.' }
    foreach ($name in @('ODC-PROD-API','ODC-PROD-API-SECONDARY')) {
        if (Get-Service -Name $name -ErrorAction SilentlyContinue) {
            $previous=Get-BackendNssmContext $name
            if ($name -ne $serviceName -or $previous.Service.State -ne 'Stopped' -or $previous.Backend -ne $backend -or
                $previous.EnvFile -ne (Join-Path $backend '.env.production') -or $previous.Port -eq (Get-PublishedBackendPort $siteConfig $apiConfig)) {
                throw 'Existing API service cannot be reused for migration.'
            }
        }
    }
    $task=Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if ($task.State -ne 'Running' -or -not $task.Settings.Enabled) { throw 'Legacy API task is not running and enabled.' }
    $expectedRunner='C:\Orange Digital Center\_odc-prod-release-20261026\start-api-production.ps1'
    if (@($task.Actions).Count -ne 1 -or $task.Actions[0].Arguments -notlike ('*-File "'+$expectedRunner+'"')) { throw 'Legacy runner changed.' }
    $runner=[IO.File]::ReadAllText($expectedRunner)
    if (-not $runner.Contains("`$backend = '$backend'") -or -not $runner.Contains("`$env:PORT = '5002'")) { throw 'Unexpected legacy backend or port.' }
    $oldPort=Get-PublishedBackendPort $siteConfig $apiConfig
    if ($oldPort -ne 5002 -or -not (Test-BackendHealth $oldPort).Healthy) { throw 'Legacy API is not healthy on expected port.' }
    $legacyListeners=@(Get-BackendListenerProcess $oldPort)
    if ($legacyListeners.Count -ne 1) { throw 'Ambiguous legacy listener.' }
    $legacy=$legacyListeners[0]
    if ($legacy.Name -ine 'python.exe' -or $legacy.CommandLine -notmatch '\brun\.py\b') { throw 'Unexpected legacy process.' }
    $oldSite=[IO.File]::ReadAllText($siteConfig); $oldApi=[IO.File]::ReadAllText($apiConfig)
    $port=5003
    while ($port -le 5099 -and (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) { $port++ }
    if ($port -gt 5099) { throw 'No free API port.' }
    $oldSiteUrl="http://127.0.0.1:$oldPort/api/{R:1}"; $oldApiUrl="http://127.0.0.1:$oldPort/{R:1}"
    $newSiteUrl="http://127.0.0.1:$port/api/{R:1}"; $newApiUrl="http://127.0.0.1:$port/{R:1}"
    if (([regex]::Matches($oldSite,[regex]::Escape($oldSiteUrl))).Count -ne 1 -or ([regex]::Matches($oldApi,[regex]::Escape($oldApiUrl))).Count -ne 1) { throw 'Ambiguous IIS targets.' }
    $runtime='C:\Orange Digital Center\ops\backend-recovery'
    $backup=Join-Path $runtime ('backups\migration-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff'))
    $null=New-Item -ItemType Directory -Path $backup -Force
    Copy-Item -LiteralPath $siteConfig -Destination (Join-Path $backup 'wwwroot.web.config')
    Copy-Item -LiteralPath $apiConfig -Destination (Join-Path $backup 'api.web.config')
    Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $backup 'legacy-task.xml') -Encoding UTF8
    @{Backend=$backend;Service=$serviceName;OldPort=$oldPort;NewPort=$port;LegacyProcessId=$legacy.ProcessId;LegacyCreated=$legacy.CreationDate} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'migration.json') -Encoding UTF8
    $created=$true
    Set-BackendNssmService -ServiceName $serviceName -BackendPath $backend -Port $port -EnvFile (Join-Path $backend '.env.production')
    Start-Service -Name $serviceName -ErrorAction Stop
    $ready=$false
    for ($attempt=0;$attempt -lt 40;$attempt++) {
        if ((Test-BackendHealth $port).Healthy) { $ready=$true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Candidate API did not become healthy.' }
    $context=Get-BackendNssmContext $serviceName
    $listeners=@(Get-BackendListenerProcess $port)
    if ($listeners.Count -ne 1 -or -not (Test-OwnedNssmBackendPython $listeners[0] $context)) { throw 'Candidate service does not own listener.' }
    if ([IO.File]::ReadAllText($siteConfig) -ne $oldSite -or [IO.File]::ReadAllText($apiConfig) -ne $oldApi) { throw 'IIS changed during preparation.' }
    Set-Service -Name $serviceName -StartupType Automatic
    Set-BackendIisTextAtomic $siteConfig ($oldSite.Replace($oldSiteUrl,$newSiteUrl)); $siteChanged=$true
    Set-BackendIisTextAtomic $apiConfig ($oldApi.Replace($oldApiUrl,$newApiUrl)); $apiChanged=$true
    foreach ($url in @('https://api.orangedigitalcenter.sn/health','https://orangedigitalcenter.sn/api/health')) {
        $health=Invoke-RestMethod -Uri $url -TimeoutSec 15
        if ($health.status -ne 'healthy' -or $health.dependencies.mongodb.status -ne 'up') { throw 'Public API health check failed.' }
    }
    $code=& curl.exe -sS -o NUL -w '%{http_code}' --max-time 15 https://orangedigitalcenter.sn/
    if ($LASTEXITCODE -ne 0 -or $code -ne '200') { throw 'Public frontend check failed.' }
    $null=Get-PublishedBackendNssmContext
    & (Join-Path $PSScriptRoot 'Install-BackendServiceWatchdog.ps1')
    Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
    $disabled=$true
    $committed=$true
    # Allow requests already accepted by the old API to finish.
    Start-Sleep -Seconds 15
    $connections=@(Get-NetTCPConnection -State Established -LocalPort $oldPort -ErrorAction SilentlyContinue)
    if ($connections.Count -eq 0) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
        Start-Sleep -Seconds 2
        $remaining=@(Get-BackendListenerProcess $oldPort)
        if ($remaining.Count -eq 1 -and $remaining[0].ProcessId -eq $legacy.ProcessId -and $remaining[0].CreationDate -eq $legacy.CreationDate -and $remaining[0].ExecutablePath -eq $legacy.ExecutablePath) {
            Stop-Process -Id $legacy.ProcessId -ErrorAction Stop
        } elseif ($remaining.Count -gt 0) { Write-Warning 'Old API listener changed; left untouched.' }
    } else { Write-Warning 'Old API retained for active connections; stop legacy task after drainage.' }
    Write-Output "API migration complete; service=$serviceName; port=$port; backup=$backup"
} catch {
    $failure=$_
    if (-not $committed) {
        # Restore only our route changes, preserving any unrelated IIS edits.
        foreach ($route in @(@($siteConfig,$siteChanged,$newSiteUrl,$oldSiteUrl),@($apiConfig,$apiChanged,$newApiUrl,$oldApiUrl))) {
            if ($route[1]) {
                $text=[IO.File]::ReadAllText($route[0])
                if (([regex]::Matches($text,[regex]::Escape($route[2]))).Count -ne 1) { throw "Rollback requires review; keep both APIs. Backup: $backup. Original: $failure" }
                Set-BackendIisTextAtomic $route[0] ($text.Replace($route[2],$route[3]))
            }
        }
        $watchdog=Get-ScheduledTask -TaskName 'ODC-TEST-PROD-API-WATCHDOG' -ErrorAction SilentlyContinue
        if ($watchdog) { Disable-ScheduledTask -TaskName $watchdog.TaskName | Out-Null }
        if ($disabled) { Enable-ScheduledTask -TaskName $taskName | Out-Null }
        if ($created -and (Get-Service -Name $serviceName -ErrorAction SilentlyContinue)) {
            Stop-Service -Name $serviceName -ErrorAction SilentlyContinue
            Set-Service -Name $serviceName -StartupType Manual
        }
    }
    throw $failure
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
