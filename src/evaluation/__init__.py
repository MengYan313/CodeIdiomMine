"""
代码习语评估模块

提供仓库专属习语挖掘结果的仓库内评估指标：
- IC_macro: 测量分区函数 AST 节点覆盖率的宏平均
- IC_micro: 测量分区函数 AST 节点覆盖率的节点微平均
- IC: IC_macro 与 IC_micro 的算术平均
- ISP (Idiom Set Precision): 参考分区习语在测量分区重现的比例
- F1: 最终 IC 与 ISP 的调和平均数
- 习语库结构: 种类数、平均簇大小、平均跨文件支持数和 AvgAST

习语发现始终先在单个仓库的完整合格源码上独立完成；参考/测量分区只用于
最终指标计算。留一项目模式仅为历史兼容保留。
"""

from importlib import import_module

__all__ = [
    "compute_idiom_coverage",
    "compute_idiom_set_precision",
    "compute_f1",
    "compute_avg_idiom_size",
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
