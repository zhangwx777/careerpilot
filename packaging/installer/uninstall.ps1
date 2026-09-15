$ErrorActionPreference = 'SilentlyContinue'

$installRoot = Split-Path -Parent $PSScriptRoot
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $installRoot 'stop.ps1')

$desktop = [Environment]::GetFolderPath('Desktop')
$startMenuRoot = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\职航 CareerPilot'
Remove-Item -LiteralPath (Join-Path $desktop '职航 CareerPilot.lnk') -Force
Remove-Item -LiteralPath $startMenuRoot -Recurse -Force

$cleanup = "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$installRoot' -Recurse -Force"
Start-Process powershell.exe -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cleanup -WindowStyle Hidden
