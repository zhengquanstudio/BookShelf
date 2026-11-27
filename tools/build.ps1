[CmdletBinding()]
param(
    [string]$InnoCompiler = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
# Python 在英文系统上默认用 cp1252 输出，脚本里任何中文 print 都会 UnicodeEncodeError。
# 本地中文 Windows 看不出来，GitHub Actions 上必现，这里统一强制 UTF-8。
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

function Resolve-InnoCompiler([string]$ExplicitPath) {
    $candidates = @()
    if ($ExplicitPath) { $candidates += $ExplicitPath }
    if ($env:INNO_ISCC) { $candidates += $env:INNO_ISCC }
    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $candidates += @(
        "D:\Inno Setup\ISCC.exe",
        "D:\Inno\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
        "C:\Program Files\Inno Setup 7\ISCC.exe"
    )
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "找不到 ISCC.exe。请安装 Inno Setup，或用 -InnoCompiler 指定路径。"
}

Push-Location $Root
try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "找不到虚拟环境 Python：$Python"
    }

    & $Python "tools\gen_version.py"
    if ($LASTEXITCODE -ne 0) { throw "版本信息生成失败，退出码 $LASTEXITCODE" }

    # --clean 清理临时构建缓存，--noconfirm 直接替换 build/dist 旧产物。
    & $Python -m PyInstaller "BookShelf.spec" --noconfirm --clean --log-level WARN
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败，退出码 $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath "dist\BookShelf\BookShelf.exe" -PathType Leaf)) {
        throw "构建结束但未找到 dist\BookShelf\BookShelf.exe"
    }

    $releaseDir = Join-Path $Root "release"
    # 历史安装包一律保留：不要清空 release 目录，只覆盖当前版本的同名文件。
    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    $checksumPath = Join-Path $releaseDir "checksums.txt"
    $appVersion = (& $Python -c "from app.config import APP_VERSION; print(APP_VERSION)").Trim()
    if (-not $appVersion) { throw "无法读取 APP_VERSION" }

    if (-not $SkipInstaller) {
        $ISCC = Resolve-InnoCompiler $InnoCompiler
        & $ISCC "/Q" "installer\BookShelf.iss"
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译失败，退出码 $LASTEXITCODE" }

        $setup = Get-Item -LiteralPath (Join-Path $releaseDir "BookShelf-Setup-$appVersion.exe") -ErrorAction SilentlyContinue
        if (-not $setup) { throw "Inno Setup 编译结束但未找到安装包" }
    }

    $checksums = Get-ChildItem -LiteralPath $releaseDir -Filter "BookShelf-Setup-*.exe" -File |
        Where-Object { $_.Name -eq "BookShelf-Setup-$appVersion.exe" } |
        ForEach-Object {
            $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
            "$($hash.Hash.ToLowerInvariant())  $($_.Name)"
        }
    $checksums | & $Python -c "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.stdin.read(), encoding='ascii')" $checksumPath

    Write-Host "onedir：$Root\dist\BookShelf\BookShelf.exe"
    if (-not $SkipInstaller) { Write-Host "安装包与校验值：$releaseDir" }
    if ($SkipInstaller) { Write-Host "已按参数跳过安装包编译。" }
}
finally {
    Pop-Location
}
