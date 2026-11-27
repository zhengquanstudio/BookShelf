"""统一异常体系。

UI 层只捕获 BookShelfError 及其子类，其余异常由全局兜底记录。
"""

from __future__ import annotations


class BookShelfError(Exception):
    """所有业务异常的基类。"""


class ConfigError(BookShelfError):
    """配置文件读写失败。"""


class DatabaseError(BookShelfError):
    """数据库连接、迁移或查询失败。"""


class ExtractError(BookShelfError):
    """电子书元数据抽取失败。"""


class NetworkError(BookShelfError):
    """联网检索失败（超时、限流、解析错误）。"""


class OrganizeError(BookShelfError):
    """整理预览或执行失败。"""


class ConvertError(BookShelfError):
    """MOBI/AZW3 转 EPUB 失败。"""
