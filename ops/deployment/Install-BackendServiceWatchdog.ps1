#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$SiteConfig = 'C:\inetpub\wwwroot\web.config',
    [string]$ApiConfig = 'C:\inetpub\api\web.config',
    [string]$RuntimeDirectory = 'C:\Orange Digital Center\ops\backend-recovery'
)

$ErrorActionPreference = 'Stop'
$taskName = 'ODC-TEST-PROD-API-WATCHDOG'
$runtimeNames = @('BackendService.Common.ps1', 'Test-BackendService.ps1')
$runtime = [IO.Path]::GetFullPath($RuntimeDirectory).TrimEnd('\')
if (-not $runtime.StartsWith('C:\Orange Digital Center\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Le runtime doit rester dans C:\Orange Digital Center.'
}
$sourceHashes = @{}
foreach ($name in $runtimeNames) {
    $source = Join-Path $PSScriptRoot $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Script necessaire introuvable: $source" }
    $tokens = $null
    $parseErrors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) { throw "Erreur de syntaxe dans $source" }
    $sourceHashes[$name] = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
}
foreach ($config in @($SiteConfig, $ApiConfig)) {
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { throw "Configuration IIS introuvable: $config" }
}
. (Join-Path $PSScriptRoot 'BackendService.Common.ps1')
$context = Get-PublishedBackendNssmContext -SiteConfig $SiteConfig -ApiConfig $ApiConfig
if ($context.Name -notin @('ODC-PROD-API', 'ODC-PROD-API-SECONDARY')) { throw 'Service API inattendu.' }
if (-not $PSCmdlet.ShouldProcess($taskName, 'Installer le controle HTTP de l API NSSM, chaque minute et au demarrage')) { return }

$hadRuntime = Test-Path -LiteralPath $runtime -PathType Container
$previousAcl = $null
if ($hadRuntime) { $previousAcl = Get-Acl -LiteralPath $runtime }
$null = New-Item -ItemType Directory -Path $runtime -Force
$backup = Join-Path $runtime ('backups\service-watchdog-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff'))
$null = New-Item -ItemType Directory -Path $backup -Force
if ($previousAcl) { $previousAcl | Export-Clixml -LiteralPath (Join-Path $backup 'runtime-acl.xml') }
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$hadTask = ($null -ne $existingTask)
if ($hadTask) {
    Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $backup 'watchdog-task.xml') -Encoding UTF8
}
$previousRuntime = @{}
foreach ($name in $runtimeNames) {
    $target = Join-Path $runtime $name
    $previousRuntime[$name] = Test-Path -LiteralPath $target -PathType Leaf
    if ($previousRuntime[$name]) { Copy-Item -LiteralPath $target -Destination (Join-Path $backup $name) }
}
@{
    TaskName = $taskName; RuntimeDirectory = $runtime; SiteConfig = $SiteConfig; ApiConfig = $ApiConfig
    HadTask = $hadTask; ServiceName = $context.Name; Port = $context.Port; SourceSha256 = $sourceHashes
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $backup 'installation.json') -Encoding UTF8

$taskTouched = $false
try {
    # Only SYSTEM and administrators may change scripts executed by this task.
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid), 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'), 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    Set-Acl -LiteralPath $runtime -AclObject $acl
    # Disable and drain only the short watchdog, never the API service.
    if ($hadTask) {
        $taskTouched = $true
        Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
        if ($existingTask.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                if ((Get-ScheduledTask -TaskName $taskName -ErrorAction Stop).State -ne 'Running') { break }
                Start-Sleep -Milliseconds 250
            }
            if ((Get-ScheduledTask -TaskName $taskName -ErrorAction Stop).State -eq 'Running') {
                throw 'Le precedent controle HTTP ne s arrete pas; installation annulee.'
            }
        }
    }
    foreach ($name in $runtimeNames) {
        $source = Join-Path $PSScriptRoot $name
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $sourceHashes[$name]) {
            throw "Le script source a change pendant l installation: $source"
        }
        $target = Join-Path $runtime $name
        Copy-Item -LiteralPath $source -Destination $target -Force
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $sourceHashes[$name]) {
            throw "Verification de copie echouee: $target"
        }
    }
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $watchdog = Join-Path $runtime 'Test-BackendService.ps1'
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $watchdog + '" -SiteConfig "' + $SiteConfig + '" -ApiConfig "' + $ApiConfig + '"'
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $runtime
    $triggers = @(
        (New-ScheduledTaskTrigger -AtStartup),
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1))
    )
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
        -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $definition = New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal
    $taskTouched = $true
    Register-ScheduledTask -TaskName $taskName -InputObject $definition -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
} catch {
    $installError = $_
    if ($taskTouched) {
        $currentTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($currentTask) {
            Disable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
            if ($currentTask.State -eq 'Running') { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue }
        }
    }
    foreach ($name in $runtimeNames) {
        $target = Join-Path $runtime $name
        if ($previousRuntime[$name]) {
            Copy-Item -LiteralPath (Join-Path $backup $name) -Destination $target -Force
        } elseif (Test-Path -LiteralPath $target -PathType Leaf) {
            Remove-Item -LiteralPath $target -Force
        }
    }
    if ($taskTouched -and $hadTask) {
        Register-ScheduledTask -TaskName $taskName -Xml (Get-Content -LiteralPath (Join-Path $backup 'watchdog-task.xml') -Raw) -Force | Out-Null
    } elseif ($taskTouched -and (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    if ($previousAcl) { Set-Acl -LiteralPath $runtime -AclObject $previousAcl }
    throw $installError
}
Write-Output "Controle API installe: $taskName (chaque minute et au demarrage)."
Write-Output "Sauvegarde: $backup"
Write-Output 'Une indisponibilite MongoDB ne provoque aucun redemarrage de l API.'
