# 评价指标

正式评价使用 `within_project_file_split`：每个仓库内部按文件划分参考分区和测量分区，避免同一文件同时贡献习语参考与覆盖结果。

主要指标包括：

- `IC`：习语覆盖到的 AST 节点占测量分区有效 AST 节点的比例；
- `ISP`：获得跨文件或多实例支持的习语比例；
- `Precision`、`Recall`、`F1`：针对人工或规则参考集合的检测质量；
- 习语数量、平均支持度、文件覆盖率、平均 AST 大小等描述性指标。

所有方法都通过 `src.evaluation.idiom_metrics` 读取当前 `idiom_judgment` 或 `idiom_synthesis` artifact。计数使用完整 `source_infos`，代码等价判断使用词法归一化后的结构签名。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp/cli11 \
  --dataset outputs/cpp/cli11/dataset.pkl \
  --output results/cpp/cli11/evaluation.json \
  --mode within_project_file_split --test-fraction 0.2
```

比较方法时必须使用相同仓库、相同文件分区和相同指标入口。通用目录习语按 `catalog_id` 汇总；仓库专属习语不跨仓库去重。
