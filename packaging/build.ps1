$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $root 'build\installer'
$sourceRoot = Join-Path $buildRoot 'release-source'
$payloadRoot = Join-Path $buildRoot 'payload'
$payloadArchive = Join-Path $buildRoot 'payload.zip'
$pyDist = Join-Path $buildRoot 'pyinstaller'
$pyWork = Join-Path $buildRoot 'pyinstaller-work'
$artifact = Join-Path $root 'dist\CareerPilotSetup.exe'
$portableArtifact = Join-Path $root 'dist\CareerPilot-portable.zip'
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

Push-Location (Join-Path $sourceRoot 'frontend')
try {
    & corepack pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & corepack pnpm build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally {
    Pop-Location
}

$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Missing backend Python environment.' }
Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean --onedir --name CareerPilotBackend --distpath $pyDist --workpath $pyWork --specpath $buildRoot --paths (Join-Path $sourceRoot 'backend') --collect-all litellm --collect-all tiktoken --collect-submodules tiktoken_ext --collect-submodules langgraph --collect-submodules langchain_mcp_adapters (Join-Path $sourceRoot 'backend\packaged_server.py')
    if ($LASTEXITCODE -ne 0) { throw 'Backend packaging failed.' }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $pgHome)) { throw 'PostgreSQL 18 installation was not found.' }
Copy-Item -Path (Join-Path $pyDist 'CareerPilotBackend\*') -Destination $payloadRoot -Recurse -Force
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
Copy-Item -Path (Join-Path $PSScriptRoot 'installer\install.ps1') -Destination (Join-Path $payloadRoot 'install.ps1') -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'installer\uninstall.ps1') -Destination (Join-Path $payloadRoot 'uninstall.ps1') -Force

$iconSource = Join-Path $sourceRoot 'frontend\public\brand-mark.png'
$iconPath = Join-Path $payloadRoot 'brand-mark.ico'
Add-Type -AssemblyName System.Drawing
$sourceImage = [System.Drawing.Image]::FromFile($iconSource)
$iconImage = New-Object System.Drawing.Bitmap(256, 256)
$graphics = [System.Drawing.Graphics]::FromImage($iconImage)
$graphics.DrawImage($sourceImage, 0, 0, 256, 256)
$iconImage.Save($iconPath, [System.Drawing.Imaging.ImageFormat]::Icon)
$graphics.Dispose()
$iconImage.Dispose()
$sourceImage.Dispose()

if (Test-Path -LiteralPath $portableArtifact) { Remove-Item -LiteralPath $portableArtifact -Force }
Compress-Archive -Path (Join-Path $payloadRoot '*') -DestinationPath $portableArtifact -CompressionLevel Fastest -Force

Compress-Archive -Path (Join-Path $payloadRoot '*') -DestinationPath $payloadArchive -CompressionLevel Fastest -Force

if (Test-Path -LiteralPath $artifact) { Remove-Item -LiteralPath $artifact -Force }
Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean --onefile --name CareerPilotSetup --icon $iconPath --distpath (Split-Path $artifact) --workpath (Join-Path $buildRoot 'setup-work') --specpath $buildRoot --add-data "$payloadArchive;." (Join-Path $PSScriptRoot 'installer\launcher.py')
    if ($LASTEXITCODE -ne 0) { throw 'Installer packaging failed.' }
} finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath $artifact)) { throw 'Installer creation failed.' }

[pscustomobject]@{
    Artifact = $artifact
    PortableArtifact = $portableArtifact
    SourceCommit = (git rev-parse HEAD)
    SizeMB = [math]::Round((Get-Item $artifact).Length / 1MB, 1)
    PortableSizeMB = [math]::Round((Get-Item $portableArtifact).Length / 1MB, 1)
} | Format-List
