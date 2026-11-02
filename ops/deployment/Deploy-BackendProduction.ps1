#Requires -RunAsAdministrator
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$source = 'C:\Orange Digital Center\odc-test\backend'
$siteConfig = 'C:\inetpub\wwwroot\web.config'
$apiConfig = 'C:\inetpub\api\web.config'
$siteUrl = 'https://orangedigitalcenter.sn/'
$apiHealthUrl = 'https://api.orangedigitalcenter.sn/health'
$serviceHelper = 'C:\Orange Digital Center\ops\backend-recovery\BackendService.Common.ps1'
$watchdogInstaller = Join-Path $source 'ops\deployment\Install-BackendServiceWatchdog.ps1'
$workerInstaller = Join-Path $source 'ops\deployment\register-production-email-worker.ps1'
$maintenance = Join-Path $source 'ops\deployment\ProductionMaintenance.Common.ps1'
$cleanup = Join-Path $source 'ops\deployment\Invoke-ProductionCleanup.ps1'
$serviceNames = @('ODC-PROD-API', 'ODC-PROD-API-SECONDARY')

foreach ($required in @($source, $siteConfig, $apiConfig, $serviceHelper, $watchdogInstaller, $workerInstaller, $maintenance, $cleanup, (Join-Path $source 'requirements.txt'))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Element necessaire introuvable: $required" }
}
. $serviceHelper
. $maintenance

function Get-ApiRuleUrl([string]$Path, [string]$RuleName) {
    [xml]$xml = [IO.File]::ReadAllText($Path)
    $action = $xml.SelectSingleNode("/configuration/system.webServer/rewrite/rules/rule[@name='$RuleName']/action")
    if (-not $action) { throw "Regle API introuvable: $RuleName dans $Path" }
    return $action.GetAttribute('url')
}

function Assert-BackendReady([int]$Port) {
    $lastDetail = ''
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $result = Test-BackendHealth -Port $Port -TimeoutSeconds 5
        if ($result.Healthy -and $result.DependencyHealthy) { return }
        $lastDetail = $result.Detail
        Start-Sleep -Seconds 1
    }
    throw "API non prete sur le port $Port : $lastDetail"
}

function Assert-BackendOwned($Context) {
    $current = Get-BackendNssmContext -ServiceName $Context.Name
    if ($current.Service.State -ne 'Running') { throw "Service API arrete: $($current.Name)" }
    $listeners = @(Get-BackendListenerProcess -Port $current.Port)
    if ($listeners.Count -ne 1 -or -not (Test-OwnedNssmBackendPython -Process $listeners[0] -Context $current)) {
        throw 'Le processus Python sur le port ne correspond pas au service API; bascule refusee.'
    }
    return $current
}

function Assert-PublicBackendHealth([string]$Url) {
    $lastDetail = ''
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        try {
            $result = Invoke-RestMethod -Uri $Url -TimeoutSec 10
            if ($result.status -eq 'healthy' -and $result.environment -eq 'production' -and
                $result.dependencies.mongodb.status -eq 'up') { return }
            $lastDetail = 'Statut de production ou dependance MongoDB non sain.'
        } catch { $lastDetail = $_.Exception.Message }
        Start-Sleep -Seconds 1
    }
    throw "Controle public API echoue: $lastDetail"
}

function Stop-BackendSlot([string]$Name) {
    $service = Get-Service -Name $Name -ErrorAction Stop
    try {
        if ($service.Status -ne 'Stopped') {
            Stop-Service -Name $Name -ErrorAction Stop
            $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
        }
    } finally { $service.Dispose() }
}

function Get-BackendStartupType($Service) {
    if ($Service.StartMode -eq 'Auto') { return 'Automatic' }
    if ($Service.StartMode -eq 'Disabled') { return 'Disabled' }
    return 'Manual'
}

function Stop-RetiredBackend([string]$Name) {
    $context=Get-BackendNssmContext $Name
    if ((Get-PublishedBackendNssmContext).Name -eq $Name) { throw 'Refusing to stop the published API.' }
    $listeners=@(Get-BackendListenerProcess $context.Port)
    if (@($listeners | Where-Object { -not (Test-OwnedNssmBackendPython $_ $context) }).Count) { throw 'Unknown retired API listener.' }
    $deadline=[DateTime]::UtcNow.AddSeconds(120)
    while ((Get-NetTCPConnection -State Established -LocalPort $context.Port -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Seconds 5 }
    if ((Get-PublishedBackendNssmContext).Name -eq $Name) { throw 'API routing changed during drainage.' }
    $null=Assert-BackendOwned (Get-PublishedBackendNssmContext)
    Set-Service -Name $Name -StartupType Manual
    Stop-BackendSlot $Name
}

function Add-ProductionDataJunction([string]$Link, [string]$Target) {
    if (-not (Test-Path -LiteralPath $Target -PathType Container)) { throw "Donnees persistantes introuvables: $Target" }
    if (Test-Path -LiteralPath $Link) { throw "Chemin de release deja existant: $Link" }
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $Link) -Force
    $null = New-Item -ItemType Junction -Path $Link -Target $Target
}

function Restore-ApiRoute([string]$Path, [string]$RuleName, [string]$CandidateUrl, [string]$PreviousUrl) {
    $text = [IO.File]::ReadAllText($Path)
    $currentUrl = Get-ApiRuleUrl $Path $RuleName
    if ($currentUrl -eq $PreviousUrl) { return }
    if ($currentUrl -ne $CandidateUrl -or
        ([regex]::Matches($text, [regex]::Escape($CandidateUrl))).Count -ne 1) {
        throw "La cible API a ete modifiee par une autre operation; restauration automatique refusee: $Path"
    }
    # Keep frontend routing and every unrelated IIS setting unchanged.
    Set-BackendIisTextAtomic -Path $Path -Content $text.Replace($CandidateUrl, $PreviousUrl)
}

$deploymentMutex = New-OdcDeploymentMutex
$deploymentLocked = $false
try {
    try { $deploymentLocked = $deploymentMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $deploymentLocked = $true }
    if (-not $deploymentLocked) { throw 'Un autre deploiement ODC est deja en cours.' }

    $gitChanges = @(& git -c "safe.directory=$source" -C $source status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw 'Git ne peut pas lire le depot backend.' }
    if ($gitChanges.Count -gt 0) { throw 'Le backend contient des changements non commites. Enregistre-les avant le deploiement.' }

    $legacyTask = Get-ScheduledTask -TaskName 'ODC-TEST-PROD-API' -ErrorAction SilentlyContinue
    if ($legacyTask -and ($legacyTask.Settings.Enabled -or $legacyTask.State -eq 'Running')) {
        throw 'La tache API historique est encore active. Finaliser la migration NSSM avant ce deploiement.'
    }
    $active = Get-PublishedBackendNssmContext -SiteConfig $siteConfig -ApiConfig $apiConfig
    $active = Assert-BackendOwned $active
    Assert-BackendReady $active.Port
    foreach ($required in @($active.EnvFile, $active.Python)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Fichier de production introuvable: $required" }
    }

    $oldSiteUrl = Get-ApiRuleUrl $siteConfig 'ReverseProxyToAPI'
    $oldApiUrl = Get-ApiRuleUrl $apiConfig 'ReverseProxyInboundRule1'
    if ($oldSiteUrl -ne "http://127.0.0.1:$($active.Port)/api/{R:1}" -or
        $oldApiUrl -ne "http://127.0.0.1:$($active.Port)/{R:1}") {
        throw 'Les deux regles IIS ne ciblent pas le meme service API; bascule refusee.'
    }

    $candidateName = @($serviceNames | Where-Object { $_ -ne $active.Name })[0]
    $inactiveService = Get-CimInstance Win32_Service -Filter "Name='$candidateName'" -ErrorAction Stop
    if ($inactiveService -and $inactiveService.State -ne 'Stopped') {
        Stop-RetiredBackend $candidateName
        $inactiveService=Get-CimInstance Win32_Service -Filter "Name='$candidateName'" -ErrorAction Stop
    }
    $inactiveStartup = if ($inactiveService) { Get-BackendStartupType $inactiveService } else { 'Manual' }
    $activeStartup = Get-BackendStartupType $active.Service
    $port = $null
    for ($candidate = 5003; $candidate -le 5099; $candidate++) {
        if (-not (Get-NetTCPConnection -State Listen -LocalPort $candidate -ErrorAction SilentlyContinue)) {
            $port = $candidate
            break
        }
    }
    if (-not $port) { throw 'Aucun port API libre entre 5003 et 5099.' }

    # Uploads remain in canonical shared source paths, never chained through an old release.
    $dataDirectories = @('uploads', 'app\uploads', 'app\static\uploads')
    if (Test-Path -LiteralPath (Join-Path $source 'flask_session') -PathType Container) { $dataDirectories += 'flask_session' }
    foreach ($relative in $dataDirectories) {
        if (-not (Test-Path -LiteralPath (Join-Path $source $relative) -PathType Container)) {
            throw "Donnees persistantes manquantes: $relative"
        }
    }

    $operation = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
    $releaseRoot = 'C:\Orange Digital Center\_odc-prod-release-' + $operation
    $release = Join-Path $releaseRoot 'backend'
    $backupDir = 'C:\Orange Digital Center\archives\sauvegardes\_odc-prod-backup-' + $operation
    $null = New-Item -ItemType Directory -Path $release -Force
    $null = New-Item -ItemType Directory -Path $backupDir -Force
    Save-OdcPublishedDeployment -Component backend -ReleaseRoot $releaseRoot -PreviousPath $active.Backend -BackupDirectory $backupDir -Status prepared
    $siteBackup = Join-Path $backupDir 'wwwroot.web.config'
    $apiBackup = Join-Path $backupDir 'api.web.config'
    Copy-Item -LiteralPath $siteConfig -Destination $siteBackup
    Copy-Item -LiteralPath $apiConfig -Destination $apiBackup
    $oldSiteText = [IO.File]::ReadAllText($siteBackup)
    $oldApiText = [IO.File]::ReadAllText($apiBackup)
    $newSiteUrl = "http://127.0.0.1:$port/api/{R:1}"
    $newApiUrl = "http://127.0.0.1:$port/{R:1}"
    if (([regex]::Matches($oldSiteText, [regex]::Escape($oldSiteUrl))).Count -ne 1 -or
        ([regex]::Matches($oldApiText, [regex]::Escape($oldApiUrl))).Count -ne 1) {
        throw 'Les cibles API IIS sont ambigues; bascule refusee.'
    }
    $inactiveRegFile = Join-Path $backupDir 'inactive-api-service.reg'
    if ($inactiveService) {
        & reg.exe export ("HKLM\SYSTEM\CurrentControlSet\Services\" + $candidateName) $inactiveRegFile /y | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Sauvegarde du service API inactif impossible.' }
    }
    @{
        ActiveService = $active.Name; ActiveBackend = $active.Backend; ActivePort = $active.Port
        ActiveStartupType = $activeStartup; EnvFile = $active.EnvFile
        CandidateService = $candidateName; CandidatePort = $port; CandidateExisted = [bool]$inactiveService
        CandidateStartupType = $inactiveStartup; Release = $release; SiteBackup = $siteBackup; ApiBackup = $apiBackup
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupDir 'deployment.json') -Encoding UTF8

    $candidateTouched = $false
    $siteChanged = $false
    $apiChanged = $false
    $committed = $false
    $workerTouched = $false
    try {
        $excludedDirs = @((Join-Path $source '.git'), (Join-Path $source '.venv'), (Join-Path $source '.venv-load'), (Join-Path $source 'venv'), (Join-Path $source 'env'), (Join-Path $source '__pycache__'), (Join-Path $source 'logs'), (Join-Path $source 'ops-logs'))
        $excludedDirs += @($dataDirectories | ForEach-Object { Join-Path $source $_ })
        & robocopy $source $release /E /COPY:DAT /R:1 /W:1 /XJ /XD $excludedDirs /XF '.env' '.env.*' '*.pyc' '*.log' '*.log.*' | Out-Null
        if ($LASTEXITCODE -gt 7) { throw "Copie du backend echouee (robocopy $LASTEXITCODE)." }
        foreach ($relative in $dataDirectories) {
            Add-ProductionDataJunction (Join-Path $release $relative) (Join-Path $source $relative)
        }

        # Install only into the candidate venv; the live Python environment is unchanged.
        & $active.Python -m venv (Join-Path $release '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Creation de l environnement Python echouee.' }
        $releasePython = Join-Path $release '.venv\Scripts\python.exe'
        & $releasePython -m pip install -r (Join-Path $release 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Installation des dependances API echouee.' }

        $candidateTouched = $true
        Set-BackendNssmService -ServiceName $candidateName -BackendPath $release -Port $port -EnvFile $active.EnvFile
        Set-Service -Name $candidateName -StartupType Manual
        Start-Service -Name $candidateName -ErrorAction Stop
        Assert-BackendReady $port
        $candidateContext = Assert-BackendOwned (Get-BackendNssmContext -ServiceName $candidateName)

        # A concurrent frontend/configuration change must not be overwritten by this deployment.
        $currentActive = Get-PublishedBackendNssmContext -SiteConfig $siteConfig -ApiConfig $apiConfig
        if ($currentActive.Name -ne $active.Name -or $currentActive.Port -ne $active.Port -or
            [IO.File]::ReadAllText($siteConfig) -ne $oldSiteText -or [IO.File]::ReadAllText($apiConfig) -ne $oldApiText) {
            throw 'La configuration de production a change pendant la preparation; bascule annulee.'
        }
        $null = Assert-BackendOwned $active
        Assert-BackendReady $active.Port
        Set-Service -Name $candidateName -StartupType Automatic
        Set-BackendIisTextAtomic -Path $siteConfig -Content $oldSiteText.Replace($oldSiteUrl, $newSiteUrl)
        $siteChanged = $true
        Set-BackendIisTextAtomic -Path $apiConfig -Content $oldApiText.Replace($oldApiUrl, $newApiUrl)
        $apiChanged = $true
        & $watchdogInstaller

        $published = Get-PublishedBackendNssmContext -SiteConfig $siteConfig -ApiConfig $apiConfig
        if ($published.Name -ne $candidateName) { throw 'IIS ne cible pas le nouveau service API.' }
        Assert-PublicBackendHealth $apiHealthUrl
        Assert-PublicBackendHealth ($siteUrl + 'api/health')
        $siteCode = & curl.exe -sS -o NUL -w '%{http_code}' --connect-timeout 10 --max-time 20 $siteUrl
        if ($LASTEXITCODE -ne 0 -or $siteCode -ne '200') { throw "Le site public ne repond pas HTTP 200 (HTTP $siteCode)." }
        $null = Assert-BackendOwned $candidateContext
        Assert-BackendReady $port
        $workerTouched = $true
        & $workerInstaller
        $committed = $true

        try {
            Set-Service -Name $active.Name -StartupType Manual
            Stop-RetiredBackend $active.Name
        } catch { Write-Warning "API publiee; ancien service a verifier: $($_.Exception.Message)" }
        Write-Output 'Deploiement API reussi: MongoDB sain, deux acces API publics et frontend HTTP 200.'
        Write-Output "Service: $candidateName ; port: $port"
        Write-Output "Release: $release"
        Write-Output 'Sauvegarde de securite temporaire creee pour ce deploiement.'
        Write-Output 'Worker email aligne sur cette release.'
        try {
            Save-OdcPublishedDeployment -Component backend -ReleaseRoot $releaseRoot -PreviousPath $active.Backend -BackupDirectory $backupDir
            & $cleanup
        } catch { Write-Warning ('API et worker publies; nettoyage differe: '+$_.Exception.Message) }
        finally {
            if (Test-Path -LiteralPath $backupDir -PathType Container) {
                try {
                    Remove-OdcTreeNoFollow -Path $backupDir -AllowedRoot 'C:\Orange Digital Center\archives\sauvegardes'
                    Write-Output 'Sauvegarde temporaire supprimee apres validation.'
                } catch { Write-Warning ('Sauvegarde temporaire conservee pour intervention: '+$_.Exception.Message) }
            }
        }
    } catch {
        $deploymentError = $_
        if (-not $committed) {
            # Restore BOTH routes before stopping the candidate; preserve unrelated IIS edits.
            $rollbackErrors = @()
            if ($siteChanged) {
                try { Restore-ApiRoute $siteConfig 'ReverseProxyToAPI' $newSiteUrl $oldSiteUrl }
                catch { $rollbackErrors += $_.Exception.Message }
            }
            if ($apiChanged) {
                try { Restore-ApiRoute $apiConfig 'ReverseProxyInboundRule1' $newApiUrl $oldApiUrl }
                catch { $rollbackErrors += $_.Exception.Message }
            }
            if ($rollbackErrors.Count -gt 0) {
                throw "Retour IIS incomplet; les deux services sont conserves. Sauvegarde: $backupDir. $($rollbackErrors -join ' ; '). Echec initial: $($deploymentError.Exception.Message)"
            }
            if ($siteChanged -or $apiChanged) {
                Set-Service -Name $active.Name -StartupType $activeStartup
                if ((Get-Service -Name $active.Name).Status -ne 'Running') { Start-Service -Name $active.Name }
            }
            if ($workerTouched) { & $workerInstaller }
            if ($candidateTouched) {
                try {
                    Stop-BackendSlot $candidateName
                    if ($inactiveService) {
                        $parametersPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$candidateName\Parameters"
                        if ($candidateName -notin $serviceNames -or $candidateName -eq $active.Name -or
                            $parametersPath -ne ("HKLM:\SYSTEM\CurrentControlSet\Services\" + $candidateName + '\Parameters')) {
                            throw 'Chemin registre de restauration refuse.'
                        }
                        if (Test-Path -LiteralPath $parametersPath) { Remove-Item -LiteralPath $parametersPath -Recurse -Force }
                        & reg.exe import $inactiveRegFile | Out-Null
                        if ($LASTEXITCODE -ne 0) { throw 'Restauration du service API inactif impossible.' }
                        Set-Service -Name $candidateName -StartupType $inactiveStartup
                    } else {
                        & sc.exe delete $candidateName | Out-Null
                        if ($LASTEXITCODE -ne 0) { throw 'Suppression du service API candidat impossible.' }
                    }
                } catch { Write-Warning "Service candidat a verifier: $($_.Exception.Message). Sauvegarde: $backupDir" }
            }
        }
        throw $deploymentError
    }
} finally {
    if ($deploymentLocked) { $deploymentMutex.ReleaseMutex() }
    $deploymentMutex.Dispose()
}
