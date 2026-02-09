"""
集中式日志系统

提供统一的日志配置和管理：
- 控制台输出：INFO 及以上级别
- 文件输出：DEBUG 及以上级别
- 日志文件按模块名组织（如 src.parser.repo2data.log）
"""

import sys
import logging
from pathlib import Path
from typing import Optional


class AppLogger:
    """
    应用日志管理器
    
    提供统一的日志配置和管理，支持：
    - 控制台输出：INFO 及以上级别（简化输出）
    - 文件输出：DEBUG 及以上级别（详细日志）
    - 日志文件按模块名组织
    """
    
    _loggers: dict[str, logging.Logger] = {}
    _file_handlers: dict[str, logging.FileHandler] = {}
    
    @classmethod
    def get_logger(
        cls,
        name: str
    ) -> logging.Logger:
        """
        获取或创建日志记录器
        
        Args:
            name: 日志记录器名称（通常是 __name__，即模块完整路径）
            
        Returns:
            配置好的日志记录器
        """
        # 处理 __main__ 情况：将其转换为实际的模块名
        log_name = cls._normalize_module_name(name)
        
        # 如果已存在，直接返回
        if log_name in cls._loggers:
            return cls._loggers[log_name]
        
        # 创建新的日志记录器
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        
        # 清除已有的处理器（避免重复）
        logger.handlers.clear()
        
        # 配置处理器
        cls._configure_handlers(logger, log_name)
        
        cls._loggers[log_name] = logger
        return logger
    
    @classmethod
    def _normalize_module_name(cls, name: str) -> str:
        """
        规范化模块名称，将 __main__ 转换为实际的模块路径
        
        Args:
            name: 模块名称（可能是 __main__ 或 src.parser.repo2data）
            
        Returns:
            规范化后的模块名称
        """
        if name != '__main__':
            return name
        
        # 从调用栈中查找调用 get_logger 的文件
        import inspect
        try:
            # 获取调用栈
            stack = inspect.stack()
            # 查找调用 get_logger 的位置（跳过当前函数和 get_logger 函数）
            for frame_info in stack[2:]:
                filename = frame_info.filename
                
                # 跳过当前 logger.py 文件
                if filename == __file__:
                    continue
                
                # 跳过标准库
                if 'site-packages' in filename or 'lib/python' in filename:
                    continue
                
                # 找到调用文件，提取模块路径
                if filename.endswith('.py'):
                    file_path = Path(filename)
                    
                    # 尝试从文件路径推断模块名
                    # 例如: /path/to/CodeIdiomMine/src/parser/repo2data.py -> src.parser.repo2data
                    try:
                        # 查找项目根目录（包含 src 的父目录）
                        parts = file_path.parts
                        if 'src' in parts:
                            src_index = parts.index('src')
                            # 从 src 开始构建模块路径
                            module_parts = parts[src_index:]
                            # 移除 .py 扩展名
                            module_parts = list(module_parts)
                            module_parts[-1] = module_parts[-1].replace('.py', '')
                            return '.'.join(module_parts)
                    except Exception:
                        pass
                    
                    # 如果无法推断完整路径，至少使用文件名
                    return file_path.stem
        except Exception:
            pass
        
        # 如果无法确定，返回 __main__
        return '__main__'
    
    @classmethod
    def _configure_handlers(
        cls,
        logger: logging.Logger,
        name: str
    ):
        """
        配置日志处理器
        
        Args:
            logger: 日志记录器
            name: 日志记录器名称（模块名）
        """
        # 1. 控制台处理器（简化输出，INFO 级别）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # 2. 文件处理器（详细输出，DEBUG 级别）
        # 日志文件名使用模块名（例如 src.parser.repo2data.log）
        log_file_path = cls._get_log_file_path(name)
        
        # 为每个模块创建独立的文件处理器
        if log_file_path not in cls._file_handlers:
            # 确保日志目录存在
            log_file = Path(log_file_path)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 创建文件 handler，使用 'w' 模式覆盖同名日志文件
            file_handler = logging.FileHandler(
                log_file, 
                mode='w',
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter('%(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            
            cls._file_handlers[log_file_path] = file_handler
        
        logger.addHandler(cls._file_handlers[log_file_path])
    
    @classmethod
    def _get_log_file_path(cls, module_name: str) -> str:
        """
        获取日志文件路径
        
        Args:
            module_name: 模块名（如 src.parser.repo2data）
        
        Returns:
            日志文件路径
        """
        project_root = Path(__file__).parent.parent
        log_dir = project_root / "logs"
        
        # 使用模块名作为日志文件名
        log_file = log_dir / f"{module_name}.log"
        return str(log_file)
    
    @classmethod
    def shutdown(cls):
        """
        关闭所有日志处理器
        """
        for handler in cls._file_handlers.values():
            handler.close()
        cls._file_handlers.clear()
        cls._loggers.clear()


def get_logger(name: str) -> logging.Logger:
    """
    便捷函数：获取日志记录器
    
    Args:
        name: 日志记录器名称（通常传入 __name__）
        
    Returns:
        配置好的日志记录器
        
    Example:
        logger = get_logger(__name__)
        logger.info("这是一条信息")
    """
    return AppLogger.get_logger(name)


# 在程序退出时自动关闭日志
import atexit
atexit.register(AppLogger.shutdown)
