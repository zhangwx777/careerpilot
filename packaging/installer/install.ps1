$ErrorActionPreference = 'Stop'

$sourceRoot = $PSScriptRoot
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\CareerPilot'
$startMenuRoot = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\职航 CareerPilot'
$desktop = [Environment]::GetFolderPath('Desktop')

if (Test-Path -LiteralPath (Join-Path $installRoot 'stop.ps1')) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $installRoot 'stop.ps1')
}
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
Copy-Item -Path (Join-Path $sourceRoot '*') -Destination $installRoot -Recurse -Force

New-Item -ItemType Directory -Force -Path $startMenuRoot | Out-Null
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut([string]$path, [string]$target, [string]$arguments, [string]$iconPath) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $installRoot
    if (Test-Path -LiteralPath $iconPath) { $shortcut.IconLocation = "$iconPath,0" }
    $shortcut.Save()
}

$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$icon = Join-Path $installRoot 'brand-mark.ico'
New-Shortcut (Join-Path $desktop '职航 CareerPilot.lnk') $wscript "`"$installRoot\start.vbs`"" $icon
New-Shortcut (Join-Path $startMenuRoot '启动职航 CareerPilot.lnk') $wscript "`"$installRoot\start.vbs`"" $icon
New-Shortcut (Join-Path $startMenuRoot '停止职航 CareerPilot.lnk') $powershell "-NoProfile -ExecutionPolicy Bypass -File `"$installRoot\stop.ps1`"" $icon
New-Shortcut (Join-Path $startMenuRoot '卸载职航 CareerPilot.lnk') $powershell "-NoProfile -ExecutionPolicy Bypass -File `"$installRoot\uninstall.ps1`"" $icon

Start-Process -FilePath $wscript -ArgumentList ('"{0}"' -f (Join-Path $installRoot 'start.vbs'))
