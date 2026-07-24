# CodeIdiomMine

当前版本：**CIM 5.5**。

CodeIdiomMine 从 C++ 仓库提取 AST 候选片段，经代码嵌入和 DBSCAN 聚类后，使用 AutoGen Agent 判断代码习语并合成可复用模板。

Parser 遵循零构建解析：被分析项目无需编译、链接或执行，只要源码可读取即可生成 AST、诊断和候选片段。CodeIdiomMine 自身仍需安装 Python 依赖。

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

以下离线命令以本地 `repos/cli11` 为例，并要求 UniXcoder 已在本机缓存；若已获准首次下载模型，可移除 `--local-files-only`。

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos --project cli11 \
  --output outputs/cpp/cli11/dataset.pkl \
  --fragment-output outputs/cpp/cli11/fragments.pkl \
  --embedding-model unixcoder --local-files-only

.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/cli11/fragments.pkl \
  --output outputs/cpp/cli11/embeddings.pkl --model unixcoder

.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/cli11/embeddings.pkl \
  --output outputs/cpp/cli11/clusters.pkl

.venv/bin/python -m src.agents.idiom_judgement \
  --input outputs/cpp/cli11/clusters.pkl --output-dir results/cpp/cli11

.venv/bin/python -m src.agents.idiom_synthesis \
  --input-dir results/cpp/cli11 --output-dir results/cpp/cli11
```

关键阶段会在交互式控制台显示进度条，并把事件和错误追加到 `logs/<run-name>.log`。

## 模块入口

- [Parser](src/parser/README.md)
- [嵌入与聚类](src/mining/README.md)
- [Agent 判断与合成](src/agents/README.md)
- [评价与 baseline](src/evaluation/README.md)
- [LLM 基础设施](src/llm/README.md)
- [公共基础设施](src/common/README.md)
- [产物工具](src/utils/README.md)

详细设计从[文档索引](docs/README.md)进入；仓库级数据流见[仓库架构](docs/guides/repository-architecture.md)，验证顺序见[测试指南](docs/guides/testing.md)。
