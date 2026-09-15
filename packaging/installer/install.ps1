$ErrorActionPreference = 'Stop'

$sourceRoot = $PSScriptRoot
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\CareerPilot'
$startMenuRoot = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\职航 CareerPilot'
$desktop = [Environment]::GetFolderPath('Desktop')

if (Test-Path -LiteralPath (Join-Path $installRoot 'stop.ps1')) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $installRoot 'stop.ps1')
}
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
Expand-Archive -LiteralPath (Join-Path $sourceRoot 'payload.zip') -DestinationPath $installRoot -Force

New-Item -ItemType Directory -Force -Path $startMenuRoot | Out-Null
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut([string]$path, [string]$target, [string]$arguments) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $installRoot
    $shortcut.Save()
}

$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
New-Shortcut (Join-Path $desktop '职航 CareerPilot.lnk') $wscript "`"$installRoot\start.vbs`""
New-Shortcut (Join-Path $startMenuRoot '启动职航 CareerPilot.lnk') $wscript "`"$installRoot\start.vbs`""
New-Shortcut (Join-Path $startMenuRoot '停止职航 CareerPilot.lnk') $powershell "-NoProfile -ExecutionPolicy Bypass -File `"$installRoot\stop.ps1`""
New-Shortcut (Join-Path $startMenuRoot '卸载职航 CareerPilot.lnk') $powershell "-NoProfile -ExecutionPolicy Bypass -File `"$installRoot\uninstall.ps1`""

Start-Process -FilePath $wscript -ArgumentList ('"{0}"' -f (Join-Path $installRoot 'start.vbs'))
