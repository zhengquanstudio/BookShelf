"""T8：安装器脚本关键配置断言（不依赖 Qt）。"""

from __future__ import annotations

from pathlib import Path

_ISSU = Path(__file__).resolve().parents[1] / "installer" / "BookShelf.iss"


def _sections(text: str) -> set[str]:
    sections: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            sections.add(stripped.lower())
    return sections


def test_iss_installs_to_program_files_and_requires_admin() -> None:
    text = _ISSU.read_text(encoding="utf-8")
    low = text.lower()

    # 默认安装到 C:\Program Files\BookShelf。
    assert "defaultdirname={autopf}\\bookshelf" in low
    # 需要管理员权限写入 Program Files。
    assert "privilegesrequired=admin" in low
    assert "privilegesrequired=lowest" not in low


def test_iss_has_run_section() -> None:
    text = _ISSU.read_text(encoding="utf-8")
    sections = _sections(text)
    assert "[run]" in sections

    # [Run] 段里有一条安装后启动主程序的条目。
    run_lines = [
        line for line in text.splitlines()
        if line.strip().lower().startswith("filename:") and "bookshelf.exe" in line.lower()
    ]
    assert run_lines, "未找到启动 BookShelf.exe 的 [Run] 条目"
    run_line = run_lines[0].lower()
    assert "postinstall" in run_line
    assert "skipifsilent" in run_line


def test_iss_prompts_legacy_dir_without_auto_delete() -> None:
    text = _ISSU.read_text(encoding="utf-8")
    sections = _sections(text)
    # 迁移提示必须由 [Code] 实现，且不能出现在自动删除段里。
    assert "[code]" in sections
    # 旧目录在 [Code] 里由 {localappdata} + \Programs\BookShelf 拼接得到。
    assert "{localappdata}" in text.lower()
    assert "\\programs\\bookshelf" in text.lower()
    # 旧用户目录不会被 [InstallDelete] / [UninstallDelete] 自动删除。
    assert "name: \"{localappdata}" not in text.lower()
