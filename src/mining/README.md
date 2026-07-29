# 挖掘模块

本模块消费 Parser 生成的 model-ready 片段，先用指定代码模型批量生成嵌入，
再按项目执行 DBSCAN。HDBSCAN 仅用于阶段2算法对照。Embedding 不允许静默
截断 Parser 已确认的片段。

正式运行必须一次只消费一个仓库的 `fragments.pkl`。不同仓库的片段、
embedding 和聚类输入不得合并；多仓库汇总只能在各仓独立完成指标后进行。

## 启动命令

```bash
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/cli11/fragments.pkl \
  --output outputs/cpp/cli11/embeddings.pkl \
  --model unixcoder --device cpu --batch-size 8 \
  --candidate-profile quality-v2

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

`cluster_merge` 是阶段2到阶段3之间的正式派生步骤。它先直接归并中心代码 C++
词法等价的簇，再只对 AST 同构、高相似且差异完全属于已声明局部变量一致换名的
簇执行保守归并。任何调用名、类型、运算符、字面量、控制条件、返回值或非局部
标识差异都会保持分离。归并一次只处理一个仓库；合并后的全部成员 embedding
重新计算质心，并选择离新质心最近的真实代码作为代表。

输出簇表仍严格保留原七列 Schema，完整成员和 `infos` 不丢失。来源 label、
归并理由、输入 SHA-256 和前后指标写入顶层
`clustering_metadata.postprocessing`。应写入新路径，不得覆盖冻结的
DBSCAN `clusters.pkl`。23仓真实验证结果见
[阶段2簇归并验证报告](../../docs/research/cpp-cluster-merge-report.md)。

正式算法在聚类前统一固定为 DBSCAN。`dbscan_tuning` 对任意新仓库使用相同的
三指标领域目标：覆盖率 50%～80% 和最大簇占比不超过 15% 作为可行性条件，以
跨文件复现供给 0.45、Top100 头部复现 0.15、密度平衡 0.40 计算质量分数。
论文调参框架沿用标准高斯过程（GP）代理模型和期望改进（EI）采集函数；所谓
“改进”只指目标函数，不改动 GP 或 EI，warm-start 也只用于初始化已有观测。
它不读取仓库名、人工标签或最终 `IC`、`ISP`、`F1`，并保存完整观测报告及
所选参数。当前冻结入口负责评价 warm-start 候选并选择最佳已观测可行参数；
该 incumbent 作为改进贝叶斯优化在当前观测集和预算下的正式参数输出。本轮
筛选前 26 仓的新增评估预算为0，因此不重复运行 DBSCAN；已有结果本身就是
warm-start 目标观测。阶段2质量复核后，`cpp-httplib`、`entt` 和 `simdjson`
只保留历史产物，正式后续流程使用其余 23 仓。若后续增加预算，则继续执行
“GP 拟合目标 → EI 提出下一组参数 →
实际聚类并更新观测 → 保留最佳可行参数”。详细公式和取值理由见
[研究稿阶段2](../../docs/research/01_C++代码习语挖掘研究稿.md)。

HDBSCAN 的独立对照入口如下。默认空间为 768 维 embedding 经 L2 归一化和
确定性 PCA-32 后的欧氏空间；簇代表仍在原始 768 维余弦空间选择。该入口不应
替代正式 DBSCAN 产物。

```bash
.venv/bin/python -m src.mining.hdbscan_clustering \
  --input outputs/cpp/cli11/embeddings.pkl \
  --output outputs/cpp/cli11/clusters-hdbscan.pkl \
  --min-cluster-size 2 --min-samples 1 \
  --cluster-selection-method leaf
```

DBSCAN 历史入口 `src.mining.clustering` 的 `--optimize` 会执行贝叶斯优化。
新正式运行使用上面的自动调参入口，并预先冻结搜索空间、约束与目标权重；
不得根据最终 `IC`、`ISP`、`F1`、人工标签或聚类后算法胜负反复选择。

数据合同与阶段关系见[仓库架构](../../docs/guides/repository-architecture.md)，模型输入治理见 [C++ Adapter 与模型输入治理](../../docs/guides/cpp-adapter-and-model-input.md)。
