# 评价与 baseline

评价器按稳定路径把仓库文件轮转为五折。IC 分母是在 Stage 3 裁决前冻结的 Stage 2 非噪声聚类机会域：只有含聚类成员的函数进入分母，每个函数只统计其聚类成员对应 AST 节点的去重并集。最终 `IC` 是函数宏平均与节点微平均的算术平均，`IC_raw` 与之相等，不再做平方根或其他数值变换。`ISP` 继续衡量至少由两个 `(仓库相对文件路径, 函数根 extent)` 支持的习语比例；同一文件中的函数不跨参考折和测量折。`IC_generalization`、`ISP_generalization`、`ISP_fold` 与完整函数 AST 的 `IC_all` 继续作为严格敏感性指标。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp/cli11 \
  --dataset outputs/cpp/cli11/dataset.pkl \
  --clusters outputs/cpp/cli11/clusters-merged.pkl \
  --output results/cpp/cli11/eval.json \
  --mode within_project_kfold --folds 5
```

每折模板只读取参考文件，确定性抽象局部变量、参数和字面量；调用目标、限定名、成员、类型、控制关键字和关键运算符保持一致。结构近似匹配允许有限局部语句差异，但语义锚点必须一致。详细公式和全部敏感性字段见 [`docs/guides/evaluation-metrics.md`](../../docs/guides/evaluation-metrics.md)。

`haggis_cpp.py`、`llm_direct_baseline.py` 和 `idiomine_cpp.py` 提供对照方法。所有方法输出当前习语 artifact，再由同一指标入口评价。
