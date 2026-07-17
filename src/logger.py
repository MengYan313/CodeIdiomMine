"""Compatibility import for the unified logging module.

New code should import from ``src.common.logging``.
"""

from .common.logging import AppLogger, get_logger

__all__ = ["AppLogger", "get_logger"]
