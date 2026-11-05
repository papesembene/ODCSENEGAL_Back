#Requires -RunAsAdministrator
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$source = 'C:\Orange Digital Center\odc-test\frontend'
$webConfig = 'C:\inetpub\wwwroot\web.config'
$siteUrl = 'https://orangedigitalcenter.sn/'
$runtime = 'C:\Orange Digital Center\ops\frontend-recovery'
$serviceHelper = Join-Path $runtime 'FrontendService.Common.ps1'
$watchdogInstaller = Join-Path $source 'ops\windows\Install-FrontendServiceWatchdog.ps1'
$serviceNames = @('ODC-PROD-FRONTEND', 'ODC-PROD-FRONTEND-SECONDARY')
foreach ($required in @($source, $webConfig, $serviceHelper, $watchdogInstaller)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Element necessaire introuvable: $required" }
}
. $serviceHelper
$maintenance='C:\Orange Digital Center\odc-test\backend\ops\deployment\ProductionMaintenance.Common.ps1'
$cleanup='C:\Orange Digital Center\odc-test\backend\ops\deployment\Invoke-ProductionCleanup.ps1'
. $maintenance

function Assert-FrontendPage([string]$Url) {
    $failure = ''
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $request = [Net.HttpWebRequest]::Create($Url)
            $request.Proxy = $null
            $request.Timeout = 5000
            $request.ReadWriteTimeout = 5000
            $request.AllowAutoRedirect = $false
            $response = $request.GetResponse()
            try {
                if ([int]$response.StatusCode -ne 200) { throw "HTTP $([int]$response.StatusCode)" }
                $reader = [IO.StreamReader]::new($response.GetResponseStream())
                try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
            } finally { $response.Close() }
        } catch {
            $failure = $_.Exception.Message
            Start-Sleep -Seconds 1
        }
    }
    throw "Aucune reponse HTTP 200 pour $Url : $failure"
}

function Assert-ServiceOwnsFrontend($Context) {
    $current = Get-FrontendNssmContext -ServiceName $Context.Name
    if ($current.Service.State -ne 'Running') { throw "Le service $($current.Name) ne fonctionne pas." }
    $listeners = @(Get-FrontendListenerProcess $current.Port)
    if ($listeners.Count -ne 1 -or -not (Test-OwnedNssmFrontendNode -Process $listeners[0] -Context $current)) {
        throw 'Le service ne possede pas le processus Node attendu; bascule refusee.'
    }
    return $current
}

function Wait-ServiceStopped([string]$Name) {
    $service = Get-Service -Name $Name -ErrorAction Stop
    try {
        if ($service.Status -ne 'Stopped') {
            Stop-Service -Name $Name -ErrorAction Stop
            $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
        }
    } finally { $service.Dispose() }
}

function Get-OriginalStartupType($Service) {
    if ($Service.StartMode -eq 'Auto') { return 'Automatic' }
    if ($Service.StartMode -eq 'Disabled') { return 'Disabled' }
    return 'Manual'
}

function Stop-RetiredFrontend([string]$Name) {
    $context=Get-FrontendNssmContext $Name
    if ((Get-PublishedFrontendNssmContext).Name -eq $Name) { throw 'Refusing to stop published frontend.' }
    $listeners=@(Get-FrontendListenerProcess $context.Port)
    if (@($listeners | Where-Object { -not (Test-OwnedNssmFrontendNode $_ $context) }).Count) { throw 'Unknown retired frontend listener.' }
    $deadline=[DateTime]::UtcNow.AddSeconds(120)
    while ((Get-NetTCPConnection -State Established -LocalPort $context.Port -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Seconds 5 }
    if ((Get-PublishedFrontendNssmContext).Name -eq $Name) { throw 'Frontend routing changed during drainage.' }
    $null=Assert-ServiceOwnsFrontend (Get-PublishedFrontendNssmContext)
    Set-Service -Name $Name -StartupType Manual
    Wait-ServiceStopped $Name
}

$deploymentMutex = New-OdcDeploymentMutex
$deploymentLocked = $false
try {
    try { $deploymentLocked = $deploymentMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $deploymentLocked = $true }
    if (-not $deploymentLocked) { throw 'Un autre deploiement frontend est deja en cours.' }

# Commit source changes before copying a production release.
$gitChanges = @(& git -c "safe.directory=$source" -C $source status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Git ne peut pas lire le depot frontend.' }
if ($gitChanges.Count -gt 0) { throw 'Le frontend contient des changements non commites. Enregistre-les avant le deploiement.' }
$active = Get-PublishedFrontendNssmContext -WebConfig $webConfig
$active = Assert-ServiceOwnsFrontend $active
if (-not (Test-FrontendResponse $active.Port).Healthy) { throw 'Le frontend actif ne repond pas correctement; verifier avant de deployer.' }
$productionEnv = Join-Path $active.Frontend '.env.production.local'
if (-not (Test-Path -LiteralPath $productionEnv -PathType Leaf)) { throw 'Configuration de production introuvable dans la release active.' }
$candidateName = @($serviceNames | Where-Object { $_ -ne $active.Name })[0]
$inactiveService = Get-CimInstance Win32_Service -Filter "Name='$candidateName'" -ErrorAction Stop
if ($inactiveService -and $inactiveService.State -ne 'Stopped') {
    Stop-RetiredFrontend $candidateName
    $inactiveService=Get-CimInstance Win32_Service -Filter "Name='$candidateName'" -ErrorAction Stop
}
$inactiveStartup = if ($inactiveService) { Get-OriginalStartupType $inactiveService } else { 'Manual' }
$activeStartup = Get-OriginalStartupType $active.Service

$port = $null
for ($candidate = 3005; $candidate -le 3099; $candidate++) {
    if (-not (Get-NetTCPConnection -State Listen -LocalPort $candidate -ErrorAction SilentlyContinue)) {
        $port = $candidate
        break
    }
}
if (-not $port) { throw 'Aucun port frontend libre entre 3005 et 3099.' }
$operation = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
$releaseRoot = 'C:\Orange Digital Center\_odc-prod-release-' + $operation
$release = Join-Path $releaseRoot 'frontend'
$backupDir = 'C:\Orange Digital Center\archives\sauvegardes\_odc-prod-backup-' + $operation
$null = New-Item -ItemType Directory -Path $backupDir -Force
$null = New-Item -ItemType Directory -Path $release -Force
Save-OdcPublishedDeployment -Component frontend -ReleaseRoot $releaseRoot -PreviousPath $active.Frontend -BackupDirectory $backupDir -Status prepared
$iisBackup = Join-Path $backupDir 'wwwroot.web.config'
Copy-Item -LiteralPath $webConfig -Destination $iisBackup
$oldIisText = [IO.File]::ReadAllText($iisBackup)
$oldUrl = "http://127.0.0.1:$($active.Port)/{R:0}"
$newUrl = "http://127.0.0.1:$port/{R:0}"
if (([regex]::Matches($oldIisText, [regex]::Escape($oldUrl))).Count -ne 1) {
    throw 'La cible IIS a change; bascule annulee.'
}
$inactiveRegFile = Join-Path $backupDir 'inactive-frontend-service.reg'
if ($inactiveService) {
    & reg.exe export ("HKLM\SYSTEM\CurrentControlSet\Services\" + $candidateName) $inactiveRegFile /y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Sauvegarde de la configuration du service inactif impossible.' }
}
@{
    ActiveService = $active.Name; ActiveFrontend = $active.Frontend; ActivePort = $active.Port
    ActiveStartupType = $activeStartup; CandidateService = $candidateName; CandidatePort = $port
    CandidateExisted = [bool]$inactiveService; CandidateStartupType = $inactiveStartup
    Release = $release; IisBackup = $iisBackup
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupDir 'deployment.json') -Encoding UTF8

$candidateTouched = $false
$iisChanged = $false
$committed = $false
try {
    & robocopy $source $release /E /COPY:DAT /R:1 /W:1 /XD .git .next node_modules .turbo ops-logs /XF .env.local .env.development.local .env.production.local next.config.mjs | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "Copie du frontend echouee (robocopy $LASTEXITCODE)." }
    Copy-Item -LiteralPath $productionEnv -Destination (Join-Path $release '.env.production.local')
    $nextConfig = Get-Content -LiteralPath (Join-Path $source 'next.config.mjs') -Raw
    $nextConfig = [regex]::Replace($nextConfig, '(?m)^\s*output:\s*["'']standalone["''],\s*\r?\n', '')
    [IO.File]::WriteAllText((Join-Path $release 'next.config.mjs'), $nextConfig, [Text.UTF8Encoding]::new($false))
    Push-Location $release
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci a echoue.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Le build Next.js a echoue.' }
    } finally { Pop-Location }
    $buildId = (Get-Content -LiteralPath (Join-Path $release '.next\BUILD_ID') -Raw).Trim()
    if (-not $buildId) { throw 'Le build Next.js ne contient pas de BUILD_ID.' }

    # Configure only the stopped inactive slot, then warm it before publication.
    $candidateTouched = $true
    Set-FrontendNssmService -ServiceName $candidateName -FrontendPath $release -Port $port
    Set-Service -Name $candidateName -StartupType Manual
    Start-Service -Name $candidateName
    $homePage = Assert-FrontendPage "http://127.0.0.1:$port/"
    $null = Assert-FrontendPage "http://127.0.0.1:$port/astrodmin"
    $asset = [regex]::Match($homePage, '(?:src|href)="(/_next/static/[^"?]+\.(?:css|js))(?:\?[^"]*)?"')
    if (-not $asset.Success) { throw 'Aucun fichier CSS ou JavaScript Next.js dans l accueil; bascule refusee.' }
    $null = Assert-FrontendPage ("http://127.0.0.1:$port" + [Net.WebUtility]::HtmlDecode($asset.Groups[1].Value))
    $candidateContext = Assert-ServiceOwnsFrontend (Get-FrontendNssmContext -ServiceName $candidateName)

    # Abort if another deployment modified the published service or IIS during the build.
    $currentActive = Get-PublishedFrontendNssmContext -WebConfig $webConfig
    if ($currentActive.Name -ne $active.Name -or $currentActive.Port -ne $active.Port -or
        [IO.File]::ReadAllText($webConfig) -ne $oldIisText) {
        throw 'La configuration de production a change pendant le build; bascule annulee.'
    }
    $null = Assert-ServiceOwnsFrontend $active
    Set-Service -Name $candidateName -StartupType Automatic
    Set-FrontendIisTextAtomic -Path $webConfig -Content $oldIisText.Replace($oldUrl, $newUrl)
    $iisChanged = $true
    & $watchdogInstaller
    $published = Get-PublishedFrontendNssmContext -WebConfig $webConfig
    if ($published.Name -ne $candidateName) { throw 'IIS ne pointe pas vers le nouveau service.' }
    # Exercise ARR locally with the production Host, then verify the public TLS endpoint.
    $localIis = Invoke-WebRequest -Uri 'http://127.0.0.1/' -Headers @{ Host = 'orangedigitalcenter.sn' } -TimeoutSec 15 -UseBasicParsing
    if ($localIis.StatusCode -ne 200) { throw 'IIS ne repond pas HTTP 200 apres la bascule.' }
    $publicCode = & curl.exe -sS -o NUL -w '%{http_code}' --connect-timeout 10 --max-time 20 $siteUrl
    if ($LASTEXITCODE -ne 0 -or $publicCode -ne '200') { throw "Le site public ne repond pas HTTP 200 (HTTP $publicCode)." }
    $null = Assert-ServiceOwnsFrontend $candidateContext
    if (-not (Test-FrontendResponse $port).Healthy) { throw 'Le nouveau frontend ne repond plus apres la bascule.' }
    $committed = $true

    # Drain old connections, then keep the stopped slot on the current build.
    # Cleanup failure must not undo an already verified public deployment.
    try {
        Set-Service -Name $active.Name -StartupType Manual
        Stop-RetiredFrontend $active.Name
        Set-FrontendNssmService -ServiceName $active.Name -FrontendPath $release -Port $active.Port
    } catch { Write-Warning "Deploiement termine; ancien service a verifier: $($_.Exception.Message)" }
    Write-Output 'Deploiement frontend reussi: site public HTTP 200.'
    Write-Output "Service: $candidateName ; port: $port ; build: $buildId"
    Write-Output "Release: $release"
    Write-Output 'Configuration de secours temporaire creee pour ce deploiement.'
    try {
        Save-OdcPublishedDeployment -Component frontend -ReleaseRoot $releaseRoot -PreviousPath $active.Frontend -BackupDirectory $backupDir
        & $cleanup
    } catch { Write-Warning ('Frontend publie; nettoyage differe: '+$_.Exception.Message) }
    finally {
        if (Test-Path -LiteralPath $backupDir -PathType Container) {
            try {
                Remove-OdcTreeNoFollow -Path $backupDir -AllowedRoot 'C:\Orange Digital Center\archives\sauvegardes'
                Write-Output 'Configuration de secours temporaire supprimee apres validation.'
            } catch { Write-Warning ('Configuration temporaire conservee pour intervention: '+$_.Exception.Message) }
        }
    }
} catch {
    $deploymentError = $_
    if (-not $committed) {
        # Restore routing before touching the candidate. The old service remained alive.
        if ($iisChanged) {
            try {
                # Preserve unrelated IIS edits made after publication. Only restore
                # this deployment's exact frontend target; an unknown target is left alone.
                $rollbackText = [IO.File]::ReadAllText($webConfig)
                [xml]$rollbackXml = $rollbackText
                $rollbackAction = $rollbackXml.SelectSingleNode("/configuration/system.webServer/rewrite/rules/rule[@name='ReverseProxyToNextJS']/action")
                if (-not $rollbackAction) { throw 'Regle frontend IIS introuvable pendant le retour arriere.' }
                $rollbackUrl = $rollbackAction.GetAttribute('url')
                if ($rollbackUrl -eq $newUrl) {
                    if (([regex]::Matches($rollbackText, [regex]::Escape($newUrl))).Count -ne 1) {
                        throw 'La cible candidate IIS est ambigue; retour arriere automatique refuse.'
                    }
                    Set-FrontendIisTextAtomic -Path $webConfig -Content $rollbackText.Replace($newUrl, $oldUrl)
                } elseif ($rollbackUrl -ne $oldUrl) {
                    throw 'La cible frontend IIS a ete modifiee par une autre operation; retour arriere automatique refuse.'
                }
                Set-Service -Name $active.Name -StartupType $activeStartup
                if ((Get-Service -Name $active.Name).Status -ne 'Running') { Start-Service -Name $active.Name }
            } catch {
                throw "Retour IIS impossible; les deux services sont conserves. Sauvegarde: $iisBackup. Erreur: $($_.Exception.Message). Echec initial: $($deploymentError.Exception.Message)"
            }
        }
        if ($candidateTouched) {
            try {
                Wait-ServiceStopped $candidateName
                if ($inactiveService) {
                    # Verify this is only the stopped, allowlisted inactive slot before recursive removal.
                    $parametersPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$candidateName\Parameters"
                    if ($candidateName -notin $serviceNames -or $candidateName -eq $active.Name -or
                        $parametersPath -ne ("HKLM:\SYSTEM\CurrentControlSet\Services\" + $candidateName + '\Parameters')) {
                        throw 'Chemin registre de restauration refuse.'
                    }
                    if (Test-Path -LiteralPath $parametersPath) { Remove-Item -LiteralPath $parametersPath -Recurse -Force }
                    & reg.exe import $inactiveRegFile | Out-Null
                    if ($LASTEXITCODE -ne 0) { throw 'Restauration du service inactif impossible.' }
                    Set-Service -Name $candidateName -StartupType $inactiveStartup
                } else {
                    & sc.exe delete $candidateName | Out-Null
                    if ($LASTEXITCODE -ne 0) { throw 'Suppression du service candidat impossible.' }
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
