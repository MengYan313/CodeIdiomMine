# 工具模块

本模块提供实验产物的只读转换和可读投影。转换结果仅用于人工检查，不得回流为正式流水线输入。

## 启动命令

```bash
.venv/bin/python -m src.utils.export_artifacts \
  --input-dir outputs/library/cli11 \
  --output-dir outputs/library/cli11/readables --limit 100 \
  --result-dir results/library/cli11/main

.venv/bin/python -m src.utils.pkl2csv --help
```

完整产物合同见[仓库架构](../../docs/guides/repository-architecture.md)。
