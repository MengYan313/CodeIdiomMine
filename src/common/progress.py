"""交互式控制台进度条；非 TTY 环境自动静默。"""

from __future__ import annotations

import sys
from typing import Iterable, Optional, TypeVar

from tqdm.auto import tqdm


T = TypeVar("T")


def progress(
    iterable: Optional[Iterable[T]] = None,
    *,
    total: Optional[int] = None,
    desc: str,
    unit: str = "项",
    leave: bool = True,
    disable: Optional[bool] = None,
):
    """创建统一进度条；重定向输出和测试环境默认不渲染。"""
    if disable is None:
        disable = not sys.stderr.isatty()
    return tqdm(
        iterable,
        total=total,
        desc=desc,
        unit=unit,
        leave=leave,
        dynamic_ncols=True,
        disable=disable,
    )
