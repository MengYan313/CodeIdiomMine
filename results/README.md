# 实验产物状态

## 当前结论

截至 2026-08-21，冻结的 15 个 Project 分组和 15 个 Library 分组均已完成
Stage 1 候选构建与 Stage 2 Embedding、DBSCAN 和仓库内保守簇归并。30 个分组的
`embeddings.pkl`、`clusters-raw.pkl`、`dbscan-tuning.json`、`clusters.pkl` 和
`cluster-merge-report.json` 共 150 份产物均存在、非空并通过反序列化或 JSON
解析校验。完整实验产物保存在本地 `outputs/`，按仓库治理规则不提交版本控制。

数据集定义、过滤、最终规模和 `train`/`test` 划分见：

- [`docs/research/cpp-dataset-classification.md`](../docs/research/cpp-dataset-classification.md)
- [`docs/research/cpp-dataset-manifest.json`](../docs/research/cpp-dataset-manifest.json)
- [`docs/research/cpp-dataset-statistics.json`](../docs/research/cpp-dataset-statistics.json)

## Stage 1/2 汇总

Stage 1 只读取冻结清单的 `train` 文件。Stage 2 使用 UniXcoder、CPU、
`batch-size=8`、余弦 DBSCAN 自动调参和仓库内保守归并；30 个分组均完成，未发生
OOM。

| 语料 | 分组 | 候选数 | 归并后簇数 | 簇内成员 | 覆盖率 | 平均簇大小 | 纯重复率 | 强结构代理率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Project | 15 | 110,875 | 17,002 | 73,735 | 66.50% | 4.34 | 14.23% | 21.66% |
| Library | 15 | 912,158 | 143,690 | 584,441 | 64.07% | 4.07 | 21.80% | 13.38% |

所有分组的覆盖率均位于 61.54%～73.04%，最大簇占候选总数的比例不超过 8.02%，
未出现聚类塌缩。这里的“强结构代理”要求代表代码非平凡、簇内至少存在两个 C++
词法变体并且至少跨两个文件；它只表示值得进入 Stage 3 的候选，不是最终习语标签。

## Stage 3 前质量筛选

本次复用既有 Stage 2 质量筛选口径，检查逐仓纯重复、跨文件复现、Top100 非平凡
结构和词法变体。针对 Library 额外按客户端仓库边界检查跨客户端复现，避免把同一
客户端内的重复误判为通用 API 习语。

分析还使用一个只服务于本次预判的保守高置信代理：候选须具有跨文件或跨客户端
复现、至少两个词法变体、代表代码非平凡、节点类型纯度与代表类型支持度均不低于
80%，且成员 AST 规模离散度受控。该代理不是 Stage 3 新门禁，也不改变正式流程。

- Project 共识别 3,683 个强结构代理和 2,343 个保守高置信簇。优先级最高的是
  `libzmq`、`envoy` 和 `drogon`；`btop`、`qbittorrent`、`polybar`、`leveldb`
  和 `fmt` 适合作为第二批。
- Library 共识别 7,431 个跨客户端强代理、4,551 个保守高置信簇，以及至少 869
  个代表代码直接包含目标 API 的保守高置信簇。优先级最高的是 `opencv`、`eigen`、
  `pybind11`、`rocksdb`、`abseil`、`boost-asio` 和 `googletest`。
- `cli11` 的跨客户端供给和组合证据最少，适合低预算抽样；Project 中的 `mosh`、
  `ninja`、`taskflow`、`yaml-cpp` 和 `yoga` 更可能是低产量组，而不是已经证明
  代码质量较差。

## 主要风险与解释边界

- `envoy` 的候选供给最高，但 22.02% 的簇内成员位于规模不小于 100 的大簇中，
  Stage 3 应优先检查这些簇的语义一致性和输入规模。
- `opencv`、`eigen` 和 `googletest` 的全量纯重复率分别约为 35.03%、31.64% 和
  31.46%。这些分组仍有大量跨客户端高质量候选，但不能直接按频率把固定样板视为
  最终习语。
- Library `fmt` 的候选总量很高，但头部节点类型纯度较低，且部分簇的中心代表不含
  `fmt` API；需要依靠 Stage 3 语义审查过滤通用或异质簇。
- Library 的目标 API 计数采用显式 namespace、类型、调用和宏证据，是保守下界；
  `nlohmann-json` 等常通过本地别名使用 API 的分组会被低估。
- 本报告只根据 Stage 2 产物预测后续习语质量。最终结论仍须经过 Stage 3 语义、
  复用价值和代码异味门禁、Stage 4 组合复审，以及盲化人工质量评价。

建议正式 Stage 3 首批运行 Project 的 `libzmq`、`envoy`、`drogon`，以及 Library
的 `opencv`、`eigen`、`pybind11` 和 `rocksdb`。这组同时覆盖高候选供给、高质量
密度、跨客户端复现和明确 API 语义。
