# BookShelf 全量整改方案 v3

> 2026-11-26 · 依据：对 `E:\BookShelf` 现有代码的复查 + 对 E 盘 500 本样书的实测
> 用法：整份交给编码 AI，按 **S1→S11** 顺序执行，一步一提交、一步一验收。
> 前置文档：`BookShelf-阅读界面重构规范-v1.md`（§9 复检、§10 元数据源）、`BookShelf-图书识别与自动命名-实现规范-v1.md`。

---

## 0. 一句话结论

**"打不开"和"124 本识别失败"是同一个 bug**：一批 EPUB 的 `META-INF/container.xml` 里写的是小写 `ops/fb.opf`，而压缩包里真实的条目是 `OPS/fb.opf`。Python 端 `zipfile` 按字面匹配 → 抛 KeyError → 判 `failed`；foliate-js 端按字面匹配 → 返回 null → 抛 `Failed to load package document`。Readest 的加载器做了大小写容错，所以它能打开。

实测数据（`_audit\epub_zip_probe.py`，扫 `F:\E-book\**\*.epub` 前 500 本）：

| 项 | 数值 |
|---|---|
| 抽样 | 500 本 |
| container 指向的 OPF 在 zip 里**找不到** | **78 本 / 15.6%** |
| 这 78 本的共同特征 | container 写 `ops/fb.opf`，实际条目是 `OPS/fb.opf`（仅大小写不同） |

按 1872 本库推算，约 **290 本**属于这类"结构不标准但内容完好"的 EPUB。修一个容错函数，能同时解决"打不开"和"识别失败"两个投诉。

---

## 1. S1（P0）EPUB 容器容错：修 `ops/fb.opf` 这一类

### 1.1 Python 侧：`app/core/metadata/epubs.py`

现状：`_package_path()`（:42）从 container 拿 `full-path`，`_read_xml()`（:35）直接 `archive.read(name)`，找不到就 `ExtractError` → `finalize(ok=False)` → `scan_service` 判 `failed`。

改法：在文件顶部加一个**条目解析器**，所有读取都过它。

```python
import unicodedata, posixpath
from urllib.parse import unquote

def _entry_index(archive):
    """把 namelist 建成可容错的索引：原文 / NFC / casefold / 去 ./ / unquote。"""
    index = {}
    for name in archive.namelist():
        for key in (
            name,
            unicodedata.normalize("NFC", name),
            name.lstrip("./"),
            unquote(name),
            unicodedata.normalize("NFC", unquote(name)).lstrip("./"),
        ):
            index.setdefault(key, name)
            index.setdefault(key.casefold(), name)   # 大小写不敏感兜底
    return index

def _resolve(archive, index, name):
    """返回真实的 zip 条目名；找不到返回 None。"""
    if not name:
        return None
    for key in (name, name.lstrip("./"), unquote(name), name.replace("\\", "/")):
        if key in index:
            return index[key]
        if key.casefold() in index:
            return index[key.casefold()]
    # 最后兜底：按 basename 唯一匹配（有的 OPF 路径前缀被改过）
    base = posixpath.basename(name).casefold()
    hits = [real for real in archive.namelist() if posixpath.basename(real).casefold() == base]
    return hits[0] if len(hits) == 1 else None
```

然后：
1. `_package_path()` 返回 container 的 `full-path`；若 `_resolve` 找不到，**回退**到"扫描 namelist 里所有 `.opf`（大小写不敏感），有且仅有一个就用它"（现在 :50-52 已有类似逻辑，但没走 `_resolve`）。
2. `_read_xml()` 签名改为 `_read_xml(archive, index, name)`，内部先 `_resolve`；解析失败信息里带上"已尝试的候选名"。
3. `_cover_bytes()` 的 `archive.read(name)` 同样走 `_resolve`（封面路径也常见大小写不一致）。
4. 顺带修一个隐患：**zip 条目名未置 UTF-8 标志位（GBK）时**，`zipfile` 按 cp437 解码会得到乱码。在 `_resolve` 找不到时，追加一次「`name.encode('cp437', 'ignore').decode('gbk', 'ignore')`」的反向尝试。

**验收**：`python -m pytest tests -q` 全绿；新增 `tests/test_epub_case.py`，用 `_audit` 里那本真实样书（或构造 zip：container 写 `ops/fb.opf`、条目为 `OPS/fb.opf`）断言 `extract()` 返回 `ok=True` 且 title 正确；再跑一次 `epub_zip_probe.py` 的逻辑做回归：78/78 全部能解析。

### 1.2 JS 侧：`app/reader/assets/vendor/foliate-js/view.js`

现状：`makeZipLoader`（:33-46）`map = new Map(entries.map(e => [e.filename, e]))`，`load` 只做 `map.has(name)`；`epub.js:1324` 的 `#loadXML(opfPath)` 因此返回 null，`epub.js:1325` 抛你看到的报错。

改法（**只改我们 vendored 的这一份，不碰 Readest 的代码**）：

```js
const normalize = s => s.normalize('NFC').replace(/^\.\//, '');
const makeZipLoader = async file => {
    ...
    const entries = await reader.getEntries()
    const map = new Map(entries.map(entry => [entry.filename, entry]))
    const lower = new Map()                       // 大小写不敏感索引
    for (const e of entries) {
        const k = normalize(e.filename).toLowerCase()
        if (!lower.has(k)) lower.set(k, e)
    }
    const find = name => {
        if (map.has(name)) return map.get(name)
        const n = normalize(name)
        if (map.has(n)) return map.get(n)
        const tryDecoded = (() => { try { return decodeURIComponent(n) } catch { return null } })()
        if (tryDecoded && map.has(tryDecoded)) return map.get(tryDecoded)
        return lower.get(n.toLowerCase()) ?? null
    }
    const load = f => (name, ...args) => {
        const entry = find(name)
        return entry ? f(entry, ...args) : null
    }
    ...
}
```

`epub.js` 里 `#loadXML` 不用改逻辑，但把错误信息补全，方便以后定位：

```js
if (!opf) throw new Error(`Failed to load package document: ${opfPath}`)
```

**验收**：用那本 `心理学大纲` 打开能正常渲染；控制台不再出现该报错；`docs` 里记一条"vendor 补丁清单"（`docs/UPSTREAM.md` 追加 `view.js` case-insensitive lookup 一条，便于将来升级 foliate-js 时保留）。

### 1.3 顺手修的错误页误导

`reader_container.py:718-731` 的错误页把所有渲染失败都写成"受 DRM 保护的文件不会进行任何解密尝试"。真实链路是 `reportError` → `bridge` → `_on_web_failed`（:2074）→ `_show_error("渲染失败：…")`。

改成三类文案：

| 情形 | 标题 | 说明 | 按钮 |
|---|---|---|---|
| 文件结构异常（container/OPF 找不到、zip 损坏） | 这本书的 EPUB 结构不规范 | 显示真实异常；附「已在书库标记为待修复」 | 重试 / 用系统程序打开 / 返回书库 |
| 确实是 DRM | 受 DRM 保护 | 当前不解密 | 同上 |
| 其它（超时、内核未加载） | 打开失败 | 原文错误 | 同上 |

判据：`converter.py` 返回 `PreparedBook(drm=True)` 时才显示 DRM 文案；其余一律走"结构异常"。

---

## 2. S2（P0）识别状态语义与批量重识别

### 2.1 为什么"识别失败"里有作者和书名

`scan_service.py:194-203`：只有 `title and authors and meta_source=="embedded"` 才 `recognized`。这批书 `extract()` 失败（S1 的 bug）→ 落到 `else` 前的 `elif not metadata.get("ok"): status="failed"`，但 `title/authors` 已经被文件名解析（L0）填上了 → 于是出现"有书名有作者却进识别失败"。

改法（两处）：

1. **状态重新定义**：
   - `failed` 只表示「文件读不出来」（zip 坏、权限、格式伪装）。文案统一为「文件无法解析」。
   - 文件能读、但没联网补全 → `need_confirm`，文案「本地元数据可用，待联网补全」。
   - `extract()` 失败但 L0 拿到书名+作者 → 至少 `need_confirm`，并记 `parse_error` 字段供"修复"页展示。

2. **`metadata_service.enrich_book`（:238-243）去掉"failed 原样保留"**：
   现在的逻辑是 `if current.status in {failed,drm,skipped}: status = current.status`。改为：
   ```python
   if current.status == "failed":
       has_local = bool(current.get("title") and current.get("author_raw"))
       status = "need_confirm" if has_local else "failed"
   ```
   这样一次批量重识别就能把 124 本里"其实只是打不开"的书捞回来。

### 2.2 批量重识别（缺的功能）

现状：只有单本 `enrich_book(book_id, force=...)`，没有批量入口、没有进度、没有"只处理失败/待确认"。

新增：

| 位置 | 内容 |
|---|---|
| `app/services/metadata_service.py` | `enrich_many(book_ids, *, force=True, on_progress=None, cancel=None) -> dict` 汇总 `{recognized, need_confirm, failed, skipped}`，内部串行 + 每 5 本回调一次 |
| `app/ui/pages/library_page.py`（或 main_window 工具栏） | 按钮「重新识别」下拉：全部 / 仅识别失败 / 仅待确认 / 仅选中 |
| 进度 | 复用现有 `scan_dialog` 的进度条样式，做成非模态小条，可取消 |
| 结果 | 结束后弹一个小结（沿用 scan 结束样式），并把变化的书高亮 3 秒 |

**验收**：对那 124 本点「仅识别失败 → 重新识别」，修完 S1 后至少 90% 落到 `need_confirm` 或 `recognized`；不联网（断网）时状态不得回退成 `failed`。

---

## 3. S3（P1）书库多视图（列表 / 卡片 / 书架 / 封面墙）

现状：`app/ui/pages/library_page.py` 只有一个 `QTableView` + `book_table.py` 的 `BookTableModel`；`author_page.py` 里倒是有一套卡片（`_book_card`，150×172、封面 88×116），可以抽出来复用。

设计：一个 `QStackedWidget` + 顶部右侧视图切换（4 个分段图标），共用同一个 `BookTableModel`（**不要为每种视图建新数据源**），只换 delegate。

| 视图 | 实现要点 |
|---|---|
| **列表**（现有） | 保留，行高 34，等比列宽；首列加 24×34 缩略封面 |
| **卡片** | `QListView` + `IconMode`，`setGridSize(QSize(168, 232))`，自绘 delegate：封面 144×196 居中、圆角 6、下方书名 2 行省略、作者小字、右下角格式角标 |
| **书架** | 同上但 `IconMode` 关掉，背景挂一层"层板"（自绘 1px 线 + 24px 阴影），每行 6 本 |
| **封面墙** | `IconMode` + `setSpacing(4)`，仅封面、无文字，鼠标悬浮浮出书名 |

性能：1872 本必须靠 `QListView` 的 viewport 惰性绘制 + 封面缩略缓存（磁盘 `cache/covers/thumb_{id}_{w}.jpg`，按需生成 144/88/48 三档）。**禁止**一次性为所有书加载大图。

细节：
- 视图状态（当前模式、排序、分组）存 `prefs.json`，重启保持。
- 空状态：插画 + 「扫描新书」按钮 + 「拖拽文件到这里」。
- 右侧详情面板（`detail_panel.py`）保持常驻，多视图共用。

**验收**：1872 本切到封面墙，首屏渲染 < 300ms，滚动不卡顿（用 `QListView` 而非 `QTableWidget`）；切换视图后选中项与滚动位置保持。

---

## 4. S4（P1）删除 / 移除 / 整理的边界

现状：书库里没有删除入口（`library_page.py` 只有一句"扫描不移动不删除原文件"的提示）。用户需要的三种操作必须显式区分，**默认不动用户原始导入目录**。

右键菜单 + 工具栏「整理」下拉，三个动作：

| 动作 | 行为 | 风险 |
|---|---|---|
| **从书库移除** | 只删数据库记录（+缓存的封面/进度），**文件原地不动** | 低，可撤销（回收站，7 天内可恢复） |
| **删除文件** | 数据库记录 + 文件一起删，**优先送系统回收站**（`send2trash` 或 Win32 `SHFileOperation`），不直接 `unlink` | 中，二次确认（列出将要删的文件数与路径） |
| **整理（移动/改名）** | 现有 `organize_service`，默认"复制入库"，原件保留 | 低，已有 undo |

实现要点：
1. 新增 `app/services/library_service.py`：`remove_from_library(ids)`、`delete_files(ids, to_trash=True)`，都写 `operations` 日志，支持 undo。
2. 批量选择时确认对话框必须显示：`共 N 本 / 合计 X MB / 其中 M 个文件将移入回收站`，并附一句"原始导入目录不受影响"。
3. 删除后刷新视图与统计（左侧"全部书籍/已归档"计数）。

**验收**：删 5 本 → 书库计数 -5、文件在回收站；撤销 → 全部回来；「从书库移除」后文件仍在原路径。

---

## 5. S5（P1）应用级主题统一（"最上面还是白条"）

现状是**两套皮肤**：
- 主窗口用 `app/ui/theme.py` 生成的一整套浅色 QSS（`main_window.py:517` `setStyleSheet(qss)`）；
- 阅读器用 `app/ui/theme_tokens.py` 的 8 套 palette，自己拼 QSS（`reader_container.py:200+`）。

`style.qss`（`app/ui/resources/style.qss:33`）甚至还是深色 `#1f2125` 的一套旧规则，属于历史残留。三套东西叠加 → 菜单条、工具栏、下拉菜单、对话框边框各走各的颜色，看起来就是"白条 + 米色 + 深色混搭"。

统一方案（**单一 token 源**）：

1. `theme_tokens.py` 扩成应用级：新增 `app_surfaces`（`menubar / toolbar / sidebar / content / card / border`），渲染函数 `build_app_qss(palette)` 生成**完整** QSS，覆盖：`QMainWindow`、`QMenuBar(+::item/::item:selected)`、`QMenu`、`QToolBar`、`QStatusBar`、`QTabBar`、`QSplitter`、`QTableView`（表头/网格线/选中态）、`QScrollBar`、`QDialog`、`QMessageBox`、`QComboBox/QLineEdit/QSpinBox`、`QPushButton`（primary/ghost/danger 三档）。
2. `main_window` 主题切换时：`self.setStyleSheet(build_app_qss(p))` + **同时**设置 `QApplication` 的 palette（`Window/Base/Text/Button/Highlight`），因为原生控件（菜单阴影、下拉滚动条）不吃 QSS。
3. 删除 `app/ui/resources/style.qss` 与 `theme.py` 里的硬编码色，全部改为从 token 取；`style.qss` 保留文件但只做"兜底"（或直接删除并在文档写明）。
4. 阅读器窗口（`reader_window.py`）与阅读页共用同一个 palette，切换主题时同步主窗口菜单条颜色 —— 这样窗口边框、菜单条、纸面、侧栏是同一个色阶。

**验收**：切 8 套主题，逐一套检查：标题栏区域、菜单条、工具栏、左侧栏、表格、对话框、阅读页顶栏 —— 颜色属于同一套，**不出现纯白 `#fff` 条**。

---

## 6. S6（P1）阅读器设置浮层重做（对标 Readest）

现状问题（截图 2 可见）：
- 浮层出现，但**内层是纯白**：`#ReaderPrefsPopup` 有 `background: theme.panel`，可里面的 `QScrollArea` viewport / `QStackedWidget` / `QFrame` 没有 objectName，走 Qt 默认调色板（白）。
- 布局是"标签—控件—标签—控件"竖排，行高忽大忽小，`- 23 +` 的小按钮挤在一起，`字重 400` 用输入框，视觉密度差。
- 三 tab（字体/版面/主题）用文字，未用图标；没有分组卡片。

目标形态（Readest 的「Aa」面板）：

```
┌ 360×auto，圆角 14，背景 theme.panel，阴影 12/24 ┐
│ [Aa] [版式] [主题]            [×]   ← 顶部 44px，tab 用图标+文字
├─────────────────────────────────────────┤
│ 卡片：字体                                │
│   字体        [ 霞鹜文楷          ▾ ]     │
│   字号        [ − ]  19  [ + ]            │
│   行距        [ − ]  1.90 [ + ]           │
│   字重        [ 400 ▾ ]                   │
│ 卡片：版面                                │
│   分栏        [ 单栏 | 双栏 ]  ← 分段控件  │
│   页宽        [ − ] 920 [ + ]             │
│   边距        [ 舒展 | 适中 | 紧凑 ]       │
│ 卡片：主题（8 个色卡 2 行 4 列，当前项描边）│
│ 卡片：翻页（instant/push/slide/curl/flip） │
└─────────────────────────────────────────┘
```

实现要点（都可落在 `reader_container.py` 里改，不换框架）：

1. **内层透明**：给浮层内所有容器补 objectName（`ReaderPrefsBody`、`ReaderPrefsCard`、`ReaderPrefsGrid`），QSS 加：
   ```css
   #ReaderPrefsBody, #ReaderPrefsCard, #ReaderPrefsGrid,
   QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
   ```
   同时设 `scroll.setFrameShape(QFrame.NoFrame)`、`viewport().setAutoFillBackground(False)`。**这是"白色内层"的直接修法。**
2. **行结构统一**：左 label（`14px，muted`）+ 右控件，行高 38，行间距 0（卡片内用 1px 分隔线），卡片 padding 14/16。
3. **数字调节改用 `Stepper`（已有 `widgets/stepper.py`）**：36×28 圆角按钮，中间值 `15px` 等宽数字 + `QTimer` 长按连发（400ms 后 90ms 一次）——上一轮遗留的第 3 条待修一起解决。
4. **分段控件**用 `SegmentedProgress` 同款样式做 `Segmented`（单栏/双栏、边距三档、翻页五档）。
5. **色卡**：28×28 圆角 8，选中加 2px accent 描边 + 右上角对勾；每行 4 个，间距 8。
6. **位置**：贴右上角图标下方 8px，宽 360；窗口 < 900px 时改为全宽底部抽屉。
7. 改动即时生效（已有 `_update_prefs`），加 150ms 防抖，避免拖动时反复重排版。

**验收**：8 套主题下浮层**没有任何白色块**；字号/行距按钮长按能连发；1440×900 与 1024×768 两种尺寸都不溢出、可滚动。

---

## 7. S7（P1）内嵌字体真的落地

现状：`app/reader/assets/fonts/` **目录不存在**，`reader.js:295` 只是把 `family` 拼进 CSS，系统没这个字体就静默回退到 SimSun/Noto Serif。所以"内嵌字体没实现"。

做法：

1. 放 2 个字体文件（授权均允许再分发）：
   - 霞鹜文楷 `LXGWWenKai-Regular.ttf`（OFL-1.1，约 20MB）
   - 思源宋体子集 `SourceHanSerifSC-Regular.otf`（OFL，可用 `pyftsubset` 只保留 GB2312 + 常用标点，压到 5–8MB）
2. `reader.css` 顶部加：
   ```css
   @font-face { font-family: "LXGW WenKai"; src: url("fonts/LXGWWenKai-Regular.ttf") format("truetype"); font-display: swap; }
   @font-face { font-family: "Source Han Serif SC"; src: url("fonts/SourceHanSerifSC-Regular.otf") format("opentype"); font-display: swap; }
   ```
3. 设置里的字体下拉**只列真实可用的字体**（后端扫 `assets/fonts/` + `QFontDatabase.families()`，合并去重），并在名字后标「内置」。
4. 无字体文件时下拉显示「系统默认」，不要假装有霞鹜文楷。
5. `BookShelf.spec` 的 `datas` 已含 `app/reader/assets`，确认打包后 `fonts/` 进 `dist`（`datas=[('app/reader/assets','app/reader/assets')]`），并加一条测试：`Path('app/reader/assets/fonts').is_dir()`。

**验收**：设置里选「霞鹜文楷」，断网、干净机器上（无该字体）打开 EPUB，字形确实是楷体（截一张对比图存档）。

---

## 8. S8（P2）双栏真正生效

现状：代码里有（`reader.js:353-361` 按 `prefs.column_count` 设 `max-column-count`、`gap 6%`；`reader_container.py:960-964` 也有"单栏/双栏"下拉），但实际没看到两栏。原因大概率是**纸面太窄**：`paperMetrics`（:330）取 `max_column_width`（默认 920）与可用宽较小值 → 单栏 920px，字号 19px 时 foliate 判断放不下第二栏，直接回落 1 栏。

改法：
1. 双栏时纸面上限提高到 `min(窗口宽 - 320, 1320)`，并且 `column_count==2` 时把默认字号降到 17，`max_column_width` 自动 ×2（920 → 1240）。
2. `layoutFoliate` 里在 `host.open()` **之后**再设 renderer 属性，并 `requestAnimationFrame` 后再 `render()` 一次（属性在 open 前设置经常被忽略）。
3. 双栏在窗口 < 1100px 时自动降为单栏（并在设置里灰掉双栏选项，提示"窗口太窄"）。

**验收**：1440×900 下切双栏，确实左右两栏、互不串行、翻页顺序为"左栏上→左栏下→右栏上→右栏下"。

---

## 9. S9（P2）全屏同色的"沉浸模式"

现状：阅读页顶部还有一条系统标题栏（Windows 原生），跟米色内容不同色；`_toggle_fullscreen` 已有全屏能力但仍是带边框窗口。

改法（两档，按风险取舍）：
- **A 档（推荐，低风险）**：进入阅读页时 `setWindowFlag(Qt.FramelessWindowHint)` + 自绘 32px 拖拽条（内容同色），退出还原。菜单条、工具条全部融入阅读页顶栏。
- **B 档（可选）**：仅在"沉浸/全屏"时无边框，其它模式保持原生标题栏（用户误以为窗口丢了按钮的概率低）。

同时把阅读页顶栏做成 Readest 结构（已有基础，补三点）：
1. 左：目录折叠按钮（`☰`）+ 书名（单行省略，14px）；
2. 中：点击书名区域 → 弹出"前往书库 / 添加标签 / 翻译 / 搜索"菜单（现在没有这个二级菜单）；
3. 右：搜索 / 书签 / Aa / 笔记本 /**图钉（固定侧栏）**/ 更多；悬浮 2 秒后整条淡出（上一轮遗留的第 4 条：`hide_chrome_delay` 至今未生效）。

---

## 10. S10（P2）右侧详情面板与"识别可视化"

现状（截图 4）：右侧只有一个封面占位 + 出版社/出版日期/语言/页数/文件大小/ISBN，全是"——"，无来源、无置信度、无操作。用户看不出"为什么识别失败"。

改成三段式：

| 区块 | 内容 |
|---|---|
| 封面 | 200×280，无封面时用首字母占位卡（不是"暂无封面"四个字） |
| 识别 | 徽标（内嵌 / 文件名 / 豆瓣 / 手动）+ 置信度进度条 + **一行诊断**：「EPUB 结构异常，未能读取 OPF」/「本地元数据完整，未联网」/「豆瓣匹配 92%，书名+作者一致」 |
| 元数据 | 每个字段右侧带来源小点（`内`/`网`/`手`），可点击就地编辑；底部按钮：重新识别 / 编辑元数据 / 打开所在文件夹 / 从书库移除 |

字段行用 `QFormLayout` 风格的对齐，`label 12px muted`，值 `13px ink`，缺值显示 `—`（细体，不用全角）。

---

## 11. S11（P2）品牌与打包：中文名「书格」

现状：`app/config.py:18-19` `APP_NAME="BookShelf"`、`APP_NAME_CN="书库助手"`；`BookShelf.spec:28,54` `name='BookShelf'`；窗口标题"书库助手 BookShelf - 书库助手"；安装后桌面图标显示英文。

改法（一次改全，避免半中半英）：

| 位置 | 改成 |
|---|---|
| `config.APP_NAME_CN` | `"书格"` |
| `config.APP_NAME`（内部标识，**不要改**） | 保持 `BookShelf`（影响 `%APPDATA%\BookShelf` 数据目录，改了会丢库） |
| `main.py` 窗口标题 | `f"{APP_NAME_CN} · 本地书库"`，即「书格 · 本地书库」 |
| `BookShelf.spec` `name=` | `'书格'`（生成 `书格.exe`；**但 `BookShelf.spec` 文件名与 `main.py` 里的资源路径不动**） |
| `installer\BookShelf.iss` | `AppName=书格`、`AppVerName=书格 {version}`、`DefaultDirName={autopf}\书格`、`AppPublisher` 保留 |
| 桌面快捷方式名 | 自动跟随 `AppName` → 显示「书格」 |
| `version_info.txt` | `ProductName="书格"`、`FileDescription="书格"`、`InternalName` 保持 BookShelf、`OriginalFilename` 改 `书格.exe` |
| 图标 | `app/ui/resources/app.ico` 保留（多尺寸已生成）；安装器 `SetupIconFile` 指向同一份 |

**注意**：`APP_USER_MODEL_ID="BookShelf.Desktop"`（`main.py:26`）用于任务栏分组，**保持不变**，否则任务栏会出现两个图标。
**验收**：安装包里 exe 名、桌面快捷方式、任务栏、Alt+Tab、属性页「产品名」全部显示「书格」；旧数据目录仍被读取（升级不丢书）。

---

## 12. 关于"移植 Readest 的阅读部分"

必须说清楚许可边界（否则以后没法收场）：

- `E:\BookShelf\readest-main` 是 **AGPL-3.0**。把它的 `.ts/.svelte/.js` 直接拷进 GPL-3.0 的 BookShelf，会让整个发行版背上 AGPL 的源码提供义务；桌面分发风险不大，但**以后想做 SaaS/闭源就彻底堵死**。
- 它里面的 `packages/foliate-js` 是上游 [johnfactotum/foliate-js] 的 fork；**上游本体是 MIT**。我们的 vendor 已经就是上游那一份。
- 所以正确做法是：**读 Readest 学交互与参数，代码自己写；内核升级从上游 MIT 仓库拉，而不是从 Readest 拷。** 本方案 S1/S6/S8 全是自己写，不涉及拷代码。

如果确实想要 Readest 那套"真实翻书"，路径仍是上一轮确认的：`grab()` 抓帧（实测 4.6ms）+ WebGL 网格 curl，工作量约 3.5 人天，属于 P3，不阻塞本次整改。

---

## 13. 执行顺序与工期

| 步骤 | 内容 | 工作量 | 依赖 |
|---|---|---|---|
| S1 | EPUB 容器容错（Python + JS）+ 错误页文案 | 0.5d | — |
| S2 | 状态语义 + 批量重识别 | 0.5d | S1 |
| S3 | 书库四视图 | 1.5d | — |
| S4 | 移除/删除/整理三档 | 0.5d | S3（右键菜单） |
| S5 | 应用级主题统一 | 1d | — |
| S6 | 设置浮层重做 | 1d | S5（token） |
| S7 | 内嵌字体 | 0.5d | S6（下拉） |
| S8 | 双栏生效 | 0.25d | S6 |
| S9 | 沉浸模式 + 顶栏菜单 | 0.75d | S5 |
| S10 | 详情面板识别可视化 | 0.5d | S2 |
| S11 | 中文品牌 + 打包 | 0.25d | 全部 |

合计约 **7 人天**。建议节奏：**先 S1+S2（1 天）出一个 1.1.4 修 bug 版**（这两个直接解决你现在最疼的"打不开/识别失败"），再按 S5→S6→S3→S4 做视觉与书库，最后 S7–S11 打包 1.2.0。

---

## 14. 总验收（一次跑完）

1. `python -m pytest tests -q` 全绿（新增用例：`test_epub_case.py`、`test_metadata_status.py`、`test_library_service.py`、`test_theme_qss.py`）。
2. 从 `F:\E-book` 抽 100 本（含已知 78 本里至少 20 本）：
   - 打开成功率 100%；
   - 识别状态里 `failed` 数量 = 0（除非文件真的损坏）；
   - `ops/fb.opf` 类样本全部 `recognized` 或 `need_confirm`。
3. 视觉：8 套主题各截 3 张（书库/阅读/设置），**无白色条、无白色内层**。
4. 书库：1872 本切四视图、滚动、搜索、批量识别、批量移除，均无卡顿与错位。
5. 打包：`tools\build.ps1` 出 `release\书格-1.2.0-setup.exe`；全新机器装完，桌面图标为「书格」，打开能读那本 `心理学大纲`。

---

## 15. 附：本次实测脚本（可复跑）

| 脚本 | 用途 |
|---|---|
| `_audit\epub_zip_probe.py` | 扫描目录下 EPUB，统计 container full-path 与 zip 条目不一致的比例（当前 78/500） |
| `_audit\epub_zip_one.py` | 打印单本的条目名与 UTF-8 标志位，用于判断是大小写问题还是编码问题 |

**结论留档**：`ops/fb.opf` vs `OPS/fb.opf` 是**纯大小写**差异，不是编码问题（`flag_bits & 0x800` 为 False 但条目名全是 ASCII，说明该包用 cp437 无碍）。因此 S1 的 `casefold` 兜底即可解决，GBK 反向解码只作为第二道保险。

**版本**：v3 · 2026-11-26 · 适用 BookShelf 1.1.3（未打包）
