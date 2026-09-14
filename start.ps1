$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$projectRoot = $root
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$backendProc = $null
$frontendProc = $null
$backendOwned = $false
$frontendOwned = $false
$exitCode = 0

function Test-Backend([int]$port) {
    try {
        $health = Invoke-RestMethod ('http://127.0.0.1:{0}/health' -f $port) -TimeoutSec 2
        if (-not ($health.status -eq 'ok' -and $health.db -eq $true)) {
            return $false
        }
        # A healthy old process can still be running after a code update.
        # Require a route introduced by the current app before reusing it.
        $openapi = Invoke-RestMethod ('http://127.0.0.1:{0}/openapi.json' -f $port) -TimeoutSec 2
        return (@($openapi.paths.PSObject.Properties.Name) -contains '/api/llm/providers/{provider}/models')
    } catch {
        return $false
    }
}

function Test-Frontend([int]$port) {
    try {
        return ((Invoke-WebRequest ('http://127.0.0.1:{0}/@vite/client' -f $port) -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Get-PortProcess([int]$port) {
    $connection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $connection) {
        return $null
    }
    try {
        $process = Get-CimInstance Win32_Process -Filter ('ProcessId={0}' -f $connection.OwningProcess) -ErrorAction Stop
        if ($null -ne $process) {
            return $process
        }
    } catch {
        # Some managed terminals cannot inspect another process. Keep a
        # placeholder so the occupied port is never mistaken for a free one.
    }
    return [PSCustomObject]@{
        ProcessId = $connection.OwningProcess
        CommandLine = ''
        ExecutablePath = ''
    }
}

function Is-ProjectProcess($process) {
    if ($null -eq $process) {
        return $false
    }
    $identity = [string]$process.CommandLine + ' ' + [string]$process.ExecutablePath
    return ($identity -like ('*' + $projectRoot + '*') -or $identity -like '*app.main:app*')
}

function Stop-Tree([int]$processId) {
    if ($processId -le 0) {
        return
    }
    # taskkill is the normal Windows path, but managed terminals can reject it
    # with Access Denied even for a process started by this script.  Fall back
    # to PowerShell so a failed cleanup cannot leave an old project server
    # listening on the next run.
    & taskkill.exe /PID $processId /T /F *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }
    try {
        $children = Get-CimInstance Win32_Process -Filter ('ParentProcessId={0}' -f $processId) -ErrorAction Stop
        foreach ($child in $children) {
            Stop-Tree ([int]$child.ProcessId)
        }
    } catch {
        # Process inspection is restricted in some terminals; stopping the
        # owned parent below is still safer than silently doing nothing.
    }
    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
    } catch {
        # The caller will report the port as occupied on a later start.
    }
}

function Find-Port([int]$preferred) {
    for ($i = 0; $i -lt 20; $i++) {
        $port = $preferred + $i
        $process = Get-PortProcess $port
        if ($null -eq $process) {
            return $port
        }
        if (Is-ProjectProcess $process) {
            Write-Host ('Cleaning stale project process PID {0} on port {1}...' -f $process.ProcessId, $port)
            Stop-Tree ([int]$process.ProcessId)
            Start-Sleep -Milliseconds 300
            if ($null -eq (Get-PortProcess $port)) {
                return $port
            }
        }
    }
    throw ('No available port found from {0}.' -f $preferred)
}

function Wait-Ready([scriptblock]$test) {
    for ($i = 0; $i -lt 30; $i++) {
        if (& $test) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

try {
    if (-not (Test-Path $python)) {
        throw 'Missing backend\.venv. Install the backend environment first.'
    }

    # Always obtain a fresh project port. This prevents a healthy-but-stale
    # project process from surviving code updates and also avoids killing an
    # unrelated process when Windows refuses process inspection.
    $backendPort = Find-Port 8000
    Push-Location (Join-Path $root 'backend')
    & $python -m scripts.init_db
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        throw 'Database initialization failed. Check PostgreSQL and .env.'
    }
    $backendProc = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',[string]$backendPort) -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru
    Pop-Location
    $backendOwned = $true
    if (-not (Wait-Ready { Test-Backend $backendPort })) {
        throw ('Backend startup timed out on port {0}.' -f $backendPort)
    }

    $marker = Join-Path $root 'frontend\node_modules\@phosphor-icons\react\package.json'
    if (-not (Test-Path $marker)) {
        Push-Location (Join-Path $root 'frontend')
        Write-Host 'Frontend dependencies are incomplete; repairing...'
        & corepack pnpm install --force
        if ($LASTEXITCODE -ne 0) {
            throw 'Frontend dependency repair failed.'
        }
        Pop-Location
    }

    $frontendPort = Find-Port 5173
    $env:VITE_API_TARGET = 'http://127.0.0.1:{0}' -f $backendPort
    $frontendProc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d','/c',('corepack pnpm exec vite --host 127.0.0.1 --port {0} --strictPort' -f $frontendPort)) -WorkingDirectory (Join-Path $root 'frontend') -PassThru
    $frontendOwned = $true
    if (-not (Wait-Ready { Test-Frontend $frontendPort })) {
        throw ('Frontend startup timed out on port {0}.' -f $frontendPort)
    }

    Write-Host ''
    Write-Host ('Backend: http://127.0.0.1:{0}' -f $backendPort) -ForegroundColor Cyan
    Write-Host ('Frontend: http://localhost:{0}' -f $frontendPort) -ForegroundColor Cyan
    Write-Host 'Press Ctrl+C to stop the services started by this script.' -ForegroundColor Yellow
    try {
        Start-Process ('http://localhost:{0}' -f $frontendPort) | Out-Null
    } catch {
        # Opening a browser can be blocked in terminals, sandboxes, or remote
        # sessions.  It must not tear down services that are already healthy.
        Write-Host ('Could not open the browser automatically; open http://localhost:{0} manually.' -f $frontendPort) -ForegroundColor Yellow
    }

    $stopRequested = $false
    $cancelHandler = [ConsoleCancelEventHandler]{ param($sender, $event); $event.Cancel = $true; $script:stopRequested = $true }
    [Console]::add_CancelKeyPress($cancelHandler)
    try {
        while ($true) {
            if ($stopRequested) {
                $answer = Read-Host 'Stop qiuzhao-agent? (Y/N)'
                if ($answer -match '(?i)^(y|yes)$') {
                    break
                }
                $stopRequested = $false
                Write-Host 'Shutdown cancelled; services are still running.' -ForegroundColor Yellow
            }
            if ($frontendOwned -and $frontendProc.HasExited) {
                Write-Host 'Frontend exited; cleaning up backend.' -ForegroundColor Yellow
                break
            }
            if ($backendOwned -and $backendProc.HasExited) {
                Write-Host 'Backend exited; cleaning up frontend.' -ForegroundColor Yellow
                break
            }
            Start-Sleep -Milliseconds 300
        }
    } finally {
        [Console]::remove_CancelKeyPress($cancelHandler)
    }
} catch {
    Write-Host ('Startup failed: {0}' -f $_.Exception.Message) -ForegroundColor Red
    $exitCode = 1
} finally {
    if ($frontendOwned -and $null -ne $frontendProc -and -not $frontendProc.HasExited) {
        Write-Host 'Stopping frontend...'
        Stop-Tree ([int]$frontendProc.Id)
    }
    if ($backendOwned -and $null -ne $backendProc -and -not $backendProc.HasExited) {
        Write-Host 'Stopping backend...'
        Stop-Tree ([int]$backendProc.Id)
    }
    Write-Host 'Services stopped.'
}

exit $exitCode
