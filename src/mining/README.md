# 嵌入与聚类

本模块读取 Parser 当前生成的 `fragments.pkl`，依次完成语义嵌入、DBSCAN 聚类和仓库内保守簇归并。

```bash
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/cli11/fragments.pkl \
  --output outputs/cpp/cli11/embeddings.pkl \
  --model unixcoder --device cpu --batch-size 8

.venv/bin/python -m src.mining.dbscan_tuning \
  --input outputs/cpp/cli11/embeddings.pkl \
  --output outputs/cpp/cli11/clusters.pkl \
  --report outputs/cpp/cli11/dbscan-tuning.json

.venv/bin/python -m src.mining.cluster_merge \
  --clusters outputs/cpp/cli11/clusters.pkl \
  --embeddings outputs/cpp/cli11/embeddings.pkl \
  --output outputs/cpp/cli11/clusters-merged.pkl \
  --report outputs/cpp/cli11/cluster-merge-report.json
```

模型输入、token 预算和候选结构直接取自当前片段产物，不维护额外 profile 或版本协商。
