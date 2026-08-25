"""
代码习语评估模块

提供按 Haggis 固定留出协议计算的仓库专属习语评估指标：
- IC_macro/IC/IC_raw: 测试文件 AST 节点并集覆盖率的文件宏平均
- IC_micro: 测试集 AST 节点并集覆盖率的节点微平均诊断值
- ISP: 训练所得习语中至少在测试集复现一次的比例
- F1: 最终 IC 与 ISP 的调和平均数
- 习语库结构: 种类数、平均簇大小、平均跨函数支持数和 AvgAST

习语发现只读取冻结 train 文件，主指标只读取冻结 test 文件。
"""

from importlib import import_module

__all__ = [
    "compute_f1",
    "compute_idiom_library_stats",
    "evaluate_project",
    "evaluate_cpp",
]

_EXPORTS = {
    name: (".idiom_metrics", name)
    for name in __all__
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
