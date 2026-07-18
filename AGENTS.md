# AGENTS.md

## 跨项目统一开发契约

本仓库与同级仓库保持相互独立，但可复用基础设施必须遵循同一套契约。修改日志、LLM 封装、AutoGen 配置、提示词、目录职责或测试组织方式前，先阅读 `docs/guides/shared-development-conventions.md`；提示词工作还应阅读 `docs/guides/prompt-engineering-guide.md`。共享文件必须在两个仓库中同步更新。

强制约定：

- 使用 `repos/` 存放本地源码仓库输入，`outputs/` 存放可复现的中间产物，`results/` 存放最终产物，`logs/` 存放运行日志，`tests/` 存放测试，`docs/` 存放纳入版本控制的文档。`repos/` 必须保持忽略且不受 Git 跟踪；不要增加重复的 `inputs/` 别名。
- 新日志代码统一使用 `from src.common.logging import get_logger`。同一命令的所有模块日志均以追加方式写入 `logs/<run-name>.log`；`src.logger` 仅用于兼容旧代码。
- LLM 代码统一从 `src.llm` 导入共享 API。根目录 `.env` 加载、模型档位、GPT-5.6 元数据、客户端创建、JSON 模式、Schema 校验、单次 JSON 修复及客户端关闭逻辑都必须集中在该包中。只有低档模型可以作为隐式默认值。
- 业务提示词和解释性字段使用中文；仅代码、模型/API 名称、必要技术术语及 JSON 字段名保留英文。结构化调用使用 `build_json_system_prompt(...)` 构建稳定的系统提示词，启用原生 JSON 模式并提供明确的 JSON Schema；不得使用 `[JSON]` 或领域标记包装响应。
- AutoGen 代码统一使用 `SingleThreadedAgentRuntime`、强类型消息、`BaseRoutedAgent`、`register_agent(...)`、`default_agent_id(...)`，并遵循 `start -> try/finally -> stop` 生命周期。Agent 之间通过路由消息通信。
- 离线测试必须可确定复现，且不得触发下载或付费调用。真实 LLM 测试必须明确模型、限制调用次数、审查成本与隐私，并将冒烟测试产物单独存放。
- 修改共享文件后，运行 `.venv/bin/python scripts/check_shared_infrastructure.py --other ../<sibling>`。两个项目可以保留各自已验证的 Python 次版本和领域依赖。

## 提示词开发规范

- 日常新增、修改、重写或评审 LLM 提示词时，先阅读本地 `docs/guides/prompt-engineering-guide.md`，无需每次访问官网。
- 目标模型/API 变化、用户要求最新实践、出现无法解释的持续回归或准备冻结正式实验配置时，使用 `$openai-docs` skill 刷新本地指南，并同步两个仓库。
- 官方指南是模型能力与 API 行为的最终来源；本地指南负责保存已经采用的稳定实践。两者都必须服从项目实际配置、领域契约和用户明确要求，不得假设项目必须使用 GPT-5.6。
- 需要刷新但 `$openai-docs` 不可用时，应明确说明，并基于本地指南继续处理。

本文件适用于整个 `/Users/sophon/Codex/CodeIdiomMine` 仓库。

## 项目使命与范围

CodeIdiomMine 用于从 C++ 仓库中挖掘重复出现的代码习语。当前实现使用 Tree-sitter C++、预训练代码嵌入、DBSCAN，以及基于 AutoGen 的判断与合成子系统。

当前工程基线是仓库中的既有实现，而不是论文草案中的拟议实现。运行时和公共 CLI 有意仅支持 C++：未经用户明确授权，不得重新引入语言选择器、非 C++ 语法依赖或语言分派逻辑。除非用户明确授权范围清晰的修改，否则应保留 Tree-sitter C++ 解析器、DBSCAN 聚类、Agent 布局、数据 Schema、提示词、阈值和历史模型设置。

以下纳入版本控制的研究文档是必要背景资料，但不是当前实现规范：

- `docs/research/01_C++代码习语挖掘研究稿.md`——拟议的 C++ 论文路线、实验、基线、消融和指标。
- `docs/research/03_面向代码可复用性增强的融合研究方案.md`——论文层面 CodeIdiomMine 与 WPF2React 的关系。两个仓库仍保持独立，不得仅因论文同时讨论二者就合并仓库。

## 必读资料与事实来源

修改行为前，应阅读相关源码以及：

1. `AGENTS.md` 和 `README.md`。
2. `docs/guides/shared-development-conventions.md`，了解与 WPF2React 共享的契约。
3. `docs/guides/prompt-engineering-guide.md`，了解本地提示词设计、JSON 契约和刷新条件。
4. `docs/guides/local-baseline.md`，了解已验证的本地环境和证据。
5. `docs/guides/repository-architecture.md`，了解仓库级架构。
6. `docs/guides/agent-system.md` 和 `docs/guides/agent-contracts.md`，了解 Agent 设计与修改契约。
7. `docs/guides/testing.md`，了解验证层级和当前命令。
8. 当任务涉及论文对齐时，阅读上述两份研究文档。

文档发生冲突时，优先采用已验证的源码行为，其次采用上述指南。应将已确认的差异记录到 `docs/guides/local-baseline.md`，不得静默改写行为。

目录名称应根据语义职责和既有 Python 约定选择，不得机械地全部使用复数。源码包包括 `agents`、`common`、`evaluation`、`llm`、`mining`、`parser` 和 `utils`；其中 `agents` 与 `utils` 有意使用复数，流程或领域包使用单数。`research` 是不可数名词。集合或产物根目录沿用 `tests`、`repos`、`outputs`、`results`、`logs` 和 `guides`。保留 `src` 作为常规源码根目录缩写，`cpp` 作为语言限定词，`.venv` 作为约定的虚拟环境名称。测试子目录必须与七个 `src` 包逐一对应。

## 本地 Python 环境

- 主机：Apple Silicon macOS（`arm64`）。
- 系统 Python：`/usr/bin/python3` 3.9.6。不得修改，也不得向其中安装项目依赖。
- 选用解释器：Homebrew Python 3.12.10，路径为 `/opt/homebrew/bin/python3.12`。
- 项目环境：`/Users/sophon/Codex/CodeIdiomMine/.venv`。
- 使用 `source .venv/bin/activate` 激活环境，或显式调用 `.venv/bin/python`。
- 如果环境不存在，使用 `/opt/homebrew/bin/python3.12 -m venv .venv` 创建。
- `requirements.txt` 是 C++ 流水线和 Agent 技术栈共同采用的安装策略；必须保留 `autogen-ext[openai]`，而不是不带 extra 的基础包，因为共享客户端需要导入 OpenAI 适配器。
- `requirements-local.lock` 是 2026-07-15 本地环境的精确快照。未经用户批准，不得将其视为上游依赖策略；只有在有意变更环境且验证成功后才能更新。

选择 Python 3.12 是因为现有完整技术栈在 arm64 上具有成熟的 wheel。规范化前的仓库文档曾提到 Python 3.14，但未选择该版本：本地 Homebrew 没有 `python@3.14` formula，仓库也没有必须使用 3.14 的功能。候选版本比较和证据见 `docs/guides/local-baseline.md`。

## 运行项目

所有功能都应从仓库根目录以模块方式运行。直接执行 `python src/parser/repo2data.py` 会破坏相对导入。

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

`src/utils/pkl2csv.py` 可通过 `.venv/bin/python -m src.utils.pkl2csv ...` 运行。

## 验证层级

优先执行成本最低且与改动相关的检查：

1. `.venv/bin/python -m pip check`。
2. `.venv/bin/python -m compileall -q src`。
3. `.venv/bin/python -m unittest discover -s tests -t . -v`。
4. 导入受影响的包，并运行受影响模块的 `--help` 入口。
5. 先使用最小仓库输入，再完整处理 `repos/cpp`。
6. 尽可能复用已缓存的 UniXcoder 模型。在当前解析的依赖栈中，全新机器需要向 Hugging Face 缓存下载约 738 MB。
7. 先在最小嵌入数据上运行 DBSCAN，再启用 `--optimize`（50 次贝叶斯优化调用）。
8. Agent 冒烟测试可以使用确定性的假模型客户端验证路由和 Schema。真实判断与合成需要 `OPENAI_API_KEY`，并会发起付费网络调用；运行前必须说明模型、调用次数、可能成本和隐私影响。

仓库在 `tests/` 下提供离线 `unittest` 测试套件。其子目录与 `src/` 对应；默认测试必须可确定复现，且不得下载模型或发起付费 API 调用。

## 敏感信息与外部服务

- 根目录 `.env` 已被忽略，当前包含本地中转服务凭据，以及 `OPENAI_MODEL_LOW=gpt-5.6-luna`、`OPENAI_MODEL_MEDIUM=gpt-5.6-terra` 和 `OPENAI_MODEL_HIGH=gpt-5.6-sol`。不得打印、提交或将密钥值与端点值复制到日志或文档；`.env.example` 中只能保留占位符。
- 当前代码仅默认使用 `OPENAI_MODEL_LOW`；未经后续任务明确授权，不得选择中档或高档模型。
- 将源码片段发送到 LLM 端点应视为对外披露。对非公开代码使用前，必须确认端点和数据范围。
- 下载新的嵌入模型前，应说明下载大小和运行时间。未经明确授权，不得下载 CodeLLaMA，也不得执行完整仓库嵌入或参数优化。

## 已确认的架构与数据契约

- 解析器输出 `dataset.pkl`：DataFrame 列为 `project`、`cppFile`、`func_ast`、`func_src`。`cppFile` 保留为历史 C++ 路径字段。
- 嵌入输出 `embeddings.pkl`：DataFrame 列为 `pros_name`、`pros_src`、`pros_emb`、`pros_info`；嵌入是位于 CPU 的 `torch.Tensor` 对象。
- 聚类输出 `clusters.pkl`：由 `{pros_name, clusters}` 构成的列表；聚类 DataFrame 列为 `label`、`center_point`、`else_point`、`cluster_size`、`center_point_info`、`infos`、`loc_label`。
- 判断输出 `{repo}_idiom.pkl`：记录包含 `center_point`、`info`、`cnt`、`avg_ast_num`、`loc_label`。
- 合成输出 `{repo}_idiom_syn.pkl`：增加 `source_infos`、`merge_rounds` 和 `synthesis_trace`。
- 评估输出 `eval.json`：包含各项目及汇总的 `IC`、`ISP`、`F1`、`avg_idiom_size`。

Agent 子系统直接使用 `autogen_core`。判断流程并发运行语义 Agent 和语法 Agent，随后调用判断 Agent。最终 `is_idiom` 由 `patent_programming_pattern_valid` 决定：较高分必须至少为 70，较低分必须至少为 50。LLM 原始判断仅用于解释。合成流程使用独立 runtime 和第二套静默判断流水线；最多执行三轮合并，只保留成功合并的结果。

`src/llm/` 负责共享配置、模型客户端工厂、严格 JSON 解析、轻量 Schema 校验和单次 LLM 修复。判断与合成流程使用其底层 AutoGen 客户端，而 `src/agents/` 负责所有 C++ 习语提示词、领域 Schema、阈值和编排逻辑。

## 本地产物与已知现象

- 可长期保留的最小 C++ 解析器、真实 UniXcoder 和 DBSCAN 产物位于已忽略的 `outputs/baselines/cpp/`。
- 假客户端 Agent 与评估产物位于已忽略的 `results/baseline-stubs/cpp/`，绝不能作为研究结果。
- 有界的真实 LLM 冒烟测试只使用合成代码片段。输入和可读证据位于已忽略的 `outputs/llm-smoke/`；判断、合成输入和合成输出位于已忽略的 `results/llm-smoke/`。这些内容只能证明端点连通性和 Schema，不属于研究结果。
- 同一命令中的所有模块都向已忽略的 `logs/<run-name>.log` 追加日志；导入同级包不再截断已有证据。仅当自动入口命名不足时，才使用 `APP_LOG_NAME` 或 `run_name=`。
- 运行部分 `python -m` 入口时会出现 `runpy` 警告，因为包的 `__init__.py` 会提前导入同一目标模块。这些入口已通过基线测试；没有明确的源码修改请求时，不要处理该问题。

完整命令、版本、结果、阻碍和研究差异统一记录在 `docs/guides/local-baseline.md`。后续任务改变已验证基线时，应更新该文件。

## 修改纪律

- 修改前后都要检查 Git 状态，并保留用户已有变更。
- 不得仅为通过冒烟测试而修改算法、提示词、评分阈值、pickle Schema 或语料过滤规则。
- 不得根据研究草案推断并执行大范围重构。只有用户给出具体范围后，才能开始论文对齐工作。
- 每次实验都要保存命令、版本、输入范围、输出路径和失败信息。Mock 或 stub 产物必须清晰标注。
- 除非用户明确要求，否则不得暂存、提交或推送文件。
