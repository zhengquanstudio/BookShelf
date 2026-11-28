# -*- coding: utf-8 -*-
"""T19：发布版本号在源码、Inno 安装器脚本与 EXE 元信息三处保持一致。"""
from __future__ import annotations

from pathlib import Path

from app import config

ROOT = Path(__file__).resolve().parents[1]


def test_app_version_is_1_1_6():
    assert config.APP_VERSION == "1.1.6"


def test_installer_version_iss_matches_app_version():
    text = (ROOT / "installer" / "version.iss").read_text(encoding="utf-8")
    assert f'#define AppVersion "{config.APP_VERSION}"' in text
    assert f'#define AppVersionQuad "{config.APP_VERSION}.0"' in text


def test_version_info_matches_app_version():
    text = (ROOT / "version_info.txt").read_text(encoding="utf-8")
    quad = f"{config.APP_VERSION}.0"
    filevers = "(" + ", ".join(config.APP_VERSION.split(".")) + ", 0)"
    assert f"filevers={filevers}" in text
    assert f'StringStruct("FileVersion", "{quad}")' in text
    assert f'StringStruct("ProductVersion", "{quad}")' in text
