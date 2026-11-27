# 书格 · 发布上传脚本（REST API，绕开网页上传器）

用途：本地打包出 `release\BookShelf-Setup-<版本>.exe` 后，一条命令把 **exe + 校验值 + 发布说明 MD** 挂到 GitHub Release，不再依赖网页拖文件（国内网络下 118MB 走网页上传经常失败）。

## 1. 准备一个 token（只需一次）

GitHub → 头像 → Settings → Developer settings → Personal access tokens → **Tokens (classic)** → Generate new token：
- Note：`bookshelf-release`
- Expiration：90 days（到期再换）
- Scope：**勾 `repo`**（只这一个就够）

生成后复制 `ghp_...`，**只在本机环境变量里用，别写进仓库**：

```powershell
# 当前窗口有效（关掉即失效，最安全）
$env:GH_TOKEN = "ghp_xxxxxxxx"
```
要长期免输，就写进用户环境变量（离开窗口也有效）：
```powershell
setx GH_TOKEN "ghp_xxxxxxxx"
```

## 2. 上传

```powershell
cd E:\BookShelf
# 用当前 APP_VERSION 和它的发布说明、安装包
.\tools\upload_release.ps1

# 指定版本 / 只传说明不传 exe
.\tools\upload_release.ps1 -Version 1.1.4
.\tools\upload_release.ps1 -Version 1.1.4 -SkipExe
```

脚本做的事：
1. 校验 token（`GET /user`）；
2. 找 `v<版本>` 这个 Release，没有就按 `tag` 现建，标题「书格 <版本>」；
3. 说明正文优先取 `docs\release-notes-v<版本>.md`，没有就用 CHANGELOG 该版本段；
4. 传 `release\BookShelf-Setup-<版本>.exe`（已存在同名附件先删再传）；
5. 传 `release\checksums.txt`；网页上传器拒收这个 .txt 时脚本会自动改名为 `BookShelf-Setup-<版本>.sha256` 再传；
6. 打印 Release 页面地址。

## 3. 和 CI 的关系

- **CI 自动路径**：`git tag v1.2.0 && git push origin v1.2.0` → Actions 的 `release` 流水线自动打包并发 Release，用的是仓库自带 `GITHUB_TOKEN`，不需要这个脚本；
- **本地兜底路径**：CI 挂了、或只想传现成的包，就用这个脚本；
- 两条路都基于同一个 tag，先后跑不会互相覆盖（脚本按附件名判重）。

> token 只给脚本用，不进 git、不进 Release、不进日志。

## 4. 从 1.1.5 起的标准动作（给 AI 编程照做）

1. 改 `app\config.py` 的 `APP_VERSION = "1.1.5"`；
2. `CHANGELOG.md` 顶部加 `## [1.1.5] - 日期` 一段，写清「新增 / 变更 / 修复」；
3. 新建 `docs\release-notes-v1.1.5.md`（就是 Release 页面正文，写成给用户看的话，含下载、安装、SHA256 占位、已知问题）；
4. `python -m pytest tests -q` 必须全绿；
5. `tools\build.ps1` 出包，确认 `release\BookShelf-Setup-1.1.5.exe` 与 `checksums.txt` 都在；
6. 本地兜底上传：`$env:GH_TOKEN="ghp_..."; .\tools\upload_release.ps1`；
7. 走 CI 自动：`git tag v1.1.5; git push origin main v1.1.5`，等 Actions 的 `release` 跑完自动挂包；
8. 两个都跑也无害：脚本会按附件名判重、覆盖同名附件，Release 正文以脚本/CI 最后一次写入为准。

**红线**：`APP_VERSION` 与 tag 必须一致（tag 不带 `v` 前缀或带都可以，脚本会自动补 `v`）；安装包不进 git；`release\` 目录留给本地和 CI 产物。

