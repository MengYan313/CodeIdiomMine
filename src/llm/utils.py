"""
工具函数模块

提供通用的工具函数，用于错误处理、数据格式化等。
"""

import time
import json
import re
from typing import Any, Callable, Dict, List, Optional, TypeVar
from functools import wraps
import logging

# 设置日志
logger = logging.getLogger(__name__)

T = TypeVar('T')


def retry_on_error(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """
    重试装饰器

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff: 延迟增长倍数
        exceptions: 要捕获的异常类型元组

    Returns:
        装饰器函数

    示例:
        >>> @retry_on_error(max_retries=3, delay=1.0)
        >>> def unreliable_function():
        >>>     # 可能失败的函数
        >>>     pass
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"函数 {func.__name__} 失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}"
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"函数 {func.__name__} 在 {max_retries + 1} 次尝试后仍然失败"
                        )

            raise last_exception

        return wrapper
    return decorator


def format_prompt(
    template: str,
    **kwargs
) -> str:
    """
    格式化提示词模板

    Args:
        template: 提示词模板字符串
        **kwargs: 模板变量

    Returns:
        格式化后的提示词

    示例:
        >>> prompt = format_prompt(
        >>>     "将以下文本翻译成 {language}：{text}",
        >>>     language="中文",
        >>>     text="Hello World"
        >>> )
    """
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise ValueError(f"模板中缺少必需的变量: {e}")


def truncate_text(
    text: str,
    max_length: int = 100,
    suffix: str = "..."
) -> str:
    """
    截断文本到指定长度

    Args:
        text: 要截断的文本
        max_length: 最大长度
        suffix: 截断后添加的后缀

    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text

    if len(suffix) >= max_length:
        return suffix[:max_length]

    return text[:max_length - len(suffix)] + suffix


def count_tokens_approximate(text: str) -> int:
    """
    粗略估算文本的 token 数量

    使用简单的规则估算，实际 token 数量可能有所不同。

    Args:
        text: 文本内容

    Returns:
        估算的 token 数量
    """
    # 简单估算：1 token ≈ 4 个字符（英文）或 1.5 个中文字符
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars

    # 中文字符：1.5 个字符 = 1 token
    # 其他字符：4 个字符 = 1 token
    estimated_tokens = (chinese_chars / 1.5) + (other_chars / 4)

    return int(estimated_tokens)


def batch_process(
    items: List[Any],
    process_fn: Callable[[Any], Any],
    batch_size: int = 10,
    show_progress: bool = False
) -> List[Any]:
    """
    批量处理数据

    Args:
        items: 要处理的数据列表
        process_fn: 处理函数
        batch_size: 批次大小
        show_progress: 是否显示进度

    Returns:
        处理结果列表
    """
    results = []
    total = len(items)

    for i in range(0, total, batch_size):
        batch = items[i:i + batch_size]
        batch_results = [process_fn(item) for item in batch]
        results.extend(batch_results)

        if show_progress:
            progress = min(i + batch_size, total)
            logger.info(f"进度: {progress}/{total} ({progress/total*100:.1f}%)")

    return results


def safe_json_dumps(
    obj: Any,
    default: str = "{}"
) -> str:
    """
    安全地序列化对象为 JSON 字符串

    Args:
        obj: 要序列化的对象
        default: 序列化失败时的默认值

    Returns:
        JSON 字符串或默认值
    """
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as e:
        logger.warning(f"JSON 序列化失败: {e}")
        return default


def merge_dicts(*dicts: Dict) -> Dict:
    """
    合并多个字典

    Args:
        *dicts: 要合并的字典

    Returns:
        合并后的字典
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


class Timer:
    """
    简单的计时器类

    示例:
        >>> with Timer("处理数据"):
        >>>     # 一些耗时操作
        >>>     pass
        >>> # 输出: 处理数据 耗时: 1.23 秒
    """

    def __init__(self, name: str = "操作", verbose: bool = True):
        """
        初始化计时器

        Args:
            name: 操作名称
            verbose: 是否打印日志
        """
        self.name = name
        self.verbose = verbose
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        """进入上下文"""
        self.start_time = time.time()
        if self.verbose:
            logger.info(f"开始: {self.name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        self.end_time = time.time()
        elapsed = self.end_time - self.start_time
        if self.verbose:
            logger.info(f"{self.name} 耗时: {elapsed:.2f} 秒")

    def elapsed(self) -> float:
        """获取已经过的时间"""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time
