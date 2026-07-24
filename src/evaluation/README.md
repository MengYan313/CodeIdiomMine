# 评价模块

本模块负责习语指标计算、baseline 产物生成与统一合同校验。最终指标只写入 `results/`；baseline 的可再生成中间数据写入 `outputs/`。

## 启动命令

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp --output results/cpp/eval.json

.venv/bin/python -m src.evaluation.baseline_validation --help
```

指标定义见[评价指标规范](../../docs/guides/evaluation-metrics.md)，复现实验见[baseline 规范](../../docs/guides/baselines.md)。
