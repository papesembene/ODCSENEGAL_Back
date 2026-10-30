#Requires -RunAsAdministrator
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$workspace='C:\Orange Digital Center'
$runtime=Join-Path $workspace 'ops\data-backup'
$destination=Join-Path $workspace 'archives\donnees-quotidiennes'
function Set-PrivateBackupDirectory([string]$Path) {
    if ((Test-Path -LiteralPath $Path) -and ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Backup runtime/destination cannot be a junction.' }
    $null=New-Item -ItemType Directory -Path $Path -Force
    $acl=[Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($sid in @('S-1-5-18','S-1-5-32-544')) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}
foreach ($path in @($runtime,$destination)) { Set-PrivateBackupDirectory $path }
$bin=Join-Path $runtime 'bin'
$null=New-Item -ItemType Directory -Path $bin -Force
$version='100.20.0'
$archive=Join-Path $runtime 'tools.zip'
$expected='B65A32595DB38CDF0F413D53CAC440C4A6DDAC0D224405B550E4100535BDD5CA'
if (-not (Test-Path -LiteralPath (Join-Path $bin 'tools-100.20.0.json'))) {
    & curl.exe --fail --silent --show-error --location --connect-timeout 10 --max-time 180 --output $archive ('https://fastdl.mongodb.org/tools/db/mongodb-database-tools-windows-x86_64-'+$version+'.zip')
    if ($LASTEXITCODE -ne 0 -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'Official MongoDB tools download/hash verification failed.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip=[IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($name in @('mongodump.exe','mongorestore.exe')) {
            $entry=@($zip.Entries | Where-Object { $_.FullName -like ('*/bin/'+$name) })
            if ($entry.Count -ne 1) { throw 'Unexpected MongoDB tools archive structure.' }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry[0],(Join-Path $bin $name),$true)
        }
    } finally { $zip.Dispose() }
    @{Version=$version;ArchiveSHA256=$expected} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $bin 'tools-100.20.0.json') -Encoding UTF8
    Remove-Item -LiteralPath $archive -Force
}
foreach ($name in @('Backup-ProductionData.ps1','BackendService.Common.ps1','ProductionMaintenance.Common.ps1','production_backup.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $runtime $name) -Force
}
$taskName='ODC-PROD-DATA-BACKUP'
$powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action=New-ScheduledTaskAction -Execute $powershell -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $runtime 'Backup-ProductionData.ps1')+'"') -WorkingDirectory $runtime
$at=[DateTime]::UtcNow.Date.AddHours(2).AddMinutes(30).ToLocalTime()
$trigger=New-ScheduledTaskTrigger -Daily -At $at
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)
$principal=New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
$definition=New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'ODC: sauvegarde locale quotidienne MongoDB/uploads, sept copies reussies conservees.'
Register-ScheduledTask -TaskName $taskName -InputObject $definition -Force | Out-Null
Write-Output 'Sauvegarde quotidienne installee: 02:30 UTC; sept copies reussies; aucune copie hors serveur configuree.'
foreach ($component in @('backend','frontend')) {
    $name=if ($component -eq 'backend') { 'Backend' } else { 'Frontend' }
    $launcher=@('#Requires -RunAsAdministrator',"`$ErrorActionPreference='Stop'",('& (Join-Path $PSScriptRoot ''odc-test\backend\ops\deployment\Deploy-'+$name+'Production.ps1'')'))
    $null=[scriptblock]::Create(($launcher -join "`n"))
    Set-Content -LiteralPath (Join-Path $workspace ('deploy-'+$component+'-production.ps1')) -Value $launcher -Encoding UTF8
}
# Adopt only known successful deployment metadata, without deleting anything.
. (Join-Path $PSScriptRoot 'ProductionMaintenance.Common.ps1')
$backupRoot=Join-Path $workspace 'archives\sauvegardes'
foreach ($directory in @(Get-ChildItem -LiteralPath $backupRoot -Directory)) {
    $file=Join-Path $directory.FullName 'deployment.json'
    if ($directory.Name -notmatch '^_odc-prod-backup-\d{8}-\d{6}-\d{3}$' -or -not (Test-Path -LiteralPath $file) -or (Test-Path -LiteralPath (Join-Path $directory.FullName 'retention.json'))) { continue }
    $record=Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
    # Adoption is restricted to the deployment currently published by IIS.
    . (Join-Path $PSScriptRoot 'BackendService.Common.ps1')
    $current=Get-PublishedBackendNssmContext
    if ($record.Release -eq $current.Backend) {
        Save-OdcPublishedDeployment -Component backend -ReleaseRoot (Split-Path -Parent $current.Backend) -PreviousPath $record.ActiveBackend -BackupDirectory $directory.FullName
    }
}
