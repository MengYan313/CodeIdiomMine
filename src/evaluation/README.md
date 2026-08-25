# 评价、baseline 与质量消融

正式评价使用 Haggis 固定留出协议。所有方法只从 `dataset.pkl` 的 train 文件发现
习语；主 `IC` 是 test 文件 AST 节点覆盖率的宏平均，主 `ISP` 是训练所得习语在
test 至少复现一次的比例，`F1` 是二者的调和平均。`IC_micro` 仅作诊断。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/library/cli11/main \
  --dataset outputs/library/cli11/stage0/dataset.pkl \
  --output results/library/cli11/main/evaluation.json \
  --stage synthesis --mode haggis_holdout
```

评价器同时报告 `idiom_type_count`、`avg_cluster_size`、
`avg_cross_function_support` 和 `AvgAST`，形成统一九项指标合同。当前协议使用唯一
固定的 70/30 文件划分，不再计算 train 内部五折或旧机会域指标。划分优化入口为
`src.evaluation.optimize_split`。

`haggis_cpp.py`、`llm_direct_baseline.py` 和 `idiomine_cpp.py` 提供三条正式外部
baseline；它们输出当前习语 artifact，再由 `baseline_validation.py` 使用同一指标
入口评价并验证 manifest、完整性和九项指标。`stage2_frequency_ablation.py` 只用于
内部质量消融，不作为外部 baseline。
