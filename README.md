# CodeIdiomMine

当前版本：**Sol 5.9**。

CodeIdiomMine 从 C++ 仓库提取 AST 候选片段，经代码嵌入和 DBSCAN 聚类后，
先由规则筛出可能抽象的局部差异，再由 LLM 基于完整簇与规则初判决定抽象或保持
原代码，并执行语义与异味审查；随后通过多 Agent 将同一区域内
相关习语合成为质量更高的模板。阶段3/4使用业务质量评分和独立代码异味门禁自动
产生 `accepted/rejected` 二态结果；阶段3/4自动加载经哈希验证的代表源码区域上下文，
阶段4复用阶段3的异味分类与审查 Agent，且只按完全相同的代表区域分组。阶段4
产物是 `synthesis_delta`，不复制未合成的阶段3习语。正式阶段4只消费阶段3已
接受产物；阶段2直达阶段4仅作
不调用 LLM 的合同验证。异味过滤另有分层人工事后审计。HDBSCAN 作为阶段2实验
对照保留，不进入正式流水线。Agent 请求采用单次 JSON 修复和一次有界逻辑重试；
失败只拒绝或跳过当前簇/组，尝试与回退证据写入产物，不中断后续处理。
长时运行支持配置一致性校验的 SQLite checkpoint 和续跑。

Parser 遵循零构建解析：被分析项目无需编译、链接或执行，只要源码可读取即可生成 AST、诊断和候选片段。CodeIdiomMine 自身仍需安装 Python 依赖。

## 核心研究边界

仓库是完整、独立的挖掘单元。每个给定 C++ 仓库都使用全部合格源码独立执行
`Parser → fragments → embedding → 聚类 → 习语判断 → 习语合成 → 评价`；不同仓库
的候选、向量和聚类输入不得混合。单仓库在聚类前不拆分训练集、开发集或
测试集。最终评价才按来源文件形成确定性的参考分区和测量分区，只测量仓库内部
覆盖、重复和分区复现，不重新挖掘，也不表示跨仓库或未知数据泛化。

## 目录

```text
CodeIdiomMine/
├── src/       # parser、mining、agents、evaluation 与共享基础设施
├── tests/     # 与 src 功能包对应的测试
├── repos/     # 本地仓库输入，所有仓库平级存放
├── outputs/   # 解析、嵌入、聚类等中间产物
├── results/   # Agent 与评价最终产物
├── logs/      # 每次命令的追加日志
├── docs/      # 设计与研究说明
└── scripts/   # 数据集分析和一致性检查
```

`repos/`、`outputs/`、`results/` 和 `logs/` 默认不纳入版本控制。数据集规则见 [repos/README.md](repos/README.md)。

## 安装

已验证环境为 Apple Silicon macOS 与 Python 3.12.10：

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

真实 Agent 阶段还需要在根目录 `.env` 中配置模型端点与密钥。代码片段会发送到所配置的外部服务，运行前应确认成本和数据披露范围。

## 最小流水线

以下命令以本地 `repos/cli11` 这一独立挖掘单元为例，并要求 UniXcoder 已在本机缓存；若已获准首次下载模型，可移除 `--local-files-only`。处理多个仓库时应分别使用 `outputs/cpp/<repo>/` 和 `results/cpp/<repo>/`，不要合并它们的 `fragments.pkl`、`embeddings.pkl` 或 `clusters.pkl`。

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos --project cli11 \
  --output outputs/cpp/cli11/dataset.pkl \
  --fragment-output outputs/cpp/cli11/fragments.pkl \
  --embedding-model unixcoder --local-files-only

.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/cli11/fragments.pkl \
  --output outputs/cpp/cli11/embeddings.pkl \
  --model unixcoder --device cpu --batch-size 8 \
  --candidate-profile quality-v2

.venv/bin/python -m src.mining.dbscan_tuning \
  --input outputs/cpp/cli11/embeddings.pkl \
  --output outputs/cpp/cli11/clusters.pkl \
  --report outputs/cpp/cli11/dbscan-tuning.json

.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/cpp/cli11/clusters.pkl \
  --source-root repos/cli11 --require-context \
  --checkpoint outputs/cpp/cli11/idiom-judgment.sqlite3 \
  --output outputs/cpp/cli11/idiom-judgment.pkl \
  --report outputs/cpp/cli11/idiom-judgment-report.json

.venv/bin/python -m src.idiom_synthesis.synthesize_idioms \
  --input outputs/cpp/cli11/idiom-judgment.pkl \
  --input-kind judgment --source-root repos/cli11 \
  --checkpoint results/cpp/cli11/idiom-synthesis.sqlite3 \
  --output results/cpp/cli11/idiom-synthesis.pkl \
  --report results/cpp/cli11/idiom-synthesis-report.json

.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp --dataset outputs/cpp/dataset.pkl \
  --stage synthesis --output results/cpp/eval.json
```

DBSCAN 自动调参和 HDBSCAN 对照入口见[嵌入与聚类](src/mining/README.md)。
正式算法在聚类前统一固定为 DBSCAN；论文中的“改进贝叶斯优化”沿用标准
高斯过程（GP）代理模型和期望改进（EI）采集函数，只把通用目标替换为三指标
领域目标。每个新仓库使用相同的搜索空间与约束，不使用仓库名、人工标签或
最终评价指标。现有26仓结果作为完整 warm-start 观测输入该优化过程，所选
incumbent 是当前观测集和预算下的正式贝叶斯优化参数输出。

关键阶段会在交互式控制台显示进度条，并把事件和错误追加到 `logs/<run-name>.log`。

## 模块入口

- [Parser](src/parser/README.md)
- [嵌入与聚类](src/mining/README.md)
- [单簇习语判断](src/idiom_judgment/README.md)
- [多习语合成](src/idiom_synthesis/README.md)
- [Agent 公共基础设施](src/agents/README.md)
- [评价与 baseline](src/evaluation/README.md)
- [LLM 基础设施](src/llm/README.md)
- [公共基础设施](src/common/README.md)
- [产物工具](src/utils/README.md)

详细设计从[文档索引](docs/README.md)进入；仓库级数据流见[仓库架构](docs/guides/repository-architecture.md)，验证顺序见[测试指南](docs/guides/testing.md)。
