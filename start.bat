@echo off
setlocal
cd /d "%~dp0"

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"

set "exitCode=%ERRORLEVEL%"
endlocal & exit /b %exitCode%
