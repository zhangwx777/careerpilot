@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -Command ^
 "$ErrorActionPreference = 'Stop'; ^
  $root = '%~dp0'; ^
  $projectRoot = $root.TrimEnd('\'); ^
  $python = Join-Path $root 'backend\.venv\Scripts\python.exe'; ^
  $backendProc = $null; $frontendProc = $null; $backendOwned = $false; $frontendOwned = $false; $exitCode = 0; ^
  function Test-Backend([int]$port) { try { $health = Invoke-RestMethod ('http://127.0.0.1:{0}/health' -f $port) -TimeoutSec 2; return ($health.status -eq 'ok' -and $health.db -eq $true) } catch { return $false } }; ^
  function Test-Frontend([int]$port) { try { return ((Invoke-WebRequest ('http://127.0.0.1:{0}/@vite/client' -f $port) -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) } catch { return $false } }; ^
  function Get-PortProcess([int]$port) { $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($null -eq $c) { return $null }; return Get-CimInstance Win32_Process -Filter ('ProcessId={0}' -f $c.OwningProcess) -ErrorAction SilentlyContinue }; ^
  function Is-ProjectProcess($p) { if ($null -eq $p) { return $false }; return (([string]$p.CommandLine + ' ' + [string]$p.ExecutablePath) -like ('*' + $projectRoot + '*')) }; ^
  function Stop-Tree([int]$pid) { if ($pid -gt 0) { & taskkill.exe /PID $pid /T /F *> $null } }; ^
  function Find-Port([int]$preferred) { for ($i = 0; $i -lt 20; $i++) { $port = $preferred + $i; $p = Get-PortProcess $port; if ($null -eq $p) { return $port }; if (Is-ProjectProcess $p) { Write-Host ('清理本项目残留进程 PID {0}（端口 {1}）...' -f $p.ProcessId, $port); Stop-Tree ([int]$p.ProcessId); Start-Sleep -Milliseconds 300; if ($null -eq (Get-PortProcess $port)) { return $port } } }; throw ('从端口 {0} 开始没有找到可用端口。' -f $preferred) }; ^
  function Wait-Ready([scriptblock]$test) { for ($i = 0; $i -lt 30; $i++) { if (& $test) { return $true }; Start-Sleep -Milliseconds 500 }; return $false }; ^
  try { ^
    if (-not (Test-Path $python)) { throw '缺少 backend\.venv，请先按 README 安装后端环境。' }; ^
    $backendPort = if (Test-Backend 8000) { 8000 } else { Find-Port 8000 }; ^
    if (-not (Test-Backend $backendPort)) { ^
      Push-Location (Join-Path $root 'backend'); & $python -m scripts.init_db; if ($LASTEXITCODE -ne 0) { throw '数据库初始化失败，请检查 PostgreSQL 和 .env。' }; ^
      $backendProc = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',[string]$backendPort) -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru; Pop-Location; $backendOwned = $true; ^
      if (-not (Wait-Ready { Test-Backend $backendPort })) { throw ('后端在端口 {0} 启动超时。' -f $backendPort) } ^
    }; ^
    $marker = Join-Path $root 'frontend\node_modules\@phosphor-icons\react\package.json'; ^
    if (-not (Test-Path $marker)) { Push-Location (Join-Path $root 'frontend'); Write-Host '前端依赖不完整，正在修复...'; & corepack pnpm install --force; if ($LASTEXITCODE -ne 0) { throw '前端依赖修复失败。' }; Pop-Location }; ^
    $frontendPort = if (($backendPort -eq 8000) -and (Test-Frontend 5173)) { 5173 } else { Find-Port 5173 }; ^
    if (-not (($frontendPort -eq 5173) -and ($backendPort -eq 8000) -and (Test-Frontend 5173))) { ^
      $env:VITE_API_TARGET = 'http://127.0.0.1:{0}' -f $backendPort; ^
      $frontendProc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d','/c',('corepack pnpm exec vite --host 127.0.0.1 --port {0} --strictPort' -f $frontendPort)) -WorkingDirectory (Join-Path $root 'frontend') -PassThru; $frontendOwned = $true; ^
      if (-not (Wait-Ready { Test-Frontend $frontendPort })) { throw ('前端在端口 {0} 启动超时。' -f $frontendPort) } ^
    }; ^
    Write-Host ''; Write-Host ('后端： http://127.0.0.1:{0}' -f $backendPort) -ForegroundColor Cyan; Write-Host ('前端： http://localhost:{0}' -f $frontendPort) -ForegroundColor Cyan; Write-Host '按 Ctrl+C 停止本次启动的服务。' -ForegroundColor Yellow; Start-Process ('http://localhost:{0}' -f $frontendPort); ^
    $stopRequested = $false; $cancelHandler = [ConsoleCancelEventHandler]{ param($sender,$event); $event.Cancel = $true; $script:stopRequested = $true }; [Console]::add_CancelKeyPress($cancelHandler); ^
    try { while ($true) { if ($stopRequested) { $answer = Read-Host '确认关闭 qiuzhao-agent？(Y/N)'; if ($answer -match '(?i)^(y|yes|是)$') { break }; $stopRequested = $false; Write-Host '已取消关闭，服务继续运行。' -ForegroundColor Yellow }; if ($frontendOwned -and $frontendProc.HasExited) { Write-Host '前端进程已退出，正在清理后端...' -ForegroundColor Yellow; break }; if ($backendOwned -and $backendProc.HasExited) { Write-Host '后端进程已退出，正在清理前端...' -ForegroundColor Yellow; break }; Start-Sleep -Milliseconds 300 } } finally { [Console]::remove_CancelKeyPress($cancelHandler) } ^
  } catch { Write-Host ('启动失败：{0}' -f $_.Exception.Message) -ForegroundColor Red; $exitCode = 1 } ^
  finally { if ($frontendOwned -and $null -ne $frontendProc -and -not $frontendProc.HasExited) { Write-Host '正在关闭前端...'; Stop-Tree ([int]$frontendProc.Id) }; if ($backendOwned -and $null -ne $backendProc -and -not $backendProc.HasExited) { Write-Host '正在关闭后端...'; Stop-Tree ([int]$backendProc.Id) }; Write-Host '服务已关闭。' }; exit $exitCode"

set "exitCode=%ERRORLEVEL%"
endlocal & exit /b %exitCode%
