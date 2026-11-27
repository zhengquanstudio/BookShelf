# 书格（BookShelf）施工总图 v3 · 给 TRAE 的执行手册

> 生成时间：2026-11-26 · 适用版本：README 1.1.3 之后的下一个版本
> 本文件是**唯一施工依据**。旧文档（`BookShelf-全量整改方案-v3.md` 的 S1–S11、`BookShelf-菜单与功能扩展方案-v2.md` 的 T1–T9、`BookShelf-阅读界面重构规范-v1.md` 的 S1–S6）编号已在本文件重排为 F/R/L/M/D 前缀，**避免 S 编号三处冲突**；旧文档降级为"细节附录"，冲突时以本文件为准。

---

## 0. 视觉基准（必须先打开再动手）

以下 3 个 HTML 是**唯一视觉验收标准**，不是参考、不是灵感，是"改完要长成这样"。用 Chrome/Edge 直接打开，与 Qt 实际界面并排比对。

| 文件 | 覆盖什么 |
|---|---|
| `docs\书格-UI原型.html` | 书库列表 + 右侧详情面板 + 批量操作浮动条；卡片视图；阅读器骨架 |
| `docs\书格-UI原型-v2-书架统计笔记设置.html` | 我的书架（网格/列数/分组/排序）、阅读统计、笔记与高亮、设置页 8 分组 |
| `docs\书格-阅读界面原型.html` | **最新版**阅读界面：单页/双页摊开、顶栏封面+书名+作者、i 详情可编辑元数据、Aa 四 tab、底栏、自动隐藏 |

**动工前的固定动作**（每个任务都做，不做等于白改）：

1. 先在浏览器打开对应 HTML，用 `Win+Shift+S` 或 `Alt+PrintScreen` 记下目标画面；
2. 改完 Qt，用同一窗口尺寸（建议 1440×900）截图，与原型叠对比；
3. 差异超过 2px 的位置、或颜色肉眼可辨，都算没改完。

---

## 1. 硬红线（违反即回滚，不要"顺手优化"）

1. **不许抄 Readest 代码**。`readest-main\` 是 AGPL-3.0，只允许"看一眼布局思路"，任何代码片段、CSS、函数名都不能进本项目。内核升级只从上游 `foliate-js`（MIT）拉。
2. **不许改 `APP_NAME` / `APP_USER_MODEL_ID` / 数据目录**（`app/config.py:18-19`）。中文显示名从 `APP_NAME_CN` 改成「书格」即可，目录名继续 `BookShelf`，否则老用户数据全丢。
3. **不许改 README / CHANGELOG 的版本号**，版本由发版流程统一改。
4. **不许引入新依赖**，除非本文件点名（唯一新增：`pypinyin`，纯 Python，MIT）。
5. **不许把 UI 改成"深色卡片 + 圆角大阴影"那套**。本项目是纸感、低对比、细边框、几乎无阴影的风格，所有颜色取自第 2 节 token。
6. **任何写文件的操作都要先备份**（`.bak` 同目录），任何"删除"都要走回收站或 `undo` 批次，不许 `rmtree` 直接删。
7. 不许 `git commit` 里混入多个任务编号，一个编号一个提交。

---

## 2. 设计 token（唯一来源）

主窗口与书库：`app/ui/theme_tokens.py`；阅读器：`reader.css` 的 `:root`。两边必须来自同一份数据，不允许手填十六进制。

```css
/* 基础（浅色） */
--canvas:#eae6de;   /* 窗口底 */
--paper:#fbf8f0;    /* 卡片/纸面 */
--chrome:#f3eee2;   /* 顶栏、左导航、底栏 */
--panel:#fffdf7;    /* 浮层、输入框 */
--ink:#2f2a22;      /* 主文字 */
--muted:#8b8371;    /* 次要文字 */
--line:#dfd6c2;     /* 1px 分隔线 */
--accent:#a97c3c;   /* 主色（琥珀） */
```

尺寸（和原型一一对应，别改）：

| 元素 | 值 |
|---|---|
| 主窗口顶栏 | 高 52（阅读器顶栏 52，书库顶栏 56） |
| 左导航 | 宽 232（一级项高 38，二级项高 34，图标 16） |
| 阅读侧栏抽屉 | 宽 268，章节行高 36，底部 tab 栏 46 |
| 书籍详情浮层 | 宽 404，圆角 14，封面 96×134 |
| Aa 设置浮层 | 宽 360，四 tab 各 1/4，卡片圆角 11 |
| 书页单页宽 | 默认 560（范围 420–900，步进 30） |
| 字号 / 行距 | 19px / 1.95（范围 12–30 / 1.2–2.6） |
| 卡片圆角 | 4（封面）/ 8（按钮）/ 11（卡片）/ 14（浮层） |
| 阴影 | 只有两档：`0 3px 8px rgba(70,56,32,.12)`、`0 18px 40px rgba(70,56,32,.18)` |

八套阅读主题（`page` = 纸面，`ink` = 字色，`canvas` = 窗口底；夜间整套反相）：

| key | 名称 | canvas | page | ink |
|---|---|---|---|---|
| paper | 米黄 | #efe8d8 | #f9f5e9 | #33302a |
| sepia | 羊皮 | #efe3c8 | #f8efd9 | #38301f |
| gray | 灰 | #e6e6e3 | #f7f7f4 | #2f2f2d |
| grass | 草绿 | #dfe8dd | #f4f8f1 | #2c332c |
| cherry | 樱粉 | #f2dedd | #fbf1f0 | #3a2c2c |
| sky | 天空 | #dde7ee | #f2f7fa | #2b333a |
| sunset | 日落 | #f3ddc4 | #fdf2e4 | #3b2e20 |
| night | 夜间 | #1e1c18 | #26231e | #d8cfbe |

高亮五色（`bookmarks.color` 存的就是这些值）：`#f2c14e` 黄、`#d99c98` 红、`#9cc39a` 绿、`#8fb3d9` 蓝、`#b6a4d9` 紫。渲染用 `color-mix(in srgb, <color> 35%, transparent)`，**禁止写死 `#ffe08a`**。

---

## 3. 任务总表（建议严格按顺序，一个编号一次提交）

| 编号 | 任务 | 依赖 | 工期 |
|---|---|---|---|
| **S1** | EPUB 容器大小写容错（15.6% 的书打不开） | — | 0.5d |
| **S2** | 识别状态语义 + 批量重识别 | S1 | 0.5d |
| **F1–F5** | 内置字体真正落地 + 打包 + 字体选择器 | — | 1d |
| **D1–D3** | schema v5（会话表、喜爱/阅读状态、笔记字段） | — | 0.5d |
| **R1–R10** | 阅读界面（单页/双页、顶栏、i 可编辑、Aa、底栏、侧栏、动效、滚动） | F、D | 3.5d |
| **L1–L7** | 书库界面（菜单行、左导航、详情面板含双路径、批量移动、空目录清理、四视图） | D | 2.5d |
| **M1–M6** | 我的书架 / 统计 / 笔记与高亮 / 喜爱 | D、L | 3d |
| **合计** | | | **≈ 11.5 人天** |

S1、S2 是**先修 Bug 再美化**：1872 本里有约 290 本因为 container.xml 大小写不一致被判定"识别失败"，界面做得再好看也盖不住这个洞。

---

## 4. S1 · EPUB 容器容错（P0，先做）

**现象**：`META-INF/container.xml` 写 `ops/fb.opf`（小写），zip 里真实条目是 `OPS/fb.opf`。Python 侧 `zipfile.getinfo` 按字面查找 → `KeyError` → `scan_service` 判 `failed`；JS 侧 `foliate-js` 的 `makeZipLoader` 建的是字面 map → `Failed to load package document`。同一个根因，两处都要修。

**落点**
- `app/core/metadata/epubs.py` → `_package_path()`（约 :42）与 `_read_xml()`（约 :35）
- `app/reader/assets/vendor/foliate-js/*`（`makeZipLoader` / `Epub` 构造函数附近）

**做法**（Python 侧，写成一个私有工具函数，别散落）

```python
def _resolve_entry(zf: zipfile.ZipFile, name: str) -> str:
    """按 字面 → 忽略大小写 → NFC 归一 → unquote 逐级降级匹配 zip 条目名"""
    # 1) name 原样命中直接返回
    # 2) 建一次 size<=2000 的 (casefold(name) -> real_name) 索引，命中即返回
    # 3) unicodedata.normalize('NFC') 后再比一次（macOS 打包常见 NFD）
    # 4) urllib.parse.unquote(name) 再走 2、3
    # 5) 都不中才抛原 KeyError
```

- 索引只在 `extract()` 内部建一次，不要每次查都遍历；
- 同一函数用于 `container.xml`、`.opf`、封面图、`toc.ncx`/`nav.xhtml`，**只改一处，全链路受益**；
- 返回值必须是**真实条目名**，后续 `zf.read()` 用真实名。

JS 侧：在 `makeZipLoader` 里对 `this.entries` 的 key 建 `casefold → real` 的 Map，`get(name)` 时降级查询；不要改 `view.js` 的业务逻辑。

**验收**
```
& .venv\Scripts\python.exe -m pytest tests -q
& .venv\Scripts\python.exe _audit\epub_zip_probe.py      # 78/500 那批应全部可读
```
再手工用受影响的书（`F:\E-book` 里 container 写小写的那本）在阅读器打开，必须能出正文，且**不再出现**"受 DRM 保护的文件不会进行任何解密尝试"这句误导文案（该文案见 `reader_container.py:718-731`，改成随真实原因变化）。

---

## 5. S2 · 识别状态语义 + 批量重识别

**现状**：`scan_service.py:194-203` 只要 `not ok` 就 `failed`，但 `fields` 里其实已经有书名/作者（`parse_name` 从文件名解析出来的 L0 结果）。结果"识别失败"列表里一堆有名字的书，用户以为全废了。

**改法**
1. 状态三分：`ok`（内嵌元数据完整）/ `partial`（只有文件名解析结果或字段残缺）/ `failed`（连书名都取不到）。DB `books.status` 允许 `partial`。
2. 书架筛选条加「待补全（partial）」，图标用半实心圆点；`failed` 用空心圆点。
3. 「批量重识别」：多选 → 右键菜单/批量条 → 对每本调 `metadata_service.find_candidates`，网络源全部超时（国内 OpenLibrary/Google Books 不通，见旧文档 §10）时**不要卡死队列**，单本 8s 超时、50 本一批、进度条 + 可取消。
4. `enrich_book`（:198）现在"failed 原样保留"，改为 partial 也允许被新结果覆盖（覆盖前把旧值记到 `books.meta_history` 可选，先不做也行，但日志要留）。

**验收**：抽 20 本 partial 的书批量重识别，10 分钟内结束，成功/失败分别计数，界面不冻结（QThread 或 QThreadPool，不许在主线程跑网络）。

---

## 6. F1–F5 · 字体

### 6.1 现状（重要）

`app/reader/assets/fonts/` 之前**不存在**，`reader.css` 里写的"霞鹜文楷"一直回退到系统宋体，所以"内嵌字体"是假的。本次已由助手建好目录并放入 7 个字体（见 6.2），TRAE 只需接线，**不要再去下载字体**。

### 6.2 已放入 `app/reader/assets/fonts/` 的文件（本次已落地，勿删）

| 文件 | 内部 family 名 | 用途 | 许可证 |
|---|---|---|---|
| `LXGWWenKai-Regular.ttf` 24.3MB | `LXGW WenKai` | 默认正文（楷体，耐读） | OFL-1.1 |
| `SourceHanSerifCN-Regular.otf` 10.7MB | `Source Han Serif CN` | 宋体选项（印刷感） | OFL-1.1 |
| `LXGWHeartSerifCHS.ttf` 4.0MB | `LXGW Heart Serif CHS` | 霞鹜新明，正文备选 | OFL-1.1 |
| `NotoSansSC-Variable.ttf` 12.2MB | `Noto Sans SC` | 无衬线正文 / 界面中文 | OFL-1.1 |
| `Literata-Variable.ttf` 0.9MB | `Literata` | 英文正文默认（Google Books 官方阅读字体） | OFL-1.1 |
| `SourceSerif4-Variable.ttf` 1.1MB | `Source Serif 4` | 英文正文备选 | OFL-1.1 |
| `EBGaramond-Variable.ttf` 0.8MB | `EB Garamond` | 英文古典/文学 | OFL-1.1 |
| `Inter-Variable.ttf` 0.8MB | `Inter` | 界面英文/数字（tabular 数字对齐） | OFL-1.1 |

合计约 **55MB**。OFL 允许随软件分发，但必须随包附许可证文本：`app/reader/assets/fonts/OFL.txt`（写 "SIL Open Font License 1.1" 全文 + 各字体版权行），F4 任务里生成。

**未入包的（留在 `docs\`（新下载的英文字体在 `docs\fonts-src\`），作为"可选字体"，不打包）**：霞鹜文楷 Light/Medium/Mono、思源宋体 Bold/Light/Medium/SemiBold/Heavy、更纱黑体 SC Semibold（23MB，单字重太重，UI 用 Noto Sans SC 代替）。想加进安装包时，只加"用户真会选的字重"，别把 78MB 的思源宋体全家桶塞进去。

### 6.3 F1 · 字体接线（`reader.html` + `reader.css`）

在 `app/reader/assets/reader.html` 的 `<head>` 里加 `@font-face`，路径用**相对 assets 的相对路径**（`fonts/xxx.ttf`），不要 `file://` 绝对路径，否则 PyInstaller 里会挂：

```css
@font-face{font-family:"LXGW WenKai";src:url("fonts/LXGWWenKai-Regular.ttf") format("truetype");font-weight:400;font-display:block}
@font-face{font-family:"Source Han Serif CN";src:url("fonts/SourceHanSerifCN-Regular.otf") format("opentype");font-weight:400;font-display:block}
@font-face{font-family:"LXGW Heart Serif CHS";src:url("fonts/LXGWHeartSerifCHS.ttf") format("truetype");font-weight:400}
@font-face{font-family:"Noto Sans SC";src:url("fonts/NotoSansSC-Variable.ttf") format("truetype");font-weight:100 900}
@font-face{font-family:"Literata";src:url("fonts/Literata-Variable.ttf") format("truetype");font-weight:200 900}
@font-face{font-family:"Source Serif 4";src:url("fonts/SourceSerif4-Variable.ttf") format("truetype");font-weight:200 900}
@font-face{font-family:"EB Garamond";src:url("fonts/EBGaramond-Variable.ttf") format("truetype");font-weight:400 800}
@font-face{font-family:"Inter";src:url("fonts/Inter-Variable.ttf") format("truetype");font-weight:100 900}
```

- `font-display:block` 而不是 `swap`：阅读器宁可等 30ms 也不要在翻页瞬间换字形；
- 中文字体加载后**必须校验真的生效**：控制台 `document.fonts.check('19px "LXGW WenKai"')` 必须为 true。F2 里写一个 `_audit\font_check.py` 打印 QtWebEngine 里这 8 个 family 的可用性，作为 CI 手检项。
- `reader.css` 的正文 `font-family` 链改成变量：`font-family: var(--reader-font-cjk, "LXGW WenKai"), var(--reader-font-latin, "Literata"), serif;`，中英混排时**西文走拉丁字体、中文回落 CJK**（把 CJK 放前面会导致英文也用中文字体的西文部分，字形偏方）。

### 6.4 F2 · 字体选择器（Aa → 字体 tab）

`reader_container.py` 的字体下拉（现在写死几个无内置的名字）改为读 `fonts.json`：

`app/reader/assets/fonts/fonts.json`（已生成，结构如下，TRAE 按它渲染下拉，不要硬编码）

```json
{
  "version": 1,
  "fonts": [
    {"key":"wenkai","label":"霞鹜文楷","family":"LXGW WenKai","file":"LXGWWenKai-Regular.ttf","lang":"cjk","kind":"serif","default":true},
    {"key":"source-serif-cn","label":"思源宋体","family":"Source Han Serif CN","file":"SourceHanSerifCN-Regular.otf","lang":"cjk","kind":"serif"},
    {"key":"heart-serif","label":"霞鹜新明","family":"LXGW Heart Serif CHS","file":"LXGWHeartSerifCHS.ttf","lang":"cjk","kind":"serif"},
    {"key":"noto-sans-sc","label":"思源黑体（无衬线）","family":"Noto Sans SC","file":"NotoSansSC-Variable.ttf","lang":"cjk","kind":"sans"},
    {"key":"literata","label":"Literata","family":"Literata","file":"Literata-Variable.ttf","lang":"latin","kind":"serif","default":true},
    {"key":"source-serif-4","label":"Source Serif 4","family":"Source Serif 4","file":"SourceSerif4-Variable.ttf","lang":"latin","kind":"serif"},
    {"key":"eb-garamond","label":"EB Garamond","family":"EB Garamond","file":"EBGaramond-Variable.ttf","lang":"latin","kind":"serif"},
    {"key":"inter","label":"Inter（界面）","family":"Inter","file":"Inter-Variable.ttf","lang":"latin","kind":"sans"}
  ]
}
```

- 下拉分两组：**中文**（4 项）/ **English**（4 项）；当前值存 `prefs.reader_font_cjk` / `prefs.reader_font_latin`。
- 切换后用 JS 改 CSS 变量即可，**不要重建 foliate view**（重建会丢滚动位置）。
- 字体文件缺失时下拉项置灰并提示"字体文件缺失"，不许静默回退。

### 6.5 F3 · 界面字体（Qt 侧）

**Qt 原生控件不要用这几个可变字体**。Qt 6.7 对 variable font 的命名实例支持不完整，`addApplicationFont("NotoSansSC-Variable.ttf")` 极易只注册到 `Noto Sans SC Thin`（实测 name 表第一实例就是 Thin），整窗口会变成细体。做法：

- Qt 侧（菜单/表格/对话框）**继续用系统字体**（Windows 下就是微软雅黑 + Segoe UI），只统一字号与颜色：
  ```python
  f = app.font(); f.setPointSize(9); app.setFont(f)          # 9pt ≈ 12px
  ```
- 需要等宽数字的列（页数、文件大小、ISBN、日期），用 `QFontMetrics` 对齐 + `font.setStyleHint(QFont.Monospace)` 兜底，或暂时用 `Consolas`；
- 可变字体**只给 WebEngine 用**（Chromium 对 `font-weight: 100 900` 的可变轴支持完整），也就是 6.3 的 `@font-face`，不要反过来把 WebEngine 的字体注册给 Qt。

### 6.6 F4 · 打包（PyInstaller + Inno Setup）

- `BookShelf.spec` 的 `datas` 已有 `app/reader/assets` 条目，**确认 `fonts/*.ttf|*.otf|*.json` 被递归包含**（PyInstaller 的 datas 不递归子目录时要显式加 `('app/reader/assets/fonts', 'app/reader/assets/fonts')`）。
- 安装包体积会涨 ~55MB，`installer\BookShelf.iss` 不需要改，但要在"安装完成页"或关于页注明"内置字体约 55MB，含 SIL OFL 许可证"。
- 生成 `OFL.txt` 放到 `fonts/` 下，随包分发。

### 6.7 F5 · 字体自检（防再次"假内嵌"）

写 `_audit\font_check.py`：启动 QWebEngine 加载 `reader.html`，执行 `document.fonts.check(...)` 对 8 个 family 逐个断言，并 `document.fonts.forEach` 打印实际加载的 `family/status`。**任何一个 failed 就让脚本 exit 1**。这个脚本进 `tools\build.ps1` 的打包前检查。

**F 验收**：Aa → 字体 tab 里 8 项可切、切换后正文形态明显变化（楷/宋/黑三档肉眼可分）、重启后记忆、`font_check.py` 全绿、安装包安装到干净机器后仍然生效（不依赖系统装过这些字体）。

---

## 7. D1–D3 · 数据层（schema v4 → v5）

### D1 建表/加列（`app/db/schema.sql` + `app/db/migrate.py`，`SCHEMA_VERSION 4→5`）

```sql
CREATE TABLE IF NOT EXISTS reading_sessions (
  id INTEGER PRIMARY KEY,
  book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  started_at TEXT NOT NULL,          -- ISO8601 本地时间
  ended_at TEXT,
  seconds INTEGER DEFAULT 0,
  pages INTEGER DEFAULT 0,
  device TEXT DEFAULT 'desktop'
);
CREATE INDEX IF NOT EXISTS ix_rs_day ON reading_sessions(substr(started_at,1,10));
CREATE INDEX IF NOT EXISTS ix_rs_book ON reading_sessions(book_id);

ALTER TABLE books ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0;
ALTER TABLE books ADD COLUMN read_state TEXT NOT NULL DEFAULT 'unread';  -- unread/reading/read
ALTER TABLE books ADD COLUMN status TEXT NOT NULL DEFAULT 'ok';          -- ok/partial/failed（S2）
```

迁移注意：SQLite 的 `ALTER TABLE ADD COLUMN` 不能带 `NOT NULL` 无默认值，上面都带默认值，安全；迁移前把 `library.db` 复制一份 `library.db.bak-v4`，失败要能回滚并提示。

### D2 会话采集

- `reader_container.py` 的 `showEvent` 起会话、`hideEvent`/`closeEvent` 结束；`QTimer(60s)` flush 一次 `seconds += 60`；
- 只统计 `isActiveWindow()` 为真且未最小化的时间；翻页时 `pages += 1`（回写 `bridge.saveProgress` 时顺带）；
- 会话落库失败只记日志，不许弹窗打断阅读。

### D3 prefs 键（`reader_container.py::_reader_prefs()`，约 :1707）

新增键（缺省值写死在这里，别散落）：`reader_font_cjk/latin`、`page_mode`（`single`/`spread`）、`page_width`（560）、`show_clock`、`show_remaining`、`auto_turn_sec`（0=关）、`reading_ruler`、`mask_top`、`highlight_colors`（5 色）、`disable_double_click`、`turn_anim`。

**验收**：`pytest tests -q` 全绿（现有 286 项不许挂）；老库升级后 1872 本书目、笔记、进度一条不少（用 `_audit` 里现成的抽样脚本核对 `count(*)`）。

---

## 8. R1–R10 · 阅读界面（对照 `docs\书格-阅读界面原型.html`）

### R1 顶栏（52px）

结构（从左到右）：
`☰ 目录` → **小封面 26×36**（点开详情）→ **书名 13.5px/600 + 作者 10.5px/muted 两行叠排**（书名点开详情）→ **圆 i 19px**（详见 R3）→ 弹性空白 → `⌕ 搜索 / ▮ 书签 / Aa / ✎ 笔记 / ▣ 固定侧栏 / ⋯ 更多`。

- 顶栏背景 = `var(--chrome)` = 与纸面同色系，**不要留白色横条**（当前 `app/ui/resources/style.qss:33 QMenuBar{background:#1f2125}` 是旧深色残留，删掉或改成 `--chrome`）；
- 自动隐藏：鼠标 `y<96` 或 `y>H-76` 时显示，离开 1.6s 隐藏（`mousemove` 重置计时器）；侧栏打开、浮层打开时**不隐藏**（原型里就是这个逻辑）；
- 隐藏用 `translateY(-100%)` + `opacity 0`，`position:absolute` 脱离布局，**书页不许跟着跳**（这是现在最容易被写错的一点）。

### R2 单页 / 双页（摊开）—— 语义必须改

现在 `reader_container.py:960-964` 的下拉写着「单栏/双栏」，`reader.js:353-361` 用 `max-column-count` 实现的是**一页里分两栏**——错的。正确语义：

| 选项 | 含义 | 实现 |
|---|---|---|
| **单页** | 一次显示一页 | `max-column-count = 1`，`#paper` 宽 = `--page-max`（默认 560） |
| **双页（摊开）** | 左右两页同时显示，中缝有书脊阴影，像摊开的书 | `max-column-count = 2`，`#paper` 宽 = `2 × --page-max`，中缝用一条伪元素画阴影 |

**不要真的拼两个 `#paper`**。做法：

```css
/* reader.css */
#paper[data-page-mode="spread"]{
  max-width: min(100%, calc(var(--page-max) * 2));
  --page-max: 560px;
}
#paper[data-page-mode="spread"]::after{   /* 书脊 */
  content:""; position:absolute; top:0; bottom:0; left:50%; width:28px; transform:translateX(-50%);
  pointer-events:none;
  background:linear-gradient(90deg, transparent, rgba(90,72,44,.16) 45%, rgba(90,72,44,.16) 55%, transparent);
}
```

`view-transition-name:reader-sheet` 现在无条件挂在 `#paper`（`reader.css:151`），双页模式下要把名字挂到 `#page` 容器或直接禁用动效，否则翻页会双影（旧文档 §9 已列此坑）。

页码与底栏：单页显示 `16`，双页显示 `16–17`；一次翻页步进 `1`（单页）或 `2`（双页）。

窗口宽度 `< 2 × page-max + 2 × 边距` 时**自动回落单页**，并在 Aa 里把"双页"置灰提示"窗口太窄"。

### R3 圆 i → 书籍详情（可编辑元数据）

浮层 404px，锚定在 i 左下方（不是屏幕右下），内容与原型一致：

1. 头部：封面 96×134、书名、`作者 · 年份 · 出版社`、标签行（含 `已读` `★ 喜爱`）；
2. 元数据 8 行：语言 / 页数 / 出版日期 / ISBN / 格式（含 DRM 与否、大小）/ 系列 / 阅读进度 / **数据文件路径** / **归档路径**；
3. 简介（4 行截断，"展开"可看全文）；
4. 动作两行：
   - 主行：`← 返回书库`、`◇ 添加标签`、`✎ 插入笔记`、`▮ 添加书签`、`▨ 标注此页`、`⇄ 翻译（未开放，虚线置灰）`；
   - 次行：`✎ 编辑元数据`、`⇩ 重新识别`、`⟲ 恢复内嵌元数据`。

**编辑元数据（本次新增的核心需求）**

- 点「编辑元数据」→ 元数据区变成 9 个输入框（书名/作者/出版社/出版日期/页数/语言/ISBN/系列/标签），下部「取消 / 保存并同步到书库」；
- 保存链路（顺序错了会脏数据）：
  1. 校验（书名非空、ISBN 若填必须通过 `app/core/isbn.py` 的 10/13 校验、页数整数）；
  2. `metadata_service.save_manual(book_id, fields)` 写库（现有 :269）；
  3. 重新计算归档路径（`naming.py` 模板）→ 若路径变化，`organize_service` 以"单本"批次移动，记 undo；
  4. **回写内嵌 OPF**（新能力）：先 `book.epub.bak` 备份，解压 → 改 `content.opf` 的 `dc:title/dc:creator/dc:publisher/dc:date/dc:language/dc:identifier` 与 `meta` 页数 → 重新打包（`zipfile` 按原条目顺序、原压缩方式写，`container.xml` 不动）→ 原子替换；
  5. 刷新书架该行 + 顶栏书名/作者 + toast「已保存并同步到书库」。
- 任何一步失败：**回滚已做的步骤**（尤其是第 3 步移动过的文件），把失败原因原样显示在浮层底部（如"文件被占用"/"无写权限"/"OPF 写入失败，已保留 .bak"），不许只弹"保存失败"。
- PDF/MOBI/AZW3 不支持 OPF 回写：只写库 + 重命名文件，浮层里把「恢复内嵌」置灰。

**双路径（详情面板与书库列表都要显示）**

- `数据文件路径`：`library_items.path`（入库文件的真实位置，只读，点击"打开所在文件夹"用 `QDesktopServices.openUrl`）；
- `归档路径`：`books.archive_path` 或按当前命名模板算出的目标路径（只读 + 「按模板重算」按钮，点了先弹预览再执行）；
- 二者相同就显示"已归档"绿标，不同显示"待归档"琥珀标；**路径过长中间省略**（`…`），hover 出 tooltip 显示全文。

### R4 Aa 设置浮层（360px，四 tab）

对齐原型，tab 顺序与内容不许自创：

1. **Aa 字体**：正文（中文/English 两个下拉）、字号 stepper 12–30、行距 1.2–2.6（步进 0.1）、字重、两端对齐/首行缩进/段落间距三个开关；
2. **◫ 版式**：展示方式（单页/双页）、单页宽度 420–900（步进 30）、边距（紧凑/适中/舒展）、滚动模式开关、阅读尺、上下渐隐遮罩、页眉时间；
3. **◐ 主题**：8 色卡（点击实时换 CSS 变量，不重建 view）、界面「顶栏与纸面同色」「顶栏自动隐藏」「自动隐藏延时 0.8–4s」；
4. **⇄ 翻页**：动效（直接 / 推进 / 翻书）、点击左右两侧翻页、禁用双击、自动翻页 + 间隔 10–120s、双页方向（从左到右 / 从右到左竖排）。

控件规格：行高 36、label 12.5px muted、Stepper 27×27 圆角 8、分段控件 3px 内边距选中项白底、卡片 `#fffefa` + 1px line + 圆角 11。**Stepper 必须支持长按连发**（旧文档 §9 待修项：现在按一下只走一格）。

### R5 底栏（42px）

`‹ ›` → 16 段墨点进度条（点击跳页，段数 = 16 固定，不是按百分比渲染 318 段）→ `本章剩余 18 分钟 · 8 页` → `◷ 22:53` → `16–17 / 318`。

- "本章剩余"算法：剩余字符数 ÷ 最近 3 分钟实测速度（字符/分钟），无速度数据时按 400 字/分钟估；分钟取整到 1；
- 时钟每 30s 刷一次（不要每秒，省电）；
- 底栏与顶栏同一套自动隐藏。

### R6 侧栏抽屉（268px）

`☰` 打开；头部 **52×72 封面 + 书名 + 作者 + `EPUB · 已读 · ★`**；章节列表行高 36、页码右对齐、当前章 accent 左边条 + 12% 底色；底部三 tab（目录 / 笔记 / 书签），当前 tab accent。

- 固定侧栏（图钉 ▣ 按下）= 打开后**不自动收起**，且书页整体右移 268px（不要遮住正文）；
- 侧栏展开时点章节：滚动到锚点并高亮 1.5s 后淡出。

### R7 点击区与箭头

- 左右各 **14%** 宽透明点击区（原型 14%，旧规范写的 18% 作废），点击 = 上一页/下一页；中间 72% 区域点击 = 切工具条显隐（不要做"点击中央出菜单"的第三套逻辑）；
- 两对箭头：`‹ ›`（当前章节内翻页，靠外 6px，垂直居中）与 `«‹ ›»`（跳上/下一章，距边 40px，半透明 45%）；
- 箭头与点击区都 `pointer-events:auto` 但**不能压字**：`#paper` 的左右 padding 至少 22px（旧文档 §9 的"两侧箭头压字"必须复检）。

### R8 翻页动效（三档，不是五档）

`直接`（0ms）/ `推进`（水平位移 + 淡出，180ms）/ `翻书`（透视 rotateY ±8° + 位移 2%，340ms，`cubic-bezier(.45,.05,.55,.95)`）。默认 `翻书`。

- 双页模式翻页时**两页一起动**，中缝阴影跟着走；
- 动效期间禁止连点（`busy` 锁 360ms），否则动画叠在一起；
- 真正的"纸页卷曲"（WebGL 网格 curl）不在本次范围，别自己上。

### R9 键盘与全屏

`→ / Space` 下一页，`←` 上一页，`Esc` 关浮层并退出全屏，`Ctrl+B` 侧栏，`Ctrl+F` 搜索，`Ctrl+= / Ctrl+-` 字号，`F11` 全屏。现有绑定在 `reader_container.py:2022-2029`，补齐即可，**不要重排已有键**。

### R10 滚动模式

foliate `renderer.setAttribute('flow','scrolled')`，关掉 `max-column-count`，`#viewer{overflow:auto; scroll-snap-type:y proximity}`；点击左右改为滚一屏（`scrollBy(top: clientHeight*0.92, behavior:'smooth')`）；进度用 `scrollTop/scrollHeight` 回写 `percent`；切回分页模式时按 `percent` 反算 locator（否则进度回跳，这是旧文档列过的坑）。

**R 验收**
1. 单页/双页切换后 `16 / 16–17` 正确、双页中缝阴影在正中、窗口收窄自动回落单页；
2. Aa 四 tab 全部可操作，8 主题切换**不重建 view**（滚动位置不跳）、字号行距即时生效；
3. i 浮层可编辑 9 个字段，保存后书架、顶栏、OPF 三处同步；改 ISBN 为非法值时拒绝保存并说明原因；
4. 顶栏/底栏自动隐藏后书页不位移；全屏下 `Esc` 能退出；
5. 截 1440×900 截图与 `docs\书格-阅读界面原型.html` 并排比对，色值与间距肉眼一致。

---

## 9. L1–L7 · 书库界面（对照两个 UI 原型）

### L1 顶栏菜单行（用户重点问的那一行）

现在这一行是「扫描新书 / 选择书库 / 识别元数据 / 预览整理 / 执行整理」五个同级按钮，语义混乱（前两个是入口，中间两个是流程步骤，最后一个是执行）。改成**两层**：

```
[☰] 书格                     [＋ 添加书籍 ▾]   [⟳ 扫描]   [⌕ 搜索…]        [◫ 列表|▦ 卡片]  [⋯]

① 一级入口（左侧）：＋ 添加书籍（下拉：扫描文件夹 / 导入文件 / 拖拽提示）、⟳ 扫描新书（只扫增量，带数字气泡"新增 12"）
② 流程动作（收进 [⋯] 与批量条）：识别元数据、预览整理、执行整理 —— 这三个是"对象的操作"，不属于顶栏
③ 右侧：搜索框（可展开）、视图切换（列表/卡片/书架/封面墙 四选一）、⋯ 更多（设置/帮助/关于/主题）
```

理由：顶栏放"入口"和"视图"，"流程"放**批量操作条**（选中书后才出现：`已选 12 本 · 识别元数据 · 预览整理 · 执行整理 · 移动到… · 移除`）。原型 `书格-UI原型.html` 第 1 屏右下那条浮动条就是它。

控件：按钮高 30、圆角 8、图标 16 + 文字 12.5；主按钮（添加书籍）用 `--accent` 底白字；其余描边按钮 `--panel` 底 + `--line` 边。

### L2 左导航（232px，可折叠）

```
书库    我的书架 1872 / 喜爱 36 / 在读 12 / 已读 148
内容    笔记与高亮 284 / 阅读统计
分类    作者 / 系列 / 标签 / 文件夹
工具    整理 / 清理空目录 / 回收站 / 格式转换
底部    设置 / 帮助 / 关于
```

- 一级分组标题 11px、字距 .08em、muted，**不可点击**；
- 二级项行高 34，图标 16，右侧计数用 Inter 12px muted；
- 选中项：`--paper` 底色 + 左侧 3px accent 条；
- 导航可折叠（宽 232 → 56，只留图标），状态存 prefs；
- 「待整理 / 识别失败」不单列，并入「我的书架」的筛选条（旧方案已定，别重复）。

### L3 书籍详情面板（右侧 404px，列表视图默认显示）

字段顺序（从上到下）：封面 + 书名 + 作者 → 标签 → 元数据（语言/页数/出版日期/ISBN/格式/大小/系列/阅读进度/添加日期/**数据文件路径**/**归档路径**）→ 简介 → 动作（打开阅读 / 编辑元数据 / 重新识别 / 定位到文件夹 / 移除）。

- 路径两条都要，且**可点击**：数据文件路径 → 打开所在文件夹；归档路径 → 若"待归档"则显示目标路径 + 「按模板重算」；
- 编辑元数据复用 R3 的编辑表单（同一个 `EditBookDialog`，别写两份 UI）；
- 列表行 hover 时详情面板 120ms 内更新，快速划过用 200ms debounce（1872 本别每行都查库）。

### L4 列表 / 卡片 / 书架 / 封面墙四视图

- 列表：`QTableView` + 自定义 delegate，列 = 封面缩略 32×44 / 书名 / 作者 / 格式 / 页数 / 大小 / 状态 / 进度 / 添加日期；行高 56；
- 卡片：`QListView IconMode`（**不要 QGridLayout**，1872 本会卡），列数 自动/4/5/6/8；
- 书架：卡片 + 分组标题条（`马伯庸 · 12 本`，可折叠）；
- 封面墙：只封面 + 底部书名，列数自动，适合"看封面挑书"。

### L5 批量移动（用户明确要的功能）

- 选中多本 → 批量条「移动到…」→ 目录选择器（默认候选：库根下的一级目录列表 + "新建文件夹"）；
- 语义是**在库内移动**（改 `library_items.path` + 可选按模板重排文件名），不是导出到库外；
- 单批次记 undo（`organize_service` 已有 undo 批次，复用它，别另写一套）；
- 目标目录已存在同名文件：默认"重命名 `(2)`"，可选"跳过/覆盖"，覆盖要二次确认；
- 「导出到库外」单独一个动作，明确提示"导出后不再受书库管理"。

### L6 空文件夹清理

- 触发点：设置 → 整理 → 「清理空目录」；左导航工具组也有入口；
- 规则：遍历库根下所有目录，**自底向上**，删除"不含任何文件且不含非空子目录"的目录；
- 安全：
  1. 先扫描 → 列出将被删除的目录（相对路径），用户勾选确认；
  2. 只删库根内、深度 ≥ 1 的目录，**绝不删库根本身**；
  3. 跳过含 `.keep` / `.gitkeep` / `desktop.ini` 的目录（视为"有意保留"）；
  4. 删除进回收站（`send2trash` 若不便，则移到 `库根\.trash\<date>\`），不物理删除；
  5. 处理 `PermissionError`（被占用/只读）时跳过并列在"未删除"清单里说明原因。
- 用户原话场景"新拷贝进去的空文件夹"——这条规则正好覆盖：拷贝留下的空壳目录会被列出，确认后清理。

### L7 格式转换（能做，但要做窄）

只做一个方向的安全子集，且必须用**纯 Python 或已许可的库**：

| 转换 | 可行性 | 库 | 结论 |
|---|---|---|---|
| EPUB → 纯文本/Markdown | 高 | 现有 zipfile + html 解析 | **做**（导出笔记/大纲时有用） |
| EPUB ↔ MOBI/AZW3 | 高 | `mobi`/`kindleunpack`(GPL) 或 calibre CLI | **调用外部 calibre 时只做"检测到就调用"，不内嵌** |
| PDF → EPUB | 低 | PyMuPDF/pdfplumber 是 AGPL | **不做**（用户已否决） |
| EPUB → PDF | 中 | QtWebEngine 打印 | 可选，二期 |
| 任意 → 任意 | — | calibre `ebook-convert` | 仅"用户机器已装 calibre"时提供入口，不打包 |

一期只上「EPUB → Markdown/TXT」与「检测到 calibre 则开放 ebook-convert」，界面上把不可用的灰掉并说明原因，不要给"敬请期待"。

**L 验收**：1440×900 下顶栏 5 个入口不换行、左导航四项分组正确、列表 1872 本滚动不卡（首屏 < 400ms）、批量移动 50 本成功且可 undo、空目录清理只删勾选项、四视图切换保持当前排序与筛选。

---

## 10. M1–M6 · 我的书架 / 统计 / 笔记 / 喜爱

细节完全沿用 `BookShelf-菜单与功能扩展方案-v2.md` §2–§5 与原型 `书格-UI原型-v2-书架统计笔记设置.html`，这里只列**验收硬指标**：

| 编号 | 任务 | 验收 |
|---|---|---|
| M1 | 我的书架网格（列数/分组/排序） | 12 维排序全部可点、升降序持久化、中文按拼音（`pypinyin`）、分组标题条可折叠 |
| M2 | 阅读统计页 | 5 卡 + 180 天热力图 + 两排行 + CSV 导出；读 10 分钟后数字变化 |
| M3 | 笔记与高亮页 | 284 条可搜索/按书筛选/颜色竖条/跳转回书；导出 Markdown 可直接粘进飞书 |
| M4 | 喜爱与阅读状态 | 卡片右上角星、左上角状态标、`percent>=98` 停留 5 分钟后**询问**而非静默改 |
| M5 | 设置页 8 分组 | 外观/书库/阅读/笔记与高亮/快捷键/整理与命名/识别与网络/关于；控件用统一组件 |
| M6 | 三层主题 + 背景图 | 界面/书库/阅读可独立组合；背景图模糊 0–40、不透明 0–100、夜间自动降 30% |

排序维度（12 项，按用户原话 + Koodo 并集）：书名、作者、格式、页数、系列、阅读日期、添加日期、出版日期、阅读进度、阅读时长、文件大小、识别度。分组（5 项 + 无）：作者 / 系列 / 标签 / 阅读状态 / 格式 / 添加月份。

---

## 11. 交给 TRAE 的开场指令（直接粘）

```
你在这个仓库里做实现，视觉真相只有三个文件：
  docs/书格-阅读界面原型.html          （阅读器，最新版）
  docs/书格-UI原型-v2-书架统计笔记设置.html（书架/统计/笔记/设置）
  docs/书格-UI原型.html               （书库列表/详情/卡片）

施工依据是 docs/书格-施工总图-v3-给TRAE.md，编号 S1→S2→F1..F5→D1..D3→R1..R10→L1..L7→M1..M6。
规则：
1. 一次只做一个编号，一个编号一个 commit，commit message 以编号开头（如 "R2 单页/双页语义修正"）。
2. 动手前先 grep 出该编号点名的函数/类（文档给了锚点，行号可能已漂移，别硬按行号改）。
3. 每完成一个编号，跑 `.venv\Scripts\python.exe -m pytest tests -q`，红了就修，不许跳过或 xfail 掩盖。
4. 字体已放进 app/reader/assets/fonts/，不要重新下载、不要改名（family 名是字体内部名字，改了会找不到）。
5. 任何涉及写文件/删目录/移动文件的功能，先备份、先进回收站、必须可 undo。
6. 不许抄 readest-main/ 里的任何代码（AGPL）。不许改 APP_NAME / 数据目录 / README 版本号。
7. 不确定的视觉细节，回到对应 HTML 原型用取色器量，别自己发挥。
先做 S1（EPUB 大小写容错），做完把 _audit\epub_zip_probe.py 的结果贴出来再往下走。
```

---

## 12. 附：字体下载地址（以后想加字体时用，本次不用下载）

国内直连 `github.com/<repo>/releases/...` 的 asset 会超时（AWS objects 域被断），实测可用的是 **jsDelivr 镜像** `fastly.jsdelivr.net`（Google Fonts 的 ofl 目录）与 `codeload.github.com`（仓库 zip）。命令模板：

```powershell
# 例：思源宋体全部字重（Google Fonts 仓库里的 Noto Serif SC）
Invoke-WebRequest 'https://fastly.jsdelivr.net/gh/google/fonts@main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf' -OutFile NotoSerifSC.ttf

# 例：霞鹜新晰黑（GitHub release，需走代理或手动下载）
https://github.com/lxgw/LxgwNeoXiHei/releases/download/v1.309/LXGWNeoXiHei.ttf
```

候选清单（都能商用，OFL/Apache）：

| 用途 | 字体 | 仓库 |
|---|---|---|
| 中文正文·楷 | 霞鹜文楷 | `lxgw/LxgwWenKai` |
| 中文正文·宋 | 思源宋体 / Noto Serif SC | `adobe-fonts/source-han-serif`、`google/fonts` |
| 中文正文·明 | 霞鹜新明（LXGW Heart Serif） | `lxgw/LXGWHeartSerif` |
| 中文界面·黑 | 思源黑体 / Noto Sans SC、霞鹜新晰黑 | `google/fonts`、`lxgw/LxgwNeoXiHei` |
| 中文等宽 | 更纱黑体 Sarasa Gothic、霞鹜文楷 Mono | `be5invis/Sarasa-Gothic` |
| 英文正文 | Literata、Source Serif 4、EB Garamond、Crimson Pro | `google/fonts` |
| 英文界面 | Inter | `rsms/inter`（或 `google/fonts`） |

**不能打包的**：Bookerly（亚马逊专有）、Georgia / Segoe UI（微软）、PingFang（苹果）、得到/微信读书内置字体——版权不允许随安装包分发。

---

## 13. 一句话总结

先把 S1（15.6% 的书打不开）和 F（假内嵌字体）这两个"底层是坏的"修掉，再按 R→L→M 把三份原型逐屏落地；每个编号一次提交、一次 pytest、一次截图比原型。改完这一轮，书格才既好看又能用。

**版本**：v3 · 2026-11-26


