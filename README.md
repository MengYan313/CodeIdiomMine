# CodeIdiomMine

CodeIdiomMine 是一个面向 C++ 仓库的轻量化代码习语挖掘实验项目。它通过零构建解析、语义聚类、LLM 判定和关联合成形成可评价的习语结果。

## 当前流程

| 阶段 | 入口 | 主要产物 |
| --- | --- | --- |
| 解析与候选构建 | `src.parser.repo2data` | `dataset.pkl`、`dataset.audit.json`、`fragments.pkl` |
| 嵌入与聚类 | `src.mining.code_embedding`、`src.mining.dbscan_tuning`、`src.mining.cluster_merge` | `embeddings.pkl`、`clusters.pkl`、`clusters-merged.pkl` |
| 习语判定 | `src.idiom_judgment.judge_clusters` | `idiom-judgment.pkl` |
| 关联合成 | `src.idiom_synthesis.synthesize_idioms` | `idiom-synthesis.pkl` |
| 评价 | `src.evaluation.idiom_metrics` | 指标 JSON |

每个仓库独立运行完整流程。文件身份使用仓库相对路径，产物只支持当前格式，不使用内容哈希或项目版本字段作为门禁。

## 环境

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

`requirements-local.lock` 仅供本机环境复现，已被 Git 忽略。UniXcoder 等本地模型需要提前缓存；离线运行不会自动下载。

## 最小示例

以下命令以 `repos/cli11` 为输入：

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos --project cli11 \
  --output outputs/cpp/cli11/dataset.pkl \
  --audit-output outputs/cpp/cli11/dataset.audit.json \
  --fragment-output outputs/cpp/cli11/fragments.pkl \
  --embedding-model unixcoder --local-files-only

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

.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/cpp/cli11/clusters-merged.pkl \
  --source-root repos/cli11 --require-context \
  --checkpoint outputs/cpp/cli11/idiom-judgment.sqlite3 \
  --output outputs/cpp/cli11/idiom-judgment.pkl \
  --report outputs/cpp/cli11/idiom-judgment-report.json

.venv/bin/python -m src.idiom_synthesis.synthesize_idioms \
  --input outputs/cpp/cli11/idiom-judgment.pkl \
  --source-root repos/cli11 \
  --checkpoint outputs/cpp/cli11/idiom-synthesis.sqlite3 \
  --output results/cpp/cli11/idiom-synthesis.pkl \
  --report results/cpp/cli11/idiom-synthesis-report.json

.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp/cli11 \
  --dataset outputs/cpp/cli11/dataset.pkl \
  --clusters outputs/cpp/cli11/clusters-merged.pkl \
  --output results/cpp/cli11/eval.json \
  --mode within_project_kfold --folds 5
```

`--resume` 仅按 checkpoint 中已经完成的位置续跑，不比较模型、提示词或输入摘要。LLM JSON 响应保留一次修复和有限重试。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

后两个阶段可能向 `.env` 配置的模型端点发送源码片段，运行前请确认数据披露范围和调用成本。

更多入口见 [`src/parser/README.md`](src/parser/README.md)、[`src/mining/README.md`](src/mining/README.md)、[`src/idiom_judgment/README.md`](src/idiom_judgment/README.md)、[`src/idiom_synthesis/README.md`](src/idiom_synthesis/README.md) 和 [`src/evaluation/README.md`](src/evaluation/README.md)。
