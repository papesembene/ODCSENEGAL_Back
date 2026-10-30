#Requires -RunAsAdministrator
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'BackendService.Common.ps1')
. (Join-Path $PSScriptRoot 'ProductionMaintenance.Common.ps1')
$mutex=New-OdcDeploymentMutex
$locked=$false
try {
    try { $locked=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked=$true }
    if (-not $locked) { throw 'Deployment in progress; backup postponed.' }
    $context=Get-PublishedBackendNssmContext
    $script=Join-Path $PSScriptRoot 'production_backup.py'
    & $context.Python $script --env-file $context.EnvFile --source 'C:\Orange Digital Center\odc-test\backend' --tools 'C:\Orange Digital Center\ops\data-backup\bin' --destination 'C:\Orange Digital Center\archives\donnees-quotidiennes'
    if ($LASTEXITCODE -ne 0) { throw 'Daily data backup failed; previous copies preserved.' }
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
