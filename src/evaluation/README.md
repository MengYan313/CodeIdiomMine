# 评价、baseline 与质量消融

评价器按稳定路径把仓库文件轮转为五折。IC 分母是在 Stage 3 裁决前冻结的 Stage 2 非噪声聚类机会域：只有含聚类成员的函数进入分母，每个函数只统计其聚类成员对应 AST 节点的去重并集。最终 `IC` 是函数宏平均与节点微平均的算术平均，`IC_raw` 与之相等，不再做平方根或其他数值变换。`ISP` 继续衡量至少由两个 `(仓库相对文件路径, 函数根 extent)` 支持的习语比例；同一文件中的函数不跨参考折和测量折。`IC_generalization`、`ISP_generalization`、`ISP_fold` 与完整函数 AST 的 `IC_all` 继续作为严格敏感性指标。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/main/cli11 \
  --dataset outputs/cli11/stage0/dataset.pkl \
  --clusters outputs/cli11/stage2/clusters.pkl \
  --output results/main/cli11/evaluation.json \
  --mode within_project_kfold --folds 5
```

每折模板只读取参考文件，确定性抽象局部变量、参数和字面量；调用目标、限定名、成员、类型、控制关键字和关键运算符保持一致。结构近似匹配允许有限局部语句差异，但语义锚点必须一致。详细公式和全部敏感性字段见 [`docs/guides/evaluation-metrics.md`](../../docs/guides/evaluation-metrics.md)。

`haggis_cpp.py`、`llm_direct_baseline.py` 和 `idiomine_cpp.py` 提供对照方法。所有方法输出当前习语 artifact，再由同一指标入口评价。

`stage2_frequency_ablation.py` 直接保留 Stage 2 高频簇，用于与 Stage 4 最终习语做
盲化人工质量比较。由于它与 IC 机会域共享聚类来源，其 IC、ISP、F1 只作为覆盖上界
诊断，不作为独立 baseline 参加自动指标质量排名。
