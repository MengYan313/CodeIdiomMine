"""Shared application logging with one append-only file per command run."""

from __future__ import annotations

import atexit
import inspect
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
    """Resolve a stable log name for ``python -m`` and direct-script runs."""
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

    for frame_info in inspect.stack()[2:]:
        filename = Path(frame_info.filename)
        if filename == Path(__file__) or filename.name in {"__init__.py", "__main__.py"}:
            continue
        if "site-packages" in filename.parts:
            continue
        if filename.suffix == ".py":
            return _safe_name(filename.stem)

    return "application"


class AppLogger:
    """Create idempotent console and file loggers shared by both projects."""

    _loggers: dict[tuple[str, str], logging.Logger] = {}
    _file_handlers: dict[Path, logging.FileHandler] = {}

    @classmethod
    def get_logger(
        cls,
        name: str,
        run_name: Optional[str] = None,
        *,
        script_name: Optional[str] = None,
    ) -> logging.Logger:
        """Return a logger writing INFO to stdout and DEBUG to ``logs/``.

        ``script_name`` remains as a compatibility alias for older WPF2React
        call sites. New code should use ``run_name`` only when the automatic
        command name is unsuitable.
        """
        if run_name and script_name and run_name != script_name:
            raise ValueError("run_name 与 script_name 不能指定不同值")

        resolved_run_name = _safe_name(run_name or script_name or _detect_run_name())
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
        """Return the normalized log file path without opening the file."""
        return LOG_DIR / f"{_safe_name(run_name or _detect_run_name())}.log"

    @classmethod
    def shutdown(cls) -> None:
        """Detach and close only the handlers owned by this logging layer."""
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
    *,
    script_name: Optional[str] = None,
) -> logging.Logger:
    """Convenience wrapper around :meth:`AppLogger.get_logger`."""
    return AppLogger.get_logger(name, run_name, script_name=script_name)


atexit.register(AppLogger.shutdown)
