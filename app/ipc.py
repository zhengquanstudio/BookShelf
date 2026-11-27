"""单实例转发：第二个进程把命令行里的文件路径交给已运行的实例。

QLocalSocket 在 Windows 上走命名管道，无需额外依赖；服务器端收到路径后
直接交给主窗口打开，避免"已在运行，请勿重复启动"把用户挡在门外。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "BookShelf-IPC-open"
_TIMEOUT_MS = 800


def notify_existing(files: list[str]) -> bool:
    """尝试把文件路径转发给已运行实例；成功返回 True。"""
    if not files:
        return False
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(_TIMEOUT_MS):
        socket.abort()
        return False
    payload = json.dumps({"files": files}, ensure_ascii=False).encode("utf-8")
    socket.write(payload)
    socket.flush()
    deadline = time.monotonic() + _TIMEOUT_MS / 1000.0
    while socket.bytesToWrite() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    sent = socket.bytesToWrite() == 0
    socket.disconnectFromServer()
    return sent


def start_server(on_files: Callable[[list[str]], None]) -> QLocalServer:
    """启动接收端；必须在 QApplication 创建之后调用。"""
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    def _on_new_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def _read() -> None:
            raw = bytes(conn.readAll()).decode("utf-8", "ignore")
            try:
                data = json.loads(raw) if raw else {}
            except ValueError:
                data = {}
            files = [str(item) for item in (data.get("files") or []) if item]
            if files:
                on_files(files)

        conn.readyRead.connect(_read)
        conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(_on_new_connection)
    return server
