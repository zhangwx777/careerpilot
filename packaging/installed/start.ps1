$ErrorActionPreference = 'Stop'

$appRoot = $PSScriptRoot
$dataRoot = Join-Path $env:LOCALAPPDATA 'CareerPilot'
$dbData = Join-Path $dataRoot 'postgres'
$stateFile = Join-Path $dataRoot 'runtime.json'
$logRoot = Join-Path $dataRoot 'logs'
$pgBin = Join-Path $appRoot 'postgresql\bin'
$backendExe = Join-Path $appRoot 'CareerPilotBackend.exe'

New-Item -ItemType Directory -Force -Path $dataRoot, $logRoot | Out-Null

function Find-FreePort([int]$preferred) {
    for ($port = $preferred; $port -lt ($preferred + 100); $port++) {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        try {
            $listener.Start()
            $listener.Stop()
            return $port
        } catch {
            $listener.Stop()
        }
    }
    throw '没有找到可用端口。'
}

function Test-Backend([int]$port) {
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2
        return $health.status -eq 'ok' -and $health.db -eq $true
    } catch {
        return $false
    }
}

function Test-Postgres([int]$port) {
    & $pgIsReady -h 127.0.0.1 -p $port *> $null
    return $LASTEXITCODE -eq 0
}

if (Test-Path -LiteralPath $stateFile) {
    try {
        $state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
        if (Test-Backend ([int]$state.backend_port)) {
            Start-Process "http://127.0.0.1:$([int]$state.backend_port)" | Out-Null
            exit 0
        }
    } catch {
        Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $backendExe)) {
    throw '安装文件不完整，请重新安装。'
}

$initdb = Join-Path $pgBin 'initdb.exe'
$pgCtl = Join-Path $pgBin 'pg_ctl.exe'
$pgIsReady = Join-Path $pgBin 'pg_isready.exe'
$pgShare = Join-Path $appRoot 'postgresql\share'
if (-not (Test-Path -LiteralPath $initdb) -or -not (Test-Path -LiteralPath $pgCtl) -or -not (Test-Path -LiteralPath $pgIsReady)) {
    throw '本地数据库运行文件缺失，请重新安装。'
}

New-Item -ItemType Directory -Force -Path $dbData | Out-Null
$pgStatus = & $pgCtl -D $dbData status 2>$null
if ($LASTEXITCODE -eq 0) {
    & $pgCtl -D $dbData stop -m fast *> (Join-Path $logRoot 'postgres-stop.log')
    Start-Sleep -Milliseconds 500
}
$dbPort = Find-FreePort 55432
if (-not (Test-Path -LiteralPath (Join-Path $dbData 'PG_VERSION'))) {
    $initLog = Join-Path $logRoot 'initdb.log'
    & $initdb -D $dbData -L $pgShare -U qiuzhao_app -A trust --encoding=UTF8 --no-locale *> $initLog
    if ($LASTEXITCODE -ne 0) { throw '本地数据库初始化失败，请查看日志。' }
}

$pgLog = Join-Path $logRoot 'postgres.log'
$pgStart = Start-Process -FilePath $pgCtl -ArgumentList "-D `"$dbData`" -l `"$pgLog`" -o `"-h 127.0.0.1 -p $dbPort`" start -W" -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'postgres-start.log') -RedirectStandardError (Join-Path $logRoot 'postgres-start-error.log')
$pgReady = $false
for ($i = 0; $i -lt 40; $i++) {
    if (Test-Postgres $dbPort) { $pgReady = $true; break }
    if ($pgStart.HasExited -and $pgStart.ExitCode -ne 0) { break }
    Start-Sleep -Milliseconds 500
}
if (-not $pgReady) {
    if (-not $pgStart.HasExited) { Stop-Process -Id $pgStart.Id -Force -ErrorAction SilentlyContinue }
    throw '本地数据库启动失败，请查看日志。'
}
if (-not $pgStart.HasExited) { Stop-Process -Id $pgStart.Id -Force -ErrorAction SilentlyContinue }

$backendPort = Find-FreePort 58080
$env:DATABASE_URL = "postgresql+psycopg://qiuzhao_app@127.0.0.1:$dbPort/postgres"
$env:TEST_DATABASE_URL = ''
$env:QIUZHAO_BACKEND_PORT = [string]$backendPort
$backendLog = Join-Path $logRoot 'backend.log'
$backendProc = Start-Process -FilePath $backendExe -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $backendLog -RedirectStandardError (Join-Path $logRoot 'backend-error.log')

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    if (Test-Backend $backendPort) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    if (-not $backendProc.HasExited) { Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue }
    & $pgCtl -D $dbData stop -m fast *> (Join-Path $logRoot 'postgres-stop.log')
    throw '应用启动失败，请查看本地日志。'
}

@{
    backend_pid = $backendProc.Id
    backend_port = $backendPort
    db_port = $dbPort
    db_data = $dbData
} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8

Start-Process "http://127.0.0.1:$backendPort" | Out-Null
