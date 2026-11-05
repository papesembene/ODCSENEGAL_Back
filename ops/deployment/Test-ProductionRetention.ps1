[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'ProductionMaintenance.Common.ps1')
$validation='C:\Orange Digital Center\ops\validation'
$fixture=Join-Path $validation ('retention-'+[guid]::NewGuid().ToString('N'))
$null=New-Item -ItemType Directory -Path $fixture -Force
try {
    $roots=@()
    for ($index=1;$index -le 4;$index++) {
        $suffix='20261030-10000'+$index+'-000'
        $release=Join-Path $fixture ('_odc-prod-release-'+$suffix)
        $backup=Join-Path $fixture ('archives\sauvegardes\_odc-prod-backup-'+$suffix)
        $null=New-Item -ItemType Directory -Path $release,$backup -Force
        @{Schema=1;Component='backend'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $release 'odc-release.json')
        $roots+=$release
        @{Schema=1;Component='backend';Status='published';CurrentRoot=$release;PreviousRoot=if ($index -gt 1) {$roots[$index-2]} else {''};CompletedUtc=('2026-10-30T10:00:0'+$index+'Z')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'retention.json')
    }
    $legacy=Join-Path $fixture '_odc-prod-release-20261029-100001-000'
    $null=New-Item -ItemType Directory -Path $legacy
    $plan=@(Get-OdcRetentionPlan -Workspace $fixture -References @($roots[0]))
    if (@($plan | Where-Object { $_.Kind -eq 'release' }).Count -ne 2 -or @($plan | Where-Object { $_.Path -notin @($roots[1],$roots[2]) -and $_.Kind -eq 'release' }).Count -ne 0) { throw 'Current, referenced or legacy release protection failed.' }
    if (@($plan | Where-Object { $_.Kind -eq 'configuration' }).Count -ne 4) { throw 'Unused configurations should not be retained.' }
    $referencedBackup=Join-Path $fixture 'archives\sauvegardes\_odc-prod-backup-20261030-100001-000'
    $referencedPlan=@(Get-OdcRetentionPlan -Workspace $fixture -References @($roots[0],$referencedBackup))
    if (@($referencedPlan | Where-Object { $_.Path -eq $referencedBackup }).Count -ne 0) { throw 'A referenced backup must remain protected.' }
    $failed=Join-Path $fixture '_odc-prod-release-20261030-100005-000'
    $failedBackup=Join-Path $fixture 'archives\sauvegardes\_odc-prod-backup-20261030-100005-000'
    $null=New-Item -ItemType Directory -Path $failed,$failedBackup
    @{Schema=1;Component='backend';Status='prepared'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $failed 'odc-release.json')
    @{Schema=1;Component='backend';Status='prepared';CurrentRoot=$failed;PreviousRoot=$roots[0];CompletedUtc='2026-10-30T10:00:05Z'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $failedBackup 'retention.json')
    $afterFailure=@(Get-OdcRetentionPlan -Workspace $fixture -References @($roots[0]))
    if (@($afterFailure | Where-Object { $_.Path -eq $roots[3] }).Count -ne 0 -or @($afterFailure | Where-Object { $_.Path -eq $failed }).Count -ne 1 -or @($afterFailure | Where-Object { $_.Path -eq $failedBackup }).Count -ne 1) { throw 'Failed attempt displaced the current release or retained unused files.' }
    $protected=Join-Path $fixture 'protected-uploads'
    $null=New-Item -ItemType Directory -Path $protected
    [IO.File]::WriteAllText((Join-Path $protected 'sentinel.txt'),'preserve')
    $null=New-Item -ItemType Junction -Path (Join-Path $roots[1] 'uploads') -Target $protected
    Remove-OdcTreeNoFollow -Path $roots[1] -AllowedRoot $fixture
    if (-not (Test-Path -LiteralPath (Join-Path $protected 'sentinel.txt')) -or (Test-Path -LiteralPath $roots[1])) { throw 'Junction target was not protected.' }
    try { Remove-OdcTreeNoFollow -Path $validation -AllowedRoot $fixture; throw 'Outside cleanup allowed' } catch { if ($_.Exception.Message -eq 'Outside cleanup allowed') { throw } }
    Write-Output 'PASS: current/live/legacy and referenced backup protection, no unused configurations, junction target preservation, outside-root refusal.'
} finally {
    if (Test-Path -LiteralPath $fixture) { Remove-OdcTreeNoFollow -Path $fixture -AllowedRoot $validation }
}
