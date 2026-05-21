@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PS_SCRIPT=%~dp0start_vidnorm.ps1"
if not exist "%PS_SCRIPT%" (
    echo [ERROR] Missing launcher script: %PS_SCRIPT%
    pause
    exit /b 1
)

if /i "%~1"=="--test" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -Test
) else if /i "%VIDNORM_LAUNCHER_TEST%"=="1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -Test
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"
)

if errorlevel 1 pause
exit /b %errorlevel%
