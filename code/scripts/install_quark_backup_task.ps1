param(
    [string]$TaskName = 'LocalVideoRenamer-QuarkBackup',
    [string]$At = '03:00'
)

$ErrorActionPreference = 'Stop'
$CodeRoot = Split-Path -Parent $PSScriptRoot
$LayoutRoot = Split-Path -Parent $CodeRoot
$EnvPath = Join-Path (Join-Path (Join-Path $LayoutRoot 'user_data') 'config') '.env'

if (-not (Test-Path -LiteralPath $EnvPath)) {
    throw "Missing configured environment file: $EnvPath"
}

$PythonExe = ''
foreach ($line in Get-Content -LiteralPath $EnvPath -Encoding UTF8) {
    if ($line -match '^\s*APP_PYTHON_EXE\s*=\s*(.+?)\s*$') {
        $PythonExe = $matches[1].Trim().Trim('"').Trim("'")
        break
    }
}
if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) {
    throw 'APP_PYTHON_EXE must point to the configured project interpreter.'
}

$RunScript = Join-Path (Join-Path $CodeRoot 'scripts') 'run_quark_backup.py'
$AtTime = [datetime]::ParseExact($At, 'HH:mm', $null)
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument ('"{0}"' -f $RunScript) -WorkingDirectory $CodeRoot
$Trigger = New-ScheduledTaskTrigger -Daily -DaysInterval 5 -At $AtTime
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 8)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Upload Local Video Renamer user_data to Quark Pan every five days.' -Force | Out-Null
Write-Output "Registered scheduled task: $TaskName at $At every 5 days."
