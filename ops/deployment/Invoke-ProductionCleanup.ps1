#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess,ConfirmImpact='Medium')]
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'ProductionMaintenance.Common.ps1')
$workspace='C:\Orange Digital Center'
$mutex=New-OdcDeploymentMutex
$locked=$false
try {
    try { $locked=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked=$true }
    if (-not $locked) { throw 'Another production operation is running.' }
    $references=@(Get-OdcLiveReferences $workspace)
    $plan=@(Get-OdcRetentionPlan -Workspace $workspace -References $references)
    foreach ($item in $plan) {
        # Re-inventory just before each removal: a newly started process protects its release.
        $current=@(Get-OdcRetentionPlan -Workspace $workspace -References @(Get-OdcLiveReferences $workspace))
        if (@($current | Where-Object { $_.Path -eq $item.Path }).Count -ne 1) { continue }
        if ($PSCmdlet.ShouldProcess($item.Path,'Remove unused managed '+$item.Kind)) {
            Remove-OdcTreeNoFollow -Path $item.Path -AllowedRoot $item.AllowedRoot
            Write-Output ('Nettoyage: '+$item.Path)
        }
    }
    if (-not $plan.Count) { Write-Output 'Nettoyage: aucune ancienne version geree a supprimer.' }
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
