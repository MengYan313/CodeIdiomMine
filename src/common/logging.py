"""共享应用日志：每条命令使用一个仅追加写入的日志文件。"""

from __future__ import annotations

import atexit
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "logs"
LOG_NAME_ENV = "APP_LOG_NAME"


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("._") or "application"


def _detect_run_name() -> str:
    """为 ``python -m`` 和直接脚本运行确定稳定的日志名称。"""
    configured_name = os.getenv(LOG_NAME_ENV)
    if configured_name:
        return _safe_name(configured_name)

    main_module = sys.modules.get("__main__")
    module_spec = getattr(main_module, "__spec__", None)
    module_name = getattr(module_spec, "name", None)
    if module_name:
        parts = module_name.split(".")
        if parts[-1] == "__main__" and len(parts) > 1:
            return _safe_name(parts[-2])
        return _safe_name(parts[-1])

    if sys.argv and sys.argv[0] not in {"", "-", "-c"}:
        script_path = Path(sys.argv[0])
        if script_path.stem == "__main__":
            return _safe_name(script_path.parent.name)
        return _safe_name(script_path.stem)
    return "application"


class AppLogger:
    """为两个项目创建幂等的控制台和文件日志器。"""

    _loggers: dict[tuple[str, str], logging.Logger] = {}
    _file_handlers: dict[Path, logging.FileHandler] = {}

    @classmethod
    def get_logger(
        cls,
        name: str,
        run_name: Optional[str] = None,
    ) -> logging.Logger:
        """返回将 INFO 写入 stdout、将 DEBUG 写入 ``logs/`` 的日志器。"""
        resolved_run_name = _safe_name(run_name or _detect_run_name())
        cache_key = (name, resolved_run_name)
        if cache_key in cls._loggers:
            return cls._loggers[cache_key]

        internal_name = f"{PROJECT_ROOT.name}.{resolved_run_name}.{name}"
        logger = logging.getLogger(internal_name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.handlers.clear()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console_handler)

        log_path = cls.get_log_path(resolved_run_name)
        file_handler = cls._file_handlers.get(log_path)
        if file_handler is None:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(
                log_path,
                mode="a",
                encoding="utf-8",
                delay=True,
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
                )
            )
            cls._file_handlers[log_path] = file_handler
        logger.addHandler(file_handler)

        cls._loggers[cache_key] = logger
        return logger

    @classmethod
    def get_log_path(cls, run_name: Optional[str] = None) -> Path:
        """返回规范化的日志文件路径，但不打开文件。"""
        return LOG_DIR / f"{_safe_name(run_name or _detect_run_name())}.log"

    @classmethod
    def shutdown(cls) -> None:
        """仅分离并关闭此日志层持有的处理器。"""
        owned_file_handlers = set(cls._file_handlers.values())
        for logger in cls._loggers.values():
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                if handler not in owned_file_handlers:
                    handler.close()
        for handler in owned_file_handlers:
            handler.close()
        cls._file_handlers.clear()
        cls._loggers.clear()


def get_logger(
    name: str,
    run_name: Optional[str] = None,
) -> logging.Logger:
    """对 :meth:`AppLogger.get_logger` 的便捷封装。"""
    return AppLogger.get_logger(name, run_name)


atexit.register(AppLogger.shutdown)
