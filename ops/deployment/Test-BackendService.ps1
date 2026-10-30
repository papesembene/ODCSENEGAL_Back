[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$SiteConfig = 'C:\inetpub\wwwroot\web.config',
    [string]$ApiConfig = 'C:\inetpub\api\web.config',
    [string]$StateDirectory = 'C:\Orange Digital Center\ops\backend-recovery\state',
    [ValidateRange(2, 10)][int]$FailureThreshold = 3
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'BackendService.Common.ps1')
$mutex = [Threading.Mutex]::new($false, 'Global\ODC-Backend-Service-Watchdog')
$locked = $false
$stateFile = Join-Path $StateDirectory 'health.json'
$state = @{ Target = ''; Failures = 0; LastHealthy = $false; LastRecoveryUtc = '' }

function Save-BackendServiceHealth {
    if (-not $WhatIfPreference) {
        $null = New-Item -ItemType Directory -Path $StateDirectory -Force
        $temporary = $stateFile + '.tmp'
        $state | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $stateFile -Force
    }
}

try {
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { exit 0 }
    $context = Get-PublishedBackendNssmContext -SiteConfig $SiteConfig -ApiConfig $ApiConfig
    if ($context.Name -notin @('ODC-PROD-API', 'ODC-PROD-API-SECONDARY')) {
        throw 'Service API inattendu; controle annule.'
    }
    if (Test-Path -LiteralPath $stateFile -PathType Leaf) {
        try {
            $saved = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
            foreach ($key in @('Target', 'Failures', 'LastHealthy', 'LastRecoveryUtc')) {
                if ($saved.PSObject.Properties[$key]) { $state[$key] = $saved.$key }
            }
        } catch {
            Write-BackendRecoveryLog $StateDirectory 'watchdog.log' 'state_unreadable; resetting failure counter'
        }
    }
    $target = "$($context.Name)|$($context.Port)|$($context.Backend)|$($context.EnvFile)"
    if ($state.Target -ne $target) {
        $state = @{ Target = $target; Failures = 0; LastHealthy = $false; LastRecoveryUtc = '' }
    }
    $health = Test-BackendHealth -Port $context.Port -TimeoutSeconds 5
    $listeners = @(Get-BackendListenerProcess -Port $context.Port)
    $unknown = @($listeners | Where-Object { -not (Test-OwnedNssmBackendPython -Process $_ -Context $context) })
    $ownedHealthy = ($health.Healthy -and $listeners.Count -eq 1 -and $unknown.Count -eq 0 -and $context.Service.State -eq 'Running')
    if ($ownedHealthy) {
        if (-not $state.LastHealthy) {
            Write-BackendRecoveryLog $StateDirectory 'watchdog.log' "healthy service=$($context.Name) port=$($context.Port)"
        }
        $state.Failures = 0
        $state.LastHealthy = $true
    } elseif ($unknown.Count -gt 0 -or $listeners.Count -gt 1) {
        $state.Failures = 0
        $state.LastHealthy = $false
        Write-BackendRecoveryLog $StateDirectory 'watchdog.log' "unrecognized_listener service=$($context.Name) port=$($context.Port); restart refused"
    } elseif ($health.Responsive -and -not $health.DependencyHealthy) {
        # A MongoDB incident cannot be repaired by restarting a responsive API.
        $state.Failures = 0
        $state.LastHealthy = $false
        Write-BackendRecoveryLog $StateDirectory 'watchdog.log' "dependency_unhealthy service=$($context.Name) port=$($context.Port); no restart; detail=$($health.Detail)"
    } elseif ($health.Responsive) {
        # Preserve a responsive application even when service ownership needs review.
        $state.Failures = 0
        $state.LastHealthy = $false
        Write-BackendRecoveryLog $StateDirectory 'watchdog.log' "responsive_service_inconsistent service=$($context.Name) port=$($context.Port) service_state=$($context.Service.State); no restart"
    } else {
        $state.Failures = [int]$state.Failures + 1
        $state.LastHealthy = $false
        Write-BackendRecoveryLog $StateDirectory 'watchdog.log' "unresponsive service=$($context.Name) port=$($context.Port) failures=$($state.Failures) service_state=$($context.Service.State) detail=$($health.Detail)"
        $wrapper = $null
        if ($context.Service.ProcessId -gt 0) {
            $wrapper = Get-CimInstance Win32_Process -Filter "ProcessId=$($context.Service.ProcessId)" -ErrorAction SilentlyContinue
        }
        $starting = ($wrapper -and ([DateTime]::UtcNow - $wrapper.CreationDate.ToUniversalTime()).TotalSeconds -lt 60)
        if (@($listeners | Where-Object { ([DateTime]::UtcNow - $_.CreationDate.ToUniversalTime()).TotalSeconds -lt 60 }).Count -gt 0) {
            $starting = $true
        }
        $cooldown = ($state.LastRecoveryUtc -and ([DateTime]::UtcNow - [DateTime]::Parse($state.LastRecoveryUtc).ToUniversalTime()).TotalSeconds -lt 120)
        $stopped = ($context.Service.State -eq 'Stopped' -and $listeners.Count -eq 0)
        if (-not $starting -and -not $cooldown -and ($stopped -or $state.Failures -ge $FailureThreshold)) {
            # Revalidate IIS and process ownership immediately before touching a service.
            $current = Get-PublishedBackendNssmContext -SiteConfig $SiteConfig -ApiConfig $ApiConfig
            $currentTarget = "$($current.Name)|$($current.Port)|$($current.Backend)|$($current.EnvFile)"
            if ($currentTarget -ne $target) {
                Write-BackendRecoveryLog $StateDirectory 'watchdog.log' 'target_changed; recovery postponed'
            } else {
                $currentListeners = @(Get-BackendListenerProcess -Port $current.Port)
                $currentUnknown = @($currentListeners | Where-Object { -not (Test-OwnedNssmBackendPython -Process $_ -Context $current) })
                if ($currentUnknown.Count -gt 0 -or $currentListeners.Count -gt 1 -or
                    ($current.Service.State -eq 'Stopped' -and $currentListeners.Count -gt 0)) {
                    Write-BackendRecoveryLog $StateDirectory 'watchdog.log' 'listener_changed; recovery refused'
                } elseif ((Test-BackendHealth -Port $current.Port -TimeoutSeconds 5).Responsive) {
                    $state.Failures = 0
                    Write-BackendRecoveryLog $StateDirectory 'watchdog.log' 'application_responding_again; no restart'
                } elseif ($PSCmdlet.ShouldProcess($current.Name, 'Recover validated API NSSM service')) {
                    $state.LastRecoveryUtc = [DateTime]::UtcNow.ToString('o')
                    Save-BackendServiceHealth
                    if ($current.Service.State -eq 'Stopped') {
                        Start-Service -Name $current.Name -ErrorAction Stop
                    } else {
                        Restart-Service -Name $current.Name -ErrorAction Stop
                    }
                    Write-BackendRecoveryLog $StateDirectory 'watchdog.log' "service_recovery_requested name=$($current.Name)"
                }
            }
        }
    }
    Save-BackendServiceHealth
} catch {
    Write-BackendRecoveryLog $StateDirectory 'watchdog.log' ("service_watchdog_failed " + $_.Exception.Message)
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
