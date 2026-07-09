$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Runtime = Join-Path $Root ".runtime"
$Installers = Join-Path $Root ".installers"
$NodeHome = Join-Path $Runtime "node"
$CondaHome = Join-Path $Runtime "miniforge"
$PyPrefix = Join-Path $Runtime "python"

function Pause-And-Exit($Message) {
  Write-Host $Message
  Read-Host "按回车退出"
  exit 1
}

function Ensure-Node {
  $NodeExe = Join-Path $NodeHome "node.exe"
  if (Test-Path $NodeExe) {
    $env:Path = "$NodeHome;$env:Path"
    return
  }

  $Archive = Get-ChildItem -Path $Installers -Filter "node-v*-win-x64.zip" | Select-Object -First 1
  if (-not $Archive) { Pause-And-Exit "缺少 Node.js Windows x64 安装包。" }

  $Extract = Join-Path $Runtime "node-extract"
  Remove-Item -Recurse -Force $Extract, $NodeHome -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path $Extract | Out-Null
  Expand-Archive -Path $Archive.FullName -DestinationPath $Extract -Force
  Move-Item (Get-ChildItem -Path $Extract -Directory | Select-Object -First 1).FullName $NodeHome
  Remove-Item -Recurse -Force $Extract -ErrorAction SilentlyContinue
  $env:Path = "$NodeHome;$env:Path"
}

function Ensure-Python {
  $CondaExe = Join-Path $CondaHome "Scripts\conda.exe"
  if (-not (Test-Path $CondaExe)) {
    $Installer = Get-ChildItem -Path $Installers -Filter "Miniforge3-Windows-x86_64.exe" | Select-Object -First 1
    if (-not $Installer) { Pause-And-Exit "缺少 Miniforge Windows x64 安装包。" }
    $Args = @("/InstallationType=JustMe", "/RegisterPython=0", "/AddToPath=0", "/S", "/D=$CondaHome")
    Start-Process -FilePath $Installer.FullName -ArgumentList $Args -Wait
  }

  $Py = Join-Path $PyPrefix "python.exe"
  if (-not (Test-Path $Py)) {
    & $CondaExe create -y -p $PyPrefix -c conda-forge python=3.11
  }

  $Marker = Join-Path $PyPrefix ".quake-deps-ok"
  $DepsOk = $false
  if (Test-Path $Marker) {
    & $Py -c "import pandas, numpy, matplotlib, cartopy, shapefile, requests, docx" *> $null
    $DepsOk = ($LASTEXITCODE -eq 0)
  }

  if (-not $DepsOk) {
    & $CondaExe install -y -p $PyPrefix -c conda-forge pandas numpy matplotlib cartopy pyshp requests python-docx
    & $Py -c "import pandas, numpy, matplotlib, cartopy, shapefile, requests, docx"
    New-Item -ItemType File -Force -Path $Marker | Out-Null
  }

  return $Py
}

New-Item -ItemType Directory -Force -Path $Runtime, ".cache/matplotlib" | Out-Null
Ensure-Node
$NodeExe = Join-Path $NodeHome "node.exe"
$NpmCmd = Join-Path $NodeHome "npm.cmd"
$Py = Ensure-Python

if (-not (Test-Path "node_modules")) {
  & $NpmCmd install --no-audit --no-fund
}

if (-not (Test-Path ".next\standalone\server.js")) {
  $env:NEXT_TELEMETRY_DISABLED = "1"
  & $NpmCmd run build
}

$ServerJs = Join-Path $Root ".next\standalone\server.js"
if (-not (Test-Path $ServerJs)) {
  Pause-And-Exit "构建完成，但没有找到 .next\standalone\server.js。"
}

$env:PYTHON = $Py
$env:NODE_ENV = "production"
$env:PORT = if ($env:PORT) { $env:PORT } else { "3100" }
$env:HOSTNAME = "localhost"
$env:NEXT_TELEMETRY_DISABLED = "1"
$env:MPLCONFIGDIR = Join-Path $Root ".cache/matplotlib"
$env:CARTOPY_DATA_DIR = Join-Path $Root "data\cartopy"
$env:QUAKE_PYTHON_WORKER = "1"
$env:QUAKE_USGS_CATALOG_DB = Join-Path $Root "var\usgs_catalog.sqlite"
$env:QUAKE_USGS_CATALOG_STATUS = Join-Path $Root "var\usgs_catalog_status.json"
Remove-Item Env:QUAKE_OFFLINE -ErrorAction SilentlyContinue

Write-Host "正在增量更新 USGS 目录..."
& $Py "scripts\sync_usgs_catalog.py" --db $env:QUAKE_USGS_CATALOG_DB --status-json $env:QUAKE_USGS_CATALOG_STATUS --min-mag 3
if ($LASTEXITCODE -ne 0) {
  Write-Warning "USGS 目录更新失败，将使用包内现有目录继续启动。"
}

$Url = "http://localhost:$($env:PORT)"
Start-Job -ScriptBlock {
  param($Url)
  for ($i = 0; $i -lt 60; $i++) {
    try {
      Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1 | Out-Null
      Start-Process $Url
      return
    } catch {
      Start-Sleep -Seconds 1
    }
  }
} -ArgumentList $Url | Out-Null

Write-Host "启动地震报告系统：$Url"
Write-Host "关闭此窗口即可停止服务。"
& $NodeExe $ServerJs
