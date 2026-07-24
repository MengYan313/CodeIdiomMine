# 评价模块

本模块负责习语指标计算、baseline 产物生成与统一合同校验。最终指标只写入 `results/`；baseline 的可再生成中间数据写入 `outputs/`。

正式默认评价先接收单个仓库使用完整合格源码产生的习语结果，再按来源文件形成
参考/测量分区。该分区不重新运行 Parser、embedding 或 DBSCAN，只测量仓库内部
覆盖与分区复现。`leave_one_project_out` 仅为历史兼容。

## 启动命令

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp/cli11 \
  --dataset outputs/cpp/cli11/dataset.pkl \
  --output results/cpp/cli11/eval.json \
  --mode within_project_file_split --test-fraction 0.2

.venv/bin/python -m src.evaluation.baseline_validation --help
```

指标定义见[评价指标规范](../../docs/guides/evaluation-metrics.md)，复现实验见[baseline 规范](../../docs/guides/baselines.md)。
