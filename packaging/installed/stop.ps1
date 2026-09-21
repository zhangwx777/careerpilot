$ErrorActionPreference = 'SilentlyContinue'

$dataRoot = Join-Path $env:LOCALAPPDATA 'CareerPilot'
$stateFile = Join-Path $dataRoot 'runtime.json'
if (-not (Test-Path -LiteralPath $stateFile)) { exit 0 }

$state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
foreach ($processId in @($state.desktop_pid, $state.backend_pid, $state.worker_pid, $state.queue_pid)) {
    if ($null -ne $processId) { Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue }
}

$pgCtl = Join-Path $PSScriptRoot 'postgresql\bin\pg_ctl.exe'
if (Test-Path -LiteralPath $pgCtl) {
    & $pgCtl -D ([string]$state.db_data) stop -m fast *> (Join-Path $dataRoot 'logs\postgres-stop.log')
}
Remove-Item -LiteralPath $stateFile -Force
