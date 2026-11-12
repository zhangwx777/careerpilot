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
$oldAppRoot = $env:CAREERPILOT_APP_ROOT
$oldDataRoot = $env:CAREERPILOT_DATA_DIR
$desktop = $null
$state = $null
$launchIndex = 0
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class UpgradeWindow {
    public delegate bool Callback(IntPtr handle, IntPtr value);
    [DllImport("user32.dll")] public static extern bool EnumWindows(Callback callback, IntPtr value);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr handle, out uint process);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr handle, StringBuilder name, int count);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr handle);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr handle, uint message, IntPtr wParam, IntPtr lParam);
}
'@

function Save-DesktopDiagnostic {
    $diagnostic = Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList @('-NoProfile','-File',('"' + (Join-Path $PSScriptRoot 'inspect-desktop.ps1') + '"'),'-DesktopId',$desktop.Id,'-OutputRoot',('"' + $TestRoot + '"')) -WindowStyle Hidden -PassThru
    if (-not $diagnostic.WaitForExit(10000)) { $diagnostic.Kill($true) }
}

function Install-TestApp([string]$installer) {
    Write-Output ('Installing acceptance build: ' + (Split-Path -Leaf $installer))
    $process = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS','/TASKS=""', ('/DIR="' + $installRoot + '"'), ('/LOG="' + (Join-Path $TestRoot 'installer.log') + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "安装失败：$($process.ExitCode)" }
}
function Start-TestApp {
    Write-Host ('Starting isolated desktop version ' + (Get-Content (Join-Path $installRoot 'resources/app/package.json') -Raw | ConvertFrom-Json).version)
    $script:launchIndex += 1
    $script:desktop = Start-Process -FilePath (Join-Path $installRoot 'CareerPilot.exe') -ArgumentList @(('--user-data-dir="' + (Join-Path $TestRoot 'user-data') + '"'),'--enable-logging=file',('--log-file="' + (Join-Path $TestRoot "desktop-$launchIndex-chromium.log") + '"')) -WorkingDirectory $installRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $TestRoot "desktop-$launchIndex-stdout.log") -RedirectStandardError (Join-Path $TestRoot "desktop-$launchIndex-stderr.log")
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if (Test-Path -LiteralPath $stateFile) {
            $script:state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
            $url = 'http://127.0.0.1:' + $state.backend_port
            $health = Invoke-RestMethod -Uri ($url + '/health') -NoProxy
            if ($health.status -ne 'ok') { throw '桌面服务未健康就绪' }
            return $url
        }
        if ($desktop.HasExited) { throw '桌面进程在就绪前退出' }
        $desktop.Refresh()
        if ($desktop.MainWindowTitle -eq 'Error') { break }
        Start-Sleep -Seconds 2
    }
    if (Test-Path -LiteralPath (Join-Path $dataRoot 'logs')) {
        Get-ChildItem -LiteralPath (Join-Path $dataRoot 'logs') -File | ForEach-Object { Write-Host ('Diagnostic: ' + $_.Name); Get-Content -LiteralPath $_.FullName -Tail 35 | Write-Host }
    }
    Get-ChildItem -LiteralPath $TestRoot -Filter 'desktop-*.log' | ForEach-Object { Write-Host ('Diagnostic: ' + $_.Name); Get-Content -LiteralPath $_.FullName -Tail 35 | Write-Host }
    Save-DesktopDiagnostic
    throw '桌面服务启动超时（独立验收日志已保存）'
}
function Stop-TestApp {
    if (-not $desktop) { return }
    if (-not $desktop.HasExited) {
        $desktop.Refresh()
        if (-not $desktop.CloseMainWindow()) {
            # Process.MainWindowHandle excludes hidden windows. WM_CLOSE still
            # exercises Electron's normal window/quit handlers in headless CI.
            $handles = [Collections.Generic.List[IntPtr]]::new()
            [void][UpgradeWindow]::EnumWindows([UpgradeWindow+Callback]{ param($handle, $value)
                [uint32]$owner = 0
                [void][UpgradeWindow]::GetWindowThreadProcessId($handle, [ref]$owner)
                if ($owner -eq $desktop.Id) {
                    $name = [Text.StringBuilder]::new(256)
                    [void][UpgradeWindow]::GetClassName($handle, $name, $name.Capacity)
                    if ($name.ToString().StartsWith('Chrome_WidgetWin')) { $handles.Add($handle) }
                }; return $true
            }, [IntPtr]::Zero)
            if ($handles.Count -ne 1 -or -not [UpgradeWindow]::IsWindowEnabled($handles[0])) { Save-DesktopDiagnostic; throw '桌面主窗口不存在或被错误对话框阻塞' }
            if (-not [UpgradeWindow]::PostMessage($handles[0], 16, [IntPtr]::Zero, [IntPtr]::Zero)) { throw '无法发送正常关闭消息' }
        }
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
    $env:CAREERPILOT_APP_ROOT = Join-Path $installRoot 'app'
    $env:CAREERPILOT_DATA_DIR = $dataRoot
    New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA, $env:APPDATA | Out-Null
    Install-TestApp $BaselineInstaller
    # v0.1.9 precreates postgres as the elevated owner, then initdb's restricted
    # token cannot chmod it on hosted Windows. Let the unmodified bundled initdb
    # create the baseline cluster; seed all business data through the original API.
    New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
    & (Join-Path $installRoot 'runtime/postgresql/bin/initdb.exe') -D (Join-Path $dataRoot 'postgres') -L (Join-Path $installRoot 'runtime/postgresql/share') -U qiuzhao_app -A trust --encoding=UTF8 --no-locale
    if ($LASTEXITCODE -ne 0) { throw '旧版测试库初始化失败' }
    $url = Start-TestApp
    $seed = @{ company_name='升级验收示例公司'; position_title='合成测试岗位'; jd_text='synthetic JD only'; status='已投递' } | ConvertTo-Json
    $application = Invoke-RestMethod -Uri ($url + '/api/applications') -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($seed)) -NoProxy
    $provider = @{ api_key='synthetic-upgrade-key'; model='qwen/qwen-max' } | ConvertTo-Json
    $saved = Invoke-RestMethod -Uri ($url + '/api/llm/providers/qwen') -Method Put -ContentType 'application/json' -Body $provider -NoProxy
    Stop-TestApp
    Install-TestApp $CandidateInstaller
    # A separate, empty data root proves candidate first-run installation without
    # preinitializing its database or changing the installed application files.
    $upgradeDataRoot = $dataRoot
    $env:LOCALAPPDATA = Join-Path $TestRoot 'fresh-local'
    $dataRoot = Join-Path $env:LOCALAPPDATA 'CareerPilot'
    $stateFile = Join-Path $dataRoot 'runtime.json'
    $env:CAREERPILOT_DATA_DIR = $dataRoot
    $url = Start-TestApp
    $empty = Invoke-RestMethod -Uri ($url + '/api/applications') -NoProxy
    if ($empty.items.Count -ne 0) { throw '全新安装意外读取了其他数据' }
    Stop-TestApp
    $env:LOCALAPPDATA = Join-Path $TestRoot 'local'
    $dataRoot = $upgradeDataRoot
    $stateFile = Join-Path $dataRoot 'runtime.json'
    $env:CAREERPILOT_DATA_DIR = $dataRoot
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
    $url = Start-TestApp
    $markerBody = @{ company_name='备份后新增标记'; position_title='应在恢复后消失'; status='已投递' } | ConvertTo-Json
    $marker = Invoke-RestMethod -Uri ($url + '/api/applications') -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($markerBody)) -NoProxy
    $changedProvider = @{ api_key='synthetic-marker-changed-9876'; model='qwen/qwen-max' } | ConvertTo-Json
    Invoke-RestMethod -Uri ($url + '/api/llm/providers/qwen') -Method Put -ContentType 'application/json' -Body $changedProvider -NoProxy | Out-Null
    Stop-TestApp
    Invoke-BackupTool @('restore',('"' + $backup + '"'),'--confirm','--replace-secret')
    $url = Start-TestApp
    $afterRestore = Invoke-RestMethod -Uri ($url + '/api/applications/' + $application.id) -NoProxy
    if ($afterRestore.position.company.name -ne '升级验收示例公司') { throw '备份恢复后数据不一致' }
    $afterRestoreList = Invoke-RestMethod -Uri ($url + '/api/applications') -NoProxy
    if (@($afterRestoreList.items | Where-Object id -eq $marker.id).Count -ne 0) { throw '恢复未撤回备份后的合成数据' }
    $providers = Invoke-RestMethod -Uri ($url + '/api/llm/providers') -NoProxy
    if (($providers | Where-Object name -eq qwen).api_key_masked -ne $saved.api_key_masked) { throw '备份恢复后加密配置不一致' }
    Stop-TestApp
    @{ status='passed'; installation=$true; upgrade=$true; data_preserved=$true; config_preserved=$true; backup_restore=$true; process_cleanup=$true; baseline_cluster_bootstrap="bundled initdb (v0.1.9 elevated-directory permission workaround)" } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $TestRoot 'acceptance.json') -Encoding utf8
    $global:LASTEXITCODE = 0
} finally {
    if ($desktop -and -not $desktop.HasExited) {
        $desktop.Kill($true)
        & (Join-Path $installRoot 'runtime/postgresql/bin/pg_ctl.exe') -D (Join-Path $dataRoot 'postgres') stop -m fast *> $null
    }
    $env:LOCALAPPDATA = $oldLocal
    $env:APPDATA = $oldRoaming
    $env:CAREERPILOT_APP_ROOT = $oldAppRoot
    $env:CAREERPILOT_DATA_DIR = $oldDataRoot
}
