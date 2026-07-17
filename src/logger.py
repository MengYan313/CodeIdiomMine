"""统一日志模块的兼容导入。

新代码应从 ``src.common.logging`` 导入。
"""

from .common.logging import AppLogger, get_logger

__all__ = ["AppLogger", "get_logger"]
