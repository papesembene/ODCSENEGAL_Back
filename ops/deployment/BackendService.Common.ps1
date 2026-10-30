Set-StrictMode -Version 2.0

function Assert-BackendServiceName([string]$ServiceName) {
    if ($ServiceName -notmatch '^ODC-PROD-API(-SECONDARY)?$') { throw 'Unexpected API service name.' }
}

function Get-BackendWorkspacePath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $full.StartsWith('C:\Orange Digital Center\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside ODC workspace.' }
    return $full
}

function Get-BackendNssmContext {
    param([Parameter(Mandatory)][string]$ServiceName)
    Assert-BackendServiceName $ServiceName
    $service = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction Stop
    $nssm = 'C:\Orange Digital Center\ops\frontend-recovery\bin\nssm.exe'
    if (-not $service -or $service.PathName.Trim('"') -ine $nssm) { throw 'Missing or unrecognized API service.' }
    $key = Get-Item -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters" -ErrorAction Stop
    try {
        $backend = Get-BackendWorkspacePath ([string]$key.GetValue('AppDirectory', ''))
        $python = [string]$key.GetValue('Application', '')
        $arguments = [string]$key.GetValue('AppParameters', '')
        $extra = @($key.GetValue('AppEnvironmentExtra', @()))
    } finally { $key.Dispose() }
    if ($python -ine (Join-Path $backend '.venv\Scripts\python.exe') -or $arguments -cne 'run.py') { throw 'Unexpected API command.' }
    $values = @{}
    foreach ($entry in $extra) {
        $pair = $entry -split '=', 2
        if ($pair.Count -ne 2 -or $values.ContainsKey($pair[0])) { throw 'Invalid API environment.' }
        $values[$pair[0]] = $pair[1]
    }
    if ($values['FLASK_ENV'] -cne 'production' -or $values['HOST'] -cne '127.0.0.1' -or
        $values['PORT'] -notmatch '^\d+$' -or [int]$values['PORT'] -lt 1024 -or [int]$values['PORT'] -gt 65535 -or
        -not $values['ODC_ENV_FILE']) { throw 'Unexpected API service environment.' }
    $envFile = Get-BackendWorkspacePath $values['ODC_ENV_FILE']
    foreach ($path in @($python, $envFile, (Join-Path $backend 'run.py'))) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing API file: $path" }
    }
    [pscustomobject]@{ Name=$ServiceName; Service=$service; Backend=$backend; Python=$python; Port=[int]$values['PORT']; EnvFile=$envFile; Logs=(Join-Path $backend 'ops-logs') }
}

function Get-PublishedBackendPort {
    param([string]$SiteConfig='C:\inetpub\wwwroot\web.config', [string]$ApiConfig='C:\inetpub\api\web.config')
    [xml]$site = [IO.File]::ReadAllText($SiteConfig)
    [xml]$api = [IO.File]::ReadAllText($ApiConfig)
    $siteAction = $site.SelectSingleNode("/configuration/system.webServer/rewrite/rules/rule[@name='ReverseProxyToAPI']/action")
    $apiAction = $api.SelectSingleNode("/configuration/system.webServer/rewrite/rules/rule[@name='ReverseProxyInboundRule1']/action")
    if (-not $siteAction -or -not $apiAction) { throw 'Missing IIS API routes.' }
    $siteMatch = [regex]::Match($siteAction.url, '^http://127\.0\.0\.1:(\d+)/api/\{R:1\}$')
    $apiMatch = [regex]::Match($apiAction.url, '^http://127\.0\.0\.1:(\d+)/\{R:1\}$')
    if (-not $siteMatch.Success -or -not $apiMatch.Success -or $siteMatch.Groups[1].Value -ne $apiMatch.Groups[1].Value) { throw 'IIS API routes disagree.' }
    return [int]$siteMatch.Groups[1].Value
}

function Get-PublishedBackendNssmContext {
    param([string]$SiteConfig='C:\inetpub\wwwroot\web.config', [string]$ApiConfig='C:\inetpub\api\web.config')
    $port = Get-PublishedBackendPort $SiteConfig $ApiConfig
    $contexts = @()
    foreach ($name in @('ODC-PROD-API','ODC-PROD-API-SECONDARY')) {
        if (Get-Service -Name $name -ErrorAction SilentlyContinue) {
            $context = Get-BackendNssmContext $name
            if ($context.Port -eq $port) { $contexts += $context }
        }
    }
    if ($contexts.Count -ne 1) { throw 'Exactly one validated API service must match IIS.' }
    return $contexts[0]
}

function Set-BackendNssmService {
    param([Parameter(Mandatory)][string]$ServiceName, [Parameter(Mandatory)][string]$BackendPath,
        [Parameter(Mandatory)][ValidateRange(1024,65535)][int]$Port, [Parameter(Mandatory)][string]$EnvFile)
    Assert-BackendServiceName $ServiceName
    $backend = Get-BackendWorkspacePath ((Resolve-Path -LiteralPath $BackendPath).Path)
    $envFile = Get-BackendWorkspacePath ((Resolve-Path -LiteralPath $EnvFile).Path)
    $python = Join-Path $backend '.venv\Scripts\python.exe'
    $nssm = 'C:\Orange Digital Center\ops\frontend-recovery\bin\nssm.exe'
    foreach ($path in @($python,$envFile,$nssm,(Join-Path $backend 'run.py'))) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing API file: $path" }
    }
    $service = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction Stop
    if ($service) {
        if ($service.State -ne 'Stopped' -or $service.PathName.Trim('"') -ine $nssm) { throw 'Refusing to reconfigure running or unknown API service.' }
    } else {
        New-Service -Name $ServiceName -BinaryPathName ('"'+$nssm+'"') -StartupType Manual -Description 'ODC API supervised directly by NSSM.' | Out-Null
    }
    $logs = Join-Path $backend 'ops-logs'
    $null = New-Item -ItemType Directory -Path $logs -Force
    $parameters = "SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters"
    $key = [Microsoft.Win32.Registry]::LocalMachine.CreateSubKey($parameters)
    try {
        $strings = @{ Application=$python; AppDirectory=$backend; AppParameters='run.py'; AppStdout=(Join-Path $logs 'nssm.stdout.log'); AppStderr=(Join-Path $logs 'nssm.stderr.log') }
        foreach ($entry in $strings.GetEnumerator()) { $key.SetValue($entry.Key,$entry.Value,[Microsoft.Win32.RegistryValueKind]::String) }
        $key.SetValue('AppEnvironmentExtra',[string[]]@('FLASK_ENV=production','HOST=127.0.0.1',"PORT=$Port","ODC_ENV_FILE=$envFile"),[Microsoft.Win32.RegistryValueKind]::MultiString)
        $numbers = @{ AppRestartDelay=2000; AppThrottle=1500; AppKillProcessTree=1; AppRotateFiles=1; AppRotateOnline=1; AppRotateSeconds=86400; AppRotateBytes=10485760 }
        foreach ($entry in $numbers.GetEnumerator()) { $key.SetValue($entry.Key,[int]$entry.Value,[Microsoft.Win32.RegistryValueKind]::DWord) }
    } finally { $key.Dispose() }
    $exitKey = [Microsoft.Win32.Registry]::LocalMachine.CreateSubKey($parameters+'\AppExit')
    try { $exitKey.SetValue('','Restart',[Microsoft.Win32.RegistryValueKind]::String) } finally { $exitKey.Dispose() }
    & sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to configure API service recovery.' }
    & sc.exe failureflag $ServiceName 1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to configure API service recovery flag.' }
}

function Get-BackendListenerProcess([int]$Port) {
    $ids = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($processId in $ids) { Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction Stop }
}

function Test-OwnedNssmBackendPython {
    param($Process,$Context)
    # Windows venv Python can launch the base interpreter as a child; validate that chain.
    if ($Process.Name -ine 'python.exe' -or $Process.CommandLine -notmatch '(?i)(?:^|\s)"?run\.py"?(?:\s|$)' -or $Context.Service.ProcessId -le 0) { return $false }
    $current = $Process
    for ($depth=0; $depth -lt 3; $depth++) {
        if ($current.ExecutablePath -ieq $Context.Python -and $current.ParentProcessId -eq $Context.Service.ProcessId) { return $true }
        if ($current.ParentProcessId -le 0) { return $false }
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($current.ParentProcessId)" -ErrorAction SilentlyContinue
        if (-not $current -or $current.Name -ine 'python.exe') { return $false }
    }
    return $false
}

function Test-BackendHealth {
    param([int]$Port,[int]$TimeoutSeconds=5)
    $response = $null
    try {
        $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/health")
        $request.Proxy=$null; $request.Timeout=$TimeoutSeconds*1000; $request.ReadWriteTimeout=$TimeoutSeconds*1000; $request.AllowAutoRedirect=$false
        try { $response = $request.GetResponse() }
        catch [Net.WebException] { if ($_.Exception.Response) { $response=$_.Exception.Response } else { throw } }
        $reader = [IO.StreamReader]::new($response.GetResponseStream())
        try { $body = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($body.service -ne 'candidatures-api' -or $body.environment -ne 'production') { throw 'Unexpected health response.' }
        $dependencies = @($body.dependencies.PSObject.Properties)
        $up = ($dependencies.Count -gt 0 -and @($dependencies | Where-Object { $_.Value.status -ne 'up' }).Count -eq 0)
        [pscustomobject]@{ Responsive=$true; DependencyHealthy=$up; Healthy=([int]$response.StatusCode -eq 200 -and $body.status -eq 'healthy' -and $up); Detail=("HTTP $([int]$response.StatusCode); status=$($body.status)") }
    } catch {
        [pscustomobject]@{ Responsive=$false; DependencyHealthy=$false; Healthy=$false; Detail=$_.Exception.Message }
    } finally { if ($response) { $response.Close() } }
}

function Write-BackendRecoveryLog([string]$Directory,[string]$Name,[string]$Message) {
    $null = New-Item -ItemType Directory -Path $Directory -Force
    $path = Join-Path $Directory $Name
    if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 2MB) { Move-Item -LiteralPath $path -Destination ($path+'.1') -Force }
    Add-Content -LiteralPath $path -Encoding UTF8 -Value ([DateTime]::UtcNow.ToString('o')+' '+$Message)
}

function Set-BackendIisTextAtomic([string]$Path,[string]$Content) {
    if ([IO.Path]::GetFullPath($Path) -notin @('C:\inetpub\wwwroot\web.config','C:\inetpub\api\web.config')) { throw 'Unexpected IIS configuration path.' }
    [xml]$xml = $Content
    if ($xml.DocumentElement.Name -ne 'configuration') { throw 'Invalid IIS XML.' }
    $staged=$Path+'.odc-'+[guid]::NewGuid().ToString('N')+'.tmp'
    $backup=$staged+'.bak'
    try {
        [IO.File]::WriteAllText($staged,$Content,[Text.UTF8Encoding]::new($false))
        [IO.File]::Replace($staged,$Path,$backup)
    } finally {
        foreach ($temporary in @($staged,$backup)) {
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
        }
    }
}
