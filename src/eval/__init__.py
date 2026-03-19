"""
代码习语评估模块

提供习语挖掘结果的评估指标：
- IC (Idiom Coverage): 函数中被习语匹配的 AST 节点比例
- ISP (Idiom Set Precision): 训练习语在测试集中重现的比例
- F1: IC 与 ISP 的调和平均数
- 平均习语规模: 习语包含的 AST 节点数量平均值
"""

from .idiom_metrics import (
    compute_idiom_coverage,
    compute_idiom_set_precision,
    compute_f1,
    compute_avg_idiom_size,
    evaluate_project,
    evaluate_language,
)

__all__ = [
    "compute_idiom_coverage",
    "compute_idiom_set_precision",
    "compute_f1",
    "compute_avg_idiom_size",
    "evaluate_project",
    "evaluate_language",
]
