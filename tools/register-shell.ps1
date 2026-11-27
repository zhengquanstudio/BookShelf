# 注册 / 注销 BookShelf 的文件关联与右键菜单（只写 HKCU，不改默认打开方式）
param(
    [string]$ExePath = "E:\BookShelf\dist\BookShelf.exe",
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$exts = @(".epub", ".pdf", ".mobi", ".azw3")
$progId = "BookShelf.ebook"
$appId = "BookShelf.exe"

function Remove-KeyIfExists([string]$path) {
    if (Test-Path $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
        Write-Host "已删除 $path"
    }
}

if ($Unregister) {
    foreach ($ext in $exts) {
        Remove-KeyIfExists "HKCU:\Software\Classes\SystemFileAssociations\$ext\shell\BookShelfRead"
        Remove-KeyIfExists "HKCU:\Software\Classes\$ext\OpenWithProgids\$progId"
    }
    Remove-KeyIfExists "HKCU:\Software\Classes\Applications\$appId"
    Remove-KeyIfExists "HKCU:\Software\Classes\$progId"
    Write-Host "注销完成。"
    return
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "找不到程序：$ExePath（请先打包，或用 -ExePath 指定路径）"
}

$iconPath = "E:\BookShelf\app\ui\resources\app.ico"
if (-not (Test-Path $iconPath)) { $iconPath = $ExePath }

# 1) ProgID：双击/打开方式使用的命令
New-Item -Path "HKCU:\Software\Classes\$progId\shell\open\command" -Force | Out-Null
Set-ItemProperty "HKCU:\Software\Classes\$progId" -Name "(Default)" -Value "电子书"
New-Item -Path "HKCU:\Software\Classes\$progId\DefaultIcon" -Force | Out-Null
Set-ItemProperty "HKCU:\Software\Classes\$progId\DefaultIcon" -Name "(Default)" -Value "$iconPath,0"
Set-ItemProperty "HKCU:\Software\Classes\$progId\shell\open\command" -Name "(Default)" -Value "`"$ExePath`" `"%1`""

# 2) 加入“打开方式”候选（不抢默认）
foreach ($ext in $exts) {
    New-Item -Path "HKCU:\Software\Classes\$ext\OpenWithProgids" -Force | Out-Null
    New-ItemProperty -Path "HKCU:\Software\Classes\$ext\OpenWithProgids" -Name $progId -Value "" -PropertyType String -Force | Out-Null
}

# 3) Applications 注册（“更多应用”里可见）
New-Item -Path "HKCU:\Software\Classes\Applications\$appId\shell\open\command" -Force | Out-Null
Set-ItemProperty "HKCU:\Software\Classes\Applications\$appId" -Name "FriendlyAppName" -Value "书库助手 BookShelf"
Set-ItemProperty "HKCU:\Software\Classes\Applications\$appId\shell\open\command" -Name "(Default)" -Value "`"$ExePath`" `"%1`""

# 4) 右键菜单：用 BookShelf 阅读
foreach ($ext in $exts) {
    $key = "HKCU:\Software\Classes\SystemFileAssociations\$ext\shell\BookShelfRead"
    New-Item -Path "$key\command" -Force | Out-Null
    Set-ItemProperty $key -Name "(Default)" -Value "用 BookShelf 阅读"
    Set-ItemProperty $key -Name "Icon" -Value "$iconPath,0"
    Set-ItemProperty "$key\command" -Name "(Default)" -Value "`"$ExePath`" `"%1`""
}

Write-Host "注册完成：$ExePath"
Write-Host "已加入打开方式候选 + 右键菜单，默认打开方式未改动。"
Write-Host "若要让 BookShelf 成为默认：设置 → 应用 → 默认应用 → 按文件类型选择。"
Write-Host "撤销：powershell -ExecutionPolicy Bypass -File tools\register-shell.ps1 -Unregister"
