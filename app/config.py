"""应用配置：数据目录、默认配置与读写。

DECISION: 未沿用文档示例里的 D:\\书库 / D:\\下载\\电子书 作为默认值，
因为本机不存在这两个目录；首次启动由用户在界面上选择，避免误建目录。
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

from .errors import ConfigError

APP_NAME = "BookShelf"
APP_NAME_CN = "书格"
APP_VERSION = "1.1.5"

SUPPORTED_EXTENSIONS = (".epub", ".pdf", ".mobi", ".azw3")


def _app_data_dir() -> Path:
    """返回用户数据目录。

    便携版（可执行文件同级存在 data 目录，或设置 BOOKSHELF_PORTABLE=1）
    把配置与数据库写在程序目录下，不做安装器写入。
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if os.environ.get("BOOKSHELF_PORTABLE") == "1" or (exe_dir / "data").is_dir():
            return exe_dir / "data"
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


DATA_DIR = _app_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
LOG_DIR = DATA_DIR / "logs"
LOG_PATH = LOG_DIR / "app.log"
DB_PATH = DATA_DIR / "library.db"
CACHE_DIR = DATA_DIR / "cache"
COVERS_DIR = CACHE_DIR / "covers"
CONVERTED_DIR = CACHE_DIR / "converted"


def default_creator_aliases() -> dict[str, dict[str, str]]:
    """原文姓名 -> 中文名/国别的用户别名表，默认空。"""
    return {}


DEFAULT_CONFIG: dict[str, Any] = {
    "library_root": "",
    "source_dirs": [],
    "formats": ["epub", "pdf", "mobi", "azw3"],
    "scan": {
        "recursive": True,
        "incremental": True,
        "ignore_hidden": True,
        "min_size_kb": 50,
        "workers": 4,
        "max_depth": 12,
    },
    "meta": {
        "read_embedded_first": True,
        "enable_network": True,
        "timeout_sec": 15,
        "retries": 3,
        "confidence_auto": 85,
        "confidence_confirm": 60,
    },
    "sources": {
        "douban": True,
        "crossref": False,
        "kongfz": False,
        "openlibrary": True,
        "googlebooks": True,
        "isbnlib": False,
        "rate_limit_ms": 2000,
        "daily_limit": 500,
        "cache_ttl_days": 30,
    },
    # 仅新装/重置使用以下默认值；load_config 深合并时保留老用户已存设置。
    "naming": {
        "author_dir_template": "{作者} [{国家}]",
        "file_template": "{作者} - {书名}{卷号} ({年份}).{扩展名}",
        "chinese_author_no_country": True,
        "country_style": "short",
        "hierarchy": "author_first",
        "volume_style": "第N卷",
        "series_subdir": False,
        "illegal_char_replacement": "_",
        "max_title_len": 120,
        "max_path_len": 250,
        "conflict_policy": "suffix",
        "creator_aliases": {},
    },
    "organize": {
        "action": "copy",
        "delete_empty_dirs": True,
        "keep_source_structure": False,
    },
    "naming_presets": {},
    "backup": {
        "retention": 5,
    },
    "reader": {
        "theme": "light",
        "mode": "auto",
        "font_family": "Noto Serif CJK SC",
        "font_size": 17,
        "line_height": 1.95,
        "font_weight": 400,
        "para_spacing": 0.75,
        "indent": True,
        "justify": True,
        "hyphens": False,
        "margin_top": 54,
        "margin_bottom": 54,
        "margin_left": 54,
        "margin_right": 54,
        "column_count": 1,
        "page_mode": "single",
        "page_width": 560,
        "fixed_page_width": True,
        "disable_double_click": False,
        "auto_turn_sec": 0,
        "reading_ruler": False,
        "mask_top": True,
        "show_clock": True,
        "show_remaining": True,
        "highlight_colors": ["#f2c14e", "#d99c98", "#9cc39a", "#8fb3d9", "#b6a4d9"],
        "turn_anim": "flip",
        "max_column_width": 920,
        "turn_style": "push",
        "click_turn": True,
        "hide_chrome_delay": 1600,
        "header_footer": {
            "remaining_time": True,
            "remaining_pages": True,
            "progress": True,
            "clock": True,
            "clock_24h": True,
            "battery": False,
        },
        "texture": "none",
        "accent": None,
        "books": {},
        "external_readest_path": "",
        "open_mode": "window",
    },
    "ui": {
        "language": "zh-CN",
        "theme": "dark",
        "accent": "blue",
        "nav_width": 220,
        "detail_width": 384,
        "window_size": [1440, 900],
    },
}


def ensure_dirs() -> None:
    """确保数据目录存在（配置文件延迟到首次保存时写入）。"""
    for path in (DATA_DIR, LOG_DIR, CACHE_DIR, COVERS_DIR, CONVERTED_DIR):
        path.mkdir(parents=True, exist_ok=True)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并，override 覆盖 base；不修改入参。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    """读取配置并与默认值合并；文件不存在或损坏时返回默认配置。"""
    path = path or CONFIG_PATH
    if not path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_CONFIG)
    merged = deep_merge(DEFAULT_CONFIG, data)
    if not merged.get("library_root"):
        merged["library_root"] = ""
    return merged


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    """原子写入配置（先写临时文件再替换）。"""
    path = path or CONFIG_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)
    except OSError as exc:
        raise ConfigError(f"配置保存失败：{path}（{exc}）") from exc
    return path


def get_setting(config: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """按 "naming.file_template" 形式读取嵌套配置。"""
    node: Any = config
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
