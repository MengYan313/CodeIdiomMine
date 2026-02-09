"""
CodeIdiomMine Common Module
公共模块：包含共享的工具和定义
"""

from .node_kinds import (
    get_node_kinds,
    get_func_kinds,
    get_block_kinds,
    get_stmt_kinds,
    LANGUAGE_NODE_KINDS,
    func_kind,
    block_kind,
    stmt_kind,
)

__all__ = [
    'get_node_kinds',
    'get_func_kinds',
    'get_block_kinds',
    'get_stmt_kinds',
    'LANGUAGE_NODE_KINDS',
    'func_kind',
    'block_kind',
    'stmt_kind',
]

