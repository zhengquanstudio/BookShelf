"""设置读写服务：界面只通过本服务修改 config.json。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .. import config
from ..db.connection import Database
from ..errors import ConfigError


class SettingsService:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.CONFIG_PATH
        self._config = config.load_config(self.path)

    @property
    def data(self) -> dict[str, Any]:
        return self._config

    def save(self) -> None:
        config.save_config(self._config, self.path)

    def set_library_root(self, path: str) -> None:
        """保存书库根目录，并校验目录存在、可写且不与源目录相同。"""
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise ConfigError("书库目录不存在")
        for source in self._config.get("source_dirs", []):
            if Path(source).expanduser().resolve() == root:
                raise ConfigError("书库目录与源目录相同，会导致自我复制")
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".bookshelf-write-", dir=root, delete=True
            ):
                pass
        except OSError as exc:
            raise ConfigError(f"书库目录不可写：{root}（{exc}）") from exc
        self._config["library_root"] = str(root)
        self.save()

    def save_scan_options(
        self,
        source_dirs: list[str],
        formats: list[str],
        scan_options: dict[str, Any],
    ) -> None:
        """保存扫描目录、格式与选项，并维护最近 5 个源目录。"""
        roots = [str(Path(item).expanduser().resolve()) for item in source_dirs]
        if not roots:
            raise ConfigError("请至少添加一个扫描目录")
        for item in roots:
            source = Path(item)
            if not source.is_dir():
                raise ConfigError(f"扫描目录不存在：{item}")
            if not os.access(source, os.R_OK):
                raise ConfigError(f"扫描目录不可读：{item}")
        library = self._config.get("library_root")
        if library:
            root = Path(library).expanduser().resolve()
            if root in [Path(item) for item in roots]:
                raise ConfigError("书库目录与源目录相同，会导致自我复制")
        if not formats:
            raise ConfigError("请至少选择一种电子书格式")
        recent = [item for item in roots if Path(item).is_dir()]
        for item in self._config.get("recent_source_dirs", []):
            if item not in recent:
                recent.append(item)
        self._config["source_dirs"] = roots
        self._config["recent_source_dirs"] = recent[:5]
        self._config["formats"] = formats
        self._config["scan"] = {**self._config.get("scan", {}), **scan_options}
        self.save()

    # ---- 设置对话框（F12） -----------------------------------------
    def apply(self, values: Mapping[str, Any]) -> None:
        """把设置对话框收集的片段深合并进配置，校验后原子保存。"""
        merged = config.deep_merge(self._config, dict(values or {}))
        self._validate(merged)
        self._config = merged
        self.save()

    def reset_naming(self) -> None:
        """只把命名与整理规则恢复为内置默认值。"""
        self._config["naming"] = copy.deepcopy(config.DEFAULT_CONFIG["naming"])
        self._config["organize"] = copy.deepcopy(config.DEFAULT_CONFIG["organize"])
        self.save()

    def reset_all(self, *, keep_paths: bool = True) -> None:
        """恢复全部默认设置，默认保留书库根目录、源目录与命名预设。"""
        library_root = self._config.get("library_root", "")
        source_dirs = self._config.get("source_dirs", [])
        presets = self._config.get("naming_presets", {})
        self._config = copy.deepcopy(config.DEFAULT_CONFIG)
        if keep_paths:
            self._config["library_root"] = library_root
            self._config["source_dirs"] = copy.deepcopy(source_dirs)
        self._config["naming_presets"] = copy.deepcopy(presets)
        self.save()

    def presets(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._config.get("naming_presets") or {})

    def save_preset(self, name: str) -> None:
        """把当前命名规则另存为一套命名方案。"""
        key = (name or "").strip()
        if not key:
            raise ConfigError("预设名称不能为空")
        presets = self._config.setdefault("naming_presets", {})
        presets[key] = copy.deepcopy(self._config.get("naming") or {})
        self.save()

    def apply_preset(self, name: str) -> None:
        preset = (self._config.get("naming_presets") or {}).get(name)
        if preset is None:
            raise ConfigError(f"预设不存在：{name}")
        self._config["naming"] = copy.deepcopy(preset)
        self.save()

    @staticmethod
    def sync_ui_state(db: Database, key: str, value: Any) -> None:
        """把界面状态写入 app_settings（配置仍以 JSON 为准）。"""
        payload = json.dumps(value, ensure_ascii=False)
        db.execute(
            "INSERT INTO app_settings(k, v, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = excluded.updated_at",
            (key, payload),
        )

    @staticmethod
    def _validate(cfg: dict[str, Any]) -> None:
        root = str(cfg.get("library_root") or "")
        if root and not Path(root).expanduser().is_dir():
            raise ConfigError(f"书库目录不存在：{root}")
        naming = cfg.get("naming") or {}
        author_template = str(naming.get("author_dir_template") or "")
        file_template = str(naming.get("file_template") or "")
        if "{作者}" not in author_template:
            raise ConfigError("作者目录模板必须包含 {作者}")
        if "{书名}" not in file_template:
            raise ConfigError("文件模板必须包含 {书名}")
