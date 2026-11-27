# BookShelf 整合开发与整改总纲 v4

> **v4 相对 v3 的三处根本变化**
> 1. 许可决策改了：既然"别人拿去商用也无所谓"，就**不再回避 GPL**，BookShelf 定为 **GPL-3.0-or-later**，代码级借鉴 Calibre 从此合法可行。
> 2. 回答了"三家选哪个当最大借鉴源"：**Calibre 第一，Readest 只取 foliate-js（MIT），Koodo 只做交互参照**，理由与代价见第 3 章。
> 3. 新增第 6 章「Calibre 代码移植手册」——含一个必须提前知道的坑：**同栈不等于能 import**（calibre 自带私有 Python + Qt，混进程必崩），真正的移植路径是"抄逻辑 + 子进程调 CLI"。

> 适用对象：AI 编程代理（Claude Code / Cursor / Codex）与开发者本人。
> 阅读顺序：第 3 章（选哪个）→ 第 5 章（许可）→ 第 6 章（怎么搬）→ 第 7 章（缺陷）→ 第 8 章（怎么排期）→ 第 9/10 章（怎么发版）→ 第 14 章（喂给 AI）。

---

## 1. 项目现状快照

| 项 | 值 |
|---|---|
| 根目录 | `E:\BookShelf` |
| 语言/框架 | Python 3.11.16 + PySide6 6.7.3（Qt 6 WebEngine） |
| 数据 | SQLite，`C:\Users\<user>\AppData\Roaming\BookShelf\library.db`，SCHEMA_VERSION=2 |
| 代码量 | 约 1.1 万行；20 个测试文件 / 194 用例，`pytest -q` 全绿 |
| 打包 | PyInstaller onefile，`dist\BookShelf.exe` 174 MB，冷启 5.6 s |
| 版本 | APP_VERSION=1.0.2，APP_NAME_CN="书库助手" |
| 格式 | .epub / .pdf / .mobi / .azw3 |
| 已做 | 扫描→识别→作者/系列/卷号归档→去重→标签→基础阅读→备份→单实例转发（双击打开）→图标 |
| 待生效 | `app.ico` 已接入 spec，但 exe 是旧构建，需重打包 |

---

## 2. 定位与硬边界

**一句话**：Windows 桌面端的「电子书自动归档 + 内嵌阅读」工具——把散乱下载的文件按「作者 / 系列 / 卷号」整理成书库，双击即可在软件内部阅读。

**做**：本地优先、离线可用、复制不删原件、国内网络友好、双击/右键即读。

**不做**：
1. 不破解 DRM、不做任何规避技术措施的功能；
2. 不做 macOS / iOS / Android / Web；
3. 不上传用户书籍（WebDAV 只连用户自有账号）；
4. 不 SetParent 嵌外部 exe、不整包嵌入 Tauri 版 Readest；
5. 不做强制联网校验。

---

## 3. 三家选哪个当"最大借鉴源"

### 3.1 打分（针对你的具体处境：已有 11k 行 Python + PySide6）

| 维度 | Calibre | Readest | Koodo Reader |
|---|---|---|---|
| 语言/框架是否与你一致 | **Python + Qt（PyQt6）** ✅ 同栈 | Rust + Next.js/TS ❌ 全异 | Node + React ❌ 全异 |
| 现有代码能否复用 | ✅ 全部保留 | ❌ 等于重写 | ❌ 等于重写 |
| 是否正好补齐你最缺的 | ✅ 元数据多源、模板引擎、格式转换、OPDS、插件 | 部分（排版、标注） | 部分（双页、TTS、翻译） |
| 成熟度/资料量 | **20 年积累，官方 API 文档全（manual 站点直接挂模块源码）** | 新，但文档较好 | 中型，中文资料多 |
| 许可与你的决策是否相容 | ✅ GPL-3，你已定 GPL-3 → 可合法搬 | ⚠️ AGPL-3，可合并但网络条款随整体生效 | ⚠️ AGPL-3，同上 |
| 代码搬到 Python 项目的实际难度 | 中（见第 6 章，不能 import，要"抄逻辑"） | 极高（要写 JS 桥） | 极高 |
| 拿到"成熟功能"的速度 | **快（逻辑可对照改写，CLI 可直调）** | 慢（2–6 周只为一个阅读内核） | 慢 |
| 迭代更新可持续性 | **强（有稳定 upstream 可跟随）** | 强 | 中 |

### 3.2 结论

> **最大借鉴源 = Calibre**
> 理由一句话：**同语言、同 GUI 框架、你的短板正好是它的长板、而且它 20 年积累的那套东西（元数据源、模板语法、转换管线、内容服务器）你自己写要几年。**

**Readest 只看一块**：`foliate-js`（MIT，独立仓库，Readest 的阅读引擎上游）。这是唯一值得整包引进来当内核的东西，因为它许可干净、体积小、QtWebEngine 直接吃得下。

**Koodo 只做交互参照**：封面墙怎么排、双页怎么切、导入向导怎么问、设置面板怎么组织——看它的产品逻辑，不碰它的 React 代码。

### 3.3 一句话路线

```
Python/PySide6 骨架（保留）
  + foliate-js 阅读内核（MIT，替换现有 reader.html/js）
  + Calibre 的"逻辑与能力"（GPL-3 合规借鉴：元数据源改写、模板语法、转换走 CLI、OPDS 自研）
  + Koodo 的交互设计（纯设计参考）
```

**不要做的事**：不要 fork Calibre 当底座。Calibre 是"全格式转换中枢 + 设备同步 + 插件平台"的巨兽，fork 它你会花三个月删功能，而不是加功能。你的差异化是"作者-系列-卷号自动归档"，Calibre 恰恰不做这个。

---

## 4. 可整合进 BookShelf 的功能总表

### 4.1 P0 — 第一批（1–2 周）

| # | 功能 | 主借鉴源 | 落地方式 | 成本 |
|---|---|---|---|---|
| P0-1 | 书库三视图：列表 / 封面墙 / 作者分组 | Calibre | 复用 `query_books`，加两个 View + 切换器 | 2d |
| P0-2 | 虚拟书库（筛选存成"书架"） | Calibre | 筛选参数序列化进 `app_settings`，侧栏列出 | 2d |
| P0-3 | 元数据双栏编辑 + 多候选对比 | Calibre | `EditBookDialog` 左原值右候选（来源+置信度+逐字段勾选） | 3d |
| P0-4 | 命名模板实时预览 | Calibre | 借它的模板语法（`{author}/{series:0>2}` 之类），输入即渲染样例 | 2d |
| P0-5 | `metadata.opf` 导入/导出 | Calibre | 整理时写侧车文件，可被 Calibre 直接读 | 1d |
| P0-6 | 单页 / 双页 / 连续滚动 | Readest+Koodo | foliate-js 三模式 + 按书记忆 | 3d |
| P0-7 | 封面墙 + 空封面占位 | Koodo | 封面缓存 + 生成式占位 | 1d |
| P0-8 | 导入向导（复制入库 / 仅登记路径） | Koodo | 扫描前二选一，写清盘行为 | 1d |

### 4.2 P1 — 第二批（3–5 周）

| # | 功能 | 主借鉴源 | 落地方式 |
|---|---|---|---|
| P1-1 | 高亮 / 书签 / 笔记 + 导出 MD | Readest | foliate-js annotations + 侧栏 |
| P1-2 | 排版面板（字号/行距/页边距/字体/护眼/夜间） | Readest | CSS 变量 + 面板 |
| P1-3 | 书内搜索 + 结果高亮跳转 | 三家 | foliate-js search API |
| P1-4 | 格式转换 | Calibre | **子进程调 `ebook-convert`**（检测本机 calibre，不捆绑） |
| P1-5 | 批量任务队列 + 进度面板 | Calibre | 统一 `TaskQueue`，扫描/识别/转换都走它 |
| P1-6 | OPDS 1.2 只读内容服务器 | Calibre | Python 起 HTTP，供手机/其他阅读器拉书；需鉴权 |
| P1-7 | WebDAV 备份（DB+封面+进度） | Koodo | 坚果云等，用户自填 |
| P1-8 | 标签/设置改右侧面板 + 阅读统计 | Calibre+Koodo | 去模态弹窗 |

### 4.3 P2 — 后续

| # | 功能 | 来源 | 备注 |
|---|---|---|---|
| P2-1 | TTS + 句级高亮 | Koodo/Calibre | edge-tts 或 SAPI，断网走本地 |
| P2-2 | 划词翻译 + StarDict 本地词典 | Koodo | 不默认外发全文 |
| P2-3 | PDF 智能裁边重排 | KOReader 思路 | pdf.js + 图像处理 |
| P2-4 | DJVU / CBR / CBZ / DOCX | Koodo | DJVU 走转换到 PDF |
| P2-5 | 插件系统（元数据源/导出器入口点） | Calibre | 框架自研，接口照它的思路 |
| P2-6 | 设备同步（Kindle/Kobo 盘符推送） | Calibre | 只做手动同步 |
| P2-7 | 阅读标尺 / RSVP 速读 / 仿真翻页 | KOReader/Readest | 阅读体验加分项 |
| P2-8 | RSS/新闻转 EPUB | Calibre | 版权与来源合规 |

### 4.4 三个"别抄"

1. **别抄 Calibre 的转换管线（plumber）与插件运行时**——它依赖 calibre 自己的环境，搬进来就是搬一座山。转换走 CLI。
2. **别抄 Electron / Tauri 的整套架构**——你现在 Qt 更轻，只是为了"同构"重写没有收益。
3. **别为功能齐全牺牲"自动归档"**——那是三家都不做、只有你有的东西。

---

## 5. 许可决策记录（ADR-001）

### 5.1 决策

> **BookShelf 采用 `GPL-3.0-or-later` 单一许可，全量开源（源码随发行版提供）。**
> 前提已确认：本人不商用；他人拿去商用**不作为限制条件**，也不需要阻止。

### 5.2 为什么这个选择让"最大化借鉴"成立

| 借鉴对象 | 许可 | 在 GPL-3 项目里能否合法使用其代码 | 依据 |
|---|---|---|---|
| **Calibre** | GPL-3.0 | ✅ **可以** | 同为 GPL-3，属于同类许可的衍生/合并 |
| **Koodo Reader** | AGPL-3.0 | ⚠️ **可以合并**，但 AGPL 第 13 条（网络交互须提供源码）随整体生效 | GPLv3 §13 允许与 AGPLv3 组成组合作品 |
| **Readest** | AGPL-3.0 | ⚠️ 同上 | 同上 |
| **foliate-js** | MIT | ✅ 可以，且不受传染 | MIT 兼容 GPL |

代价必须接受的三条：
1. **发行 exe 必须同时提供完整源码**（放 GitHub，安装包与"关于"页给链接即可，不必塞进安装包）；
2. **每个移植文件保留原作者版权头**，`NOTICE` 列清来源与 commit；
3. **不能加"禁止商用"条款**——那会让许可自相矛盾。想表达态度就写在 README（"本项目不用于商业目的"是社区声明，不是许可限制）；事实上 GPL 下别人商用你无法阻止，你也已接受。

### 5.3 一个容易忽略的连带影响

一旦合并了 AGPL 代码（Readest/Koodo），**整个 BookShelf 都受 AGPL 第 13 条约束**：只要它通过网络对外提供服务（比如 P1-6 的 OPDS 内容服务器），就必须向这些网络用户提供对应源码。

你已开源，所以这条对你无成本——但要在 OPDS 服务页放一行"源码地址"，这才叫合规。

### 5.4 合规清单（每次发版对照）

- [ ] 仓库根有 `LICENSE`（GPL-3.0 全文）
- [ ] `NOTICE` 列出：calibre（版本/commit/被移植的文件）、foliate-js、pdf.js、OpenCC、highlight.js、PySide6(LGPL)
- [ ] 每个移植文件头部保留原版权声明 + 追加一行"Ported into BookShelf, modified by <you>, <date>"
- [ ] "关于"页：源码链接、许可名称、第三方声明入口
- [ ] 安装包内 `licenses\` 目录含各依赖许可原文
- [ ] 若启用 OPDS：服务页显示源码地址
- [ ] README 写明"非商业用途"仅为作者声明，不构成额外许可限制（可选）

---

## 6. Calibre 代码移植手册

### 6.1 先讲那个坑：同栈 ≠ 能 import

Calibre 发行版自带**私有的 Python 解释器和私有编译的 Qt**，它还带一堆 C 扩展（`html5_parser`、`regex`、`msgpack`、`tinycss2` 的定制版等）。你在自己的 PySide6 进程里 `import calibre...`：

- 轻则 `ModuleNotFoundError: calibre.utils.…`；
- 重则 PyQt6 与 PySide6 两套绑定同进程 → **直接崩溃**；
- 打包时 PyInstaller 也解析不了它的动态导入。

**所以"搬 Calibre"只有两条真实路径**：

| 路径 | 做法 | 适用 | 风险 |
|---|---|---|---|
| **A. 抄逻辑（推荐，主力）** | 读它的源码，把**算法/语法/规则**用自己的代码重写，不留 calibre 依赖 | 命名模板、文件名净化、元数据源解析、系列归一化、重复判定 | 中：要读懂再写，不能复制粘贴整文件（那会带来一片依赖） |
| **B. 子进程调 CLI（推荐，重活）** | 检测用户机器上是否装了 calibre，用 `ebook-convert` / `calibre-debug -c "..."` 跑 | 格式转换、批量元数据抓取、OPDS 起服务 | 低：进程隔离，崩了也不影响主程序；但依赖用户装 calibre |
| C. 直接复制文件进 vendor | 整文件拷贝 | —— | **高，不推荐**：依赖链会自动扩散，最后你要维护半个 calibre |

> 一句话：**能力搬进来，代码别搬进来。**

### 6.2 值得"抄逻辑"的模块清单（按性价比排序）

| 优先级 | Calibre 模块/能力 | 你要写的东西 | 工作量 |
|---|---|---|---|
| ★★★ | `calibre.utils.filenames`（`sanitize_path`、`ascii_filename`、保留名/长度处理） | `app/core/pathsafe.py`：逐段净化、Windows 保留名、255 字节截断、Unicode 归一化 | 1d |
| ★★★ | calibre **模板语言**（StringFormatter 语法：`{author}`, `{series:0>2}`, `{tags:', '}`, 函数 `uppercase()` 等） | `app/core/template.py`：自己实现一个小型格式化 DSL，支持字段、格式串、切片、条件。**不要引入 jinja**（语法不兼容用户习惯） | 3d |
| ★★★ | `calibre.ebooks.metadata.sources.*`（`amazon`/`google`/`covers`/`edelweiss` 等，统一 `Source` 基类：`identify()` / `download_cover()` / `touched_fields`） | `app/net/sources/`：写自己的 `Source` 抽象（identify/fetch_cover/priority/touched_fields），再按它实现的**解析思路**写国内源（PDC / 豆瓣 / 微信读书 / 京东） | 5d |
| ★★☆ | `calibre.ebooks.oeb` 的元数据读写思路（opf 结构、`<meta>` 字段映射） | `app/core/opf.py`：读写 `metadata.opf`（结构照 Calibre 的，这样它能直接读） | 1d |
| ★★☆ | calibre 内容服务器 / OPDS 的**路由与 XML 结构** | `app/net/opds.py`：`/opds`、`/opds/author/{id}`、`/opds/series/{id}`、`/get/{id}/{fmt}`，Atom XML | 3d |
| ★★☆ | `calibre.ebooks.conversion` 的**选项语义**（页边距、字体、TOC 生成规则） | 不自己写转换器：把选项映射成 `ebook-convert` 参数 | 2d |
| ★☆☆ | 虚拟书库的**查询 DSL**（`tags:"x" and authors:"y"`） | `app/core/query_dsl.py`：字段+布尔+比较，翻译成 SQL | 2d |
| ★☆☆ | 插件 API 的**类型划分**（元数据源 / 输出格式 / 设备 / 界面动作） | 后期再考虑，先别做 | — |

### 6.3 PyQt6 → PySide6 适配表（"抄逻辑"时必然遇到）

| Calibre 写法（PyQt6） | BookShelf 写法（PySide6） |
|---|---|
| `from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot` | `from PySide6.QtCore import Qt, Signal, Slot` |
| `pyqtSignal(str)` | `Signal(str)` |
| `Qt.ItemDataRole.DisplayRole` | 枚举可直接用 `Qt.DisplayRole`（PySide6 两种都行，统一用短名） |
| `QAction` in `QtGui` | `QAction` in `PySide6.QtGui`（一致） |
| `Qt.AlignmentFlag.AlignLeft` | `Qt.AlignLeft` |
| `QApplication.exec()` | `app.exec()` |
| `sip`/`pyqtProperty` | `Property`（`PySide6.QtCore.Property`） |
| `QRegExp` | `QRegularExpression`（两边都该换了） |
| `QtCore.QVariant` | 直接传 Python 对象 |

**规则**：不允许 `import PyQt6` 出现在任何文件里；CI 加一条 grep 检查（`grep -r "PyQt6" app/` 必须为空）。

### 6.4 目录约定

```
app/
├── core/
│   ├── pathsafe.py         # 源自 calibre.utils.filenames 的逻辑（自写）
│   ├── template.py         # 命名模板 DSL（参考 calibre StringFormatter 语法）
│   ├── opf.py              # metadata.opf 读写（结构对齐 Calibre）
│   └── query_dsl.py        # 虚拟书库查询语法
├── net/
│   ├── sources/
│   │   ├── base.py         # Source 抽象（identify/fetch_cover/priority/touched_fields）
│   │   ├── pdc.py  douban.py  weread.py  jd.py
│   │   └── registry.py     # 源装配、按字段优先级调度、失败降级
│   └── opds.py
├── services/
│   └── convert_service.py  # 检测 calibre → 组装 ebook-convert 参数 → 子进程 → 进度回传
└── vendor/
    └── foliate-js/         # MIT，附 LICENSE
```

`docs/UPSTREAM.md` 记录：被借鉴的 calibre 版本、commit、文件清单、移植人、日期——以后跟随升级时按这张表比对。

### 6.5 跟随上游更新（"成熟软件方便快速迭代"的正解）

不是"把 calibre 拉下来当依赖"，而是**定期回看**：

| 频率 | 动作 |
|---|---|
| 每季度 | 看 calibre 的 `metadata/sources/` 新增/失效了哪些源（网站改版很频繁），同步改自己的 `sources/` |
| 每半年 | 看模板语言有无新语法、opf 字段有无扩展 |
| 每次发版前 | 跑一遍真实书库回归（95 本），确认净化/模板/元数据没退化 |

`tools/sync_upstream.md` 里放一份"比对清单"，把"该看哪几个文件"写死，避免每次重新找。

---

## 7. 缺陷与整改清单

### 7.1 A 级：正确性（先修）

| 编号 | 位置 | 现象 | 修法 | 验收 |
|---|---|---|---|---|
| A1 | `app/core/naming.py:248` `_author_directory` | 中文作者被强加国别，出"大仲马 [法国]"目录 | 国别仅在确有国籍数据或作者名为拉丁字母时加；`{国家}` 空则连同分隔符省略 | 中文作者目录 = 纯作者名 |
| A2 | `scan_service._record_duplicate` | 用 stem 覆盖 `title`、清空 `author_raw`/`isbn`；保留谁取决于扫描顺序 | 字段级合并：非空优先、来源优先级 手填>元数据>文件名；标题取信息量更大者；记 `dup_of`；结果与顺序无关 | 重复导入元数据不丢、两次不同顺序结果一致 |
| A3 | 默认 `hierarchy="series_first"` | 与"作者目录放该作者全部书"相反 | 默认 `author_first`，系列作二级；提供三选一 | 默认结果 `作者/系列/卷号 - 书名.epub` |
| A4 | 默认 `file_template` 缺 `{卷号}` | 卷号在文件名中丢失 | 默认 `{作者} - {卷号} {书名}.{扩展名}`，空值省分隔符 | 多卷书名带"第1卷" |

### 7.2 B 级：功能与体验

| 编号 | 问题 | 修法 |
|---|---|---|
| B1 | 查询硬限 1000 本、无分页（`library_service.py:37`） | 游标分页 + 虚拟滚动 |
| B2 | 只认 ASCII 罗马数字 I–X | 补 Ⅰ–Ⅻ、中文"第一卷/卷一"、阿拉伯混排 |
| B3 | 系列聚类弱，`XX全集/套装/合集` 归并不上 | 归一化：去副标题括号、去"全集/套装/合集"、卷号正则扩展 |
| B4 | 元数据仅 OpenLibrary/Google Books，国内直连超时 | 建 `sources/` 适配层；国内源 PDC/豆瓣/微信读书/京东；全失败降级本地文件名解析 |
| B5 | 无应用图标 | ✅ 已做（7 尺寸 ico + AppUserModelID + spec icon），待重打包 |
| B6 | exe 无版本信息、onefile 174MB、冷启 5.6s、双进程 | onedir + `version_info.txt` + Inno Setup |
| B7 | 无闪屏、首启无引导 | `QSplashScreen` + 首启向导 |
| B8 | 不记忆窗口位置；最小 1180×880 小屏越界 | 存 `geometry/state`；最小 960×640；按 `availableGeometry` 夹取 |
| B9 | 菜单"合并重复作者/统一卷号"是假入口 | 实现（别名表+合并事务）或删除 |
| B10 | 长路径只截书名 | 按层级截断，保留卷号与扩展名，tooltip 全路径 |
| B11 | 撤销清空书库所有空目录 | 只删本次创建的目录（记 `created_dirs`） |
| B12 | onefile 双进程 | onedir 单进程 |
| B13 | 标签/设置是模态弹窗 | 改右侧可停靠面板 |
| B14 | "外部 Readest"实为调已装程序，文案误导 | 删除，或改名"用系统默认程序打开" |
| B15 | 备份无路径/保留策略 | 备份列表（时间/大小/路径）+ 保留 N 份 + 恢复前自动再备份 |
| B16 | 清缓存无确认 | 二次确认 + 显示释放空间 |
| B17 | 阅读器无加载进度 | 遮罩 + 百分比 + 失败兜底 |
| B18 | 空书库无引导 | 空状态页 + 三步 CTA |

### 7.3 C 级：文案与边角

| 编号 | 问题 | 修法 |
|---|---|---|
| C1 | `failed` 行空白 | 加"原因"列，落 `task_log` |
| C2 | 跳过文案与条件不符 | 逐条校对 |
| C3 | copy 模式仍提示"归档" | 统一"复制入库" |
| C4 | `stem.split(".")[0]` 截断含点书名 | 改 `os.path.splitext` |
| C5 | 保留名未处理目录每一段 | 逐段净化（并入 `pathsafe.py`） |

### 7.4 仍待处理

- A1–A4 源码未改（最影响体验）；
- `dist\BookShelf.exe` 是旧构建，图标未生效；
- `tools\register-shell.ps1` 未执行（写 HKCU，用安装器做成可选勾选更合适）。

---

## 8. 阶段计划 S0–S6

> 每阶段完成即：`pytest -q` 全绿 + 手工验证 + git tag。不跨阶段并行改文件。

### S0 基线（0.5 天）
清 `_audit\`、`_run_err.txt`、`_run_out.txt`、探针产生的备份；`git init` + `.gitignore`（`.venv/ dist/ build/ *.db _audit/`）；建 `docs/`（本文档 + 前序 + `LICENSE` + `NOTICE` + `UPSTREAM.md`）；记录基线耗时与内存。

### S1 正确性（3–5 天）
A1–A4 + C1–C5。纯逻辑，全走单测。
**验收**：新增 ≥12 用例；用 95 本真实文件夹跑，目录结构符合预期。

### S2 交互与稳定（5–8 天）
B1、B2、B3、B7、B8、B10、B11、B13、B15、B16、B17、B18。
**验收**：1366×768 可用；空库有引导；备份可恢复；阅读有进度。

### S3 阅读内核（5–8 天）
引入 foliate-js（MIT）：`app/reader/assets/vendor/foliate-js/` + 保留 LICENSE；`bridge.py` 重写为 QWebChannel 协议（`openBook`/`goTo`/`search`/`addAnnotation`/`setTheme`/`setLayout`/`setFont`）；三模式、目录、搜索、高亮、主题、按书记忆；删 `open_external`（B14）。
**验收**：EPUB 打开 <800ms；双页无白屏；高亮重开仍在。

### S4 能力汲取（8–12 天）——本阶段是 v4 的核心变化
顺序做（都走"抄逻辑"，不整文件拷贝）：
1. `pathsafe.py`（1d）——顺带彻底解决 C5/B10；
2. `template.py` 命名模板 DSL + 设置页实时预览（3d）→ 同时消掉 A4 与 P0-4；
3. `sources/` 抽象 + 国内源首批（PDC 必做，豆瓣/京东按可抓性）→ 顺带解决 B4（4d）；
4. `opf.py`（1d）；
5. 三视图 + 虚拟书库（query_dsl）（3d）。
**验收**：断网也能靠国内源识别 ≥70%；模板预览与实际落盘完全一致；`metadata.opf` 能被 Calibre 读入。

### S5 打包安装（3–5 天）
onedir + `version_info.txt` + Inno Setup + 覆盖升级 + 自动更新（见第 9、10 章）。
**验收**：全新机器装 → 自选目录 → 图标正常 → 双击 .epub 打开 → 覆盖安装后数据保留。

### S6 持续增强
P1 全量 → P2 选做。每 2 周一个迭代，一次只上一个条目。

### 工期

| 阶段 | 工期 | 累计 |
|---|---|---|
| S0 | 0.5d | 0.5d |
| S1 | 3–5d | 5.5d |
| S2 | 5–8d | 13.5d |
| S3 | 5–8d | 21.5d |
| S4 | 8–12d | 33.5d |
| S5 | 3–5d | 38.5d |

单人全职约 **6–7 周** 到"可分发 v2.0"（比 v3 略短，因为 S4 有了明确的借鉴路径，不再从零设计）。

---

## 9. 打包与安装

### 9.1 onefile → onedir

```python
exe = EXE(pyz, a.scripts, [],
          exclude_binaries=True,
          name='BookShelf', console=False,
          icon='app/ui/resources/app.ico',
          version='version_info.txt')
coll = COLLECT(exe, a.binaries, a.datas, name='BookShelf')
```

`version_info.txt` 必须含：`FileDescription`、`ProductName`、`CompanyName`、`FileVersion=2.0.0.0`、`ProductVersion`、`LegalCopyright`。收益：冷启 5.6s → 1–2s，单进程，更新只换变动文件。

### 9.2 Inno Setup（`installer\BookShelf.iss` 要点）

```ini
[Setup]
AppId={{8F3C2A11-5B7D-4E9A-9C21-BOOKSHELF0001}}   ; 固定 GUID，永不变
AppName=BookShelf 书库助手
AppVersion=2.0.0
DefaultDirName={localappdata}\Programs\BookShelf
DisableProgramGroupPage=yes
PrivilegesRequired=lowest          ; 按用户装，免 UAC，支持静默自更新
UsePreviousAppDir=yes              ; ★ 覆盖安装沿用上次目录
CloseApplications=yes              ; ★ 装前自动关旧版
Compression=lzma2/ultra64
SetupIconFile=..\app\ui\resources\app.ico
UninstallDisplayIcon={app}\BookShelf.exe
OutputBaseFilename=BookShelf-Setup-2.0.0
LicenseFile=..\LICENSE             ; GPL-3 全文（合规要求）
```

三条铁律：
1. `AppId` GUID 一旦定下永不修改——它是覆盖安装的唯一标识；
2. 程序装 `{app}`，用户数据永远在 `%APPDATA%\BookShelf`，升级不动；
3. `PrivilegesRequired=lowest` + `{localappdata}`，才能静默更新不弹 UAC。

卸载默认**保留**书库数据，向导末页提示"数据保留在 …"。

---

## 10. 更新机制与上游跟随

### 10.1 `update.json`

```json
{"version":"2.1.0","url":"https://…/BookShelf-Setup-2.1.0.exe",
 "sha256":"…","size":92345123,"notes":"修复卷号识别，新增双页模式",
 "mandatory":false,"min_version":"1.9.0"}
```

### 10.2 客户端流程（`app/services/update_service.py`）

1. 启动后延迟 10s 检查，或"帮助→检查更新"；
2. `packaging.version` 比版本；
3. 下载到 `%LOCALAPPDATA%\BookShelf\updates\`，**校验 sha256**；
4. `BookShelf-Setup-x.y.z.exe /SILENT /CLOSEAPPLICATIONS /NORESTART`；
5. 安装器按 `AppId` 覆盖，数据目录不动；
6. 重启后 `schema_version` 不符先备份再迁移，失败回滚。

不做差分更新：ondir + lzma2 后安装包 60–90 MB，不值得那个复杂度。

### 10.3 数据迁移

`app/db/migrations/v2_to_v3.sql` 按序号排；启动比对 `schema_version`；迁移前自动备份；只增不删。

### 10.4 回滚

保留最近 2 个安装包 + 3 份备份；"回滚到上一版本"菜单项。

### 10.5 跟随 Calibre 上游

见 6.5：季度看元数据源变化，半年看模板/opf 变化，发版前跑 95 本回归。

---

## 11. 工程规范

```
E:\BookShelf
├── main.py
├── app/
│   ├── core/      naming series pathsafe template opf query_dsl constants
│   ├── db/        schema.sql migrations/ repos/
│   ├── services/  scan organize metadata library maintenance convert update
│   ├── net/       client sources/{base,pdc,douban,weread,jd,registry} opds
│   ├── reader/    view bridge + assets/(reader.html, vendor/foliate-js)
│   ├── ui/        main_window pages/ dialogs/ widgets/ resources/
│   └── ipc.py
├── installer/BookShelf.iss
├── tools/         build.ps1 register-shell.ps1 make_icon.py sync_upstream.md
├── tests/
├── docs/          v4 总纲 + 前序 + LICENSE + NOTICE + UPSTREAM.md
├── BookShelf.spec  version_info.txt
```

规则：
- `core/`、`services/`、`net/` 不得 import PySide6（保证可测）；
- UI 只做展示与转发；
- 路径操作一律走 `pathsafe.py`；
- 移植来的文件头必须写来源（见 5.4）；
- CI 检查：`grep -r "PyQt6" app/` 为空、`pytest -q` 全绿。

---

## 12. 测试与验收

| 层级 | 内容 | 目标数量 |
|---|---|---|
| 单元 | naming / series / pathsafe / template / opf / 合并策略 | 130+ |
| 集成 | 扫描→去重→归档→撤销（临时目录） | 30+ |
| 网络 | sources 各源用固定 fixture 测解析（不真联网） | 20+ |
| UI 冒烟 | 离屏构造主窗、切页、开阅读器 | 15+ |
| 手工 | 95 本真实库、安装/覆盖/卸载 20 项清单 | 20 项 |

**DoD**：测试全绿 + 手工清单通过 + 无空壳入口 + 版本号与 CHANGELOG 更新 + 合规清单勾完。

---

## 13. 路线图

| 季度 | 目标 |
|---|---|
| Q1 | S0–S3：正确性、体验、foliate-js 内核、双击即读稳定 |
| Q2 | S4–S5：能力汲取（模板/国内源/opf/三视图/虚拟书库）+ 安装包与自动更新 → 发 v2.0 并开源 |
| Q3 | P1 全量：标注、排版、转换（CLI）、任务队列、OPDS、WebDAV |
| Q4 | P2 选做：TTS/翻译/PDF 重排/格式扩展/插件框架 |

---

## 14. 喂给 AI 的提示词模板

**通用前置（每次都贴）**

```
项目：BookShelf（E:\BookShelf），Windows 桌面电子书整理+阅读工具。
技术栈：Python 3.11 + PySide6 6.7.3 + SQLite + QtWebEngine；打包 PyInstaller(onedir) + Inno Setup。
许可：GPL-3.0-or-later（本项目已开源，允许借鉴 Calibre 的 GPL 代码逻辑）。
硬约束：
1) 禁止 import PyQt6；禁止引入 GPL/AGPL 第三方"包"，只允许 MIT/Apache/BSD 库；
2) 借鉴 Calibre 时只能"抄逻辑并重写"，不得整文件复制（会扩散依赖）；
3) core/ services/ net/ 不得 import PySide6；
4) 不破解 DRM、不上传用户书籍；
5) 改动前后 pytest -q 必须全绿；
6) 只改本阶段涉及的文件。
先读 docs/BookShelf-整合开发与整改总纲-v4.md 的第 6 章（移植手册）、第 7 章（缺陷表）、第 11 章（工程规范）。
```

**S1**

```
任务：修 A1–A4、C1–C5（总纲 7.1/7.3）。
- A1：中文作者不加国别；{国家} 为空则省分隔符（改 naming.py 的 _author_directory / _file_name）
- A2：_record_duplicate 改字段级合并（手填>元数据>文件名），标题取信息量更大者，记 dup_of，结果与扫描顺序无关
- A3：默认 hierarchy=author_first
- A4：默认 file_template 加 {卷号}，空值省分隔符
- C4：os.path.splitext；C5：逐段净化（新建 app/core/pathsafe.py）
每项补单测，并输出"改前/改后路径样例"对比。不要动 UI。
```

**S2**

```
任务：修 B1/B2/B3/B7/B8/B10/B11/B13/B15/B16/B17/B18（总纲 7.2）。
重点：B1 去 limit=1000 改游标分页；B8 存 geometry/state、最小 960×640、按 availableGeometry 夹取；
B13 标签与设置改右侧可停靠面板（保留原对话框作兜底）；B15 备份列表+保留策略+恢复前再备份；
B17 阅读加载遮罩+进度+失败兜底。每项给手工验证步骤。
```

**S3**

```
任务：阅读内核换 foliate-js（MIT）。
1) vendor 到 app/reader/assets/vendor/foliate-js/，保留 LICENSE；
2) bridge.py 重写为 QWebChannel：openBook/goTo/search/addAnnotation/setTheme/setLayout/setFont；
3) reader.html 用 <foliate-view>，实现单页/双页/连续；
4) 位置/模式/主题存 reading_state；
5) 删除 open_external。
验收：EPUB 打开 <800ms，双页无白屏，高亮重开仍在，原有用例全绿。
```

**S4**

```
任务：情境化借鉴 Calibre（只抄逻辑，见总纲第 6 章）。
1) app/core/pathsafe.py：参考 calibre.utils.filenames 的规则（保留名/非法字符/长度/Unicode），自己重写；
2) app/core/template.py：实现模板 DSL（{author} {series:0>2} {tags:', '} 与 uppercase() 等函数），
   设置页做"输入即预览最终路径"；
3) app/net/sources/{base,pdc,douban,weread,jd,registry}.py：先写 Source 抽象
   （identify/fetch_cover/priority/touched_fields），再实现 PDC（国家版本数据中心）解析；
   全部失败时降级为本地文件名解析；
4) app/core/opf.py：读写 metadata.opf，结构对齐 Calibre（保证它能读）；
5) 三视图 + 虚拟书库（app/core/query_dsl.py 把 tags:"x" and authors:"y" 翻成 SQL）。
每个新建文件头写：来源、许可、是否改写。
```

**S5**

```
任务：打包与安装（总纲 9/10 章）。
1) spec 改 onedir + version='version_info.txt'；
2) 生成 version_info.txt（FileVersion/ProductName/CompanyName/LegalCopyright）；
3) installer/BookShelf.iss：固定 AppId、PrivilegesRequired=lowest、DefaultDirName={localappdata}\Programs\BookShelf、
   UsePreviousAppDir=yes、CloseApplications=yes、LicenseFile=..\LICENSE、桌面/开始菜单/可选右键菜单、卸载保留 %APPDATA%；
4) app/services/update_service.py：update.json → 版本比较 → 下载 → sha256 校验 → /SILENT /CLOSEAPPLICATIONS；
5) tools/build.ps1 一键 build → iscc → release/。
验收：全新安装可自选目录；覆盖安装数据保留；文件属性版本正确。
```

---

## 15. 变更记录

| 版本 | 内容 |
|---|---|
| **v4** | 许可改为 GPL-3.0 全量开源（ADR-001）；新增第 3 章"三家选哪个"打分与结论（Calibre 为主借鉴源）；新增第 6 章 Calibre 移植手册（同栈不可 import 的坑、抄逻辑/子进程两条路、PyQt6→PySide6 适配表、上游跟随）；S4 重定义为"能力汲取"；新增合规清单与 CI 检查项 |
| v3 | 三份前序合并；借鉴总表；S0–S6；Inno Setup + 更新机制；AI 提示词 |
| v2 | 运行验收 + 23 项探针 + Readest 四路线 + 国内源 + B12–B18 |
| v1 | 首轮审计 A/B/C 分级、20 项缺陷、M0–M6 |
