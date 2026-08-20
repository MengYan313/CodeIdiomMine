# 嵌入与聚类

本模块读取 Parser 当前生成的 `fragments.pkl`，依次完成语义嵌入、DBSCAN 聚类和仓库内保守簇归并。

```bash
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/library/cli11/stage1/fragments.pkl \
  --output outputs/library/cli11/stage2/embeddings.pkl \
  --model unixcoder --device cpu --batch-size 8

.venv/bin/python -m src.mining.dbscan_tuning \
  --input outputs/library/cli11/stage2/embeddings.pkl \
  --output outputs/library/cli11/stage2/clusters-raw.pkl \
  --report outputs/library/cli11/stage2/dbscan-tuning.json

.venv/bin/python -m src.mining.cluster_merge \
  --clusters outputs/library/cli11/stage2/clusters-raw.pkl \
  --embeddings outputs/library/cli11/stage2/embeddings.pkl \
  --output outputs/library/cli11/stage2/clusters.pkl \
  --report outputs/library/cli11/stage2/cluster-merge-report.json
```

模型输入、token 预算和候选结构直接取自当前片段产物，不维护额外 profile 或版本协商。

## 轻量批处理

批处理入口按数据清单顺序调用上述现有模块。`--target` 可重复；省略时运行该
corpus 的全部目标。先处理小型目标时可直接指定目标和步骤：

```bash
.venv/bin/python scripts/run_stage12.py \
  --corpus project --target btop --target mosh \
  --steps stage1,embedding

.venv/bin/python scripts/run_stage12.py \
  --corpus project --target btop \
  --steps dbscan,merge
```

Project 与 Library 分开运行，产物分别写入
`outputs/project/<target>/` 和 `outputs/library/<target>/`。入口不增加参数快照、
版本清单或额外续跑状态；需要重跑时直接再次执行目标即可。
