$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $root 'build\installer'
$sourceRoot = Join-Path $buildRoot 'release-source'
$payloadRoot = Join-Path $buildRoot 'iexpress\payload'
$payloadArchive = Join-Path $buildRoot 'iexpress\payload.zip'
$pyDist = Join-Path $buildRoot 'pyinstaller'
$pyWork = Join-Path $buildRoot 'pyinstaller-work'
$artifact = Join-Path $root 'dist\QiuzhaoAgentSetup.exe'
$pgHome = 'C:\Program Files\PostgreSQL\18'

if ($buildRoot -notlike "$root\build\installer*") { throw 'Invalid build path.' }
if (Test-Path -LiteralPath $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $sourceRoot, $payloadRoot, (Split-Path $artifact) | Out-Null

Push-Location $root
try {
    $sourceArchive = Join-Path $buildRoot 'source.zip'
    git archive --format=zip HEAD -o $sourceArchive
    if ($LASTEXITCODE -ne 0) { throw 'Source archive creation failed.' }
    Expand-Archive -LiteralPath $sourceArchive -DestinationPath $sourceRoot -Force
} finally {
    Pop-Location
}

function Write-Utf8([string]$path, [string]$content) {
    [System.IO.File]::WriteAllText($path, $content, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-HeadText([string]$relativePath) {
    Push-Location $root
    try { return ((git show "HEAD:$relativePath") -join "`n") + "`n" } finally { Pop-Location }
}

function Copy-WorkingFile([string]$relativePath) {
    $source = Join-Path $root $relativePath
    $destination = Join-Path $sourceRoot $relativePath
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

$webConfigFiles = @(
    '.env.example', '.gitignore', 'CLAUDE.md', 'README.md',
    'backend/app/config.py', 'backend/app/llm/config_store.py',
    'backend/app/llm/registry.py', 'backend/app/llm_schemas.py',
    'backend/app/parsing.py', 'backend/scripts/smoke_llm.py',
    'frontend/src/pages/SettingsPage.tsx'
)
foreach ($file in $webConfigFiles) { Copy-WorkingFile $file }
Copy-WorkingFile 'backend/app/main.py'
Copy-WorkingFile 'backend/packaged_server.py'

$models = Get-HeadText 'backend/app/models.py'
$models = $models -replace '(?m)^from app\.llm\.registry import default_provider\r?\n', ''
$models = $models.Replace('default=default_provider)', 'default="qwen")')
Write-Utf8 (Join-Path $sourceRoot 'backend\app\models.py') $models

$provider = Get-HeadText 'backend/app/llm/provider.py'
$provider = $provider.Replace('from app.llm.registry import LLM_RETRIES, LLM_TIMEOUT_SECONDS, PROVIDERS', 'from app.llm.registry import LLM_RETRIES, LLM_TIMEOUT_SECONDS')
$provider = $provider.Replace('cfg = config if config is not None else PROVIDERS.get(provider)', 'cfg = config')
$provider = $provider.Replace('raise ValueError(f"未知 provider: {provider}")', 'raise RuntimeError("模型配置必须来自网页设置或任务快照")')
Write-Utf8 (Join-Path $sourceRoot 'backend\app\llm\provider.py') $provider

$types = Get-HeadText 'frontend/src/types.ts'
$types = $types.Replace('source: "env" | "database" | null', 'source: "database" | null')
Write-Utf8 (Join-Path $sourceRoot 'frontend\src\types.ts') $types

$forbidden = @('agent_runtime.py', 'agent_schemas.py', 'agent_tools.py', 'test_agent_runtime.py', 'test_agent_tools.py')
foreach ($name in $forbidden) {
    if (Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Filter $name -ErrorAction SilentlyContinue) {
        throw "Agent 优化文件意外进入发布源：$name"
    }
}
$forbiddenText = rg -n --glob '*.py' --glob '*.ts' --glob '*.tsx' 'AgentRun|run_chat_agent|chat_with_tools|build_chat_toolset' $sourceRoot 2>$null
if ($forbiddenText) { throw 'Agent 优化符号意外进入发布源。' }

Push-Location (Join-Path $sourceRoot 'frontend')
try {
    & corepack pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & corepack pnpm build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally {
    Pop-Location
}

$pyinstaller = Join-Path $root 'backend\.venv\Scripts\pyinstaller.exe'
if (-not (Test-Path -LiteralPath $pyinstaller)) { throw 'PyInstaller is not installed in backend\.venv.' }
Push-Location $root
try {
    & $pyinstaller --noconfirm --clean --onedir --name QiuzhaoAgentBackend --distpath $pyDist --workpath $pyWork --specpath $buildRoot --paths (Join-Path $sourceRoot 'backend') --collect-all litellm --collect-all tiktoken --collect-submodules tiktoken_ext --collect-submodules langgraph --collect-submodules langchain_mcp_adapters (Join-Path $sourceRoot 'backend\packaged_server.py')
    if ($LASTEXITCODE -ne 0) { throw 'Backend packaging failed.' }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $pgHome)) { throw 'PostgreSQL 18 installation was not found.' }
Copy-Item -Path (Join-Path $pyDist 'QiuzhaoAgentBackend\*') -Destination $payloadRoot -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $payloadRoot '_internal\tiktoken'), (Join-Path $payloadRoot '_internal\tiktoken_ext') | Out-Null
Copy-Item -Path (Join-Path $root 'backend\.venv\Lib\site-packages\tiktoken\*.py') -Destination (Join-Path $payloadRoot '_internal\tiktoken') -Force
Copy-Item -Path (Join-Path $root 'backend\.venv\Lib\site-packages\tiktoken_ext\*.py') -Destination (Join-Path $payloadRoot '_internal\tiktoken_ext') -Force
New-Item -ItemType Directory -Force -Path (Join-Path $payloadRoot 'frontend') | Out-Null
Copy-Item -Path (Join-Path $sourceRoot 'frontend\dist\*') -Destination (Join-Path $payloadRoot 'frontend') -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $payloadRoot 'postgresql\bin'), (Join-Path $payloadRoot 'postgresql\lib'), (Join-Path $payloadRoot 'postgresql\share') | Out-Null
Copy-Item -Path (Join-Path $pgHome 'bin\*') -Destination (Join-Path $payloadRoot 'postgresql\bin') -Recurse -Force
Copy-Item -Path (Join-Path $pgHome 'lib\*') -Destination (Join-Path $payloadRoot 'postgresql\lib') -Recurse -Force
Copy-Item -Path (Join-Path $pgHome 'share\*') -Destination (Join-Path $payloadRoot 'postgresql\share') -Recurse -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'installed\*') -Destination $payloadRoot -Recurse -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'installer\install.ps1') -Destination (Join-Path $buildRoot 'iexpress\install.ps1') -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'installer\install.cmd') -Destination (Join-Path $buildRoot 'iexpress\install.cmd') -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'installer\uninstall.ps1') -Destination (Join-Path $payloadRoot 'uninstall.ps1') -Force

Compress-Archive -Path (Join-Path $payloadRoot '*') -DestinationPath $payloadArchive -CompressionLevel Fastest -Force

$iexpressRoot = Join-Path $buildRoot 'iexpress'
$strings = [System.Collections.Generic.List[string]]::new()
$sourceEntries = [System.Collections.Generic.List[string]]::new()
$strings.Add('FILE0="install.ps1"')
$sourceEntries.Add('%FILE0%=')
$strings.Add('FILE1="payload.zip"')
$sourceEntries.Add('%FILE1%=')
$strings.Add('FILE2="install.cmd"')
$sourceEntries.Add('%FILE2%=')
$sed = @(
    '[Version]', 'Class=IEXPRESS', 'SEDVersion=3', '[Options]',
    'PackagePurpose=InstallApp', 'ShowInstallProgramWindow=1', 'HideExtractAnimation=1',
    'UseLongFileName=1', 'InsideCompressed=1', 'CAB_FixedSize=0', 'CAB_ResvCodeSigning=0',
    'RebootMode=N', 'InstallPrompt=', 'DisplayLicense=', 'FinishMessage=',
    ('TargetName={0}' -f $artifact), 'FriendlyName=职航 CareerPilot',
    'AppLaunched=cmd.exe /c install.cmd',
    'PostInstallCmd=<None>', 'AdminQuietInstCmd=', 'UserQuietInstCmd=', 'SourceFiles=SourceFiles',
    '[Strings]'
)
$sed += $strings
$sed += '[SourceFiles]'
$sed += ('SourceFiles0={0}' -f $iexpressRoot)
$sed += '[SourceFiles0]'
$sed += $sourceEntries
Write-Utf8 (Join-Path $buildRoot 'installer.sed') (($sed -join "`r`n") + "`r`n")

if (Test-Path -LiteralPath $artifact) { Remove-Item -LiteralPath $artifact -Force }
& iexpress.exe /N /Q (Join-Path $buildRoot 'installer.sed')
if (-not (Test-Path -LiteralPath $artifact)) {
    1..180 | ForEach-Object {
        Start-Sleep -Seconds 1
        if (Test-Path -LiteralPath $artifact) { break }
    }
}
if (-not (Test-Path -LiteralPath $artifact)) { throw "IExpress installer creation failed (exit code $LASTEXITCODE)." }

[pscustomobject]@{
    Artifact = $artifact
    SourceCommit = (git rev-parse HEAD)
    ExcludedAgentFiles = ($forbidden -join ', ')
    SizeMB = [math]::Round((Get-Item $artifact).Length / 1MB, 1)
} | Format-List
