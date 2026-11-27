# BookShelf 整合开发与整改总纲 v5

> **v5 的来源**：AI 编程代理（TRAE）拉了真实代码复核 v4，指出"首版范围过大、一批待办其实已完成、两处验收口径自相矛盾"。
> 本版据此**重排范围与工期**：首版从 24.5–38.5 人日压到 **8–11 人日**，并把每个任务拆到"改哪个文件第几行、改成什么、怎么验"的粒度。
>
> **v5 三条主线**
> 1. **先收敛**：删掉重复开发（已实现的能力不再重做），首版只做"正确性 + 必要体验 + 能装"。
> 2. **再拆细**：R0–R4 共 22 个任务，每个都给文件、函数、伪代码、单测、验收命令。
> 3. **后立专项**：阅读内核（foliate-js）独立立项，先做等价性验证，不与首版捆绑。

---

## 目录

1. 本次修订依据（AI 复核采纳表）
2. 现状复核（逐条改口径）
3. 定位与边界
4. 借鉴策略（只借什么，不借什么）
5. 许可决策（ADR-001 保留，附说明）
6. **任务分解 R0–R4（核心章）**
7. 逐日推进表
8. 首版明确不做
9. 验收口径（含两处改写）
10. 阅读内核专项（R5，独立）
11. 后续版本路线（v2.1 / v2.2 / v3.0）
12. 打包与安装（详细步骤）
13. 工程规范与 CI
14. 给 AI 的任务级提示词
15. 变更记录

---

## 1. 本次修订依据（AI 复核采纳表）

| AI 复核意见 | 处理 | 说明 |
|---|---|---|
| P0-4 命名模板预览已存在（`settings_dialog.py:665` 调 `plan_target`） | ✅ 采纳 | 删掉"新建模板 DSL"，改为"补卷号/国别等缺失格式" |
| 阅读器目录/书签/高亮/搜索/主题/进度已存在（`reader_container.py`） | ✅ 采纳 | S3 换内核移出首版，另立 R5 专项 |
| P0-3 候选对比已存在（`edit_book_dialog.py`） | ✅ 采纳 | 只补"逐字段勾选"，不重做对话框 |
| B5 图标已完成 | ✅ 采纳 | 删待办，只留发布验收 |
| B16 清缓存确认已完成 | ✅ 采纳 | 删待办 |
| B9 作者合并已有实现 | ✅ 采纳 | 不计工作量，需要时只改菜单绑定 |
| C4 含点书名 | ⚠️ 部分采纳 | 实读 `naming.py:343` **确有** `stem.split(".")[0]`，会截断；按"小修 + 回归测试"处理 |
| C5 目录保留名 | ⚠️ 部分采纳 | `_safe_segment()` 已用于作者/系列，但路径其他段仍需覆盖；补测试为主 |
| B2 卷号形式已支持不少 | ✅ 采纳 | 只补失败样例（Unicode 罗马数字、"卷一"） |
| B1 表格已虚拟化 | ✅ 采纳 | 只改查询分页（`book_repo` 已支持 page/page_size） |
| S0–S5 压缩为 R0–R4（8–11 人日） | ✅ 采纳 | 见第 6、7 章 |
| B8 最小尺寸与"改回 960×640"冲突 | ✅ 采纳 | **首版保留 1180×880，只补窗口记忆**；小屏自适应另立 R6 |
| "断网识别 ≥70%"不成立 | ✅ 采纳 | 改为分场景口径，见第 9 章 |
| 首版不做自动更新/回滚/三视图/虚拟书库/OPDS/WebDAV/插件/TTS | ✅ 采纳 | 见第 8 章"明确不做" |
| foliate-js 库 API 不稳定、PDF 适配实验性 | ✅ 采纳 | 见第 10 章前置条件 |

---

## 2. 现状复核（逐条改口径）

以下为**实读源码后**的结论，v4 里与之不符的待办一律作废。

| 编号 | v4 的说法 | 实际代码 | 真实待办 |
|---|---|---|---|
| A1 | 中文作者被强加国别 | `naming.py:43` `chinese_author_no_country: bool = True`，默认已生效 | **已实现，仅需回归验证**；若用户 settings 里存了 False 则尊重用户值 |
| A2 | 重复导入覆盖 title、清空作者/ISBN | `scan_service.py:57-70` `fields` 里 `"title": candidate.path.stem`，且 `books.update(book_id, **fields)` 直接覆盖 | **真 bug，必修** |
| A3 | 默认 `series_first` 与需求相反 | `naming.py:45` `hierarchy: str = "series_first"` | **真待办，改默认 + 迁移策略** |
| A4 | 默认模板无 `{卷号}` | `naming.py:42` `"{作者} [{国家}] - {书名}.{扩展名}"`；`_file_name` 已有空卷号剥离逻辑 | **只改默认字符串 + 测试** |
| B1 | 查询硬限 1000 无分页 | `library_service.py:37` `limit: int = 1000`；`book_repo.py:200` 已支持 `LIMIT ? OFFSET ?`，`count()` 已存在 | **只需把 page/page_size 透出到 UI** |
| B2 | 只认 ASCII 罗马数字 | 已支持多种中文卷号写法 | **补 Unicode 罗马数字与"卷一"失败样例** |
| B5 | 无图标 | spec 已加 icon，`main.py` 已设 AppUserModelID | **已完成，重打包即可** |
| B8 | 最小 1180×880 越界 | `main_window.py:90` `setMinimumSize(1180, 880)` | **不改尺寸**，只补 `saveGeometry`/`restoreGeometry` |
| B9 | 菜单假入口 | 作者页已有合并实现，菜单负责跳转 | **降级，不计工作量** |
| B16 | 清缓存无确认 | 已有二次确认 + 文件数 + 释放空间 | **已完成** |
| C4 | `split` 截断含点书名 | `naming.py:343` `stem = stem.split(".")[0]` 仍在 | **真 bug，小修** |
| C5 | 保留名未处理目录段 | `_safe_segment` 已覆盖作者/系列段 | **补覆盖 + 测试** |
| P0-4 | 需新建模板引擎 | `settings_dialog.py:665` 已调 `plan_target` 实时预览 | **已完成 90%** |
| S3 | 需换 foliate-js | `reader_container.py` 已有 TOC/书签/高亮/搜索/主题/进度/错误页 | **移出首版** |

---

## 3. 定位与边界

**一句话**：Windows 桌面端的「电子书自动归档 + 内嵌阅读」工具——把散乱下载的文件按「作者 / 系列 / 卷号」整理成书库，双击即在软件内阅读。

**做**：本地优先、离线可用、复制不删原件、双击/右键即读、国内网络可用。

**不做**：不破 DRM；不做 mac/移动/Web；不上传书籍；不嵌外部 exe；不做强制联网。

---

## 4. 借鉴策略（v5 收敛版）

> 原则：**首版只借"规则"，不借"代码"，不借"架构"。**

### 4.1 Calibre（第一参考，只借规则）

| 借 | 具体是什么 | 用在哪 |
|---|---|---|
| ✅ Windows 路径净化与超长路径处理规则 | 保留名清单、非法字符、255 字节上限、逐段净化 | `app/core/pathsafe.py`（R1-9） |
| ✅ 重复元数据的合并策略 | 字段级"非空优先 + 来源优先级" | `scan_service._record_duplicate`（R1-1） |
| ✅ 元数据字段映射与测试样例 | 书名/作者/系列/卷号/ISBN 的映射约定 | `metadata_service` 的 fixture（R4） |

**首版不做**：完整模板语言、查询 DSL、自研转换管线、插件系统、OPDS、一次性建四个源。
格式转换等确有需求，再用官方 `ebook-convert` CLI **进程隔离调用**，不嵌入 Calibre 环境。

### 4.2 Readest / foliate-js（移出首版，独立专项）

理由（据其官方说明）：库 API 尚不稳定；PDF 适配仍属实验性；高层 reader 需自行修改或替换；搜索/标注/排版仍需与现有桥接和持久化整合。而且 Readest 本身是 AGPL + 另一套技术栈，成熟体验不等于可直接获得。
→ 见第 10 章，作为 R5 专项，先验证 EPUB/PDF/MOBI/AZW3 与现有功能的**等价性**。

### 4.3 Koodo Reader（只借交互）

首版只借三件：
1. 空书库三步引导的写法；
2. 设置项分组与说明文案的组织方式；
3. 扫描前把"只读取目录 / 默认复制归档"讲清楚。

封面墙、三视图、WebDAV、笔记导出 → 后续版本。

---

## 5. 许可决策（ADR-001 保留）

**决定**：BookShelf 用 `GPL-3.0-or-later`，全量开源。

**v5 补充说明**：首版并不搬任何 GPL 代码，"抄规则 + 自己重写"不构成衍生作品，所以首版其实**不依赖 GPL**。之所以仍提前锁定 GPL-3，是为了避免将来真要整段移植 Calibre 模块时再做一次不可逆的许可切换。

合规清单（发版前勾）：
- [ ] `LICENSE`（GPL-3 全文）、`NOTICE`、`docs/UPSTREAM.md`
- [ ] 若日后移植 Calibre 文件：文件头保留原版权 + 追加 "Ported into BookShelf"
- [ ] "关于"页：源码链接
- [ ] 安装包带 `licenses\` 目录

> 注意：**不要**在 LICENSE 里加"禁止商用"——GPL 不允许附加限制。想表态写在 README（社区声明，非许可条款）。

---

## 6. 任务分解 R0–R4

> 约定：每个任务都是"能独立提交、能独立验收"的最小单元。
> 验收统一用：`cd E:\BookShelf; .\.venv\Scripts\python.exe -m pytest -q`

### R0 基线（0.5 人日）

#### R0-1 建失败样例集（0.25d）
- **做什么**：在 `tests\fixtures\` 下建固定样例，后续每个修复都用它们验收：
  - `书名.含.点.epub`（测 C4）
  - `XX 全集 第Ⅰ卷.epub`、`某书 卷一.pdf`（测 B2）
  - 三份内容相同但文件名不同的 epub（测 A2 顺序无关性）
  - 一份"作者=中文、国家=法国"的元数据样例（测 A1 回归）
- **验收**：`pytest tests/test_fixtures_meta.py -q` 能枚举出上述文件。

#### R0-2 清场与建仓（0.25d）
- 把 `_audit\`、`_run_err.txt`、`_run_out.txt` 移到 `_archive\`（**不删除**，AI 复核明确要求"不自动删除备份或真实书库文件"）；
- `git init` + `.gitignore`（`.venv/ dist/ build/ *.db _audit/ _archive/`）；
- `docs\` 放 v5 总纲 + 前序 + LICENSE + NOTICE + UPSTREAM.md；
- 记录基线：用例数、冷启耗时、峰值内存（写进 `docs\BASELINE.md`）。

### R1 正确性（3–4 人日）

#### R1-1 修 A2：去重不再覆盖元数据（1d）★核心
- **文件**：`app\services\scan_service.py`（`_record_duplicate`，45–75 行）、`app\db\repositories\book_repo.py`
- **改法**：
  1. 删掉 `fields` 里的 `"title": candidate.path.stem`；
  2. 新增 `books.merge_meta(book_id, incoming: dict)`：仅当目标字段为空/`meta_source` 优先级更低时才写入；
  3. 优先级常量：`manual(3) > metadata(2) > filename(1) > embedded(0)`；
  4. 标题冲突时取"信息量更大"者：含副标题 > 长度更长 > 非纯数字；
  5. 记录 `dup_of=book_id`，`dup_group_id` 保持现有逻辑；
  6. 结果与扫描顺序无关：合并只依赖优先级，不依赖先后。
- **伪代码**：
```python
def merge_meta(self, book_id: int, incoming: dict, source_rank: int) -> None:
    row = self.get(book_id)
    for key, value in incoming.items():
        if value in (None, "", 0):
            continue
        current = row.get(key)
        current_rank = SOURCE_RANK.get(row.get("meta_source") or "", 0)
        if current in (None, "") or source_rank > current_rank:
            self.update(book_id, **{key: value})
        elif key == "title" and _richness(value) > _richness(current):
            self.update(book_id, title=value)
```
- **单测**：`tests\test_dedup_merge.py`
  - `test_duplicate_keeps_existing_author`
  - `test_duplicate_keeps_isbn`
  - `test_order_independent`（正反两序扫描结果一致）
  - `test_manual_source_wins`
- **验收**：`pytest tests/test_dedup_merge.py -q` 全绿；手工用三份同内容文件跑两次扫描，库内 title/author 不一致次数为 0。

#### R1-2 修 A3：默认层级改 author_first（0.5d）
- **文件**：`app\core\naming.py:45`；`app\services\settings_service.py`（若有默认写入）
- **改法**：`hierarchy: str = "author_first"`；`from_dict` 的 fallback 同步改为 `"author_first"`。
- **迁移策略**：**不改用户已有 settings 的值**——老用户保持其原设置，只有新装/重置才拿到新默认。在设置页加一行说明"当前层级：作者优先 / 系列优先（老库不变）"。
- **单测**：`test_default_hierarchy_is_author_first`、`test_existing_settings_not_overwritten`
- **验收**：新库归档结果形如 `作者\系列\第1卷 书名.epub`；老库行为不变。

#### R1-3 修 A4：默认模板带卷号（0.25d）
- **文件**：`app\core\naming.py:42`
- **改法**：默认改 `"{作者} - {卷号} {书名}.{扩展名}"`；空卷号剥离已有逻辑（316–319 行）覆盖 `" {卷号}"`，确认分隔符也一起省。
- **单测**：`test_volume_in_default_template`、`test_empty_volume_no_dangling_separator`
- **验收**：`第1卷 三个火枪手.epub`；无卷号时为 `三个火枪手.epub`（无多余空格/横杠）。

#### R1-4 修 C4：含点书名被截断（0.25d）
- **文件**：`app\core\naming.py:343`
- **改法**：`stem = stem.split(".")[0]` → 保留完整 stem；仅在最终超长时按字节截断（复用 `_fit_path`）。
- **单测**：`test_dotted_title_preserved`（`书名.含.点` 完整保留）、`test_dotted_title_still_length_limited`
- **验收**：fixture `书名.含.点.epub` 归档后文件名完整。

#### R1-5 补 B2：卷号识别（0.5d）
- **文件**：`app\core\series.py`
- **改法**：卷号匹配加入：
  - Unicode 罗马数字 `Ⅰ Ⅱ Ⅲ Ⅳ Ⅴ Ⅵ Ⅶ Ⅷ Ⅸ Ⅹ Ⅺ Ⅻ` → 阿拉伯；
  - `卷一` / `第卷一` / `卷1` / `Vol.1` / `Volume 1`；
  - 全角数字 `１`–`９`；
- 统一归一成 `第N卷`（沿用 `volume_style`）。
- **单测**：参数化 ≥12 例（`test_volume_forms.py`）
- **验收**：`第Ⅰ卷`→`第1卷`；`卷一`→`第1卷`；误判率：`卷一`不把"卷一"当系列名。

#### R1-6 补 B3：系列名归一（0.5d）
- **文件**：`app\core\series.py`
- **改法**：归一化流水线：去副标题括号内容 → 去尾缀 `全集|套装|合集|文集|丛书` → 去多余空白/全角空格 → 小写折叠比较。
- **单测**：`《XX全集》《XX 套装》《XX（新译）》` 归为同一系列。
- **验收**：3 种写法在书库中合并到同一 series_id。

#### R1-7 修 B10：长路径显示（0.5d）
- **文件**：`app\ui\widgets\book_table.py`（或表格 delegate）
- **改法**：显示用 `QFontMetrics.elidedText(path, Qt.ElideMiddle, width)`，鼠标悬停 tooltip 显示完整路径；列宽自适应按"目录层级 + 卷号 + 扩展名"优先保留。
- **验收**：1180 宽窗口下能看出"作者/系列"两级，且能看到扩展名与卷号。

#### R1-8 修 B11：撤销误删空目录（0.5d）
- **文件**：`app\services\organize_service.py`（`execute`/`undo`/`_prune_empty_dirs`）
- **改法**：`execute` 记录 `created_dirs`（本次真正新建的目录）；`undo` 只对 `created_dirs` 内的路径做空目录清理，且只向上清理到任务根为止。
- **单测**：`test_undo_keeps_preexisting_empty_dir`
- **验收**：先手动建一个空目录 → 归档 → 撤销 → 该空目录仍在。

#### R1-9 C 类收尾 + pathsafe 补测（0.5–1d）
- **C1**：`failed` 行增加"原因"列，值取 `task_log.message`；
- **C2/C3**：文案统一为"复制入库 / 仅登记路径"，跳过原因逐条对齐真实条件；
- **C5**：新增 `app\core\pathsafe.py`（先只做 `sanitize_segment()`），`naming._safe_segment` 委托给它；补测保留名 `CON/PRN/AUX/NUL/COM1…`、尾点尾空格、255 字节超长。
- **验收**：`pytest tests/test_pathsafe.py -q` 全绿。

### R2 必要体验（2–3 人日）

#### R2-1 B1 查询分页（0.5d）
- **文件**：`app\services\library_service.py:30-51`、`app\ui\pages\library_page.py`、`app\ui\models\book_table_model.py`
- **改法**：`query_books(page=1, page_size=200, **filters)`；返回 `(rows, total)` 已有；表格改"滚动到底加载下一页 / 加载更多按钮"，并用 `total` 显示"共 N 本"。
- **验收**：造 1200 条测试数据，首屏加载 < 300ms，滚动可全部到达。

#### R2-2 B8 窗口记忆（0.5d）
- **文件**：`app\ui\main_window.py`（90 行处、`closeEvent` 1047）
- **改法**：`QSettings("BookShelf","BookShelf")` 存 `geometry`、`windowState`、`splitter` 位置；启动 `restoreGeometry` 后 `clamp_to_screen()`（按 `availableGeometry` 校正，防拔掉副屏后越界）。
- **不改**：`setMinimumSize(1180, 880)` **保持原样**（AI 复核：改小必返工）。
- **验收**：移动/最大化 → 退出 → 重开位置一致；在 1366×768 上仍可拖动（窗口超出可滚动，不崩）。

#### R2-3 B15 备份保留策略（0.5d）
- **文件**：`app\services\maintenance_service.py`、`app\ui\dialogs\backup_dialog.py`（新增或改造）
- **改法**：
  - `create_backup()` 返回 `(path, size)`；
  - 保留策略：按数量保留 N 份（默认 5，可配），超出删除最旧；
  - **恢复前自动再备份** `pre-restore-<ts>.db`；
  - UI 列表：时间 / 大小 / 路径（可复制）/ 操作（恢复、删除、打开所在目录）。
- **验收**：连续备份 8 次 → 只剩 5 份 + 最近一次恢复前的自动备份；恢复后数据与备份一致。

#### R2-4 B17 真实加载状态（0.5d）
- **文件**：`app\ui\pages\reader_container.py`（`open_book` 434 起）、`app\reader\converter.py`
- **改法**：打开流程拆阶段并发信号：`探测格式 → 转换(如需) → 载入 HTML → 渲染完成`；遮罩上显示阶段文案与百分比；>10s 提示"转换中，可稍候"；失败显示原因 + "用系统默认程序打开"按钮（即原 B14 的按钮改造为**兜底**，不再叫"外部 Readest"）。
- **验收**：打开 80MB PDF 能看到阶段变化；损坏文件给出可读错误而非白屏。

#### R2-5 B18 空书库引导（0.25d）
- **文件**：`app\ui\pages\library_page.py`
- **改法**：空态三块：① 说明"BookShelf 会按作者/系列/卷号归档"；② 主按钮"选择文件夹扫描"；③ 次链接"先看看示例书库"。文案参考 Koodo 的空态（借交互，不搬代码）。
- **验收**：新库启动即见引导，点主按钮直接进扫描对话框。

#### R2-6 B13 复核（0.25d，可选）
- 标签/设置仍是模态弹窗。**首版只做一件事**：设置对话框改为非模态（`show()` 而非 `exec()`），避免阻塞主窗；右侧面板化留到 v2.2。

### R3 基础分发（2–3 人日）

#### R3-1 onedir + 版本信息（1d）
- **文件**：`BookShelf.spec`、新增 `version_info.txt`、`tools\gen_version.py`
- **改法**：
```python
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='BookShelf',
          console=False, icon='app/ui/resources/app.ico', version='version_info.txt')
coll = COLLECT(exe, a.binaries, a.datas, name='BookShelf')
```
- `gen_version.py` 从 `app/core/constants.py` 读 `APP_VERSION` 生成 VSVersionInfo（**版本号单一来源，安装器不得另写死 2.0.0.0**）。
- **验收**：`dist\BookShelf\BookShelf.exe` 属性页显示版本；冷启 < 2s；任务管理器只有一个进程。

#### R3-2 Inno Setup 基础版（1–1.5d）
- **文件**：新增 `installer\BookShelf.iss`
- **必含指令**：
```ini
AppId={{8F3C2A11-5B7D-4E9A-9C21-BOOKSHELF0001}}
DefaultDirName={localappdata}\Programs\BookShelf
PrivilegesRequired=lowest
UsePreviousAppDir=yes
CloseApplications=yes
SetupIconFile=..\app\ui\resources\app.ico
UninstallDisplayIcon={app}\BookShelf.exe
LicenseFile=..\LICENSE
OutputBaseFilename=BookShelf-Setup-{#AppVersion}
```
- 图标：桌面 + 开始菜单；可选任务：右键菜单（把 `tools\register-shell.ps1` 的逻辑搬成 `[Registry]` 段）。
- 卸载**保留** `%APPDATA%\BookShelf`，末页提示数据位置。
- **验收**：`dist` 与 `installer` 双目录产出安装包，双击可装。

#### R3-3 覆盖安装验证（0.5d）
十步清单（写进 `docs\INSTALL-CHECKLIST.md`）：
1. 全新机安装 → 自选目录生效；
2. 桌面/开始菜单图标正确；
3. 双击 `.epub` 打开（单实例转发）；
4. 建库、扫描 20 本；
5. 关闭程序；
6. 直接跑 v2 安装包（同一目录）→ 不提示"已安装"而是**升级**；
7. 安装目录未变（沿用上次选的）；
8. 书库数据、设置、阅读进度全部在；
9. 卸载 → 程序目录清空、`%APPDATA%\BookShelf` 保留；
10. 重装 → 数据自动识别。

#### R3-4 一键构建脚本（0.5d）
`tools\build.ps1`：清理 `build/` → `pyinstaller BookShelf.spec --noconfirm` → `iscc installer\BookShelf.iss` → 产物归到 `release\` → 计算 sha256 写 `release\checksums.txt`。

### R4 可选增强（2–4 人日，可不阻塞发布）

#### R4-1 单一国内源接入（2–4d）
- **前置技术验证（0.5d）**：对候选源（国家版本数据中心 PDC / 豆瓣 / 京东）各写 20 行探针，测可达性、字段完整度、是否有反爬。**只要有一个稳定可用就接**。
- **文件**：`app\net\sources\base.py`（新增抽象）、`app\net\sources\pdc.py`、`app\services\metadata_service.py:74-94`（源装配）
- **接口设计**（照 Calibre `Source` 的思路，自己实现）：
```python
class Source(Protocol):
    name: str
    priority: int
    touched_fields: frozenset[str]
    def identify(self, query: Query) -> list[Candidate]: ...
    def fetch_cover(self, candidate: Candidate) -> bytes | None: ...
```
- **降级**：源异常 → 记 `task_log`，continue；全失败 → 进"待确认"状态，不覆盖已有元数据。
- **测试**：固定 fixture（把一次真实响应存 json），断网也能跑解析测试。
- **验收**：国内网络下，30 本固定样本识别成功数 ≥ 15（即 50%，比 v4 的 70% 更现实）；断网时无异常、不覆盖。

---

## 7. 逐日推进表（单人全职）

| 天 | 任务 | 产出 |
|---|---|---|
| D1 上午 | R0-1 / R0-2 | fixtures、干净仓库、BASELINE.md |
| D1 下午 – D2 | R1-1（A2 去重合并） | `merge_meta` + 4 个单测 |
| D3 | R1-2 / R1-3 / R1-4 | 默认层级、默认模板、点号修复 |
| D4 | R1-5 / R1-6 | 卷号识别 + 系列归一 |
| D5 | R1-7 / R1-8 / R1-9 | 路径显示、撤销、C 类 + pathsafe |
| **D5 末** | **里程碑 1** | **onefile 正确性修正版可交付** |
| D6 | R2-1 / R2-2 | 分页、窗口记忆 |
| D7 | R2-3 / R2-4 / R2-5 | 备份策略、加载状态、空态引导 |
| D8 | R3-1 | onedir + 版本信息，冷启达标 |
| D9 | R3-2 | 安装包可装、可选目录 |
| D10 | R3-3 / R3-4 | 覆盖安装 10 步通过、一键构建 |
| **D10 末** | **里程碑 2** | **首个可安装版本 v1.1.0** |
| D11–D14 | R4-1 | 国内源（不阻塞发布；失败则延期） |

**R0–R3 合计 8–11 人日**；R4 另计 2–4 人日，可选。

---

## 8. 首版明确不做（写进 README 与给 AI 的约束）

- ❌ 自动更新 / 回滚菜单
- ❌ 三视图 / 封面墙 / 虚拟书库 / 查询 DSL
- ❌ 完整模板语言
- ❌ OPDS / WebDAV / 插件系统
- ❌ TTS / 划词翻译 / 笔记导出
- ❌ 阅读内核替换（foliate-js）→ 见第 10 章独立立项
- ❌ 格式转换（`ebook-convert`）→ v2.1
- ❌ 小屏（<1180×880）自适应布局 → R6

---

## 9. 验收口径（两处改写）

### 9.1 B8 改写
- **原文（作废）**：最小尺寸改 960×640。
- **新口径**：首版**保留** `setMinimumSize(1180, 880)`（当前详情栏布局按此设计，硬改小必返工）；只验收"窗口位置/大小/分隔条记忆 + 多屏拔插不越界"。小屏适配作为 R6 独立任务，需先出布局方案（折叠详情栏）。

### 9.2 网络识别改写
- **原文（作废）**："断网也能靠国内源识别 ≥70%"——断网时无网络源可查，除非命中缓存，逻辑不成立。
- **新口径（三场景）**：
  1. **国内网络可达**：固定 30 本样本集，识别成功 ≥ 15 本（50%），且字段错误（作者/书名张冠李戴）为 0；
  2. **断网**：本地文件名解析不报错、不覆盖已有元数据、界面提示"当前离线，使用本地信息"；
  3. **源异常**：统一进"待确认"状态，可在元数据对话框里手动确认，不静默写库。

### 9.3 全局 DoD
`pytest -q` 全绿 + 该任务单测存在 + 手工步骤通过 + CHANGELOG 有该条 + 无新增空壳入口。

---

## 10. 阅读内核专项 R5（独立立项，不绑首版）

### 10.1 为什么单独做
foliate-js 官方明确：API 尚不稳定、PDF 适配实验性、高层 reader 需自行修改。直接替换会与现有桥接（`bridge.py`）、持久化（`reading_state`/`bookmarks`）冲突，风险高且收益已部分被现有实现覆盖。

### 10.2 前置：等价性基线（1–2d，先做这个）
对现有阅读器录 12 项基线（EPUB×3、PDF×3、MOBI×2、AZW3×2、含图/含表/含 CJK 竖排各一）：
`打开耗时 / 目录层级正确 / 搜索命中数 / 书签持久化 / 高亮持久化 / 字号行距生效 / 主题切换 / 进度恢复精度 / 翻页方向键 / 复制文本 / 图片渲染 / 崩溃率`。

### 10.3 决策门
只有当 foliate-js 在 12 项里 **≥10 项持平或更好**，且 API 版本可锁定（vendor 固定 commit + 保留 LICENSE），才进入替换；否则**维持现有内核**，改做增量增强（双页模式、排版面板）。

### 10.4 若替换，实施顺序
1. vendor 到 `app/reader/assets/vendor/foliate-js/`，锁 commit；
2. `bridge.py` 重写为 QWebChannel 协议（`openBook/goTo/search/addAnnotation/setTheme/setLayout/setFont`）；
3. 三模式（单页/双页/连续）+ 按书记忆；
4. 现有 bookmarks/highlights 表结构做**适配层**，不迁移数据，双写一版；
5. 灰度：设置项"使用新内核（实验）"，默认关。

---

## 11. 后续版本路线

| 版本 | 内容 | 预估 |
|---|---|---|
| **v1.1.0（首版）** | R0–R3：正确性 + 必要体验 + 可安装 | 8–11d |
| v1.2.0 | R4 国内源 + C 类收尾 + 安装包自检 | 2–4d |
| v1.3.0 | 格式转换（`ebook-convert` CLI 进程隔离）+ 批量任务队列与进度 | 3–5d |
| v1.4.0 | 双页模式 / 排版面板 / 阅读统计（不动内核） | 3–5d |
| v2.0.0 | 阅读内核专项（R5）决策与落地 | 5–8d |
| v2.1.0 | 三视图 / 封面墙 / 虚拟书库（查询 DSL 简版） | 4–6d |
| v2.2.0 | 标签右侧面板 / 笔记导出 MD / 设置页重构 | 3–5d |
| v2.3.0 | WebDAV 备份 / OPDS 只读服务 | 4–6d |
| v3.0.0 | 插件框架（元数据源/导出器入口点）+ TTS + 划词翻译 | 8–12d |

每个版本只上一个主题，不混装。

---

## 12. 打包与安装（详细步骤）

### 12.1 一次性准备
```powershell
# 1) 生成 version_info
.\.venv\Scripts\python.exe tools\gen_version.py
# 2) 打包（onedir）
.\.venv\Scripts\pyinstaller.exe BookShelf.spec --noconfirm --clean
# 3) 生成安装包
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\BookShelf.iss
# 4) 校验
Get-FileHash release\BookShelf-Setup-*.exe -Algorithm SHA256
```

### 12.2 关键点
- `AppId` GUID **永不修改**（覆盖安装的唯一标识）；
- `PrivilegesRequired=lowest` + `{localappdata}` 才能免 UAC，为将来静默更新留口；
- 程序装 `{app}`，数据永远在 `%APPDATA%\BookShelf`；
- 卸载保留数据；
- 版本号从 `constants.py` 流入 `version_info.txt` 与 `.iss`，**单点定义**。

### 12.3 自动更新（v1.3.0 再做）
`update.json`（version/url/sha256/notes）→ 延迟 10s 检查 → 下载到 `%LOCALAPPDATA%\BookShelf\updates` → 校验 → `/SILENT /CLOSEAPPLICATIONS /NORESTART`。首版不做。

---

## 13. 工程规范与 CI

```
E:\BookShelf
├── main.py
├── app/{core,db,services,net,reader,ui}/…
├── installer/BookShelf.iss
├── tools/{build.ps1,gen_version.py,register-shell.ps1,make_icon.py}
├── tests/{fixtures/,test_dedup_merge.py,test_pathsafe.py,test_volume_forms.py,…}
├── docs/{v5 总纲,LICENSE,NOTICE,UPSTREAM.md,BASELINE.md,INSTALL-CHECKLIST.md}
├── BookShelf.spec
└── version_info.txt
```

CI 三条硬检查（本地脚本亦可）：
1. `grep -r "PyQt6" app/` 必须为空；
2. `grep -r "import PySide6" app/core app/services app/net` 必须为空；
3. `pytest -q` 全绿。

---

## 14. 给 AI 的任务级提示词

**通用前置（每任务都贴）**

```
项目：BookShelf（E:\BookShelf），Python 3.11 + PySide6 6.7.3 + SQLite，Windows 桌面。
许可 GPL-3.0-or-later。禁止 import PyQt6；core/services/net 禁止 import PySide6；
不破 DRM、不上传书籍；只改本任务涉及的文件；改动前后 pytest -q 必须全绿。
先读 docs/BookShelf-整合开发与整改总纲-v5.md 的第 6 章对应任务，再动手。
完成时输出：改了哪些文件、每处改动的前后行为、新增测试名、手工验收步骤。
```

**R0-1**
```
建 tests/fixtures/：书名.含.点.epub、XX 全集 第Ⅰ卷.epub、某书 卷一.pdf、
三份同内容不同名的 epub、中文作者+法国国籍的元数据 json。
再写 tests/test_fixtures_meta.py 能枚举并断言这些文件存在与可解析。
```

**R1-1（最重要）**
```
修 app/services/scan_service.py 的 _record_duplicate（45–75 行）：
1) 删除 fields 中的 "title": candidate.path.stem；
2) 在 book_repo 新增 merge_meta(book_id, incoming, source_rank)，按
   手填(3)>元数据(2)>文件名(1)>内嵌(0) 只升级不降级，空值跳过；
3) 标题冲突取"含副标题优先、其次更长"；
4) 记录 dup_of；
5) 保证扫描顺序不影响结果。
补 4 个单测：保持作者、保持 isbn、顺序无关、手填优先。
```

**R1-2 ~ R1-6**
```
按总纲 6 章逐条改：naming.py 默认 hierarchy→author_first（不动老用户的已存设置）；
默认 file_template 加 {卷号} 且空值省分隔符；修 naming.py:343 的 stem.split(".")[0]；
series.py 补 Unicode 罗马数字 / 卷一 / Vol.N；系列名归一去 全集|套装|合集|文集|丛书。
每条配 2–3 个单测。
```

**R2 四件**
```
R2-1 library_service.query_books 支持 page/page_size，UI 滚动加载 + total 显示；
R2-2 main_window 存/恢复 geometry/windowState，最小尺寸保持 1180×880 不变，加 clamp_to_screen；
R2-3 maintenance_service 备份保留 N 份、恢复前自动再备份、UI 列表含路径与大小；
R2-4 reader_container 打开流程分阶段信号（探测→转换→载入→完成）+ 遮罩进度 + 失败兜底。
```

**R3 打包**
```
1) spec 改 onedir + version='version_info.txt'；tools/gen_version.py 从 constants.py 读 APP_VERSION；
2) installer/BookShelf.iss 用固定 AppId、PrivilegesRequired=lowest、{localappdata} 目录、
   UsePreviousAppDir=yes、CloseApplications=yes、LicenseFile=..\LICENSE、桌面/开始菜单/可选右键菜单、
   卸载保留 %APPDATA%；
3) tools/build.ps1 一键 build→iscc→release+sha256；
4) 写 docs/INSTALL-CHECKLIST.md 的 10 步并逐条验证。
```

---

## 15. 变更记录

| 版本 | 变化 |
|---|---|
| **v5** | 采纳 AI 代码复核：删 10 项已完成待办；首版压缩为 R0–R4（8–11 人日）；22 个任务拆到文件/行级；改写 B8 与网络识别两处口径；阅读内核移出首版立项 R5；补齐逐日推进表与任务级提示词 |
| v4 | 许可改 GPL-3 全量开源；选 Calibre 为最大借鉴源；Calibre 移植手册（同栈不可 import）；S4 重定义 |
| v3 | 三份前序合并；借鉴总表；S0–S6；Inno Setup + 更新机制 |
| v2 | 运行验收 + 23 项探针 + Readest 四路线 + 国内源 + B12–B18 |
| v1 | 首轮审计 A/B/C 分级、20 项缺陷 |
