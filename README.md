# CodeIdiomMine

当前版本：**CIM 5.5**

CodeIdiomMine 面向 C++ 仓库提取 AST 片段，生成代码嵌入，聚类候选习语，并通过 AutoGen Agent 完成判断与合成。

当前工程基线以仓库现有实现为准：Tree-sitter、预训练代码模型、DBSCAN，以及 `autogen_core` 驱动的判断/合成流水线。论文研究稿用于后续实验设计，不代表当前代码已经实现其中的 Clang、HDBSCAN 或 AST 反统一方案。

项目已固定为仅支持 C++：解析、扫描、节点类型、嵌入和评价入口都不再接受语言参数，也不安装 Python、Java 或 JavaScript 的 Tree-sitter grammar。`repos/cpp`、`outputs/cpp` 和 `results/cpp` 作为既有 C++ 产物路径继续保留。其中 `repos/` 是 Git 忽略的本地源码输入目录，其内容不会随仓库克隆或提交。

## 核心理念：源码可得即可解析

CodeIdiomMine 的 Parser 遵循**零构建解析（Zero-Build Parsing, ZBP）**原则：
对被分析的目标 C++ 项目，免编译、免链接、免执行，只要源码可读取就能直接生成
AST、逐文件诊断、原文映射和候选片段。这使宏密集、依赖缺失、平台不匹配、
无法复现构建环境或尚未写完整的源码仍能进入统一审计，而不会因一个构建错误使
整个仓库消失。

“开箱即用”针对的是 Parser 对输入项目的采用成本，并不等于 CodeIdiomMine
自身无需安装依赖，也不表示每个原文片段脱离项目上下文后天然可独立编译。
Parser 不运行目标仓库的构建脚本、包管理器、测试或二进制。现成的
`compile_commands.json`、Clang 语义信息和可信隔离环境中的静态编译检查可以
作为增强或下游模板验证，但缺失或失败时不能阻断 Tree-sitter 主链路，也不能
静默删除基础候选。这个约束既是安全边界，也是论文“可复用性”的组成部分：
被复用的不只是挖掘出的习语，还包括无需逐项目重建专用编译环境的解析方法。

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
  --input repos/cpp --output outputs/cpp/dataset.pkl \
  --fragment-output outputs/cpp/fragments.pkl \
  --embedding-model unixcoder --local-files-only

.venv/bin/python -m src.parser.audit \
  --source-root repos/cpp \
  --dataset outputs/cpp/dataset.pkl \
  --candidate-profile quality-v2 \
  --output outputs/cpp/parser-audit.json

.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/fragments.pkl --output outputs/cpp/embeddings.pkl \
  --model unixcoder --candidate-profile quality-v2

.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/embeddings.pkl --output outputs/cpp/clusters.pkl

.venv/bin/python -m src.agents.idiom_judgement \
  --input outputs/cpp/clusters.pkl --output-dir results/cpp

.venv/bin/python -m src.agents.idiom_synthesis \
  --input-dir results/cpp --output-dir results/cpp

.venv/bin/python -m src.evaluation.idiom_metrics
```

Parser 会在 `dataset.pkl` 旁写出覆盖所有扫描文件的
`dataset.audit.json`，其中包含 `ERROR`、missing、未覆盖源码和宏恢复证据。
主数据集仍保持四列 Schema；AST 节点和 quality-v2 候选保留原始字节范围，
不再删除注释或空行。长函数和区域可以额外产生局部 Def-Use 语义核心，
但下游粒度仍只有函数、区域和语句三种。

`fragments.pkl` 由 Parser 阶段针对目标 tokenizer 生成。默认 UniXcoder 总输入
上限为 512 tokens，超长函数或区域会降级为合格区域、Def-Use 或语句，所有拒绝
都有可追溯记录。embedding 只接受该 model-ready 产物并禁止静默截断。复杂 C++
语法和长度治理详见
[C++ Adapter 与模型输入治理](docs/guides/cpp-adapter-and-model-input.md)。
设计、指标和全量结果另见
[Parser v2 设计](docs/guides/parser-design.md)与
[Parser 基线对比](docs/guides/parser-quality-report.md)。

PKL 保持为阶段间唯一机器接口。需要人工检查时，生成全量汇总与限量 JSON 预览：

```bash
.venv/bin/python -m src.utils.export_artifacts \
  --input-dir outputs/cpp --output-dir outputs/cpp/readables \
  --limit 100 --cluster-top 100
```

解析与嵌入默认各展示前 100 条，聚类按每个项目的簇大小展示 Top100；这些文件仅是人工预览，不参与任何 baseline 或 CIMAS-CPP 的最终习语数量选择，完整 AST、tensor 和成员列表仍只保存在 PKL 中。
真实 Agent 产物生成后，可追加 `--result-dir results/cpp --stages judgment synthesis`，导出判断与合成的全量摘要和前 100 条预览。

Agent 阶段从根目录 `.env` 读取端点、密钥和 GPT-5.6 模型分档。可从 `.env.example` 复制本地配置；当前所有默认调用只使用低档 `OPENAI_MODEL_LOW=gpt-5.6-luna`，中档 `gpt-5.6-terra` 与高档 `gpt-5.6-sol` 仅作后续显式选择。代码片段会被发送给配置的外部模型服务；运行前应确认端点、成本和数据披露范围。

Agent 业务提示词和说明字段统一使用中文，代码、必要技术术语和 JSON 字段名保留英文。结构化响应使用原生 JSON mode 与显式 JSON Schema；完整响应会被严格解析和校验，失败时由同一模型修复一次，不使用响应标签或 Markdown JSON 猜测。

## 文档与验证

- [文档索引](docs/README.md)
- [仓库架构](docs/guides/repository-architecture.md)
- [Parser v2 设计与使用](docs/guides/parser-design.md)
- [C++ Adapter 与模型输入治理](docs/guides/cpp-adapter-and-model-input.md)
- [Parser 基线与优化对比](docs/guides/parser-quality-report.md)
- [Parser 代表性产物审计](docs/guides/parser-artifact-audit.md)
- [Parser 风险与限制](docs/guides/parser-risks.md)
- [评价指标规范](docs/guides/evaluation-metrics.md)
- [baseline 复现与统一评价](docs/guides/baselines.md)
- [两项目共享开发约定](docs/guides/shared-development-conventions.md)
- [提示词优化本地指南](docs/guides/prompt-engineering-guide.md)
- [本地验证指南](docs/guides/testing.md)
- [Agent 子系统](docs/guides/agent-system.md)
- [已验证本地基线](docs/guides/local-baseline.md)

建议先运行低成本检查，再使用最小数据验证各阶段。完整步骤和已知问题见本地验证指南与基线记录。
