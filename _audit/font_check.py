"""F5 字体自检：在 QWebEngine 里加载 reader.html，逐个断言 8 个内置字体可用。

用法：.venv\\Scripts\\python.exe _audit\\font_check.py
任一字体加载失败即 exit 1；打包前应全绿，防止再次出现“假内嵌”。
离屏（offscreen）运行，不弹窗。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import QApplication

# QtWebEngine 要求在 QApplication 之前共享 OpenGL 上下文。
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.reader import READER_HTML  # noqa: E402

FAMILIES = [
    "LXGW WenKai",
    "Source Han Serif CN",
    "LXGW Heart Serif CHS",
    "Noto Sans SC",
    "Literata",
    "Source Serif 4",
    "EB Garamond",
    "Inter",
]


def main() -> int:
    app = QApplication([])
    view = QWebEngineView()
    result: dict = {}

    def on_loaded(ok: bool) -> None:
        if not ok:
            print("reader.html 加载失败")
            app.exit(2)
            return
        # 同步触发所有字体加载（document.fonts.load 返回 Promise，不在此等待），
        # 延迟后统一读取结果，避免 runJavaScript 拿不到 Promise 返回值。
        trigger = (
            "(function(){var fs=" + json.dumps(FAMILIES) + ";window.__ferr={};"
            "for (var i=0;i<fs.length;i++){(function(f){try{"
            "document.fonts.load('19px \"'+f+'\"').catch(function(e){window.__ferr[f]=String(e);});"
            "}catch(e){window.__ferr[f]=String(e);}})(fs[i]);}"
            "return 'loading';})()"
        )
        view.page().runJavaScript(trigger)
        QTimer.singleShot(4000, read_result)

    def read_result() -> None:
        script = (
            "(function(){var fs=" + json.dumps(FAMILIES) + ";"
            "var checks=fs.map(function(f){return {family:f, ok:document.fonts.check('19px \"'+f+'\"')};});"
            "var loaded=[];document.fonts.forEach(function(ff){loaded.push(ff.family+' ['+ff.status+']');});"
            "return JSON.stringify({checks:checks, loaded:loaded, errors:window.__ferr||{}});})()"
        )
        view.page().runJavaScript(script, 0, on_result)

    def on_result(payload) -> None:
        try:
            result.update(json.loads(payload))
        except Exception:
            print("无法解析字体检查结果：", payload)
            app.exit(2)
            return
        app.exit(0)

    view.loadFinished.connect(on_loaded)
    view.load(QUrl.fromLocalFile(str(READER_HTML)))
    QTimer.singleShot(60000, lambda: app.exit(3))  # 60s 兜底，防字体加载卡死
    code = app.exec()

    print("document.fonts 已注册：")
    for line in result.get("loaded") or []:
        print("   ", line)
    checks = result.get("checks") or []
    for item in checks:
        print(("  OK   " if item.get("ok") else "  FAIL ") + item["family"])
    for fam, err in (result.get("errors") or {}).items():
        print("  错误详情", fam, "->", err)

    failed = [c["family"] for c in checks if not c.get("ok")]
    if code != 0 or len(checks) != len(FAMILIES) or failed:
        print(f"字体自检失败：exit={code}，未通过：{', '.join(failed) or '（结果不完整）'}")
        return 1
    print("字体自检通过：8/8 内置字体可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
