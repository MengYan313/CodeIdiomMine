# 挖掘模块

本模块消费 Parser 生成的 model-ready 片段，先用指定代码模型批量生成嵌入，再按项目执行 DBSCAN 聚类。Embedding 不允许静默截断 Parser 已确认的片段。

## 启动命令

```bash
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/fragments.pkl \
  --output outputs/cpp/embeddings.pkl --model unixcoder

.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/embeddings.pkl \
  --output outputs/cpp/clusters.pkl
```

数据合同与阶段关系见[仓库架构](../../docs/guides/repository-architecture.md)，模型输入治理见 [C++ Adapter 与模型输入治理](../../docs/guides/cpp-adapter-and-model-input.md)。
