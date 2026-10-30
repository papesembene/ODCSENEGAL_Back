Set-StrictMode -Version 2.0

function New-OdcDeploymentMutex {
    # SYSTEM nightly jobs and administrator deployments must share the same lock.
    $security=[Security.AccessControl.MutexSecurity]::new()
    $security.SetAccessRuleProtection($true,$false)
    foreach ($sid in @('S-1-5-18','S-1-5-32-544')) {
        $security.AddAccessRule([Security.AccessControl.MutexAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))
    }
    $created=$false
    return [Threading.Mutex]::new($false,'Global\ODC-Production-Deployment',[ref]$created,$security)
}

function Test-OdcContainedPath([string]$Path, [string]$Root) {
    $full=[IO.Path]::GetFullPath($Path).TrimEnd('\')
    $base=[IO.Path]::GetFullPath($Root).TrimEnd('\')
    return $full.StartsWith($base+'\',[StringComparison]::OrdinalIgnoreCase)
}

function Remove-OdcTreeNoFollow([string]$Path,[string]$AllowedRoot) {
    $full=[IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not (Test-OdcContainedPath $full $AllowedRoot)) { throw 'Cleanup path outside allowed root.' }
    $parent=Split-Path -Parent $full
    while ($parent -and ($parent -ieq $AllowedRoot -or (Test-OdcContainedPath $parent $AllowedRoot))) {
        if ((Get-Item -LiteralPath $parent -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Cleanup ancestor cannot be a junction.' }
        if ($parent -ieq $AllowedRoot) { break }
        $parent=Split-Path -Parent $parent
    }
    $item=Get-Item -LiteralPath $full -Force -ErrorAction Stop
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        # DirectoryInfo.Delete removes the junction itself, never its target.
        if ($item -is [IO.DirectoryInfo]) { $item.Delete() } else { $item.Delete() }
        return
    }
    if ($item -is [IO.DirectoryInfo]) {
        foreach ($child in @($item.EnumerateFileSystemInfos())) {
            Remove-OdcTreeNoFollow $child.FullName $AllowedRoot
        }
        $item.Delete()
    } else {
        $item.Attributes=$item.Attributes -band (-bnot [IO.FileAttributes]::ReadOnly)
        $item.Delete()
    }
}

function Get-OdcLiveReferences([string]$Workspace) {
    # A failed inventory aborts cleanup instead of assuming that nothing uses a path.
    $refs=[Collections.Generic.List[string]]::new()
    foreach ($service in @(Get-CimInstance Win32_Service -ErrorAction Stop)) {
        if ($service.PathName) { $refs.Add([string]$service.PathName) }
        $key='HKLM:\SYSTEM\CurrentControlSet\Services\'+$service.Name+'\Parameters'
        if (Test-Path -LiteralPath $key) {
            $values=Get-Item -LiteralPath $key -ErrorAction Stop
            try {
                foreach ($name in @('Application','AppDirectory','AppParameters','AppStdout','AppStderr')) {
                    $value=[string]$values.GetValue($name,'')
                    if ($value) { $refs.Add($value) }
                }
            } finally { $values.Dispose() }
        }
    }
    foreach ($task in @(Get-ScheduledTask -ErrorAction Stop)) {
        foreach ($action in $task.Actions) {
            foreach ($name in @('Execute','Arguments','WorkingDirectory','Data')) {
                $property=$action.PSObject.Properties[$name]
                if ($property -and $property.Value) { $refs.Add([string]$property.Value) }
            }
        }
    }
    foreach ($process in @(Get-CimInstance Win32_Process -ErrorAction Stop)) {
        if ($process.ExecutablePath) { $refs.Add([string]$process.ExecutablePath) }
        if ($process.CommandLine) { $refs.Add([string]$process.CommandLine) }
    }
    foreach ($config in @('C:\inetpub\wwwroot\web.config','C:\inetpub\api\web.config')) {
        $refs.Add([IO.File]::ReadAllText($config))
    }
    # Protect a release used as the target of a junction anywhere in the workspace.
    $pending=[Collections.Generic.Stack[string]]::new()
    $pending.Push($Workspace)
    while ($pending.Count) {
        $directory=Get-Item -LiteralPath $pending.Pop() -Force -ErrorAction Stop
        foreach ($entry in $directory.EnumerateFileSystemInfos()) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                $link=Get-Item -LiteralPath $entry.FullName -Force -ErrorAction Stop
                foreach ($target in @($link.Target)) { if ($target) { $refs.Add([string]$target) } }
            } elseif ($entry -is [IO.DirectoryInfo]) { $pending.Push($entry.FullName) }
        }
    }
    return $refs.ToArray()
}

function Get-OdcRetentionPlan {
    param([string]$Workspace,[string[]]$References,[int]$KeepConfigurations=3)
    if ($KeepConfigurations -lt 3) { throw 'Keep at least three configuration backups.' }
    $backupRoot=Join-Path $Workspace 'archives\sauvegardes'
    $metadata=@()
    if (Test-Path -LiteralPath $backupRoot) {
        foreach ($dir in @(Get-ChildItem -LiteralPath $backupRoot -Directory -Force)) {
            $file=Join-Path $dir.FullName 'retention.json'
            if ($dir.Name -notmatch '^_odc-prod-backup-\d{8}-\d{6}-\d{3}$' -or -not (Test-Path -LiteralPath $file)) { continue }
            $record=Get-Content -LiteralPath $file -Raw -ErrorAction Stop | ConvertFrom-Json
            if ($record.Schema -ne 1 -or $record.Component -notin @('backend','frontend') -or $record.Status -notin @('published','prepared')) { throw 'Invalid retention metadata; cleanup refused.' }
            $metadata += [pscustomobject]@{Directory=$dir.FullName; Record=$record; Completed=[DateTime]::Parse($record.CompletedUtc)}
        }
    }
    $protected=[Collections.Generic.List[string]]::new()
    foreach ($reference in $References) { if ($reference) { $protected.Add($reference) } }
    $oldBackups=@()
    foreach ($component in @('backend','frontend')) {
        $ordered=@($metadata | Where-Object { $_.Record.Component -eq $component -and $_.Record.Status -eq 'published' } | Sort-Object Completed -Descending)
        if ($ordered.Count) {
            foreach ($path in @($ordered[0].Record.CurrentRoot,$ordered[0].Record.PreviousRoot)) {
                if ($path) { $protected.Add([string]$path) }
            }
            $oldBackups+=@($ordered | Select-Object -Skip $KeepConfigurations)
        }
        $incomplete=@($metadata | Where-Object { $_.Record.Component -eq $component -and $_.Record.Status -eq 'prepared' } | Sort-Object Completed -Descending)
        $oldBackups+=@($incomplete | Select-Object -Skip 3)
    }
    foreach ($directory in @(Get-ChildItem -LiteralPath $Workspace -Directory -Force)) {
        if ($directory.Name -notmatch '^_odc-prod-release-\d{8}-\d{6}-\d{3}$') { continue }
        $marker=Join-Path $directory.FullName 'odc-release.json'
        if (-not (Test-Path -LiteralPath $marker)) { continue } # Preserve unadopted legacy folders.
        $record=Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        if ($record.Schema -ne 1 -or $record.Component -notin @('backend','frontend')) { throw 'Invalid release marker.' }
        if ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Release root cannot be a junction.' }
        $used=@($protected | Where-Object { $_.IndexOf($directory.FullName,[StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -gt 0
        if (-not $used) { [pscustomobject]@{Kind='release';Path=$directory.FullName;AllowedRoot=$Workspace} }
    }
    foreach ($backup in $oldBackups) {
        $used=@($protected | Where-Object { $_.IndexOf($backup.Directory,[StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -gt 0
        if (-not $used) { [pscustomobject]@{Kind='configuration';Path=$backup.Directory;AllowedRoot=$backupRoot} }
    }
    foreach ($relative in @('ops\backend-recovery\backups','ops\frontend-recovery\backups')) {
        $root=Join-Path $Workspace $relative
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $snapshots=@(Get-ChildItem -LiteralPath $root -Directory | Where-Object { $_.Name -match '^service-watchdog-\d{8}T\d{6,}$' } | Sort-Object Name -Descending)
        foreach ($snapshot in @($snapshots | Select-Object -Skip 3)) {
            if (@($protected | Where-Object { $_.IndexOf($snapshot.FullName,[StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -eq 0) {
                [pscustomobject]@{Kind='watchdog-configuration';Path=$snapshot.FullName;AllowedRoot=$root}
            }
        }
    }
}

function Save-OdcPublishedDeployment {
    param([string]$Component,[string]$ReleaseRoot,[string]$PreviousPath,[string]$BackupDirectory,[ValidateSet('published','prepared')][string]$Status='published')
    $workspace='C:\Orange Digital Center'
    if ($Component -notin @('backend','frontend') -or -not (Test-OdcContainedPath $ReleaseRoot $workspace) -or
        -not (Test-OdcContainedPath $BackupDirectory (Join-Path $workspace 'archives\sauvegardes'))) { throw 'Invalid deployment retention paths.' }
    $previousRoot=Split-Path -Parent $PreviousPath
    $record=@{Schema=1;Component=$Component;Status=$Status;CurrentRoot=$ReleaseRoot;PreviousRoot=$previousRoot;CompletedUtc=[DateTime]::UtcNow.ToString('o')}
    $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ReleaseRoot 'odc-release.json') -Encoding UTF8
    $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $BackupDirectory 'retention.json') -Encoding UTF8
}
