# CodeIdiomMine

CodeIdiomMine 面向 C++ 仓库提取 AST 片段，生成代码嵌入，聚类候选习语，并通过 AutoGen Agent 完成判断与合成。

当前工程基线以仓库现有实现为准：Tree-sitter、预训练代码模型、DBSCAN，以及 `autogen_core` 驱动的判断/合成流水线。论文研究稿用于后续实验设计，不代表当前代码已经实现其中的 Clang、HDBSCAN 或 AST 反统一方案。

项目已固定为仅支持 C++：解析、扫描、节点类型、嵌入和评价入口都不再接受语言参数，也不安装 Python、Java 或 JavaScript 的 Tree-sitter grammar。`repos/cpp`、`outputs/cpp` 和 `results/cpp` 作为既有 C++ 产物路径继续保留。其中 `repos/` 是 Git 忽略的本地源码输入目录，其内容不会随仓库克隆或提交。

## 目录结构

```text
CodeIdiomMine/
├── AGENTS.md                 # 仓库级开发约定
├── README.md                 # 项目入口文档
├── .env.example              # 无密钥的端点与模型分档模板
├── docs/
│   ├── README.md             # 文档索引
│   ├── guides/               # 架构、测试、Agent 与本地基线
│   └── research/             # 论文与研究背景
├── src/
│   ├── agents/               # 通用 Agent 基类与判断/合成 Agent
│   ├── common/               # 共享日志、兼容配置与 C++ 节点类型
│   ├── evaluation/           # 指标计算
│   ├── llm/                  # 统一模型配置、客户端与轻量 Agent 封装
│   ├── mining/               # 嵌入与 DBSCAN 聚类
│   ├── parser/               # Tree-sitter 扫描和 AST 提取
│   └── utils/                # 通用工具
├── tests/                    # 与 src 子包一一对应的自动化测试
├── scripts/                  # 共享基础设施一致性检查
├── repos/                    # 本地输入仓库语料（Git 忽略）
├── outputs/                  # 解析、嵌入和聚类产物（忽略）
├── results/                  # Agent 与评价产物（忽略）
├── logs/                     # 运行日志（忽略）
├── .venv/                    # 项目虚拟环境（忽略）
├── requirements.txt          # 上游依赖下限
└── requirements-local.lock   # 已验证本地环境快照
```

目录按语义和 Python 社区惯例命名，不机械统一单复数：`agents/` 表示多个独立 Agent，`utils/` 是常见工具包名称；`common/`、`evaluation/`、`llm/`、`mining/` 和 `parser/` 表示共享层、流程或领域包。`research/` 使用不可数名词。`tests/` 的七个子目录与 `src/` 完全一致。

首次克隆后请在本地创建 `repos/cpp/`，并自行放入待分析的 C++ 仓库。该目录中的源码、许可证及上游元数据由本地使用者管理，不属于本项目的版本控制内容。

## 本地环境

已验证环境为 Apple Silicon macOS、Python 3.12.10，项目虚拟环境位于 `.venv/`。不要向 macOS 系统 Python 安装依赖。

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt \
  autogen-core 'autogen-ext[openai]' python-dotenv
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -t . -v
```

`requirements.txt` 暂未包含 Agent 依赖；`requirements-local.lock` 是本机成功验证的精确快照，而不是新的上游依赖策略。

## 运行流水线

所有命令都必须从仓库根目录以模块方式执行。直接运行 `python src/...py` 会破坏相对导入。

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos/cpp --output outputs/cpp/dataset.pkl

.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/dataset.pkl --output outputs/cpp/embeddings.pkl \
  --model unixcoder

.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/embeddings.pkl --output outputs/cpp/clusters.pkl

.venv/bin/python -m src.agents.idiom_judgement \
  --input outputs/cpp/clusters.pkl --output-dir results/cpp

.venv/bin/python -m src.agents.idiom_synthesis \
  --input-dir results/cpp --output-dir results/cpp

.venv/bin/python -m src.evaluation.idiom_metrics
```

PKL 保持为阶段间唯一机器接口。需要人工检查时，生成全量汇总与限量 JSON 预览：

```bash
.venv/bin/python -m src.utils.export_artifacts \
  --input-dir outputs/cpp --output-dir outputs/cpp/readables \
  --limit 100 --cluster-top 100
```

解析与嵌入默认各展示前 100 条，聚类按每个项目的簇大小展示 Top100；完整 AST、tensor 和成员列表仍只保存在 PKL 中。
真实 Agent 产物生成后，可追加 `--result-dir results/cpp --stages judgment synthesis`，导出判断与合成的全量摘要和前 100 条预览。

Agent 阶段从根目录 `.env` 读取端点、密钥和 GPT-5.6 模型分档。可从 `.env.example` 复制本地配置；当前所有默认调用只使用低档 `OPENAI_MODEL_LOW=gpt-5.6-luna`，中档 `gpt-5.6-terra` 与高档 `gpt-5.6-sol` 仅作后续显式选择。代码片段会被发送给配置的外部模型服务；运行前应确认端点、成本和数据披露范围。

Agent 业务提示词和说明字段统一使用中文，代码、必要技术术语和 JSON 字段名保留英文。结构化响应使用原生 JSON mode 与显式 JSON Schema；完整响应会被严格解析和校验，失败时由同一模型修复一次，不使用响应标签或 Markdown JSON 猜测。

## 文档与验证

- [文档索引](docs/README.md)
- [仓库架构](docs/guides/repository-architecture.md)
- [评价指标规范](docs/guides/evaluation-metrics.md)
- [两项目共享开发约定](docs/guides/shared-development-conventions.md)
- [提示词优化本地指南](docs/guides/prompt-engineering-guide.md)
- [本地验证指南](docs/guides/testing.md)
- [Agent 子系统](docs/guides/agent-system.md)
- [已验证本地基线](docs/guides/local-baseline.md)

建议先运行低成本检查，再使用最小数据验证各阶段。完整步骤和已知问题见本地验证指南与基线记录。
