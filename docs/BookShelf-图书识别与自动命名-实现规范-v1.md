# BookShelf 图书识别与自动命名 · 实现规范 v1

> **用法**：整份交给编码 AI，按 §7 的 N1→N7 执行，一步一提交。
> **前置**：本文件是"施工图"，§1 解释别人怎么做的（为什么要这么设计），§2–§5 是模型，§6 是对照差距，§7 是可直接粘的指令。
> **配套**：`docs/BookShelf-阅读界面重构规范-v1.md` §10（元数据源实测矩阵）；`docs/UPSTREAM.md`（复用边界）。

---

## 0. 硬约束

1. 技术栈不动：Python 3.11 + PySide6 + requests + rapidfuzz + pypdf。**不引入 ebooklib / PyMuPDF / pdfplumber**（AGPL）。
2. 网络请求**只走 `app/net/client.py`** 的 `HttpClient`：它已有按源限速（默认 2s）、每日上限、3 次重试。新源不许自己 new `requests`。
3. 识别与改名**必须是两件事**：识别只写数据库字段，改名只动文件系统。任何一步失败都不能让另一件事半途而废。
4. 任何自动匹配都必须能解释：UI 上要显示"凭什么给了 92 分"（ISBN 一致 / 书名相似 96 / 作者一致 / 同年）。
5. 不改 `books` 表已有列语义；新增列/表只通过 `app/db/migrate.py` 迁移。

---

## 1. 别的软件到底怎么做的

**先说结论：没有一个软件是靠"看图认书"的。** 它们全都走同一条链——**先找标识符（ISBN/DOI），标识符没有就退到"书名+作者"模糊比对，最后靠多源交叉验证**。封面只用来给人看，最多做一次次要校验。

### 1.1 Calibre（这套体系的原型，最值得学）

Calibre 把这件事拆成四层，职责非常清楚：

| 层 | 做什么 | 关键实现 |
|---|---|---|
| L1 读取 | 从文件里抠元数据 | `ebook-meta`：EPUB 读 OPF（dc:title/creator/identifier/publisher/date/series），MOBI/AZW3 读 EXTH（100 作者 / 101 出版社 / 104 ISBN / 106 出版日 / 503 标题），PDF 读 Info 字典 + XMP |
| L2 检索 | 多源并发查 | 插件基类 `MetadataSourcePlugin`，统一接口 **`identify(isbn=None, title=None, authors=None)`**，返回 `Metadata` 对象列表 + `source_relevance`（该源的可信度权重） |
| L3 合并 | 多个结果选一个 | 内置 `similar()` / `compare_identifiers()` 比对；按"标识符一致 > 标题相似 > 作者相似"排序；用户可以逐字段选择（Merge 规则：`title` 用 A 的、`publisher` 用 B 的） |
| L4 命名 | 按模板改文件名 | `save_to_disk_template` / 设备模板；库内固定 `作者/书名 (id)/`，命名与识别解耦，改名失败不影响库里数据 |

插件生态就是靠 L2 那一个 `identify()` 签名长起来的：英文有 Amazon/Google/OpenLibrary，中文有第三方 `fugary/calibre-douban`（1,386★，Apache-2.0，**抓 `book.douban.com` 网页**，无 API key），以及它的服务版 `fugary/calibre-web-douban-api`（464★），calibre-web 就是调这个 API 拿豆瓣数据的。

**可借鉴的三点**：
1. **接口按"字段"而不是"查询串"设计**（`isbn/title/authors` 三个入参分开），源自己决定用哪个；我们现在只有 `by_isbn(str)` / `search(str)`，信息在拼串时就已经丢了。
2. **每个源给一个可信度权重**，排序时先比权重再比分。
3. **命名模板与识别彻底分离**，且库内路径带 id 兜底重名。

### 1.2 Zotero（PDF 识别做得最狠的）

Zotero 的 "Retrieve metadata for PDF" 是另一条路，专治"PDF 什么元数据都没有"：

1. 抽 **PDF 正文前几页的文本**，正则找 **DOI / ISBN / arXiv id**（DOI 带校验位、ISBN 带校验位，找到就基本锁定）。
2. 用标识符查 **Crossref / arXiv**（不是查电商），拿到结构化 `title/author/publisher/issued/type`。
3. 拿到候选后**必须回比**：候选标题与 PDF 里出现的标题做相似度，低于阈值就判"未识别"，不硬塞。
4. 附件重命名用模板（`{{firstCreator}} {{year}} - {{title}}`），失败就保留原名。

开源里这套算法最干净的参考是 **`pdf2doi`（MIT）**：正则 + 校验位 + Crossref 查证 + 置信度分级，非常适合我们照结构实现（代码自己写）。

### 1.3 Readest / Koodo Reader / KOReader（都不联网）

- **Readest**：只读 EPUB OPF 的 `dc:*` 与封面，没有在线补元数据。
- **Koodo Reader**：靠 epub.js 读 OPF，书名/作者可在界面手改。
- **KOReader**：`bookinfo` 面板读 EPUB/MOBI/CBZ 内嵌信息，联网只用于 OPDS 下载，不做识别。

**所以"识别"这件事，在你现在这套代码里是要自己补的，没有现成软件可以直接对标。**

### 1.4 一句话总结

> 识别 = **标识符优先 + 多源交叉 + 打分否决 + 保守阈值**；改名 = **模板渲染 + 冲突去重 + 可撤销**。
> 中文书的关键在豆瓣（网页抓取）；外文/学术的关键在 Crossref；两头都不占的（扫描版、无 ISBN 的旧书）只能靠文件名 + 人工确认。

---

## 2. 四层漏斗（BookShelf 的目标模型）

| 层 | 输入 | 产出 | 置信度上限 | 何时用 |
|---|---|---|---|---|
| **L0 文件名解析** | `某作者 - 某书名 (2019).epub` | title/author/series/year 猜测 | 40 | 永远先做，成本为零 |
| **L1 内嵌元数据** | OPF / EXTH / PDF Info+XMP | 全字段，可能含 ISBN | 95（有 ISBN）/ 70（无 ISBN） | 永远第二做 |
| **L2 内容指纹** | PDF 前 3 页文本 / EPUB 封面 / 页数 | ISBN / DOI / 标题候选 | 90（ISBN 校验通过） | L1 缺 ISBN 时 |
| **L3 联网多源** | 上面所有线索 | 候选列表 + 分数 | 100（ISBN 一致） | 前两层仍不全时 |

每层的产出都写进同一个 `evidence` 字典，最后统一打分：

```json
{
  "title_raw": "红楼梦", "title_clean": "红楼梦",
  "authors_raw": ["(清)曹雪芹"], "authors_clean": ["曹雪芹"],
  "isbn": "9787020002207", "isbn_valid": true,
  "publisher": "人民文学出版社", "year": "1982",
  "series": "", "series_index": "",
  "source": "embedded|filename|pdf_text", "confidence": 95,
  "evidence": ["opf:dc:identifier", "isbn:checksum_ok"]
}
```

**规则：字段级合并，不做整条覆盖。** L1 已有且合法的字段，L3 不许覆盖；只有空字段才让 L3 填（Calibre 的 Merge 规则就是这个意思）。

---

## 3. 判定"是不是同一本书"（核心规则）

### 3.1 硬否决（这条比加分重要）

| 情况 | 处理 |
|---|---|
| 书有 ISBN，候选 ISBN **不同且都合法** | **直接丢弃该候选**（不是扣分，是丢弃）。现在的代码只做到"不加 45 分"，于是靠书名+作者+出版社还能凑到 70 分，这就是串书的主因 |
| 候选 ISBN 非法（校验位不过） | 丢弃 |
| 书有 ISBN，候选**没有** ISBN，但书名相似度 < 85 | 丢弃（防止同名不同书） |

### 3.2 打分表（在现有 `app/net/scoring.py` 上改，不要重写）

| 维度 | 分 | 说明 |
|---|---|---|
| ISBN 完全一致 | **55** | 提高到"一票即定"级别 |
| 书名（去卷号/去副标题/NFKC/去标点后 `token_set_ratio`） | 0–25 | `25 × ratio/100` |
| 作者任一命中 | 8；姓氏+首字命中 | 6 | 译名/笔名走 `core/authors.normalize_author` |
| 出版社一致 | 5 | |
| 年份差 0 / ±1 | 5 / 2 | 重印年容忍 |
| 语言一致 | 2 | |
| **源权重** | douban +3 / kongfz +2 / crossref +2 / 其它 0 | 替换现有"openlibrary 优先"的 tie-break（那个源已经不可用了） |

**阈值（沿用现有配置 `confidence_auto=85` / `confidence_confirm=60`）**：
- ≥85 → 自动采用，状态 `recognized`
- 60–84 → 状态 `need_confirm`，进待确认队列，**绝不自动改名**
- <60 → 丢弃，状态保持 `failed`，只用内嵌/文件名

### 3.3 中文书专属规则（不写这些会一直认错）

1. **卷/册**：`strip_volume()` 已经会去掉"第N卷/册/部"，比较时用它；但**写回书名时要把卷号保留**（`series_index` 单独存）。
2. **丛书 vs 书名**：`红楼梦（脂评汇校本）` 与 `红楼梦` 是不同版本，括号里的"汇校本/大字本/插图本"要**作为版别参与比较**（相似度会自然降一点，正好落到 60–84 区间让人确认）。
3. **译名**：`(清)曹雪芹` → `曹雪芹`；`[美] 某某` → `某某`；已有 `authors.normalize_author`，比较前必须过一遍。
4. **繁简**：可选做 `opencc`（Apache-2.0）转换后比较，不做也不影响主流程。
5. **同名不同书**（如《活着》有小说也有剧本）：仅靠书名永远分不清，必须靠 ISBN 或作者，**没有就进待确认**。

---

## 4. 各格式怎么抽（现状 + 缺口）

| 格式 | 现有实现 | 已能拿到 | 缺口 |
|---|---|---|---|
| **EPUB** | `app/core/metadata/epubs.py` | dc:title/subtitle/creator/identifier(ISBN)/publisher/date/language/series + 封面 | ①`calibre:` 自定义字段未读；②`dc:identifier` 里 `urn:isbn:` 之外的形式（如 `ISBN:978...`）要再兜一层；③多作者分隔符（`;`、`、`、`&`）未规范化 |
| **PDF** | `app/core/metadata/pdfs.py` | Info 字典、前 3 页文本抽 ISBN、无文本层标 `scanned` | ①**没有抽 DOI**；②标题猜测取"第一行 2–80 字"，中文排版下常拿到页眉/出版社名 → 应优先用 **PDF 书签第一层标题**，其次才第一行；③加密文档直接放弃（可接受） |
| **MOBI / AZW3** | `app/core/metadata/mobis.py` | EXTH 的 title/author/publisher/isbn/date | ①EXTH 缺失时未回退到 PDB name；②`azw3` 若实际是 KF8 双段，要读第二段的 EXTH |
| **扫描版 PDF** | — | 只能标 `scanned` | **不做 OCR**（体积与准确率都不划算）；改为：文件名 + 封面 pHash 比对（见 N5，可选） |
| **TXT / 无元数据** | — | 文件名 | 只做 L0，识别后进待确认 |

---

## 5. 重命名引擎

### 5.1 模板（现有 `app/core/naming.py`，扩展即可）

| 变量 | 含义 | 备注 |
|---|---|---|
| `{作者}` | 第一作者（规范化后） | 多作者默认只取第一，`{作者全}` 取全部 |
| `{书名}` | 书名（**保留版别括号**） | 已清洗非法字符 |
| `{卷号}` | `series_index` | 无则整段消失（现有逻辑已支持） |
| `{丛书}` | series | 新增 |
| `{年份}` | 4 位年 | 新增 |
| `{出版社}` | publisher | 新增 |
| `{ISBN}` | 13 位 | 新增 |
| `{扩展名}` | 原扩展名（小写） | 已有 |

默认建议（改成这个，比现在的更可读）：
- 目录：`{作者} [{国家}]`（保持）
- 文件：`{作者} - {书名}{卷号?} ({年份}).{扩展名}`，其中卷号段为 ` 第N卷`

### 5.2 清洗与冲突

- 非法字符：`\/:*?"<>|` → 全角或下划线（`pathsafe.py` 已有，直接复用）。
- 长度：单段 ≤ 120 字符，超长按词截断，不截断扩展名。
- 冲突：同名存在 → 追加 ` (2)`、` (3)`；**不覆盖**。
- 大小写：Windows 不敏感，去重时按 `casefold` 比较。

### 5.3 事务与回滚

现在 `organize_service` 已有批次 + `undo(batch)`（`main_window._undo_last_organize` 在用）。要求补两条：

1. **先写日志再动文件**：`operations` 里记录 `src/dst/book_id/at`，动文件失败则整批回滚。
2. **改名 ≠ 移动**：只改名时不允许跨目录；跨目录必须显式"整理"操作，避免误把书挪走。
3. 数据库 `file_path` 与文件系统**同事务**更新，失败一起回滚。

---

## 6. BookShelf 现状对照（差距表）

| 能力 | 现状 | 差距 | 对应指令 |
|---|---|---|---|
| ISBN 校验 | ✅ `core/isbn.py` 有 10/13 校验、全角、连字符 | 无 | — |
| 内嵌抽取 | ✅ EPUB/PDF/MOBI/AZW3 | 见 §4 缺口 | N5 |
| 多源检索 | ⚠️ 只有 OpenLibrary + Google（**国内全挂**） | 需豆瓣/孔夫子/Crossref | N2 N3 |
| 源接口 | ⚠️ `by_isbn(str)` / `search(str)`，字段被拼串丢失 | 改 `lookup(isbn,title,authors)` | N2 |
| 打分 | ⚠️ 45/30/15/10/5，**ISBN 冲突只不加分不否决**；tie-break 绑 `openlibrary` | 见 §3 | N4 |
| 阈值 | ✅ 85/60 已有 | 无 | — |
| 文件名解析 | ❌ 无 | 新写 | N5 |
| HTTP | ⚠️ 只有 `get_json`，UA 写死成 `BookShelf/x.y` | 需要 `get_text`/`get_bytes` + 可覆盖 UA/Referer + 跟随跳转 | N1 |
| 重命名 | ✅ 模板 + 冲突 + undo | 模板变量少；缺"只改名"模式 | N6 |
| 候选 UI | ✅ `preview_dialog` 有候选列表 | 缺"分数解释"与字段级勾选 | N7 |

---

## 7. 指令 N1–N7

### N1（0.25d）HTTP 客户端补三种取法
```
改 app/net/client.py，保持现有 get_json 行为不变：
1) get_text(url, *, source, params=None, headers=None, allow_redirects=True) -> str
   - 复用同一套限速/日上限/重试；
   - headers 合并到 session.headers 的临时副本，不污染全局；
   - 需要 HTML 的源（豆瓣/孔夫子）必须传 Referer。
2) get_bytes(url, *, source, headers=None) -> bytes（封面下载，同样走限速）。
3) UA 策略：默认仍 BookShelf/x.y；新增可选 ua="browser"，
   传浏览器 UA（Chrome 120 Windows），豆瓣类站必须用这个。
验收：3 个单元测试（假 session），限速间隔仍 ≥2s，日上限计数正确。
```

### N2（0.25d）Source 接口升级为字段式（向后兼容）
```
1) 新约定：源可以实现 lookup(isbn=None, title=None, authors=None) -> list[dict]；
   未实现的源继续用 by_isbn/search（service 里 try lookup → 回退老接口）。
2) metadata_service.find_candidates 改为传结构化字段（isbn/title/authors），
   不再拼成一个 query 串；缓存 key 改为 isbn:<v> 或 q:<归一化书名>|<首作者>。
3) 打分调用不变（rank_candidates 仍吃 book dict）。
验收：现有 openlibrary/googlebooks 测试不破；新增一个假源验证 lookup 优先被调用。
```

### N3（0.5d）豆瓣 + Crossref + 孔夫子三个源
```
app/net/douban.py：name="douban" label="豆瓣读书"
- lookup(isbn=...)：GET https://book.douban.com/isbn/{isbn}/，allow_redirects，
  UA=browser，Referer=https://book.douban.com/；
  解析最终页：<title> 去后缀、#mainpic img[src]、.info 里的
  作者/出版社/出版年/页数/定价/装帧/ISBN；
  **强制校验：页面 ISBN 归一化后必须等于请求 ISBN，不等返回 []**（假 ISBN 会乱跳）。
- lookup(title=..., authors=...)：GET /j/subject_suggest?q={title}（JSON，title/author_name/year/pic/id），
  取前 5，再逐个抓 /subject/{id}/（串行，客户端限速已保证 2s）。
- 不返回 description（详情页简介需二次展开，先不做）。
app/net/crossref.py：query.bibliographic={isbn或"title author"}&rows=3，
  映射 title/author/publisher/issued/ISBN；无封面。
app/net/kongfz.py：search.kongfz.com/product/?keyword={isbn或书名}，解析卡片；
  只填 title/author/publisher/date。
注册进 _build_sources()，settings: metadata.sources.douban=true、crossref=false、kongfz=false。
验收：用 3 本真书离线 fixture（HTML 存本地）跑解析，不联网；联调时手工跑一次真请求确认字段。
```

### N4（0.25d）打分改成"先否决后打分"
```
改 app/net/scoring.py：
1) 新增 reject_reason(candidate, book) -> str：ISBN 冲突/非法、书有 ISBN 候选无且书名<85 → 返回原因；
   score_candidate 开头调用，命中返回 0 且写入 candidate["rejected"]=reason。
2) 权重重排：ISBN 55 / 书名 25 / 作者 8|6 / 出版社 5 / 年份 5|2 / 语言 2 / 源权重（douban3 kongfz2 crossref2）。
3) rank_candidates：排序键改为 (score, source_weight, -index)，删掉 `source=="openlibrary"`。
4) 输出里加 "why": ["isbn:equal","title:96","author:hit","source:douban"]，UI 直接展示。
验收：构造 6 个用例——ISBN 冲突被丢弃、同名不同作者降级、缺 ISBN 靠书名+作者入选、openlibrary 不再优先、纯外文走 crossref、全空返回 0。
```

### N5（0.5d）文件名解析 + PDF 标题与 DOI
```
1) 新建 app/core/filename_meta.py：
   parse_name(stem) -> dict(title, authors, year, series, series_index)
   规则按优先级：
   a) 《书名》作者 / 《书名》(year)
   b) 作者 - 书名 (year) / 作者 - 书名 - 出版社
   c) [作者] 书名 / 【作者】书名
   d) 书名 (第N卷) / 书名 N（N 为纯数字且 ≤ 30 视作卷号）
   先剥离噪声：`(z-lib.org)`、`[PDF]`、`_OCR`、`v1.0`、`扫描版`、`epub`、重复分隔符；
   抽到 ISBN（复用 isbn.find_isbns）优先用。
2) app/core/metadata/pdfs.py 补：
   - 标题：先取 reader.outline 第一层第一个标题；没有再回退 _guess_title；
   - DOI：正则 `10\.\d{4,9}/[-._;()/:A-Za-z0-9]+`，配合 core/isbn 类似的校验（DOI 无校验位，靠 Crossref 回查）；
   - 输出新增 doi/page_count/scanned 已有。
3) scan 流程：L0 文件名 → L1 内嵌 → 合并（空字段才覆盖），落库。
验收：10 个畸形文件名用例全过；一本无元数据 PDF 能靠 outline 拿到正确书名。
```

### N6（0.25d）命名模板扩变量 + 只改名模式
```
1) naming.py 变量表加 {丛书}{年份}{出版社}{ISBN}{作者全}；默认模板改
   "{作者} - {书名}{卷号} ({年份}).{扩展名}"。
2) organize_service 新增 rename_only(book_ids)：只改文件名不跨目录，
   冲突追加 (2)/(3)，先写 operations 日志再动文件，失败整批回滚。
3) 设置界面加"只重命名 / 重命名并整理"两个入口。
验收：批量 20 本，改名后 file_path 全部存在且可打开；undo 能完整还原。
```

### N7（0.25d）候选 UI 讲清"为什么"
```
preview_dialog 每条候选显示：源徽标、score、why 列表（ISBN 一致/书名 96%/作者命中/同年）、
封面缩略图、字段级勾选（书名✓ 作者✓ 出版社☐ …），勾选结果直接映射到 apply_candidate 的字段。
need_confirm（60–84）的候选置顶并标黄，不允许"全选自动套用"。
验收：一本错配的书，用户能在 10 秒内看出"哪里不像"，并只勾选可信字段。
```

---

## 8. 验收（20 本样书）

| # | 类型 | 期望 |
|---|---|---|
| 1–3 | 中文 EPUB，OPF 完整、有 ISBN | 自动 recognized（≥85），书名/作者/出版社与原书一致 |
| 4–6 | 中文 EPUB，OPF 无 ISBN，文件名含书名 | 走 L2/L3，豆瓣命中，≥85 自动 |
| 7–8 | 中文 PDF，有 Info 元数据 | 自动，页码数正确 |
| 9–10 | 中文 PDF，无元数据但有书签 | 书名来自书签第一层，进 need_confirm（60–84） |
| 11–12 | 扫描版 PDF（无文本层） | 标 `scanned`，只用文件名，status=need_confirm，不自动改名 |
| 13 | 同名不同书（如《活着》小说/剧本） | 必须进 need_confirm，不许自动 |
| 14 | ISBN 故意错一位（校验位不过） | 不采用该 ISBN，改用书名+作者 |
| 15 | MOBI，EXTH 完整 | 自动，作者/出版社正确 |
| 16 | AZW3（KF8） | 同 15 |
| 17 | 文件名畸形：`[美]某某_书名(第2卷)_2019_扫描版.pdf` | 解析出作者/书名/卷号/年份，噪声被剥离 |
| 18 | 丛书第 3 卷 | series_index=3，文件名带" 第3卷" |
| 19 | 繁体竖排 EPUB | 内嵌优先，繁简不强制转换，识别成功 |
| 20 | 完全无信息 TXT | 仅文件名，need_confirm，不联网也可入库 |

**命令**：`python -m pytest tests -q`；`python -m pytest tests/test_scoring_veto.py tests/test_filename_meta.py -q`。
**人工**：20 本跑完导出一份 CSV（`file_path, title, author, publisher, year, isbn, score, source, status`），逐行核对。

---

## 9. 参考实现与许可

| 参考 | 许可 | 怎么用 |
|---|---|---|
| Calibre（`kovidgoyal/calibre`） | GPL-3.0 | 只读 `metadata/sources/`、`customize/builtins.py` 的 `identify()` 设计与 Merge 规则；**不可 import**（自带私有 Python/Qt） |
| `fugary/calibre-douban`（1,386★） | Apache-2.0 | 看它的豆瓣搜索页/详情页选择器与字段映射；代码自己写，便于豆瓣改版后单独修 |
| `fugary/calibre-web-douban-api`（464★） | Apache-2.0 | 结构最干净，适合对着搭 `app/net/douban.py` |
| `pdf2doi` | MIT | DOI/ISBN 抽取 + Crossref 回查的置信度分级思路 |
| `isbn/isbnlib` | MIT | 已安装；注意其内置 provider（openlibrary/google）在国内不可用，别启用 |

---

**版本**：v1 · 2026-11-26 · 适用 BookShelf 1.1.3
**依赖本文件的其他文档**：`BookShelf-阅读界面重构规范-v1.md`（§10 实测矩阵）、`UPSTREAM.md`（复用边界）
