param(
    [switch]$Test
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$guiScript = Join-Path $root 'Local_Video_gui.py'
$envPath = Join-Path $root '.env'

if (-not (Test-Path $guiScript)) {
    throw "Missing GUI script: $guiScript"
}

$pythonExe = $null

if (Test-Path $envPath) {
    foreach ($line in Get-Content $envPath -Encoding UTF8) {
        if ($line -match '^\s*APP_PYTHON_EXE\s*=\s*(.+?)\s*$') {
            $candidate = $matches[1].Trim().Trim('"').Trim("'")
            if ($candidate -and (Test-Path $candidate)) {
                $pythonExe = $candidate
                break
            }
        }
    }
}

if (-not $pythonExe) {
    $candidates = @(
        (Join-Path $root '.venv\Scripts\pythonw.exe'),
        (Join-Path $root '.venv\Scripts\python.exe'),
        (Join-Path $root 'venv\Scripts\pythonw.exe'),
        (Join-Path $root 'venv\Scripts\python.exe')
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $pythonExe = $candidate
            break
        }
    }
}

if (-not $pythonExe) {
    foreach ($commandName in @('pyw.exe', 'py.exe', 'pythonw.exe', 'python.exe')) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source) {
            $pythonExe = $command.Source
            break
        }
    }
}

if (-not $pythonExe) {
    throw 'No usable Python interpreter was found. Please set APP_PYTHON_EXE in .env.'
}

if ($Test) {
    Write-Output "[TEST] Interpreter resolved: $pythonExe"
    exit 0
}

Write-Output "[START] Using interpreter: $pythonExe"
Start-Process -FilePath $pythonExe -ArgumentList @($guiScript) -WorkingDirectory $root
