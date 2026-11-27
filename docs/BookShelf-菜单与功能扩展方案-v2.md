# 书格 · 菜单与功能扩展方案 v2

> 2026-11-26 · 承接 `BookShelf-UI重构与图书管理方案-v1.md`
> 原型：`docs\书格-UI原型.html`（书库/卡片/阅读器）+ `docs\书格-UI原型-v2-书架统计笔记设置.html`（书架/统计/笔记/设置）
> 本文件只回答一件事：**在现有界面上要加哪些菜单、每个菜单怎么排、数据从哪来、怎么落地**。

---

## 0. 取舍原则（Koodo vs Readest 怎么选）

| 维度 | Koodo 的做法 | Readest 的做法 | 选谁 |
|---|---|---|---|
| 功能宽度 | 很宽：书架、统计、笔记、标签、收藏、封面墙 | 克制：书库 + 阅读 + 笔记 | **菜单学 Koodo（够用就好），视觉学 Readest（留白与分组）** |
| 排序/分组 | 9 种排序 + 分组 + 网格列数 | 6 种排序 + 分组 | **取并集，做 9 维 + 5 分组 + 自动/固定列数** |
| 设置页 | 一长列选项，滚动很长 | 左分组 + 右卡片，视觉分层 | **Readest 式：左侧 8 个分组，右侧卡片两列** |
| 主题 | 单层主题 | **界面主题 / 书库主题 / 阅读主题分层 + 背景图** | **学 Readest 的三层** |
| 阅读模式 | 翻页为主 | **滚动 / 分页两种，可配自动翻页、阅读尺** | **两种都做，滚动用 CSS 多列 + scroll-snap** |

一句话：**功能面按 Koodo 补齐，呈现面照 Readest 重排。**

---

## 1. 左导航新增四项（书库 → 内容 → 分类 → 工具）

```
书库      我的书架(1872) / 喜爱(36) / 在读(12) / 已读(148)
内容      笔记与高亮(284) / 阅读统计
分类      作者 / 系列 / 标签 / 文件夹
工具      整理 / 清理空目录 / 回收站 / 格式转换
```

- 「待整理 / 识别失败」并入「我的书架」的筛选条，不再单列一级项（否则导航过长）；
- 「喜爱」= `favorite=1` 的书，用实心星图标；
- 「在读 / 已读」来自新增的 `read_state` 字段，**不是**按 percent 猜的；
- 「笔记与高亮」合并原侧栏的"笔记/书签"，按 `bookmarks.kind` 分三档（高亮/想法/书签）。

---

## 2. 排序与分组：9 个维度，统一升降序

### 2.1 排序维度

| 维度 | 数据来源 | 备注 |
|---|---|---|
| 书名 | `books.title` | 中文按 pinyin 排序（`pypinyin`，纯 Python，MIT），否则"张、王、李"会乱 |
| 作者 | `author_raw` / `authors.name` | 同姓再按书名 |
| 格式 | `books.format` | EPUB → PDF → MOBI 顺序 |
| 页数 | `books.page_count` | 空值排最后 |
| 系列 | `series.name` + `volume` | 先系列名再卷号 |
| **阅读日期** | `reading_state.last_read_at` | 最近读的在前 |
| 添加日期 | `books.added_at` | 默认 |
| 出版日期 | `books.publish_date` | 只取年份位比较，缺年份排最后 |
| **阅读进度** | `reading_state.percent` | 0–100 |
| **阅读时长** | `reading_state.total_seconds` | 需配合 §3 的会话表 |
| **文件大小** | `books.file_size` | |
| **识别度** | `books.confidence` | 便于先处理可疑项 |

（前 6 个是用户原话要求，后 5 个从 Koodo 补齐；合计 12 项，UI 下拉里分两组：`基础 / 阅读`。）

### 2.2 分组

`无分组 / 作者 / 系列 / 标签 / 阅读状态 / 格式 / 添加月份`

- 分组后在书架里生成**分组标题条**（`马伯庸 · 12 本`），同组内再按当前排序维度排；
- 分组标题条可折叠（`▾`），折叠状态存 prefs；
- "按添加月份"用于回顾（`2026-11 · 42 本`）。

### 2.3 网格列数

`自动 / 4 / 5 / 6 / 8`：
- 自动 = 按窗口宽度算 `floor((可用宽 + gap) / (最小卡宽 150 + gap))`，夹在 3–8；
- 固定值在窄窗口下自动降级并提示"窗口太窄，已降到 4 列"；
- 卡片高度随列数缩放：封面 `144×196 @6列 → 180×245 @4列`，文字两行恒定。

实现：`QListView` + `IconMode`（不要 `QGridLayout` 动态重排，1872 本会卡）。`setGridSize` 随列数变化重算，`setResizeMode(Adjust)`。

---

## 3. 阅读统计：数据从哪来

现有表只能支撑"累计时长"：`reading_state.total_seconds`。热力图、时段分布、日均都需要**会话明细**。

### 3.1 迁移（schema v5）

```sql
-- 每次进入阅读页到离开为一段会话，每 60s 落一次
CREATE TABLE IF NOT EXISTS reading_sessions (
  id          INTEGER PRIMARY KEY,
  book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  started_at  TEXT NOT NULL,        -- ISO8601
  ended_at    TEXT,
  seconds     INTEGER DEFAULT 0,
  pages       INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_rs_day ON reading_sessions(substr(started_at,1,10));

-- books 增两列（用 ALTER TABLE 加，别重建表）
ALTER TABLE books ADD COLUMN favorite INTEGER DEFAULT 0;
ALTER TABLE books ADD COLUMN read_state TEXT DEFAULT 'unread';   -- unread/reading/read
```

### 3.2 采集

- `bridge.py` 已有 `saveProgress`；在阅读页 `showEvent` 开一段会话，`hideEvent`/关闭时结束；每 60s `flush` 一次（防止崩溃丢时长）；
- 只统计**前台且窗口激活**的时间（`isActiveWindow()`），最小化不算；
- 翻页/滚动时累加 `pages`。

### 3.3 指标（5 个卡片 + 热力图 + 两个排行）

| 指标 | 算法 |
|---|---|
| 累计阅读 | `SUM(seconds)` |
| 本周 / 本月 | 按 `started_at` 周/月过滤 |
| 连续阅读天数 | 按天去重，从今天往前数 |
| 日均 | 有阅读的天数做分母（不是自然日） |
| 读完本数 | `read_state='read'` 计数 + 平均天数 |
| 热力图 | 近 180 天，每格 = 当天秒数，四档色阶（<10/30/60/90 分钟） |
| 读得最多的书 | `SUM(seconds) GROUP BY book_id` Top 5 |
| 阅读时段分布 | 按 `strftime('%H', started_at)` 分 5 段 |

**导出**：统计页右上 `⋯` 里可导出 CSV（`日期, 书名, 时长, 页数`），便于自己算。

---

## 4. 笔记与高亮：一个模块，三种类型

现有 `bookmarks(kind, color, note, text, chapter, locator_json)` 已经够用，**不新建表**，只补两件事：

1. `kind` 固定为 `highlight / note / bookmark`；`note` 非空且 `kind='highlight'` 时 UI 显示为"高亮+想法"。
2. 列表项显示：书名 · 章节 · 进度、正文片段（高亮底色 = 该条颜色）、时间、颜色竖条。

页面结构（原型 ⑥）：左侧时间倒序列表 + 右侧「按书筛选 / 高亮颜色图例 / 导出」。
- 搜索框支持"在笔记中搜索"（只查 `text/note`）；
- 导出格式：Markdown（`## 书名 · 章节` + 引用块 + 想法）、CSV、以及"复制到剪贴板"；
- 点击一条 → 直接跳到书里对应位置（复用 `locator_json` 的 `openBookAt`）。

---

## 5. 喜爱 / 阅读状态（标星与已读）

- `books.favorite`：书架卡片右上角实心星，点击即切换，**不需要进详情**；
- `books.read_state`：`unread / reading / read`，三处可见——书架卡片左上角小标、列表"状态"列、详情面板；
- 自动规则（可关）：打开书 → `reading`；`percent >= 98` 且停留 5 分钟 → 提示"标记为已读？"（**不静默改**）；
- 筛选条支持：`仅喜爱 / 在读 / 已读 / 未读 / 有笔记`。

---

## 6. 主题：三层，不是一个开关

| 层 | 影响范围 | 取值 |
|---|---|---|
| **界面主题** | 顶栏、菜单、左导航、列表、对话框、设置页 | 跟随系统 / 白天 / 夜间 × 4 主色（琥珀/蓝/绿/砖红） |
| **书库主题** | 书架背景、卡片阴影、分组条 | 米黄 / 灰 / 草绿 / 粉樱 / 天空 / 日落 / 夜间（8 套） |
| **阅读主题** | 纸面、字色、底栏、设置浮层 | 与书库主题同源，但**纸面色单独可调**（阅读时可微调亮度/色温） |

实现要点：
1. `theme_tokens.py` 输出三组 palette：`ui_palette`、`shelf_palette`、`reader_palette`（reader 已存在）；
2. **同一个"夜间"开关要同时切三层**，但允许"界面夜间 + 阅读米黄"这种组合（很多人喜欢）；
3. 跟随系统用 `QGuiApplication.styleHints().colorScheme()`（Qt 6.5+ 有信号），不需要定时轮询。

### 6.1 背景图（Readest 有，加上）

- 设置 → 书库 → 「书架背景图」：导入本地图片（jpg/png/webp），存 `%APPDATA%\BookShelf\assets\shelf_bg.<ext>`；
- 两个滑块：`模糊 0–40px`、`不透明度 0–100%`（默认 40%，压一层纸色蒙版保证文字可读）；
- 卡片本身不透明，避免"背景图透到书名上"；
- 可选：给每张封面加统一的 1px 描边 + 12% 阴影，让它在背景图上仍然立得住；
- 夜间主题下背景图自动降亮度 30%。

---

## 7. 高亮颜色与阅读辅助

### 7.1 高亮五色 + 自定义

默认：`黄 #f2c14e / 红 #d99c98 / 绿 #9cc39a / 蓝 #8fb3d9 / 紫 #b6a4d9`。

- 选中文本 → 浮动条（现有 `#selectionBar`）里 5 个色点 + "写想法"；
- 设置 → 笔记与高亮：每个色可点开取色器改（存 prefs `highlight_colors`）；
- 渲染层通过 `addAnnotation({value, color})` 传色，样式用 `background: color-mix(in srgb, color 35%, transparent)`，**不要写死 `#ffe08a`**（现在代码里默认色就是它）。

### 7.2 阅读尺 / 遮罩

- **阅读尺（reading ruler）**：一条 28px 高的半透明横条，跟随鼠标 Y 坐标，`pointer-events:none`，用 CSS `mix-blend-mode: multiply`，颜色取主题 ink 的 8%；
- **阅读遮罩**：纸面上下各 40px 的线性渐变（`transparent → paper`），缓解"看到边缘就出戏"；
- 两者都在设置里独立开关，默认遮罩开、阅读尺关。

### 7.3 页眉时间与进度

- 阅读页顶栏右侧显示 `22:53`（当前时间）+ `16/318`；底栏显示"本章剩余 18 分钟 / 8 页"；
- 设置里可关（`show_clock` / `show_remaining`），全屏时默认开。

---

## 8. 阅读模式：滚动 / 分页 / 自动翻页

| 能力 | 实现 |
|---|---|
| **分页**（默认） | 现有 paginator，`max-column-count` 控制单双栏 |
| **滚动** | foliate 的 `flow: scrolled`：`host.renderer.setAttribute('flow','scrolled')`；需关掉 `max-column-count`，改用 `#viewer{overflow:auto}` + `scroll-snap-type:y proximity`；滚动进度用 `scrollTop/scrollHeight` 回写 `percent` |
| 点击左右翻页 | 已有 `handleTap`，滚动态下改成"滚一屏"（`scrollBy({top: clientHeight*0.9, behavior:'smooth'})`） |
| 禁用双击 | prefs `disable_double_click`；开启后双击不再触发"放大/选中" |
| 自动翻页 | `QTimer` 在 JS 里更好：`setInterval` 按 `prefs.auto_turn_sec`（10–120s）调 `turn('next')`；滚动态调 `scrollBy`；鼠标移动/按键时暂停 30s |
| 翻页动画 | 已有五档（instant / push / slide / curl / flip），设置里做成 5 个小图标 + 文字 |
| 快捷键 | 现有表已够（→ ← Space J K Shift+J Ctrl+B Ctrl+F Ctrl+= / Ctrl+- F11），**加可改绑定**：设置 → 快捷键 → 点一下按钮再按键，存 `prefs.keymap` |

---

## 9. 设置页结构（照 Readest 排）

左侧 8 个分组（原型 ⑦），右侧两列卡片：

| 分组 | 卡片 |
|---|---|
| 外观 | 界面主题（模式/主色/标题栏同色）· 书库主题（8 套/背景图/模糊/不透明度） |
| 书库 | 视图默认（列表/卡片/书架/墙）· 列数 · 默认分组 · 默认排序 · 缩略缓存上限 |
| 阅读 | 排版（分页/滚动）· 点击翻页 · 禁用双击 · 自动翻页与间隔 · 翻页动画 · 双栏阈值 |
| 笔记与高亮 | 五色自定义 · 阅读尺 · 阅读遮罩 · 页眉时间/进度 |
| 快捷键 | 表格 + 可改绑定 + 恢复默认 |
| 整理与命名 | 目录模板 / 文件模板 / 冲突策略 / 复制或移动 |
| 识别与网络 | 元数据源开关（豆瓣/孔夫子/Crossref）· 每日上限 · 超时 · 缓存 TTL |
| 关于 | 版本 / 许可（GPL-3.0）/ 数据目录 / 检查更新（手动） |

统一控件规格（别再用零散 QSS）：
- 行高 38，label 12.5px `--muted`，值右对齐；
- 开关：38×20 圆角 10，开启 accent；
- 分段：24px 高、3px 内边距、选中项白底细阴影；
- Stepper：26×26 圆角 7，中间值 13px 等宽；
- 卡片：`radius 11 / border 1px / padding 14-16 / 标题 11px 字距 .08em`。

---

## 10. 落地任务（T1–T9）

| # | 内容 | 落点 | 工作量 |
|---|---|---|---|
| T1 | schema v5：`reading_sessions` + `books.favorite/read_state` + 迁移脚本 | `db/schema.sql`、`db/migrate.py` | 0.5d |
| T2 | 会话采集（进出阅读页、60s flush、仅前台） | `bridge.py`、`reader_container.py`、新 `stats_service.py` | 0.5d |
| T3 | 书架视图：网格 + 列数（自动/4/5/6/8）+ 分组标题条 | `library_page.py`、新 `shelf_view.py` | 1.5d |
| T4 | 排序 12 维 + 升降序 + 中文拼音 | `book_repo.py`（SQL 排序键）、`pinyin` 依赖 | 0.5d |
| T5 | 阅读统计页（5 卡 + 热力图 + 两排行 + CSV 导出） | 新 `pages/stats_page.py` | 1d |
| T6 | 笔记页（列表 + 筛选 + 颜色 + 导出 MD/CSV） | 新 `pages/notes_page.py` | 1d |
| T7 | 设置页重构（8 分组 + 卡片 + 统一控件） | `dialogs/settings_dialog.py` 重写 | 1.5d |
| T8 | 三层主题 + 背景图 + 高亮自定义色 | `theme_tokens.py`、`theme.py` | 1d |
| T9 | 滚动模式 + 自动翻页 + 阅读尺/遮罩 + 快捷键可改 | `reader.js`、`reader_container.py` | 1.5d |

合计 **9 人天**，建议顺序 T1→T2→T4→T3（先把数据打通再上界面），T7/T8 并行，T9 收尾。

### 验收

1. 1872 本切 6 列网格，滚动 60fps 级别（`QListView` 不重建）；
2. 排序 12 项全可点，中文作者按拼音有序，升降序状态持久化；
3. 读 10 分钟后统计页数字变化，热力图当天格子变色；导出 CSV 行数与阅读天数一致；
4. 笔记页 284 条可搜索、可跳转、可导出 Markdown（格式可直接粘进飞书）；
5. 8 套书库主题 + 3 档界面模式任意组合，**不出现白色块**；背景图开启后书名仍清晰；
6. 滚动/分页切换后进度不回跳；自动翻页 30s 稳定；阅读尺遮挡位置正确；
7. 快捷键改绑定后重启仍生效。

---

**版本**：v2 · 2026-11-26
