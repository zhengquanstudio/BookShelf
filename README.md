# BookShelf 书格

BookShelf 是一个 Windows 桌面电子书书库管理工具，支持 EPUB、PDF、MOBI、AZW3 的扫描、元数据整理、标签与文件夹管理、书库备份恢复和阅读。双击书籍会在独立的阅读窗口中打开，书库界面不受影响。

当前版本：**1.1.4**。应用界面使用中文，主窗口最小尺寸为 1180×880。EPUB 阅读内核为 foliate-js（与 Readest 同源，MIT 许可），PDF 使用 pdf.js。

## 安装与数据

- 使用 `release\BookShelf-Setup-1.1.4.exe` 安装，可在安装向导中自选程序目录；普通用户安装不需要管理员权限。
- 安装向导使用简体中文；如果 Inno Setup 未附带中文语言文件会自动回退英文。
- 安装器创建开始菜单图标，可选创建桌面图标与电子书右键菜单。
- 安装器只把 BookShelf 加入电子书“打开方式”候选，不抢占已有默认程序。
- 书库数据库、设置、缓存、日志与阅读进度保存在 `%APPDATA%\BookShelf`。
- 覆盖安装沿用上次程序目录；卸载只清理程序目录，保留 `%APPDATA%\BookShelf`，重装后可继续使用原数据。

## 阅读窗口

- 双击书籍、右键菜单“在新窗口阅读”或详情页阅读按钮，都会打开独立的阅读窗口；关闭阅读窗口即保存进度。
- 同一本书只保留一个阅读窗口，重复打开会切换到已有窗口。
- 设置里的“双击书籍”可改为用外部程序打开。
- 载入失败或超时时会显示错误页，可直接用系统默认程序打开，或点“重试”。
- EPUB 由 foliate-js 排版，支持目录跳转、按页翻页、全文搜索、书签、选中高亮与笔记，进度按 CFI 保存；字体、字号、行距、页边距和主题在阅读中即时生效。

## 本地运行

需要 Python 3.11：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试应使用临时目录，不得指向真实书库、真实配置或真实备份。

## 一键构建

安装 Inno Setup（自带 `Languages\ChineseSimplified.isl` 时安装向导为中文）后执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

脚本会依次生成版本信息、清理旧构建、生成 onedir、编译安装包、复制到 `release\` 并计算 SHA256。也可用 `-InnoCompiler` 指定编译器：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build.ps1 -InnoCompiler "D:\Inno Setup\ISCC.exe"
```

产物：

- `dist\BookShelf\BookShelf.exe`：免安装 onedir 主程序，整个 `BookShelf` 目录需一起分发。
- `release\BookShelf-Setup-1.1.4.exe`：安装包。
- `release\checksums.txt`：安装包 SHA256。

只构建 onedir 时可使用 `-SkipInstaller`。

版本号只在 `app\config.py` 的 `APP_VERSION` 修改；`tools\gen_version.py` 会同步生成 EXE 与安装器版本信息。固定 `AppId` 不得修改，否则无法识别覆盖安装。

## 首版范围

首版包含 R0–R3 的正确性修复、必要体验与基础分发能力：元数据合并与规范化、路径安全和整理撤销、分页与窗口状态记忆、数据库备份恢复、分阶段阅读加载、空书库引导，以及 onedir 和 Inno Setup 安装包。1.1.2 起 EPUB 阅读内核为 foliate-js（Readest 同源，MIT），PDF 继续使用 pdf.js。

首版明确不包含：

- 自动更新与回滚菜单。
- 三视图、封面墙、虚拟书库与查询 DSL。
- 完整模板语言。
- OPDS、WebDAV 与插件系统。
- TTS、划词翻译与笔记导出。
- `ebook-convert` 格式转换扩展。
- 小于 1180×880 的小屏自适应布局。

安装与覆盖安装的人工验收步骤见 `docs\INSTALL-CHECKLIST.md`。许可证见 `LICENSE` 与 `NOTICE`。
