# 数据集仓库

`repos/` 只保存本地源码仓库，所有仓库必须直接位于本目录，禁止再建立 `cpp/`、`candidates/` 等分组层。仓库源码由 Git 忽略；只有本说明进入版本控制。

正式论文主数据集由 `docs/research/cpp-dataset-selection.json` 中状态为“保留”
或“条件保留”的 23 个固定版本仓库组成。`cpp-httplib`、`entt` 和 `simdjson`
属于“阶段2后排除”：本地源码可用于筛选复核，但不得进入后续 LLM、合成或主结果
统计；其历史阶段1/2产物已移除。只有正式 23 仓保留统一全量产物。`gsl` 已淘汰且
不得留在本地。Haggis 的
`codemining-treelm` 只作为文献与实现来源引用，不作为数据集仓库存放。

## 快速使用

从根目录解析单个仓库：

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos --project cli11 \
  --output outputs/cli11/stage0/dataset.pkl \
  --fragment-output outputs/cli11/stage1/fragments.pkl \
  --embedding-model unixcoder --local-files-only
```

分析单个固定仓库：

```bash
.venv/bin/python -m scripts.analyze_cpp_dataset analyze-repo \
  --repo repos/cli11 --project cli11 \
  --output outputs/cli11/stage0/analysis.json
```

仓库版本、稀疏路径、许可与筛选证据见
[数据集现状报告](../docs/research/cpp-dataset-status-report.md)、
[数据集分类与选取方法](../docs/research/cpp-dataset-classification.md)、
[逐项目排查](../docs/research/cpp-dataset-project-audit.md)和
[聚类质量筛选报告](../docs/research/cpp-clustering-quality-screening.md)。
