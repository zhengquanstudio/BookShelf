"""书格 BookShelf 入口。

职责：单实例锁、日志、数据库初始化、主窗口。
"""

from __future__ import annotations

import ctypes
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app import config, ipc
from app.db.migrate import init_database
from app.errors import BookShelfError
from app.logger import get_logger, setup_logging
from app.ui.main_window import MainWindow

log = get_logger("main")

APP_ICON = Path(__file__).with_name("app") / "ui" / "resources" / "app.ico"
APP_USER_MODEL_ID = "BookShelf.Desktop"


def _apply_windows_identity(app: QApplication) -> None:
    """设置窗口图标与任务栏身份，避免显示 python 默认图标。"""
    if APP_ICON.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):  # 非 Windows 或调用失败时不影响启动
        log.debug("设置 AppUserModelID 失败，已忽略")


def _install_excepthook() -> None:
    """未捕获异常：写日志并提示，不静默退出。"""

    def handler(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.error("未捕获异常：\n%s", detail)
        QMessageBox.critical(
            None,
            f"{config.APP_NAME_CN} 发生错误",
            f"程序遇到未处理的错误，详情已写入日志：\n{config.LOG_PATH}\n\n{exc_value}",
        )

    sys.excepthook = handler


def _book_paths(argv: list[str]) -> list[str]:
    """从命令行里挑出可打开的电子书路径（资源管理器双击/右键会传进来）。"""
    result: list[str] = []
    for item in argv[1:]:
        path = Path(item)
        if path.suffix.lower() in config.SUPPORTED_EXTENSIONS and path.is_file():
            result.append(str(path))
    return result


def main() -> int:
    config.ensure_dirs()
    setup_logging()

    app = QApplication(sys.argv)
    # Qt 原生控件统一系统字体 9pt（≈12px）；内置可变字体只给 WebEngine 用，
    # 不注册给 Qt（Qt 对 variable font 的命名实例支持不完整，易注册成 Thin）。
    base_font = app.font()
    base_font.setPointSize(9)
    app.setFont(base_font)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationDisplayName(config.APP_NAME_CN)
    app.setOrganizationName(config.APP_NAME)
    _apply_windows_identity(app)

    files = _book_paths(sys.argv)

    # 单实例：第二个进程不再弹"已在运行"，而是把文件交给已有窗口打开。
    lock = QLockFile(str(config.DATA_DIR / "bookshelf.lock"))
    if not lock.tryLock(200):
        if files and ipc.notify_existing(files):
            log.info("已转交给运行中的实例：%s", files)
            return 0
        QMessageBox.warning(
            None, config.APP_NAME_CN, f"{config.APP_NAME_CN} 已在运行，请勿重复启动。"
        )
        return 1

    _install_excepthook()
    try:
        init_database()
    except BookShelfError as exc:
        log.error("数据库初始化失败：%s", exc)
        QMessageBox.critical(None, config.APP_NAME_CN, f"数据库初始化失败：\n{exc}")
        return 2

    window = MainWindow()
    window.show()
    server = ipc.start_server(window.open_paths)
    if files:
        window.open_paths(files)
    log.info("启动完成 version=%s data=%s", config.APP_VERSION, config.DATA_DIR)
    exit_code = app.exec()
    server.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
