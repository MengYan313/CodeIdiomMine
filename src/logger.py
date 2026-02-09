# -*- coding: utf-8 -*-
"""
日志配置模块

提供统一的日志系统，支持：
- 控制台输出（简化，INFO 级别）
- 文件输出（详细，DEBUG 级别）
- 按运行的脚本文件名组织日志文件
"""

import logging
import sys
import inspect
from pathlib import Path
from typing import Optional


def _get_script_name() -> str:
    """
    检测当前运行的脚本文件名
    
    Returns:
        脚本文件名（不含路径和扩展名）
    """
    # 方法1: 处理 python -m module.submodule 的情况
    if sys.argv and len(sys.argv) > 1 and sys.argv[0] == '-m':
        # python -m tests.test_agents -> test_agents
        module_path = sys.argv[1]
        parts = module_path.split('.')
        return parts[-1]  # 取最后一部分
    
    # 方法2: 尝试从 sys.argv[0] 获取
    if sys.argv and sys.argv[0]:
        script_arg = sys.argv[0]
        
        # 处理模块运行的情况 (python -m module.submodule)
        if script_arg.endswith('__main__.py') or '/__main__.py' in script_arg:
            # 从模块路径中提取名称
            parts = script_arg.replace('\\', '/').split('/')
            # 找到包含 __main__.py 的部分，取前面的模块名
            for i, part in enumerate(parts):
                if part == '__main__.py' or part.endswith('__main__.py'):
                    if i > 0:
                        # 取前一个部分作为模块名
                        module_name = parts[i-1]
                        return module_name.replace('.py', '')
        
        # 处理普通脚本文件
        script_path = Path(script_arg)
        if script_path.exists():
            return script_path.stem
        elif script_path.suffix == '.py':
            return script_path.stem
        elif '.' in script_arg and not script_arg.startswith('.'):
            # 可能是模块路径，如 src.migration.migration_team
            parts = script_arg.split('.')
            return parts[-1]  # 取最后一部分
    
    # 方法3: 从调用栈中查找最外层的脚本文件
    try:
        stack = inspect.stack()
        # 从栈顶向下查找，找到第一个不是当前文件且不是标准库的脚本
        for frame_info in stack:
            filename = frame_info.filename
            # 跳过标准库和当前文件
            if 'site-packages' in filename or 'lib/python' in filename:
                continue
            if filename == __file__:
                continue
            
            # 如果是 .py 文件，返回其名称
            if filename.endswith('.py'):
                script_path = Path(filename)
                # 跳过 __init__.py 和 __main__.py
                if script_path.name in ('__init__.py', '__main__.py'):
                    continue
                return script_path.stem
    except Exception:
        pass
    
    # 默认值
    return "unknown_script"


class AppLogger:
    """
    应用日志管理器
    
    提供统一的日志配置和管理，支持：
    - 控制台输出：INFO 及以上级别（简化输出）
    - 文件输出：DEBUG 及以上级别（详细日志）
    - 日志文件按运行的脚本文件名组织
    """
    
    _loggers: dict[str, logging.Logger] = {}
    _handlers_configured: dict[str, bool] = {}
    _file_handlers: dict[str, logging.FileHandler] = {}  # 跟踪文件处理器，避免重复创建
    _script_name: Optional[str] = None
    
    @classmethod
    def _get_script_name(cls) -> str:
        """获取当前脚本名称（缓存）"""
        if cls._script_name is None:
            cls._script_name = _get_script_name()
        return cls._script_name
    
    @classmethod
    def get_logger(
        cls,
        name: str,
        script_name: Optional[str] = None
    ) -> logging.Logger:
        """
        获取或创建日志记录器
        
        Args:
            name: 日志记录器名称（通常是模块名或 Agent 类型）
            script_name: 脚本名称（如果为 None，则自动检测）
            
        Returns:
            配置好的日志记录器
        """
        # 确定脚本名称
        if script_name is None:
            script_name = cls._get_script_name()
        
        logger_key = f"{name}_{script_name}"
        
        # 如果已存在，直接返回
        if logger_key in cls._loggers:
            return cls._loggers[logger_key]
        
        # 创建新的日志记录器
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        
        # 避免重复添加处理器
        if logger_key not in cls._handlers_configured:
            cls._configure_handlers(logger, name, script_name)
            cls._handlers_configured[logger_key] = True
        
        cls._loggers[logger_key] = logger
        return logger
    
    @classmethod
    def _configure_handlers(
        cls,
        logger: logging.Logger,
        name: str,
        script_name: str
    ):
        """
        配置日志处理器
        
        Args:
            logger: 日志记录器
            name: 日志记录器名称
            script_name: 脚本名称
        """
        # 清除已有的处理器（避免重复）
        logger.handlers.clear()
        
        # 1. 控制台处理器（简化输出，INFO 级别）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(message)s',  # 简化格式，只显示消息
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # 2. 文件处理器（详细输出，DEBUG 级别）
        # 日志目录：项目根目录下的 logs 文件夹（与 src 同级）
        project_root = Path(__file__).parent.parent  # 从 src/logger.py 向上两级到项目根目录
        log_dir = project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 日志文件名：{script_name}.log（覆盖同名日志）
        log_file = log_dir / f"{script_name}.log"
        
        # 确保每个脚本名称只有一个文件 handler（避免多个 logger 写入同一文件导致混乱）
        file_handler_key = str(log_file)
        if file_handler_key not in cls._file_handlers:
            # 如果文件已存在，先删除（确保干净的开始）
            if log_file.exists():
                try:
                    log_file.unlink()
                except Exception:
                    pass  # 忽略删除错误
            
            # 创建文件 handler，使用 'w' 模式覆盖同名日志文件
            # 使用 UTF-8 编码，确保文件是纯文本格式
            file_handler = logging.FileHandler(
                log_file, 
                mode='w',  # 覆盖模式
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            # 精简格式：只保留级别和消息，去除时间戳和记录器名称
            file_formatter = logging.Formatter(
                '%(levelname)s - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            
            # 立即刷新，确保文件被正确创建
            file_handler.stream.flush()
            
            cls._file_handlers[file_handler_key] = file_handler
        
        # 使用共享的文件 handler
        logger.addHandler(cls._file_handlers[file_handler_key])


def get_logger(
    name: str,
    script_name: Optional[str] = None
) -> logging.Logger:
    """
    便捷函数：获取日志记录器
    
    Args:
        name: 日志记录器名称
        script_name: 脚本名称（如果为 None，则自动检测）
        
    Returns:
        配置好的日志记录器
    """
    return AppLogger.get_logger(name, script_name)

