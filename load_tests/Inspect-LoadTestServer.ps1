# Read-only preparation for a JMeter run. No HTTP requests, email, installation,
# service changes, database access, or credential output.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$report = [ordered]@{
    purpose = 'Preparation JMeter uniquement - aucune charge lancee'
    email_safety_verified = $false
    errors = @()
}

try {
    $system = Get-CimInstance Win32_ComputerSystem
    $os = Get-CimInstance Win32_OperatingSystem
    $report.machine = [ordered]@{
        name = $env:COMPUTERNAME
        os = $os.Caption
        logical_processors = $system.NumberOfLogicalProcessors
        ram_gb = [math]::Round($system.TotalPhysicalMemory / 1GB, 2)
        free_ram_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    }
} catch { $report.errors += 'Lecture des ressources Windows impossible.' }

try {
    $report.odc_services = @(Get-Service | Where-Object {
        $_.Name -match 'ODC|Mongo|Redis' -or $_.DisplayName -match 'Orange Digital'
    } | Select-Object Name, @{Name='Status'; Expression={ [string]$_.Status }})
} catch { $report.errors += 'Lecture des services impossible.' }

try {
    $report.odc_tasks = @(Get-ScheduledTask | Where-Object {
        $_.TaskName -match 'ODC|email|mail-worker'
    } | Select-Object TaskName, @{Name='State'; Expression={ [string]$_.State }})
} catch { $report.errors += 'Lecture des taches impossible; utiliser PowerShell administrateur.' }

try {
    # Inspect command lines for identification, but never include them in output.
    $workers = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -match '(?i)\bemail_worker\.py\b'
    })
    $report.visible_email_worker_pids = @($workers | ForEach-Object { $_.ProcessId })
    $report.email_note = 'L absence de processus visible ne prouve pas le blocage des emails ni de leur mise en file.'
} catch { $report.errors += 'Identification des workers email impossible.' }

$report.tools_on_path = @('java', 'jmeter', 'python') | ForEach-Object {
    $name = $_
    $found = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    [pscustomobject]@{ name = $name; found_on_path = [bool]$found }
}

try {
    $report.dns = @('orangedigitalcenter.sn', 'api.orangedigitalcenter.sn') | ForEach-Object {
        $hostname = $_
        try {
            [pscustomobject]@{
                host = $hostname
                addresses = @([System.Net.Dns]::GetHostAddresses($hostname) |
                    ForEach-Object { $_.IPAddressToString })
            }
        } catch {
            [pscustomobject]@{ host = $hostname; addresses = @(); error = 'DNS indisponible' }
        }
    }
} catch { $report.errors += 'Resolution DNS impossible.' }

$report | ConvertTo-Json -Depth 6
