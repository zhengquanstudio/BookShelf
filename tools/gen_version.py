"""从 app.config.APP_VERSION 生成 EXE 与 Inno Setup 的版本信息。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import APP_VERSION  # noqa: E402


def version_parts(version: str) -> tuple[int, int, int, int]:
    """把三位或四位数字版本转换为 Windows 四段版本号。"""
    parts = version.split(".")
    if len(parts) not in (3, 4) or any(not part.isdigit() for part in parts):
        raise ValueError(f"APP_VERSION 必须是三位或四位数字版本号：{version!r}")
    numbers = tuple(int(part) for part in parts)
    if any(number > 65535 for number in numbers):
        raise ValueError(f"APP_VERSION 每段必须在 0–65535 之间：{version!r}")
    padded = (numbers + (0,))[:4]
    return padded  # type: ignore[return-value]


def version_info_text(version: str) -> str:
    """生成可由 PyInstaller version 参数读取的 Python 源码。"""
    parts = version_parts(version)
    version_quad = ".".join(str(part) for part in parts)
    return f'''# -*- coding: utf-8 -*-
# 此文件由 tools/gen_version.py 生成，请勿手工修改。
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers={parts!r},
        prodvers={parts!r},
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable(
                "080404B0",
                [
                    StringStruct("CompanyName", "BookShelf contributors"),
                    StringStruct("FileDescription", "书格 BookShelf"),
                    StringStruct("FileVersion", "{version_quad}"),
                    StringStruct("InternalName", "BookShelf"),
                    StringStruct("LegalCopyright", "Copyright (C) 2026 BookShelf contributors"),
                    StringStruct("OriginalFilename", "BookShelf.exe"),
                    StringStruct("ProductName", "书格 BookShelf"),
                    StringStruct("ProductVersion", "{version_quad}"),
                ],
            )
        ]),
        VarFileInfo([VarStruct("Translation", [2052, 1200])]),
    ],
)
'''


def generate(version: str, version_path: Path, inno_path: Path) -> None:
    """写入 PyInstaller 与 Inno 共用的版本文件。"""
    parts = version_parts(version)
    version_quad = ".".join(str(part) for part in parts)
    version_path.write_text(version_info_text(version), encoding="utf-8")
    inno_path.parent.mkdir(parents=True, exist_ok=True)
    inno_path.write_text(
        "; 此文件由 tools/gen_version.py 生成，请勿手工修改。\n"
        f'#define AppVersion "{version}"\n'
        f'#define AppVersionQuad "{version_quad}"\n',
        encoding="utf-8",
    )


def main() -> int:
    generate(APP_VERSION, ROOT / "version_info.txt", ROOT / "installer" / "version.iss")
    print(f"已生成 BookShelf {APP_VERSION} 的 EXE 与安装器版本信息。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

