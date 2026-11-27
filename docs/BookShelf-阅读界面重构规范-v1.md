# BookShelf 阅读界面重构规范 v1（AI 可直接执行）

> **用法**：把这份文件整份交给编码 AI（TRAE / Claude Code / Cursor 均可），然后让它**按 §6 的 S1→S6 顺序**执行，一次只做一步，做完停下等验收。
> **定位**：本文件是"施工图"，不是调研报告。之前的《阅读体验对标Readest改造方案》v6 是调研与依据，冲突时**以本文件为准**。
> **验收基线**：每一步都必须 `python -m pytest tests -q` 全绿，并逐条对照 §7。

---

## 0. 开工须知（硬约束，违反即回滚）

1. **技术栈冻结**：Python 3.11 + PySide6 6.7.3 + QtWebEngine（Chromium 118）+ foliate-js（MIT，已 vendor）+ pdf.js。**不许换框架、不许引入 React/Vue/任何前端框架、不许重写 foliate 内核**。
2. **不许动**：EPUB/PDF 的解析链路（`app/reader/prepare*.py`）、`app/reader/bridge.py` 已有 Signal/Slot 的**签名**（只许新增，不许改名/改参数）、SQLite 已有列（只许加迁移）、`installer/` 与 `BookShelf.spec` 的打包语义。
3. **许可**：新引入依赖只允许 MIT / BSD / Apache / LGPL。**AGPL 一律不收**。`readest-main/`、`koodo-reader-dev/` 只读、不复制、不提交。
4. **风格**：注释写中文；**颜色、尺寸、时长一律从 §2 的 token 取**，不许在函数里写裸数字（现有代码里的魔法数字要在本次重构中收口）。
5. **不做的事**（本期明确不实现，别自己加）：翻译、语音朗读、云同步、Mac/移动端、DRM。
6. **每步单独提交**，提交信息用 `ui: S<n> <一句话>`；不要攒到最后一次性提交。

---

## 1. 目标画面

最小窗口 1180×880；下表尺寸单位 px，括号内是可变范围。

```
┌────────────────────────────────────────────────────────────────────────────┐
│ [☰]  书名 · 第三章                                    [⌕] [🔖] [Aa] [⛶]   │  topbar 44
├──────────────┬─────────────────────────────────────────────────────────────┤
│ 目录│笔记│书签 │                                                             │
│              │        ‹«                                      »›            │
│  01 序章  12 │        ┌───────────────────────────────────┐                 │
│  02 第一… 34 │        │                                   │                 │
│ ▶03 第二… 56 │        │            纸 面（正文）            │  sidebar 268    │
│  04 …     88 │        │                                   │  （可折叠到 0） │
│              │        └───────────────────────────────────┘                 │
│              │                                                             │
├──────────────┴─────────────────────────────────────────────────────────────┤
│ ‹ ›  ▂▃▄▅▆▇  1/318   本章剩余 1 分钟 / 1 页   19:45   A− 19 A+             │  bottom 40
└────────────────────────────────────────────────────────────────────────────┘
```

| 区域 | 规格 |
|---|---|
| 顶栏 | 高 44；左 `☰` 折叠按钮 + 书名（13px，超长省略）；右 4 个图标按钮（36×36，间距 4） |
| 侧栏 | 宽 268（折叠 0，动效 160ms）；顶部 3 个等宽 tab（目录/笔记/书签，高 34）；列表行高 34，右侧页码用 muted 色右对齐 |
| 阅读区 | 底色 = 主题 `canvas`；纸面居中，`max-width 920`、`min-width 520`，宽度随窗口自适应；纸面圆角 6、内边距由 foliate 的 margin 控制（默认上下 48 / 左右 56） |
| 底栏 | 高 40；`‹ ›` 32×32；分段刻度进度条占剩余宽度；右侧信息组 13px muted |
| 纸面阴影 | `0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06)`；夜间主题减半 |

**关键视觉原则**（这三条决定"像不像现代阅读器"）：

1. **四周不能有黑边**：`body` 与 `#canvas` 的底色必须等于主题 `canvas`，任何情况下不得出现 `#0e0f12` 这类写死深色。
2. **纸面永远等比**：任何图片、封面、插图都只做等比缩放，宽高各封顶取较小者，绝不允许拉伸。
3. **工具条与纸同族**：顶栏/底栏/侧栏用主题 `chrome`，纸面用 `page`，三者亮度差不超过 6%，且都从同一份色卡取。

---

## 2. 设计 token

### 2.1 八套主题色卡（唯一来源）

| key | 名称 | page（纸） | ink（正文） | muted（次要） | chrome（工具条） | canvas（桌面） | border | accent |
|---|---|---|---|---|---|---|---|---|
| `paper` | 纸白 | `#fbfaf7` | `#1f2328` | `#8b9099` | `#f3f1ec` | `#e9e6df` | `#ddd8cd` | `#3f6fa8` |
| `sepia` | 米黄 | `#f5ecd8` | `#4a3b2a` | `#9a8a6f` | `#efe2c6` | `#e2d4b6` | `#dccbaa` | `#a8763e` |
| `gray` | 灰白 | `#f2f3f4` | `#23262b` | `#8d9299` | `#e8eaec` | `#dcdee1` | `#d4d7db` | `#4a5563` |
| `grass` | 草绿 | `#eef2e7` | `#24301f` | `#7d8a72` | `#e3ead9` | `#d3dcc7` | `#cbd6be` | `#4e7d46` |
| `cherry` | 樱粉 | `#fbeef2` | `#45232c` | `#a5808b` | `#f6e0e7` | `#ecd2db` | `#e5c6d1` | `#c05a78` |
| `sky` | 天青 | `#eff5fb` | `#1f2c3d` | `#7d8fa3` | `#e3edf8` | `#d3e1f0` | `#c9d9eb` | `#3d7bb5` |
| `sunset` | 日晖 | `#fff7ef` | `#43302a` | `#a08678` | `#fbeade` | `#f0dccb` | `#e8d2bd` | `#d9764a` |
| `night` | 夜读 | `#23262b` | `#d8dbe0` | `#8b929c` | `#1b1e22` | `#131518` | `#33373d` | `#7ba7e0` |

**生成规则（别手抄第二套）**：深色变体不单独列表，统一由公式推导：

```python
def _mix(fg: str, bg: str, t: float) -> str:
    a = [int(fg[i:i+2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i+2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(b[i] + (a[i] - b[i]) * t):02x}" for i in range(3))

# 浅色主题的 canvas 不再手填，一律 canvas = _mix(ink, page, 0.10)
# night 的 canvas = _mix("#000000", page, 0.75)
```

### 2.2 字体与字号

| 用途 | 字体 | 字号 | 行距 | 字重 |
|---|---|---|---|---|
| 正文（默认） | 霞鹜文楷 LXGW WenKai Regular | 19（10–40 可调） | 1.90（1.00–3.00，步进 0.05） | 400 |
| 正文（备选） | 思源宋体 / 系统宋体 | 同上 | 同上 | 400 |
| 代码/等宽 | JetBrains Mono | 15 | 1.6 | 400 |
| 界面文字 | 系统微软雅黑 / Segoe UI | 13 | 1.4 | 400 |
| 小字（底栏/页码） | 同上 | 12 | 1.3 | 400 |

- 霞鹜文楷放 `app/reader/assets/fonts/LXGWWenKai-Regular.ttf`，**同时给两处用**：Qt 侧 `QFontDatabase.addApplicationFont`，Web 侧 `@font-face`（相对路径 `fonts/...`，与 reader.html 同目录，file:// 可读）。
- 中文字体必须有 `font-display: swap`，避免首屏空白。
- 段首缩进 2em、两端对齐、断字关闭（中文断字会出丑）。

### 2.3 间距 / 圆角 / 阴影 / 动效

```
间距阶：4 8 12 16 20 24 32 40 48 56
圆角：4（小控件） 6（纸面） 9（图标按钮） 14（弹层）
阴影：paper  = 0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06)
      night  = 0 1px 2px rgba(0,0,0,.02), 0 8px 24px rgba(0,0,0,.10)
      弹层   = 0 8px 28px rgba(0,0,0,.18)
动效：hover 120ms；侧栏/弹层 160ms；主题切换 200ms 淡入；
      翻页 push 300ms / slide 420ms / curl 520ms / flip 520ms；统一 ease `cubic-bezier(.2,.8,.2,1)`
```

---

## 3. 交互与信息架构

### 3.1 顶栏

```
[☰ 折叠目录]   书名（左对齐，QLabel，13px，elide）        [⌕ 搜索] [🔖 批注] [Aa 设置] [⛶ 全屏]
```

- 所有按钮 `objectName = "ReaderIconButton"`，36×36，圆角 9，透明底，`:hover` 用 `rgba(0,0,0,.06)`（night 用 `rgba(255,255,255,.08)`），`:checked` 用 `.10`。
- **图标必须是 SVG**（`app/ui/resources/icons/*.svg`，24×24 线性，`stroke: ink`），不许再用 `⌕ 🔖 ◐ ⛶` 这类文字字符。
- 包标题的容器**必须** `setAttribute(Qt.WA_StyledBackground, True)` + `background: transparent`，否则会出现白色断层（这是当前截图里顶栏发白的根因）。
- 主题切换按钮从顶栏**移除**，并入 Aa 弹层（少一个入口）。

### 3.2 侧栏

- 三个等宽 tab：**目录 / 笔记 / 书签**（`ReaderTabButton`，高 34，选中态底部 2px accent 下划线）。
- 目录行：`序号（muted，宽 28，右对齐）` + `标题（ink，省略）` + `页码（muted，右对齐，宽 32）`；行高 34，选中行左侧 2px accent 竖条 + `panel` 底。
- 页码来源：PDF 取 outline 的 page；EPUB 用"已访问章节缓存"，未访问显示 `~`（**不许**为了页码去逐章 `goTo` 实测）。
- 当前章节自动 `setCurrentRow` 并 `scrollToItem` 可见。
- 折叠动效：`QSplitter` 左栏宽度 268 → 0，用 `QPropertyAnimation(160ms)`；折叠后顶栏 `☰` 保持 available。

### 3.3 底栏

```
[‹] [›]   ▂▃▄▅▆▇分段刻度条   1/318   本章剩余 1 分钟 / 1 页   19:45   A− 19 A+
```

- 进度条：`QSlider` range 0–1000，轨道高 4，手柄 12；**叠一层自绘刻度**（每 10% 一条 3px 竖线，`muted` 30% 透明）；`sliderReleased` 才 seek，拖动中只更新页码文字。
- 页码文案：`{page}/{total}`，无 total 时只显示 `第 N 页`。
- 本章剩余：`N 分钟 / M 页`，分钟 = 剩余页数 × `avg_page_seconds` / 60；没有统计数据时显示 `本章剩余 —`。
- 时间：`QTimer` 每 30s 刷新，格式跟随 `hour24` 设置。
- 右侧 `A−` / `A+` 用 §3.4 的 Stepper 同一套控件（34×30）。

### 3.4 Aa 弹层（三 tab）

宽 320，`QFrame(self, Qt.Popup)`，圆角 14，阴影按 §2.3。

| tab | 内容 |
|---|---|
| **字体** | 中文字体下拉（霞鹜文楷/思源宋体/系统宋体）+ 字号 Stepper + 行距 Stepper + 字重下拉（400/500/600） |
| **版面** | 段距 Stepper（0–3em，步进 0.25）+ 首行缩进开关 + 两端对齐开关 + 上/下/左/右页边距（各 0–240，步进 4）+ 分栏数（1/2）+ 最大列宽（520–1200，步进 20） |
| **主题** | 8 个色卡圆点（30×30，选中加 3px accent 环）+ 模式（浅色/深色/跟随系统）+ 自定义强调色（`QColorDialog`）+ 背景纹理（无/纸纹/细噪）+ 恢复默认 |

**Stepper 是本期必须新建的控件**（当前 `QSpinBox` 自带上下小箭头 + `A−/A+` 按钮，三套控件混用是"难看"的根源）：

```python
class Stepper(QWidget):
    """− [ 19 ] +   值只读，支持长按连发与滚轮。"""
    changed = Signal(float)
    # 尺寸：按钮 34×30，圆角 8，中间值 44 宽、居中、13px
    # 长按：按下 400ms 后每 90ms 重发一次
    # 滚轮：每格 = 一个 step，需同时支持正负方向
```

样式：`QPushButton#StepBtn` 透明底 + `1px border`，hover 边框变 `accent`、字色变 `accent`，pressed 反色（`accent` 底 + 白字）。

### 3.5 点击区与两侧箭头

- **点击区必须绑在 foliate 的 iframe document 上**（绑外层 `#canvas` 无效）：
  - 左 25% → `prev()`，右 25% → `next()`，中间 50% → 收起/呼出工具条；
  - 排除 `<a>`、`<img>`、输入控件、非折叠选区；
  - 快速连点（间隔 < 200ms）合并为一次，避免连翻。
- 两侧箭头照 Readest，**两组各两枚**：
  ```
  ‹«（上一章）  ‹（上一页）  ……  ›（下一页）  »（下一章）
  ```
  34×34 圆形、半透明底 + `backdrop-filter: blur(6px)`；默认 `opacity:0`，鼠标进入正文区淡入（120ms），离开淡出。
- **翻页动效五档**（设置里可选，默认 `push`）：
  | 档 | 值 | 实现 |
  |---|---|---|
  | 直接翻页 | `instant` | 移除 `turn-style` + `body.no-turn-anim`（`*{transition:none!important}`） |
  | 平移 | `push` | 移除 `turn-style`，用 paginator 内置两段式 |
  | 滑动 | `slide` | `renderer.setAttribute("turn-style","slide")` |
  | 卷角 | `curl` | `renderer.setAttribute("turn-style","curl")` |
  | 整页翻 | `flip` | View Transitions + `perspective/rotateY`，`transform-origin` 左右镜像 |
  - 启动探测：`typeof document.startViewTransition === "function"`（本机 Chromium 118 支持，`ViewTransition.prototype.group` 不支持，所以 `push` 用内置实现，不做 group 分层）。
  - 所有翻页入口（点击区、箭头、键盘、按钮、底栏 `‹ ›`）**统一走 `turn(dir)`**，不许各自直连 `next()/prev()`，否则 `flip` 档会漏一半入口。

### 3.6 快捷键（与 Readest 对齐）

| 动作 | 键 |
|---|---|
| 上一页 | `←` / `h` / `Shift+空格` |
| 下一页 | `→` / `l` / `空格` |
| 上/下一章 | `Alt+←` / `Alt+→` |
| 半页 | `d` / `u` |
| 首/尾 | `Home` / `End` |
| 字号 | `Ctrl+=` / `Ctrl+-` / `Ctrl+0` |
| 搜索 | `Ctrl+F` |
| 折叠/展开侧栏 | `Ctrl+B` |
| 全屏 | `F11` |
| 高亮 | `Shift+F` |
| 快捷键帮助 | `Shift+?` |
| 主题循环 | `Ctrl+Shift+T` |

推荐实现放在 `app/ui/shortcuts.py`，用 `QShortcut(QKeySequence(...), self)` 注册，`Qt.WindowShortcut` 上下文；Web 侧的 `handleKey` 只保留正文区（iframe 内）的按键，**两边不许抢同一个键**。

### 3.7 工具条自动隐藏

- 鼠标离开顶栏/底栏/侧栏且正文区静止 2.5s → 顶栏与底栏下滑 8px 淡出（160ms）；移动鼠标到窗口顶部 24px 内或点正文中间 → 淡入。
- 弹层打开时**不自动隐藏**。
- 全屏模式下默认隐藏，只保留底栏进度条（可设置关闭）。

---

## 4. 偏好数据（单一来源）

存 `%APPDATA%\BookShelf\settings.json` 的 `reader` 段，**全局默认 + 按书覆盖**：

```json
{
  "reader": {
    "theme": "paper", "mode": "auto",
    "font_family": "LXGW WenKai", "font_size": 19, "line_height": 1.90, "font_weight": 400,
    "para_spacing": 0.75, "indent": true, "justify": true, "hyphens": false,
    "margin_top": 48, "margin_bottom": 48, "margin_left": 56, "margin_right": 56,
    "column_count": 1, "max_column_width": 920,
    "turn_style": "push", "click_turn": true, "hide_chrome_delay": 2500,
    "header_footer": {"remaining_time": true, "remaining_pages": true, "progress": true,
                      "clock": true, "clock_24h": true, "battery": false},
    "texture": "none", "accent": null,
    "highlight_colors": ["yellow", "green", "blue", "pink", "red"],
    "books": { "12": { "turn_style": "curl", "font_size": 21 } }
  }
}
```

- **主题色值不落盘**，落盘只存 `theme` 的 key；调色板由 §2.1 的代码常量生成。
- Python 把整包 `prefs` + `palette` 一起塞进 `open_payload` 传给前端（当前 `_finish_prepared` 已在传 `prefs`，只需补 `palette`）。
- JS 侧 `applyPrefs()` 是**唯一入口**：先 `applyPalette()`，再 `applyFoliateStyles()`，再 `layoutFoliate()`，最后 `applyTurnStyle()`。任何新设置都必须挂进这个链条。

---

## 5. 文件级改动清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `app/ui/pages/reader_container.py` | 大改 | 顶栏/侧栏/底栏重排；删掉文字图标；`_apply_theme` 接 token；prefs 弹层换三 tab |
| `app/ui/widgets/stepper.py` | **新增** | `Stepper` 控件（§3.4） |
| `app/ui/widgets/segmented_progress.py` | **新增** | 带刻度的进度条（§3.3） |
| `app/ui/widgets/icon_button.py` | **新增** | `IconButton`（36×36，加载 SVG） |
| `app/ui/theme_tokens.py` | **新增** | 8 套色卡 + `_mix()` + `ReaderPalette` dataclass + `palette_for(key, mode)` |
| `app/ui/shortcuts.py` | **新增** | 快捷键表（§3.6） |
| `app/ui/resources/icons/*.svg` | **新增** | 12 个线性图标 |
| `app/reader/assets/fonts/LXGWWenKai-Regular.ttf` | **新增** | 内嵌字体（OFL，随包分发） |
| `app/reader/assets/reader.css` | 大改 | 删 `--canvas` 硬编码与三段 `data-theme`；纸面自适应；工具条主题化；五档动效关键帧；两侧箭头 |
| `app/reader/assets/reader.html` | 中改 | 加 `#turnOverlay`、`.side-nav` 两组箭头、字体 `@font-face` |
| `app/reader/assets/reader.js` | 大改 | `applyPalette`、`fitPaper/fitPdf`、`bindTapZones`、`turn(dir)`、`applyTurnStyle`、`bindChromeAutoHide` |
| `tests/test_reader_prefs.py` | 新增 | 偏好读写与按书覆盖 |
| `tests/test_theme_tokens.py` | 新增 | 8 套色卡合法性（含 canvas 推导） |

**不许新建**：`themes2.py`、`reader_v2.css` 这类"平行实现"。改就改原文件，避免两套样式打架。

---

## 6. 执行步骤（S1 → S6）

> 每步独立提交；每步结束后运行 `python -m pytest tests -q` 并自查该步的验收点。**不要跳步**，S2 依赖 S1 的 token。

### S1 · 主题单一来源（0.5d）

**目标**：切任何一套主题，阅读区底色、纸面、工具条三者同族，永不出现黑边。

1. 新建 `app/ui/theme_tokens.py`：照 §2.1 落 8 套 `ReaderPalette`（字段 `page/ink/muted/chrome/canvas/border/accent`），`canvas` 用 `_mix()` 推导，禁止手填。
2. `reader_container.py`：删掉 `_ReaderTheme` 与 `_READER_THEMES`，改从 `theme_tokens` 取；`_reader_prefs()` 输出增加 `palette` 字典。
3. `reader.css`：删掉 `:root` 里的 `--canvas: #0e0f12` 与 `body[data-theme=light|sepia|dark]` 三段；变量全改由 JS 写入。
4. `reader.js`：

```js
function applyPalette() {
  const p = (STATE.prefs && STATE.prefs.palette) || {};
  const root = document.documentElement.style;
  root.setProperty("--canvas", p.canvas || "#e9e6df");
  root.setProperty("--page-bg", p.page || "#fbfaf7");
  root.setProperty("--page-text", p.ink || "#1f2328");
  root.setProperty("--muted", p.muted || "#8b9099");
  root.setProperty("--chrome", p.chrome || "#f3f1ec");
  root.setProperty("--border", p.border || "#ddd8cd");
  root.setProperty("--accent", p.accent || "#3f6fa8");
  if (STATE.foliate?.renderer) {
    applyFoliateStyles();                       // 内部取 p.page / p.ink
    STATE.foliate.renderer.setBackground?.(p.page);
  }
}
```

5. `themeColors()`、`foliateBackground()` 全部改为读 `palette`，**函数体里不许再出现 `if (theme === "dark")` 这类分支**。

**验收**：8 套主题逐个切换，截图对比——阅读区底色与顶栏同族；`cherry` 下不再出现黑边；切主题 200ms 淡入无闪烁。

### S2 · 版面与自适应（0.75d）

**目标**：纸面随窗口等比缩放，图片永不被压扁。

1. `reader.css`：`#paper` 去掉 `width:720px` → `width:auto; flex:1 1 auto; max-width:min(100%, var(--page-max, 920px))`；`height:calc(100vh - 24px)`；`#canvas` padding 收到 `12px 16px 16px`。
2. **EPUB 图片覆盖（最关键的一条）**：

```css
img, svg { max-width:100% !important; height:auto !important; object-fit:contain; }
figure, .cover, .calibre1 { max-height:none !important; }
img.fullpage { display:block; margin:0 auto; max-height:100%; width:auto; max-width:100%; }
```
`!important` 不能省——出版方 CSS 常写 `img{height:100%}`，不加就被它盖掉，就是"上下压扁"的成因。

3. `reader.js` 新增 `fitPaper()`：按可用宽高算 `--page-max` 并 `setAttribute("max-inline-size"/"max-block-size")`；`resize` 防抖 150ms 调它。
4. `layoutFoliate()` 里 `max-inline-size`、`max-block-size`、`max-column-count`、`gap` 全部改读 prefs，不再写死。
5. PDF 分支：`openPdf` 里去掉 `min(820, …)`，改 `fitPdf(availW, availH)`，缩放取 `min(availW/baseW, availH/baseH)`。

**验收**：窗口 1000×700 ↔ 1600×1000 来回拖，封面比例不变、完整可见、不出现滚动条以外的裁切；把字号调到 40 也不溢出。

### S3 · 顶栏 / 图标 / 侧栏（1d）

**目标**：不再有白块，图标统一，目录可显示页码并可折叠。

1. 顶栏按 §3.1 重排；包标题容器设 `WA_StyledBackground + transparent`；删 `◐` 主题按钮。
2. 生成 12 个 SVG（`library/toc/search/bookmark/note/aa/fullscreen/prev_chapter/prev_page/next_page/next_chapter/theme`），接 `IconButton`。
3. 侧栏改三 tab（目录/笔记/书签）；目录行按 §3.2 加序号、页码、选中竖条；当前章节自动定位。
4. `QSplitter` 折叠动效 160ms；折叠后顶栏 `☰` 仍可展开。

**验收**：顶栏无白色断层；5 个图标风格一致；目录每行都有页码（EPUB 未访问显示 `~`）；点 `☰` 有平滑收起动画，`Ctrl+B` 也能切。

### S4 · Aa 弹层与 Stepper（0.75d）

**目标**：设置面板"看起来是同一套系统做的"。

1. 新建 `Stepper`（§3.4），字号/行距/段距/页边距四行全换它；`QSpinBox/QDoubleSpinBox` 若保留必须 `setButtonSymbols(NoButtons)`。
2. 弹层改三 tab（字体/版面/主题），宽 320，圆角 14，tab 高 32、选中下划线 2px accent。
3. 主题 tab：8 个 30×30 圆点 + 模式三选 + 自定义强调色 + 恢复默认。
4. 任何改动即时生效并写回 prefs（**不要"确定/取消"按钮**，Readest 也没有）。

**验收**：长按 `+` 字号连续变大且不丢步；行距显示两位小数；切换 tab 无跳变；改字号时纸面重排但不闪黑。

### S5 · 阅读交互与动效（1d）

**目标**：点两侧翻页、有箭头、五档动效可切。

1. `bindTapZones()` 绑 iframe document（§3.5 规则），PDF 模式绑 `#canvas` 调 `scrollToPage`。
2. `.side-nav` 两组箭头（`«‹ ›»`），hover 淡入；点击调 `turn(dir)` / 章节跳转。
3. 新增 `turn(dir)`：所有入口统一走它；`flip` 档用 `startViewTransition` + `#paper{view-transition-name:reader-sheet}` + `sheetOut` 关键帧（左翻 `-102deg`、右翻 `+102deg`，`transform-origin` 镜像）。
4. `applyTurnStyle()` 五档写入；`instant` 档加 `body.no-turn-anim`。
5. 工具条自动隐藏（§3.7）+ 快捷键（§3.6）。

**验收**：点右侧 1/4 翻下一页、点链接不翻页、选中文字时点不翻页；五档逐一切换即时生效；连点 5 次不叠层、不残留；`flip` 时能看到下一页已就位。

### S6 · 底栏与页脚信息（0.5d）

**目标**：信息密度对齐 Readest。

1. `SegmentedProgress`（§3.3）：4px 轨道 + 每 10% 刻度 + 12px 手柄；拖动只更新文字，`sliderReleased` 才 seek。
2. 右侧信息组：`1/318`、`本章剩余 N 分钟 / M 页`、`HH:MM`（30s 刷新）。
3. 剩余时间算法：`剩余页数 × avg_page_seconds / 60`；无统计数据时显示 `—` 并 tooltip 说明"读几页后开始估算"。
4. `A−/A+` 换成 Stepper 同款。

**验收**：底栏 5 组信息在 1000 宽下不换行、不重叠；拖进度条松手才跳转；时间每半分钟跳一次。

---

## 7. 验收清单

**命令**

```
python -m pytest tests -q
python -m pytest tests/test_theme_tokens.py tests/test_reader_prefs.py -q
QT_QPA_PLATFORM=offscreen python _audit/feature_probe.py    # 冒烟：窗口能起、能开书
```

**人工 12 点（截图留证）**

1. 8 套主题 × 2 个窗口尺寸，均无黑边、无白块。
2. `cherry` 主题下，顶栏/侧栏/底栏/纸面四者同族。
3. 封面与插图在 1000×700、1440×900、1920×1080 下比例不变、完整可见。
4. 字号 10 与 40 两个极端下，纸面不溢出、不出现横向滚动。
5. 目录 3 个 tab 都能切；当前章节高亮且自动滚到可见。
6. 目录行有页码（EPUB 未访问为 `~`）。
7. Aa 弹层 3 个 tab 无横向滚动条；Stepper 长按可连调。
8. 点正文左/右 1/4 能翻页；点链接/选中文字不翻页。
9. 两侧箭头 hover 才出现，离开 160ms 淡出。
10. 五档动效逐一切换，`flip` 下无闪烁、无残留。
11. 底栏 5 组信息不重叠；时间会走。
12. 关掉工具条自动隐藏后，顶栏常显且不抖。

---

## 8. 禁止与常见坑

| 坑 | 后果 | 正确做法 |
|---|---|---|
| 在 `reader.css` 里补 7 段 `body[data-theme=…]` | 做 8 套色卡时变 16 段，必然漏一套 | 单一来源：Python 算、JS 写 CSS 变量 |
| 给 `img` 只写 `max-width` 不加 `!important` | 出版方 `height:100%` 生效 → 图被压扁 | 三条一起写（§S2-2） |
| 点击区绑在 `#canvas` 上 | iframe 里的点击拿不到，点了没反应 | 绑 foliate 的 `renderer.getDoc()` |
| 各入口各自直连 `next()/prev()` | `flip` 档只有部分入口生效 | 统一 `turn(dir)` |
| 用 `QSpinBox` 默认箭头 + 自绘按钮混用 | 视觉三套控件打架 | 统一 `Stepper` |
| 抄 `readest-main/.../pageCurl.ts` | AGPL 污染，整包被迫带网络条款 | 只读参数，着色器自己写 |
| 主题色值写进 settings.json | 改色卡后老用户不更新 | 只存 key |
| 在 `openPayload` 里塞 base64 大图 | WebChannel 卡顿 | 翻页位图走单独 slot，且只在真 curl 档才抓 |

---

**版本**：v1 · 2026-11-26 · 适用 BookShelf 1.1.3 代码结构
**上游依据**：《BookShelf-阅读体验对标Readest改造方案》v6（调研结论与实测数据），`docs/UPSTREAM.md`（复用边界）

---

## 9. 复检结论（2026-11-26 21:10，S1–S6 已执行后）

**总体**：`python -m pytest tests -q` **286 项全绿**；S1–S6 的骨架都落地了，没有走"平行实现"的歪路。下面只列**没做完 / 做错**的部分。

### 9.1 已正确落地（不用再动）

| 项 | 证据 |
|---|---|
| 主题单一来源 | `app/ui/theme_tokens.py`（8 套 + `mix()` 推导 canvas/panel）；`_reader_prefs()` 输出 `palette`（`:1718`） |
| CSS 去硬编码 | `reader.css` 无 `body[data-theme]` 段、无 720px；变量由 `reader.js:157 applyPalette()` 写入 |
| 图片不压扁 | `foliateStyles()` 里 `img,svg{...!important}` + `figure/.cover/.calibre1{max-height:none!important}`（`:269-271`） |
| 纸面自适应 | `#paper{width:auto;max-width:min(100%,var(--page-max))}`；`paperMetrics/fitPaper/scheduleFitPaper`（js:292-347） |
| 点击区 | `handleTap()` 绑 iframe document（js:425-447、543） |
| 五档动效 | `applyTurnStyle()` + `turn(dir)`（js:194-208、364-388）；`turn_style` 有 UI（`:978-983`） |
| 控件 | `Stepper`、`SegmentedProgress`、`IconButton` + 12 个 SVG 已建并接入 |
| 侧栏三 tab + 页码 | `_TocItemDelegate`、`sidebar_tabs[0..2]`；`_toggle_chrome` 已接 bridge |
| 快捷键 | `Ctrl+B` 等已注册（`:2022-2029`） |

### 9.2 必须修（按严重度）

| # | 问题 | 位置 | 修法 |
|---|---|---|---|
| **1** | **霞鹜文楷没内嵌**：`app/reader/assets/fonts/` 根本没有，`font_family` 默认空 → 实际渲染是 Noto Serif CJK/SimSun | `reader.js:236-241`；Qt 侧无 `addApplicationFont` | 放 `LXGWWenKai-Regular.ttf`（OFL）；Qt 启动时 `QFontDatabase.addApplicationFont`；`reader.css` 加 `@font-face`；字体下拉默认项改"霞鹜文楷" |
| **2** | **`view-transition-name: reader-sheet` 无条件挂在 `#paper`** → 选 `slide/curl` 时，paginator 自己的 View Transition 也会命中 `sheet-turn-out`，两种动效叠加 | `reader.css:151-153` | 改成只在高档位生效：`body.flip-turn #paper{view-transition-name:reader-sheet}`，`applyTurnStyle()` 里 `classList.toggle("flip-turn", style==="flip")` |
| **3** | **Stepper 没有长按连发**（只有 wheel）；规格要求"按下 400ms 后每 90ms 重发" | `app/ui/widgets/stepper.py`（无 `QTimer`/`mousePressEvent`） | 加 `QTimer` + `pressed/released`；到边界自动停 |
| **4** | 两侧箭头在**纸面内侧 6px**，会压住正文最后几个字；`#paper:hover` 触发，鼠标在纸内任意位置都会弹 | `reader.css:106-117` | 挪到纸外（`left:-44px; right:-44px`，不足宽度时回落纸内并降为 30px），触发改 `#canvas:hover` |
| **5** | **工具条自动隐藏没实现**：`hide_chrome_delay` 只进了 prefs，没有任何计时器 | `reader_container.py:1750`，JS 无 `idle` 逻辑 | Qt 侧加 `_idle_timer`（2500ms，鼠标移动/按键重置），到点 `_toggle_chrome(hide=True)`；弹层打开时停表 |
| 6 | `#canvas` 的 `padding:12px 16px 16px` 与 `#paper` 的 `calc(100vh - 28px)` 是巧合对齐（12+16=28），改 padding 会错位 | css:26、37 | 用 CSS 变量 `--canvas-pad` 一处定义，`#paper` 高度改 `calc(100vh - var(--canvas-pad-y))` |
| 7 | `reader.html` 仍留 `body data-theme="light"`（已无 CSS 使用） | html:7 | 删掉，避免下一个人以为它还生效 |

**修完这 7 条再打包**：现在打出来的 1.1.4 会是"新控件 + 旧字体 + 动效打架"的半成品。

---

## 10. 元数据源改造（OpenLibrary / Google Books 在国内不可用的替代方案）

### 10.1 实测矩阵（2026-11-26，本机直连，`curl` 带浏览器 UA，ISBN=9787020002207）

| 源 | 结果 | 结论 |
|---|---|---|
| `openlibrary.org` | 000 / 10s 超时 | **不可用**，现在的默认源等于死链 |
| `googleapis.com/books` | 000 / 10s 超时 | **不可用** |
| `book.douban.com/j/subject_suggest` | **200**（2.7s，JSON：title/author/year/pic/id） | 可用；**但只吃书名/作者，不吃 ISBN** |
| `book.douban.com/isbn/{isbn}/` | **301 → 200**（跳到 `/subject/{id}/`，页面含书名/出版社/ISBN/年份） | **可用**，ISBN 直查就靠它；注意假 ISBN 也会跳，必须回页校验 ISBN |
| `book.douban.com/subject/{id}/` | **200**（136 KB，含 `.info` 出版社/出版年/页数/定价/ISBN/装帧） | 可用，字段最全 |
| `img*.doubanio.com`（封面） | **200**（14 KB jpg，需 Referer） | 可用，封面可直接下载 |
| `search.douban.com/book/subject_search` | 200，含 `window.__DATA__`；书名有结果、ISBN 常空 | 备用（解析 `__DATA__`） |
| `search.kongfz.com/product` | **200** | 可用，旧书/绝版/无 ISBN 的中文书 |
| `api.crossref.org/works` | **200**（1.9s） | 可用，外文/学术书（部分带 ISBN） |
| `search.jd.com` | 302 后返回"京东验证" | 反爬，**不作默认源** |
| `search.dangdang.com` | 200 但正文无书名（疑似风控页） | 不可靠，**不作默认源** |
| `opac.nlc.cn` / `find.nlc.cn` / `pd.capub.cn` | 000 超时 | 不可用，别投入 |

### 10.2 目标架构（`app/net/` 里加 3 个 Source，接口与现有一致）

现有 Source 是鸭子类型：`name`、`label`、`by_isbn(isbn) -> list[dict]`、`search(query) -> list[dict]`，在 `metadata_service._build_sources()` 按 settings 开关装配。**照这个形状加，不动 service 层**。

| 新文件 | 优先级 | 职责 | 关键实现 |
|---|---|---|---|
| `app/net/douban.py` | **P1（主源）** | ISBN 直查 + 书名/作者搜 | ① `GET https://book.douban.com/isbn/{isbn}/` 跟随跳转，取最终 URL 的 subject id；② 解析详情页 `.info` 的 `出版社/出版日期/页数/定价/ISBN/装帧` 与 `<title>`、`#mainpic img`；③ **校验页面 ISBN == 请求 ISBN**（假 ISBN 也会跳转，不校验会串书） |
| `app/net/kongfz.py` | P2 | 旧书 / 无 ISBN | `search.kongfz.com/product/?keyword=`，解析商品卡片；字段少（书名/作者/出版社/年份），只作补充 |
| `app/net/crossref.py` | P3 | 外文 / 学术 | `api.crossref.org/works?query.bibliographic=ISBN或书名`，取 `title/author/publisher/issued`，**无封面** |

配套硬要求：

1. **限速 + 缓存**：豆瓣单请求实测 2.7s，必须 `1 请求/2s` 串行 + 本地缓存 7 天（`cache/metadata/`），否则批量补元数据会被封。
2. **UA/Referer**：豆瓣要带浏览器 UA 与 `Referer: https://book.douban.com/`；封面下载同样要 Referer。
3. **可开关**：设置里给"元数据源"三勾（豆瓣/孔夫子/Crossref），默认豆瓣开、其余关——豆瓣是爬网页，随时可能变，必须能一键关掉。
4. **排序与打分**：沿用 `app/net/scoring.py`，但**中文源加权**：ISBN 完全一致 +60、书名归一化相等 +30、作者相等 +20、出版社相等 +10。
5. **内嵌优先**：批量流程必须"先读内嵌（EPUB OPF / MOBI EXTH / PDF XMP），缺失字段才联网"，现在 `app/core/metadata/` 已支持 epub/pdf/mobi/azw3，直接复用 `extract_metadata()`。

### 10.3 重命名（已有能力，只需接上）

`app/core/naming.py` 已按模板生成：默认目录 `{作者} [{国家}]`、文件 `{作者} - {卷号} {书名}.{扩展名}`（`config.py:85-86`，可在设置里改）。元数据补齐后由 `organize_service` 执行改名——**不需要新写重命名逻辑**，只要保证 `title/author/publisher/date/series/series_index` 五个字段填对。

### 10.4 指令 M1–M3

**M1（0.5d）豆瓣源**
```
新建 app/net/douban.py，实现 DoubanSource(name="douban", label="豆瓣读书")：
- by_isbn：GET https://book.douban.com/isbn/{isbn}/，allow_redirects，解析最终页；
  从 .info 提取 出版社/出版日期/页数/定价/ISBN/装帧，title 取 <title> 去后缀，
  authors 取 .info 里 "作者:" 或页面作者行；cover_url 取 #mainpic img 的 src；
  **必须校验解析出的 ISBN 与请求 ISBN 归一化后相等，否则返回 []**。
- search：先 GET /j/subject_suggest?q={query}（JSON），取前 5 个 id，
  再逐个抓 /subject/{id}/ 详情页（串行 + 2s 间隔），映射成同一结构。
- 反爬：UA 用浏览器 UA，Referer=https://book.douban.com/；失败重试 1 次，间隔 3s。
注册进 metadata_service._build_sources()，settings 键 metadata.sources.douban（默认 true）。
加 3 个 fixture 测试（真 HTML 片段，离线跑，不许联网）。
```

**M2（0.25d）Crossref + 孔夫子**
```
app/net/crossref.py：GET api.crossref.org/works?query.bibliographic={isbn或书名}&rows=3，
映射 title/author/publisher/issued.date-parts[0]/ISBN；无封面。
app/net/kongfz.py：GET search.kongfz.com/product/?keyword={q}，解析商品卡片标题与作者/出版社；
只填 title/author/publisher/date，其余留空。
两者默认关闭，设置里可开；同样走 scoring 与缓存。
```

**M3（0.25d）内嵌优先 + 改名串联**
```
scan 与"批量补元数据"统一入口：
1) extract_metadata(path) 先填；2) 缺失字段才调 find_candidates()；
3) 用户确认后 naming.build_target(...) 生成新名，organize_service 执行移动/改名；
4) 命名冲突按现有 _dedupe 规则追加 (2)/(3)。
验收：10 本中文 EPUB（含 3 本无 ISBN），补全后文件名符合 "{作者} - {卷号} {书名}.{扩展名}"，
且原文件哈希不变、数据库 file_path 同步更新。
```

### 10.5 可借鉴的 GitHub 实现（只读实现思路，别整包引入）

| 仓库 | 星 | 许可 | 借鉴点 |
|---|---|---|---|
| `fugary/calibre-douban` | 1,386 | Apache-2.0 | **就是抓 `book.douban.com` 网页**做的 calibre 元数据插件；可看它的搜索页/详情页选择器与字段映射（2025-11 仍在更新） |
| `fugary/calibre-web-douban-api` | 464 | Apache-2.0 | 上面插件的独立 API 服务版，Python，**解析逻辑更干净**，最适合对着抄结构（不是抄代码） |
| `isbn/isbnlib` | 3k+ | MIT | 已装；它的 provider 机制可参考，但国内 provider 为空，仍需自写 |

> 许可提示：两个 fugary 仓库是 Apache-2.0，与 GPL-3.0 兼容，可放心读；但**别直接整包 vendored**，只取选择器与字段规则，代码自己写，便于以后豆瓣改版时单独维护。

