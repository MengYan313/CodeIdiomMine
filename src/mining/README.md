# 嵌入与聚类

本模块读取 Parser 当前生成的 `fragments.pkl`，依次完成语义嵌入、DBSCAN 聚类和仓库内保守簇归并。

```bash
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cli11/stage1/fragments.pkl \
  --output outputs/cli11/stage2/embeddings.pkl \
  --model unixcoder --device cpu --batch-size 8

.venv/bin/python -m src.mining.dbscan_tuning \
  --input outputs/cli11/stage2/embeddings.pkl \
  --output outputs/cli11/stage2/clusters-raw.pkl \
  --report outputs/cli11/stage2/dbscan-tuning.json

.venv/bin/python -m src.mining.cluster_merge \
  --clusters outputs/cli11/stage2/clusters-raw.pkl \
  --embeddings outputs/cli11/stage2/embeddings.pkl \
  --output outputs/cli11/stage2/clusters.pkl \
  --report outputs/cli11/stage2/cluster-merge-report.json
```

模型输入、token 预算和候选结构直接取自当前片段产物，不维护额外 profile 或版本协商。
