#requires -Version 7.0
<#
.SYNOPSIS
  把本地安装包 + 校验值 + 发布说明上传到 GitHub Release（走 REST API，不依赖网页/gh CLI）。

.EXAMPLE
  $env:GH_TOKEN = "ghp_xxx"
  .\tools\upload_release.ps1

.EXAMPLE
  .\tools\upload_release.ps1 -Version 1.1.4 -SkipExe
#>
[CmdletBinding()]
param(
    [string]$Token = $env:GH_TOKEN,
    [string]$Repo = "zhengquanstudio/BookShelf",
    [string]$Version = "",
    [switch]$SkipExe,
    [switch]$Draft
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    if (-not $Token) {
        throw "缺少 token。先执行：`$env:GH_TOKEN = `"ghp_xxx`"（scopes 需要 repo）"
    }
    if (-not $Version) {
        $Version = (& "$Root\.venv\Scripts\python.exe" -c "from app.config import APP_VERSION; print(APP_VERSION)" 2>$null)
        if (-not $Version) { throw "无法读取 APP_VERSION，请用 -Version 指定" }
        $Version = $Version.Trim()
    }
    $Tag = if ($Version.StartsWith("v")) { $Version } else { "v$Version" }
    $Ver = $Tag.TrimStart("v")
    $Name = "书格 $Ver"

    $Head = @{
        Authorization          = "token $Token"
        Accept                 = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
        "User-Agent"           = "bookshelf-release-script"
    }

    # 0) token 自检
    $me = curl.exe -s -f -H "Authorization: token $Token" -H "User-Agent: bookshelf-release-script" "https://api.github.com/user"
    if ($LASTEXITCODE -ne 0) { throw "token 无效或权限不足（需要 repo scope）" }
    $login = ($me | ConvertFrom-Json).login
    Write-Host "token 有效：$login  目标仓库：$Repo  版本：$Ver"

    # 1) 发布说明正文
    $notesPath = Join-Path $Root "docs\release-notes-v$Ver.md"
    if (Test-Path $notesPath) {
        $body = Get-Content $notesPath -Raw -Encoding utf8
    } else {
        $inChangelog = Select-String -Path (Join-Path $Root "CHANGELOG.md") -Pattern "^## \[$([regex]::Escape($Ver))\]" -Context 0,60
        if ($inChangelog) {
            $body = (($inChangelog.Context.PostContext) -join "`n")
        } else {
            $body = "见 CHANGELOG.md。"
        }
    }

    # 2) 找/建 Release
    $existing = curl.exe -s -H "Authorization: token $Token" -H "X-GitHub-Api-Version: 2022-11-28" `
        "https://api.github.com/repos/$Repo/releases/tags/$Tag"
    $relJson = $null
    try { $relJson = $existing | ConvertFrom-Json } catch { }
    if (-not $relJson -or -not $relJson.id) {
        Write-Host "Release $Tag 不存在，按 tag 现建（tag 必须已 push 到远端）"
        $payload = @{
            tag_name         = $Tag
            name             = $Name
            body             = $body
            draft            = [bool]$Draft
            prerelease       = $false
            make_latest      = "true"
        } | ConvertTo-Json -Depth 4
        $payloadPath = Join-Path $env:TEMP "bookshelf-release.json"
        [IO.File]::WriteAllText($payloadPath, $payload, [Text.UTF8Encoding]::new($false))
        $created = curl.exe -s -f -X POST `
            -H "Authorization: token $Token" -H "X-GitHub-Api-Version: 2022-11-28" `
            -H "Content-Type: application/json" --data-binary "@$payloadPath" `
            "https://api.github.com/repos/$Repo/releases"
        if ($LASTEXITCODE -ne 0) { throw "创建 Release 失败（tag $Tag 是否已 push？）" }
        $relJson = $created | ConvertFrom-Json
        Write-Host "已创建 Release id=$($relJson.id)"
    } else {
        Write-Host "Release 已存在 id=$($relJson.id)，更新说明正文"
        $payload = @{ name = $Name; body = $body; draft = [bool]$Draft; make_latest = "true" } | ConvertTo-Json -Depth 4
        $payloadPath = Join-Path $env:TEMP "bookshelf-release.json"
        [IO.File]::WriteAllText($payloadPath, $payload, [Text.UTF8Encoding]::new($false))
        curl.exe -s -X PATCH -H "Authorization: token $Token" -H "X-GitHub-Api-Version: 2022-11-28" `
            -H "Content-Type: application/json" --data-binary "@$payloadPath" `
            "https://api.github.com/repos/$Repo/releases/$($relJson.id)" | Out-Null
    }

    $releaseId = $relJson.id
    $uploadBase = "https://uploads.github.com/repos/$Repo/releases/$releaseId/assets"

    function Get-Assets {
        (curl.exe -s -H "Authorization: token $Token" -H "X-GitHub-Api-Version: 2022-11-28" `
            "https://api.github.com/repos/$Repo/releases/$releaseId/assets") | ConvertFrom-Json
    }

    function Send-Asset([string]$Path, [string]$AssetName) {
        $sizeMb = "{0:N1}" -f ((Get-Item $Path).Length / 1MB)
        Write-Host "上传 $AssetName（$sizeMb MB）…"
        $enc = [uri]::EscapeDataString($AssetName)
        $t0 = Get-Date
        $uploadUrl = "${uploadBase}?name=$enc"
        curl.exe -# -X POST `
            -H "Authorization: token $Token" -H "X-GitHub-Api-Version: 2022-11-28" `
            -H "Content-Type: application/octet-stream" `
            --data-binary "@$Path" `
            $uploadUrl
        if ($LASTEXITCODE -ne 0) { throw "上传失败：$AssetName" }
        $sec = [int]((Get-Date) - $t0).TotalSeconds
        Write-Host "完成 $AssetName（$sec s）"
    }

    $assets = Get-Assets
    $existingNames = @($assets | ForEach-Object { $_.name })

    $uploadList = @()
    if (-not $SkipExe) {
        $exe = Join-Path $Root "release\BookShelf-Setup-$Ver.exe"
        if (-not (Test-Path $exe)) { throw "找不到安装包：$exe（先跑 tools\build.ps1）" }
        $uploadList += @{ Path = $exe; Name = "BookShelf-Setup-$Ver.exe" }
    }
    $checks = Join-Path $Root "release\checksums.txt"
    if (Test-Path $checks) {
        # 网页上传器拒收纯 .txt，这里改用 .sha256 后缀命名
        $uploadList += @{ Path = $checks; Name = "BookShelf-Setup-$Ver.sha256" }
    }

    foreach ($item in $uploadList) {
        if ($existingNames -contains $item.Name) {
            Write-Host "已存在同名附件，先删除：$($item.Name)"
            $id = ($assets | Where-Object { $_.name -eq $item.Name } | Select-Object -First 1).id
            curl.exe -s -X DELETE -H "Authorization: token $Token" -H "X-GitHub-Api-Version: 2022-11-28" `
                "https://api.github.com/repos/$Repo/releases/assets/$id" | Out-Null
        }
        Send-Asset -Path $item.Path -AssetName $item.Name
    }

    Write-Host ""
    Write-Host "完成。Release 页面：https://github.com/$Repo/releases/tag/$Tag"
}
finally {
    Pop-Location
}
