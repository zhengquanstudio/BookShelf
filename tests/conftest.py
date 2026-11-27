"""测试夹具：每个用例独立临时数据库。"""

from __future__ import annotations

import pytest

from app.db.connection import Database
from app.db.migrate import init_database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    init_database(database)
    yield database
    database.close()


@pytest.fixture()
def qt_settings(tmp_path):
    """主窗口界面状态使用独立 INI，避免测试读写真实用户配置。"""
    from PySide6.QtCore import QSettings

    return QSettings(str(tmp_path / "window-state.ini"), QSettings.IniFormat)
