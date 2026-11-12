param(
    [Parameter(Mandatory)][string]$BaselineInstaller,
    [Parameter(Mandatory)][string]$CandidateInstaller,
    [Parameter(Mandatory)][string]$TestRoot
)
$ErrorActionPreference = 'Stop'
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
if (Test-Path -LiteralPath $TestRoot) { throw '验收目录必须不存在，禁止复用用户数据目录。' }
if ((Split-Path -Leaf $TestRoot) -notlike 'careerpilot-upgrade-*') { throw '验收目录名称必须以 careerpilot-upgrade- 开头。' }
New-Item -ItemType Directory -Path $TestRoot | Out-Null
$installRoot = Join-Path $TestRoot 'installed'
$dataRoot = Join-Path $TestRoot 'local/CareerPilot'
$stateFile = Join-Path $dataRoot 'runtime.json'
$oldLocal = $env:LOCALAPPDATA
$oldRoaming = $env:APPDATA
$desktop = $null
$state = $null

function Install-TestApp([string]$installer) {
    $process = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS','/TASKS=""', ('/DIR="' + $installRoot + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "安装失败：$($process.ExitCode)" }
}
function Start-TestApp {
    $script:desktop = Start-Process -FilePath (Join-Path $installRoot 'CareerPilot.exe') -ArgumentList ('--user-data-dir="' + (Join-Path $TestRoot 'user-data') + '"') -WindowStyle Hidden -PassThru
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if (Test-Path -LiteralPath $stateFile) {
            $script:state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
            $url = 'http://127.0.0.1:' + $state.backend_port
            $health = Invoke-RestMethod -Uri ($url + '/health') -NoProxy
            if ($health.status -ne 'ok') { throw '桌面服务未健康就绪' }
            return $url
        }
        if ($desktop.HasExited) { throw '桌面进程在就绪前退出' }
        Start-Sleep -Seconds 2
    }
    throw '桌面服务启动超时'
}
function Stop-TestApp {
    if (-not $desktop) { return }
    if (-not $desktop.HasExited) {
        if (-not $desktop.CloseMainWindow()) { throw '无法正常关闭桌面窗口' }
        if (-not $desktop.WaitForExit(30000)) { throw '桌面进程未正常退出' }
    }
    if ($state) {
        foreach ($childId in @($state.backend_pid, $state.worker_pid, $state.queue_pid)) {
            if (Get-Process -Id $childId -ErrorAction SilentlyContinue) { throw "退出后子进程仍运行：$childId" }
        }
        $postgresData = [IO.Path]::GetFullPath([string]$state.db_data)
        if (-not $postgresData.StartsWith($TestRoot + [IO.Path]::DirectorySeparatorChar)) { throw '数据库路径越过验收目录' }
        & (Join-Path $installRoot 'runtime/postgresql/bin/pg_ctl.exe') -D $postgresData status *> $null
        if ($LASTEXITCODE -eq 0) { throw '退出后数据库仍运行' }
        if ($LASTEXITCODE -ne 3) { throw '无法确认数据库已停止' }
    }
    $script:desktop = $null
    $script:state = $null
}
function Invoke-BackupTool([string[]]$arguments) {
    $process = Start-Process -FilePath (Join-Path $installRoot 'runtime/backend/CareerPilotBackend.exe') -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "备份工具失败：$($process.ExitCode)" }
}
try {
    $env:LOCALAPPDATA = Join-Path $TestRoot 'local'
    $env:APPDATA = Join-Path $TestRoot 'roaming'
    New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA, $env:APPDATA | Out-Null
    Install-TestApp $BaselineInstaller
    $url = Start-TestApp
    $seed = @{ company_name='升级验收示例公司'; position_title='合成测试岗位'; jd_text='synthetic JD only'; status='已投递' } | ConvertTo-Json
    $application = Invoke-RestMethod -Uri ($url + '/api/applications') -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($seed)) -NoProxy
    $provider = @{ api_key='synthetic-upgrade-key'; model='qwen/qwen-max' } | ConvertTo-Json
    $saved = Invoke-RestMethod -Uri ($url + '/api/llm/providers/qwen') -Method Put -ContentType 'application/json' -Body $provider -NoProxy
    Stop-TestApp
    Install-TestApp $CandidateInstaller
    $url = Start-TestApp
    $restored = Invoke-RestMethod -Uri ($url + '/api/applications/' + $application.id) -NoProxy
    if ($restored.position.company.name -ne '升级验收示例公司') { throw '升级后数据不一致' }
    $providers = Invoke-RestMethod -Uri ($url + '/api/llm/providers') -NoProxy
    if (($providers | Where-Object name -eq qwen).api_key_masked -ne $saved.api_key_masked) { throw '升级后模型配置不一致' }
    $history = Invoke-RestMethod -Uri ($url + '/api/applications/' + $application.id + '/stage-history') -NoProxy
    if ($history.items.Count -ne 0) { throw '升级伪造了历史阶段记录' }
    Stop-TestApp
    $backup = Join-Path $TestRoot 'backup'
    Invoke-BackupTool @('backup','--output',('"' + $backup + '"'))
    Invoke-BackupTool @('restore',('"' + $backup + '"'),'--confirm','--replace-secret')
    $url = Start-TestApp
    $afterRestore = Invoke-RestMethod -Uri ($url + '/api/applications/' + $application.id) -NoProxy
    if ($afterRestore.position.company.name -ne '升级验收示例公司') { throw '备份恢复后数据不一致' }
    $providers = Invoke-RestMethod -Uri ($url + '/api/llm/providers') -NoProxy
    if (($providers | Where-Object name -eq qwen).api_key_masked -ne $saved.api_key_masked) { throw '备份恢复后加密配置不一致' }
    Stop-TestApp
    @{ status='passed'; installation=$true; upgrade=$true; data_preserved=$true; config_preserved=$true; backup_restore=$true; process_cleanup=$true } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $TestRoot 'acceptance.json') -Encoding utf8
    $global:LASTEXITCODE = 0
} finally {
    if ($desktop -and -not $desktop.HasExited) {
        $desktop.Kill($true)
        & (Join-Path $installRoot 'runtime/postgresql/bin/pg_ctl.exe') -D (Join-Path $dataRoot 'postgres') stop -m fast *> $null
    }
    $env:LOCALAPPDATA = $oldLocal
    $env:APPDATA = $oldRoaming
}
