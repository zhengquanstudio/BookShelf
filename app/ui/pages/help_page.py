"""M7 使用说明页：工作流、快捷键与数据位置。"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ... import config

_HELP_HTML = """
<h2>书库助手使用说明</h2>
<p>书库助手负责扫描、识别、整理和阅读本地电子书。所有操作先写数据库，只有执行整理时才会复制或移动书籍文件。</p>

<h3>1. 初次使用</h3>
<ol>
  <li>点击工具栏「选择书库」，指定整理后的归档根目录。</li>
  <li>点击「扫描新书」，添加一个或多个源目录（只读）。</li>
  <li>扫描完成后，在「待整理」中检查元数据，必要时右键编辑。</li>
</ol>

<h3>2. 扫描与识别</h3>
<ul>
  <li>扫描会读取 EPUB / PDF / MOBI / AZW3 的内嵌元数据，不会修改原文件。</li>
  <li>识别失败或需要确认的书会进入「识别失败」或「待整理」。</li>
  <li>工具栏「识别元数据」可对当前书联网检索并校正作者、书名、ISBN。</li>
</ul>

<h3>3. 整理与撤销</h3>
<ul>
  <li>「预览整理」先计算目标路径，确认无误后再执行。</li>
  <li>默认使用复制模式，原文件保留；移动模式仅在复制校验成功后删除源文件。</li>
  <li>「撤销上次整理」只删除该次整理新建的文件，不影响原有文件。</li>
</ul>

<h3>4. 分类与查找</h3>
<ul>
  <li>左侧「作者目录」「套书系列」用于维护作者、系列与卷号。</li>
  <li>「文件夹视图」按实际目录展示层级与数量，双击目录即可筛选。</li>
  <li>「标签」支持筛选、重命名、合并与删除；「收藏」是内置标签。</li>
  <li>顶部搜索框可搜索书名、作者与 ISBN，格式下拉框可限定格式。</li>
</ul>

<h3>5. 阅读</h3>
<ul>
  <li>双击书籍会在独立的阅读窗口中打开，可在设置中改为用外部程序打开。</li>
  <li>阅读器支持目录跳转、字号与主题调整，并记住阅读位置；关闭阅读窗口即保存进度。</li>
  <li>载入失败或超时会显示错误页，可用系统默认程序打开或点“重试”。</li>
</ul>

<h3>6. 右键批量操作</h3>
<p>在书籍列表中勾选或选中多本后右键，可批量加入收藏、编辑标签、分配作者/系列、归档或从书库移除（不删除文件）。</p>

<h3>7. 数据与备份</h3>
<ul>
  <li>数据库：{db_path}</li>
  <li>缓存目录：{cache_dir}</li>
  <li>日志目录：{log_dir}</li>
  <li>「工具 → 数据库备份」会生成一致性副本到数据目录下的 backups 文件夹。</li>
  <li>「工具 → 清理缓存」只清理转换缓存与检索缓存，封面缩略图会保留。</li>
</ul>

<h3>8. 快捷键</h3>
<ul>
  <li>Ctrl+N：扫描新书</li>
  <li>Ctrl+Return：在新窗口阅读当前书</li>
  <li>Ctrl+Q：退出</li>
</ul>
"""


class HelpPage(QWidget):
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HelpPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        back_button = QPushButton("返回书库")
        back_button.setObjectName("GhostButton")
        back_button.clicked.connect(lambda: self.back_requested.emit())
        toolbar.addWidget(back_button)
        for text, directory in (
            ("打开数据目录", config.DATA_DIR),
            ("打开日志目录", config.LOG_DIR),
        ):
            button = QPushButton(text)
            button.setObjectName("GhostButton")
            button.clicked.connect(
                lambda _=False, path=directory: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(path))
                )
            )
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        version = QLabel(f"{config.APP_NAME_CN} {config.APP_VERSION}")
        version.setObjectName("DetailSub")
        toolbar.addWidget(version)
        layout.addLayout(toolbar)

        browser = QTextBrowser()
        browser.setObjectName("HelpBrowser")
        browser.setOpenExternalLinks(True)
        browser.setHtml(
            _HELP_HTML.format(
                db_path=config.DB_PATH,
                cache_dir=config.CACHE_DIR,
                log_dir=config.LOG_DIR,
            )
        )
        layout.addWidget(browser, 1)


__all__ = ["HelpPage"]
