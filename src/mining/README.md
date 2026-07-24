# 挖掘模块

本模块消费 Parser 生成的 model-ready 片段，先用指定代码模型批量生成嵌入，再按项目执行 DBSCAN 聚类。Embedding 不允许静默截断 Parser 已确认的片段。

正式运行必须一次只消费一个仓库的 `fragments.pkl`。不同仓库的片段、
embedding 和 DBSCAN 输入不得合并；多仓库汇总只能在各仓独立完成评价后进行。

## 启动命令

```bash
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/cli11/fragments.pkl \
  --output outputs/cpp/cli11/embeddings.pkl \
  --model unixcoder --device cpu --batch-size 8 \
  --candidate-profile quality-v2

.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/cli11/embeddings.pkl \
  --output outputs/cpp/cli11/clusters.pkl \
  --eps 0.5 --min-samples 2
```

上例固定 DBSCAN 参数且不启用 `--optimize`。若正式实验改用每仓无监督自动优化，
必须预先冻结优化目标和搜索规则，并保存每仓参数；不得根据最终
`IC`、`ISP`、`F1` 或人工标签反复选择。

数据合同与阶段关系见[仓库架构](../../docs/guides/repository-architecture.md)，模型输入治理见 [C++ Adapter 与模型输入治理](../../docs/guides/cpp-adapter-and-model-input.md)。
