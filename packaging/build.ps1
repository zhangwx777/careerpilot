param(
    [switch]$AppOnly
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $root 'build\installer'
$payloadRoot = Join-Path $buildRoot 'payload'
$runtimeRoot = Join-Path $payloadRoot 'runtime'
$appLayer = Join-Path $payloadRoot 'app'
$pyDist = Join-Path $buildRoot 'pyinstaller'
$pyWork = Join-Path $buildRoot 'pyinstaller-work'
$electronRoot = Join-Path $buildRoot 'electron'
$artifact = Join-Path $root 'dist\CareerPilotSetup.exe'
$portableArtifact = Join-Path $root 'dist\CareerPilot-portable.zip'
$payloadArchive = Join-Path $buildRoot 'payload.zip'
$pgHome = 'C:\Program Files\PostgreSQL\18'
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'

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
    Write-Host '应用层已刷新（-AppOnly）。运行时层与 Electron 壳保持不变。'
    return
}

# ===== 以下仅完整构建执行：运行时层 + Electron 壳 + 打包 =====

# --- 运行时层：PyInstaller onedir 冻结瘦启动器（业务源码不冻结） ---
$launcher = Join-Path $PSScriptRoot 'runtime\launcher_entry.py'
Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean --onedir --name CareerPilotBackend `
        --distpath $pyDist --workpath $pyWork --specpath $buildRoot `
        --collect-all litellm --collect-all tiktoken --collect-submodules tiktoken_ext `
        --collect-submodules langgraph --collect-submodules langchain_mcp_adapters `
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
Copy-Item -Path (Join-Path $PSScriptRoot 'installer\install.ps1') -Destination (Join-Path $payloadRoot 'install.ps1') -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'installer\uninstall.ps1') -Destination (Join-Path $payloadRoot 'uninstall.ps1') -Force

# --- 图标（PNG 压缩的 ICO 容器） ---
$iconSource = Join-Path $root 'frontend\public\brand-mark.png'
$iconPath = Join-Path $buildRoot 'brand-mark.ico'
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

# --- Electron 壳 ---
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
Copy-Item -LiteralPath $iconSource -Destination (Join-Path $payloadRoot 'brand-mark.png') -Force

# --- 打包产物：绿色版 zip + 自解压安装器 ---
if (Test-Path -LiteralPath $portableArtifact) { Remove-Item -LiteralPath $portableArtifact -Force }
Compress-Archive -Path (Join-Path $payloadRoot '*') -DestinationPath $portableArtifact -CompressionLevel Fastest -Force
Compress-Archive -Path (Join-Path $payloadRoot '*') -DestinationPath $payloadArchive -CompressionLevel Fastest -Force

if (Test-Path -LiteralPath $artifact) { Remove-Item -LiteralPath $artifact -Force }
Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean --onefile --name CareerPilotSetup --icon $iconPath --distpath (Split-Path $artifact) --workpath (Join-Path $buildRoot 'setup-work') --specpath $buildRoot --add-data "$payloadArchive;." (Join-Path $PSScriptRoot 'installer\launcher.py')
    if ($LASTEXITCODE -ne 0) { throw '安装器打包失败。' }
} finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath $artifact)) { throw '安装器生成失败。' }

[pscustomobject]@{
    Artifact = $artifact
    PortableArtifact = $portableArtifact
    SizeMB = [math]::Round((Get-Item $artifact).Length / 1MB, 1)
    PortableSizeMB = [math]::Round((Get-Item $portableArtifact).Length / 1MB, 1)
} | Format-List
