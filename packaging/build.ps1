param(
    [switch]$AppOnly
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $root 'build\installer'
$iconPath = Join-Path $buildRoot 'brand-mark.ico'
$payloadRoot = Join-Path $buildRoot 'payload'
$runtimeRoot = Join-Path $payloadRoot 'runtime'
$appLayer = Join-Path $payloadRoot 'app'
$pyDist = Join-Path $buildRoot 'pyinstaller'
$pyWork = Join-Path $buildRoot 'pyinstaller-work'
$electronRoot = Join-Path $buildRoot 'electron'
$artifact = Join-Path $root 'dist\CareerPilotSetup.exe'
$portableArtifact = Join-Path $root 'dist\CareerPilot-portable.zip'
$garnetVersion = '1.1.10'
$dotnetRuntimeVersion = '10.0.8'
$garnetArchive = Join-Path $buildRoot "garnet-win-x64-$garnetVersion.zip"
$dotnetArchive = Join-Path $buildRoot "dotnet-runtime-$dotnetRuntimeVersion-win-x64.zip"
$garnetUrl = "https://github.com/microsoft/garnet/releases/download/v$garnetVersion/win-x64-based-readytorun.zip"
$dotnetUrl = "https://builds.dotnet.microsoft.com/dotnet/Runtime/$dotnetRuntimeVersion/dotnet-runtime-$dotnetRuntimeVersion-win-x64.zip"
$pgHome = 'C:\Program Files\PostgreSQL\18'
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$desktopPackage = Get-Content (Join-Path $root 'desktop\package.json') -Raw | ConvertFrom-Json
$appVersion = $desktopPackage.version

if (-not (Test-Path -LiteralPath $python)) { throw '缺少后端 Python 虚拟环境。' }
if (-not $AppOnly -and -not (Test-Path -LiteralPath $pgHome)) { throw '未找到 PostgreSQL 18 安装。' }
if ($AppOnly -and -not (Test-Path -LiteralPath $payloadRoot)) { throw '-AppOnly 需要已有完整构建的 payload，请先完整构建一次。' }

# 完整构建：清空重来；-AppOnly：只清应用层，保留运行时层与 Electron 壳
if (-not $AppOnly) {
    if (Test-Path -LiteralPath $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $payloadRoot, $runtimeRoot, $appLayer, (Split-Path $artifact) | Out-Null
} else {
    if (Test-Path -LiteralPath $appLayer) { Remove-Item -LiteralPath $appLayer -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $appLayer | Out-Null
}

function Ensure-Download([string]$url, [string]$destination) {
    if (-not (Test-Path -LiteralPath $destination)) {
        Write-Host "下载 $url"
        Invoke-WebRequest -Uri $url -OutFile $destination -UseBasicParsing
    }
}

function Write-InstallerArtifacts {
    if (Test-Path -LiteralPath $portableArtifact) { Remove-Item -LiteralPath $portableArtifact -Force }
    Compress-Archive -Path (Join-Path $payloadRoot '*') -DestinationPath $portableArtifact -CompressionLevel Fastest -Force

    if (Test-Path -LiteralPath $artifact) { Remove-Item -LiteralPath $artifact -Force }
    $inno = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $inno) { throw '未找到 Inno Setup 6 的 ISCC.exe。' }
    $iss = Join-Path $PSScriptRoot 'installer\CareerPilot.iss'
    & $inno "/DAppVersion=$appVersion" "/DPayloadRoot=$payloadRoot" "/DOutputDir=$(Split-Path $artifact)" "/DIconPath=$iconPath" $iss
    if ($LASTEXITCODE -ne 0) { throw '标准安装器生成失败。' }
    if (-not (Test-Path -LiteralPath $artifact)) { throw '安装器生成失败。' }
}

function Build-ElectronShell {
    $electronSource = Join-Path $root 'desktop'
    Push-Location (Join-Path $root 'frontend')
    try {
        & corepack pnpm exec electron-packager $electronSource CareerPilot --platform=win32 --arch=x64 --electron-version=37.10.3 --out $electronRoot --overwrite --icon $iconPath
        if ($LASTEXITCODE -ne 0) { throw '桌面应用打包失败。' }
    } finally {
        Pop-Location
    }
    Copy-Item -Path (Join-Path $electronRoot 'CareerPilot-win32-x64\*') -Destination $payloadRoot -Recurse -Force
    Copy-Item -LiteralPath $iconPath -Destination (Join-Path $payloadRoot 'brand-mark.ico') -Force
    Copy-Item -LiteralPath (Join-Path $root 'frontend\public\brand-mark.png') -Destination (Join-Path $payloadRoot 'brand-mark.png') -Force
}

# --- 应用层：前端 dist ---
Push-Location (Join-Path $root 'frontend')
try {
    & corepack pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
    & corepack pnpm build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
} finally {
    Pop-Location
}
New-Item -ItemType Directory -Force -Path (Join-Path $appLayer 'frontend\dist') | Out-Null
Copy-Item -Path (Join-Path $root 'frontend\dist\*') -Destination (Join-Path $appLayer 'frontend\dist') -Recurse -Force

# --- 应用层：后端源码（明文外置，改动无需重新 freeze） ---
$appBackend = Join-Path $appLayer 'backend'
New-Item -ItemType Directory -Force -Path $appBackend | Out-Null
Copy-Item -Path (Join-Path $root 'backend\packaged_server.py') -Destination $appBackend -Force
Copy-Item -Path (Join-Path $root 'backend\app') -Destination $appBackend -Recurse -Force
Copy-Item -Path (Join-Path $root 'backend\scripts') -Destination $appBackend -Recurse -Force
Get-ChildItem -Path $appBackend -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

# @@MARKER_FULL_BUILD@@
if ($AppOnly) {
    Write-Host '应用层与 Electron 壳已刷新（-AppOnly）。运行时层保持不变。'
    Build-ElectronShell
    Write-InstallerArtifacts
    [pscustomobject]@{
        Artifact = $artifact
        PortableArtifact = $portableArtifact
        SizeMB = [math]::Round((Get-Item $artifact).Length / 1MB, 1)
        PortableSizeMB = [math]::Round((Get-Item $portableArtifact).Length / 1MB, 1)
    } | Format-List
    return
}

# ===== 以下仅完整构建执行：运行时层 + Electron 壳 + 打包 =====

# --- 运行时层：桌面包自带固定任务队列运行时 + .NET Runtime，不依赖宿主机服务 ---
Ensure-Download $garnetUrl $garnetArchive
Ensure-Download $dotnetUrl $dotnetArchive
$garnetExtract = Join-Path $buildRoot 'garnet-extract'
Expand-Archive -LiteralPath $garnetArchive -DestinationPath $garnetExtract -Force
New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot 'garnet') | Out-Null
Copy-Item -Path (Join-Path $garnetExtract 'net10.0\*') -Destination (Join-Path $runtimeRoot 'garnet') -Recurse -Force
Expand-Archive -LiteralPath $dotnetArchive -DestinationPath (Join-Path $runtimeRoot 'dotnet') -Force

# --- 运行时层：PyInstaller onedir 冻结瘦启动器（业务源码不冻结） ---
$launcher = Join-Path $PSScriptRoot 'runtime\launcher_entry.py'
Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean --onedir --name CareerPilotBackend `
        --distpath $pyDist --workpath $pyWork --specpath $buildRoot `
        --collect-all litellm --collect-all tiktoken --collect-submodules tiktoken_ext `
        --collect-submodules langgraph --collect-submodules langchain_mcp_adapters --collect-all celery --collect-all redis `
        --collect-all psycopg $launcher
    if ($LASTEXITCODE -ne 0) { throw '后端启动器打包失败。' }
} finally {
    Pop-Location
}
New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot 'backend') | Out-Null
Copy-Item -Path (Join-Path $pyDist 'CareerPilotBackend\*') -Destination (Join-Path $runtimeRoot 'backend') -Recurse -Force
# tiktoken 纯 .py 补齐（历史上 collect 不全，需显式补 encoding 注册模块）
$tkDst = Join-Path $runtimeRoot 'backend\_internal\tiktoken'
$tkeDst = Join-Path $runtimeRoot 'backend\_internal\tiktoken_ext'
New-Item -ItemType Directory -Force -Path $tkDst, $tkeDst | Out-Null
Copy-Item -Path (Join-Path $root 'backend\.venv\Lib\site-packages\tiktoken\*.py') -Destination $tkDst -Force
Copy-Item -Path (Join-Path $root 'backend\.venv\Lib\site-packages\tiktoken_ext\*.py') -Destination $tkeDst -Force

# --- 运行时层：内嵌 PostgreSQL ---
New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot 'postgresql\bin'), (Join-Path $runtimeRoot 'postgresql\lib'), (Join-Path $runtimeRoot 'postgresql\share') | Out-Null
Copy-Item -Path (Join-Path $pgHome 'bin\*') -Destination (Join-Path $runtimeRoot 'postgresql\bin') -Recurse -Force
Copy-Item -Path (Join-Path $pgHome 'lib\*') -Destination (Join-Path $runtimeRoot 'postgresql\lib') -Recurse -Force
Copy-Item -Path (Join-Path $pgHome 'share\*') -Destination (Join-Path $runtimeRoot 'postgresql\share') -Recurse -Force

# --- 生命周期脚本 ---
Copy-Item -Path (Join-Path $PSScriptRoot 'installed\stop.ps1') -Destination $payloadRoot -Force

# --- 图标（PNG 压缩的 ICO 容器） ---
$iconSource = Join-Path $root 'frontend\public\brand-mark.png'
$iconPng = Join-Path $buildRoot 'brand-mark-256.png'
Add-Type -AssemblyName System.Drawing
$sourceImage = [System.Drawing.Image]::FromFile($iconSource)
$iconImage = New-Object System.Drawing.Bitmap(256, 256)
$graphics = [System.Drawing.Graphics]::FromImage($iconImage)
$graphics.DrawImage($sourceImage, 0, 0, 256, 256)
$iconImage.Save($iconPng, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose(); $iconImage.Dispose(); $sourceImage.Dispose()
$iconBytes = [System.IO.File]::ReadAllBytes($iconPng)
$iconStream = [System.IO.File]::Open($iconPath, [System.IO.FileMode]::Create)
$iconWriter = New-Object System.IO.BinaryWriter($iconStream)
try {
    $iconWriter.Write([uint16]0); $iconWriter.Write([uint16]1); $iconWriter.Write([uint16]1)
    $iconWriter.Write([byte]0); $iconWriter.Write([byte]0); $iconWriter.Write([byte]0); $iconWriter.Write([byte]0)
    $iconWriter.Write([uint16]1); $iconWriter.Write([uint16]32)
    $iconWriter.Write([uint32]$iconBytes.Length); $iconWriter.Write([uint32]22)
    $iconWriter.Write($iconBytes)
} finally {
    $iconWriter.Dispose()
}

Build-ElectronShell

Write-InstallerArtifacts

[pscustomobject]@{
    Artifact = $artifact
    PortableArtifact = $portableArtifact
    SizeMB = [math]::Round((Get-Item $artifact).Length / 1MB, 1)
    PortableSizeMB = [math]::Round((Get-Item $portableArtifact).Length / 1MB, 1)
} | Format-List
