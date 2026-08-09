"""
代码习语评估模块

提供仓库专属习语挖掘结果的仓库内评估指标：
- IC_macro: 已接受实例在冻结聚类机会域 AST 节点上的函数宏平均覆盖率
- IC_micro: 已接受实例在冻结聚类机会域 AST 节点上的节点微平均覆盖率
- IC/IC_raw: (IC_macro + IC_micro) / 2，不执行数值变换
- ISP: 具有至少两个独立来源函数域的习语比例
- F1: 最终 IC 与 ISP 的调和平均数
- 习语库结构: 种类数、平均簇大小、平均跨函数支持数和 AvgAST

习语发现始终先在单个仓库的完整合格源码上独立完成。稳定轮转五折让每个文件
恰好一次贡献主覆盖足迹；同文件函数不跨折，只由参考折归纳模板的 IC/ISP
泛化指标另行报告。
"""

from importlib import import_module

__all__ = [
    "compute_idiom_coverage",
    "compute_idiom_set_precision",
    "compute_f1",
    "compute_avg_idiom_size",
    "compute_idiom_library_stats",
    "evaluate_project_kfold",
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
