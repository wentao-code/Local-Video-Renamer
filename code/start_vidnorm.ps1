param(
    [switch]$Test,
    [switch]$Legacy
)

$ErrorActionPreference = 'Stop'

function Resolve-PythonInterpreter {
    param(
        [string]$CodeRoot,
        [string]$LayoutRoot,
        [switch]$PreferConsole
    )

    $envPath = Join-Path (Join-Path (Join-Path $LayoutRoot 'user_data') 'config') '.env'
    $legacyEnvPath = Join-Path $CodeRoot '.env'
    if (-not (Test-Path $envPath) -and (Test-Path $legacyEnvPath)) {
        $envPath = $legacyEnvPath
    }
    if (Test-Path $envPath) {
        foreach ($line in Get-Content $envPath -Encoding UTF8) {
            if ($line -match '^\s*APP_PYTHON_EXE\s*=\s*(.+?)\s*$') {
                $candidate = $matches[1].Trim().Trim('"').Trim("'")
                if ($candidate -and (Test-Path $candidate)) {
                    if ($PreferConsole -and $candidate.ToLower().EndsWith('pythonw.exe')) {
                        $consoleCandidate = Join-Path (Split-Path $candidate -Parent) 'python.exe'
                        if (Test-Path $consoleCandidate) {
                            return $consoleCandidate
                        }
                    }
                    return $candidate
                }
            }
        }
    }

    $candidates = @()
    if ($PreferConsole) {
        $candidates += @(
            (Join-Path $CodeRoot '.venv\Scripts\python.exe'),
            (Join-Path $CodeRoot 'venv\Scripts\python.exe'),
            (Join-Path $CodeRoot '.venv\Scripts\pythonw.exe'),
            (Join-Path $CodeRoot 'venv\Scripts\pythonw.exe')
        )
    }
    else {
        $candidates += @(
            (Join-Path $CodeRoot '.venv\Scripts\pythonw.exe'),
            (Join-Path $CodeRoot '.venv\Scripts\python.exe'),
            (Join-Path $CodeRoot 'venv\Scripts\pythonw.exe'),
            (Join-Path $CodeRoot 'venv\Scripts\python.exe')
        )
    }

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $commandNames = if ($PreferConsole) {
        @('python.exe', 'py.exe', 'pythonw.exe', 'pyw.exe')
    }
    else {
        @('pythonw.exe', 'pyw.exe', 'python.exe', 'py.exe')
    }

    foreach ($commandName in $commandNames) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source) {
            return $command.Source
        }
    }

    return $null
}

$codeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$layoutRoot = Split-Path -Parent $codeRoot
$guiScript = Join-Path $codeRoot 'Local_Video_gui.py'
$safeLauncher = Join-Path $codeRoot 'safe_start_vidnorm.py'

if (-not (Test-Path $guiScript)) {
    throw "Missing GUI script: $guiScript"
}

if (-not (Test-Path $safeLauncher)) {
    throw "Missing safe launcher: $safeLauncher"
}

if ($Legacy) {
    $pythonExe = Resolve-PythonInterpreter -CodeRoot $codeRoot -LayoutRoot $layoutRoot
    if (-not $pythonExe) {
        throw 'No usable Python interpreter was found. Please set APP_PYTHON_EXE in user_data/config/.env.'
    }

    if ($Test) {
        Write-Output "[TEST] Legacy interpreter resolved: $pythonExe"
        exit 0
    }

    Write-Output "[START] Legacy mode using interpreter: $pythonExe"
    Start-Process -FilePath $pythonExe -ArgumentList @($guiScript) -WorkingDirectory $codeRoot
    exit 0
}

$pythonExe = Resolve-PythonInterpreter -CodeRoot $codeRoot -LayoutRoot $layoutRoot -PreferConsole
if (-not $pythonExe) {
    throw 'No usable Python interpreter was found. Please set APP_PYTHON_EXE in user_data/config/.env.'
}

if ($Test) {
    & $pythonExe $safeLauncher --test
    exit $LASTEXITCODE
}

Write-Output "[START] Safe mode using interpreter: $pythonExe"
& $pythonExe $safeLauncher
exit $LASTEXITCODE
