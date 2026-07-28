# AGENTS.md

## 跨项目统一开发契约

本仓库与同级仓库保持相互独立，但可复用基础设施必须遵循同一套契约。修改日志、LLM 封装、AutoGen 配置、提示词、目录职责或测试组织方式前，先阅读 `docs/guides/shared-development-conventions.md`；提示词工作还应阅读 `docs/guides/prompt-engineering-guide.md`。共享文件必须在两个仓库中同步更新。

强制约定：

- 项目自有文档统一使用中文，包括 `README.md`、`AGENTS.md` 和 `docs/**/*.md` 的标题、正文、表格说明与图注；仅代码、命令、路径、模型/API 名称、标准缩写、公式、JSON 字段和必要引文保留英文。第三方论文与 `rags/` 等原始检索语料保持来源语言，不得伪装成项目自有中文文档。开发文档统一放在 `docs/guides/`，研究材料统一放在 `docs/research/`；除约定入口文件和带编号的研究稿外，Markdown 文件名使用小写 kebab-case。评估指标、baseline 复现和本地基线分别固定命名为 `evaluation-metrics.md`、`baselines.md` 和 `local-baseline.md`。
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

CodeIdiomMine 用于从 C++ 仓库中挖掘重复出现的代码习语。当前正式流程使用
Tree-sitter C++、预训练代码嵌入、DBSCAN，以及基于规则与 AutoGen 的习语判断
和多习语合成子系统；HDBSCAN 作为阶段2实验对照保留，不进入正式流水线。

当前工程基线是仓库中的既有实现，而不是论文草案中的拟议实现。运行时和公共 CLI
有意仅支持 C++：未经用户明确授权，不得重新引入语言选择器、非 C++ 语法依赖或
语言分派逻辑。除非用户明确授权范围清晰的修改，否则应保留 Tree-sitter C++
解析器、DBSCAN 正式聚类、HDBSCAN 对照实现、Agent 布局、数据 Schema、
提示词、阈值和历史模型设置。

### 最高优先级领域约束：仓库隔离发现与双层知识组织

CodeIdiomMine 不以混合仓库发现或未知仓库泛化为研究目标。目标是针对每一个
给定 C++ 仓库，使用该仓库的全部合格源码，独立发现仓库内部成立的代码习语；
最终知识层再把已接受结果组织为目录化通用习语和仓库专属习语，并保留二者并集
的全量联合视图。目录化通用习语的下游跨仓库汇总与复用不改变发现隔离。该约束
高于研究稿中的旧实验设想，后续实验设计、文档解释和实现判断必须遵守：

1. 仓库是完整、独立的挖掘单元；每个仓库独立执行
   `源码 → Parser → fragments → embedding → DBSCAN → 习语判断 → 习语合成 → 评价`。
2. 不同仓库的候选、embedding 和聚类输入不得混合；多仓库汇总只能在每个仓库
   独立完成指标计算之后发生，例如报告仓库宏平均。
3. embedding、聚类、习语判断和合成之前，不把单个仓库拆成训练集、开发集
   和测试集。DBSCAN 可以且应观察该仓库的全部合格候选；HDBSCAN 对照实验
   也必须使用相同的全仓候选。
4. 不执行留一仓库挖掘，不在发现阶段从其他仓库导入习语实例、候选或判断先验，
   也不把未知仓库泛化作为正式评价或流水线门槛；各仓完成后对目录化通用习语的
   下游汇总、比较和复用不在此限。
5. 最终指标阶段可以对已经完成全仓挖掘的来源位置做确定性文件分区。该分区只
   表示“参考分区/测量分区”，用于测量仓库内部覆盖性、重复性和分区复现性；
   不重新运行 Parser、embedding 或聚类，也不证明独立测试集泛化。
6. 代码或 Schema 中为兼容保留的 `train`、`training`、`test` 字段只表示最终
   评价的参考/测量分区。文档不得把这些名称重新解释为模型训练和未知测试。
7. 正式算法在聚类前固定为 DBSCAN，不得按仓库名或聚类后结果路由算法。
   DBSCAN 参数采用预先冻结的、仅改进领域目标函数的标准贝叶斯规则：代理模型
   固定为高斯过程（GP），采集函数固定为期望改进（EI），warm-start 只用于
   初始化已有观测；每个仓库使用相同搜索空间、硬约束和三指标目标，不得根据
   最终 IC、ISP、F1 或人工标签反复选择。
8. 能够精确对应当前受控目录的已接受结果归为目录化通用习语，以
   `taxonomy_version + catalog_id` 为跨仓库知识聚合键；无法可靠对应的结果归为
   仓库专属习语，以项目和阶段内记录身份保持作用域。不常见但可能通用、尚未进入
   当前目录的习语也按仓库专属习语处理；这是目录版本下的操作性分类，不是对其
   本体性质的永久断言。
9. 跨仓库的通用类型统计和复用只能发生在各仓库独立完成挖掘之后，属于下游知识
   组织，不得反向混合候选、embedding、聚类输入或 Agent 判断证据，也不构成未知
   仓库泛化实验。最终报告可分别分析目录化通用习语、仓库专属习语及二者并集。

任何把 split manifest、聚类前数据划分或留一仓库实验恢复为正式流程硬门槛
的修改，均视为违反项目目标。历史兼容入口可以保留，但必须显式标注为非正式。

### 零构建解析原则

Parser 的长期架构不变量是：**免目标项目编译、免链接、免执行，源码可得即可解析**。本文档将其简称为零构建解析（Zero-Build Parsing, ZBP）。这里的“开箱即用”是指安装 CodeIdiomMine 自身依赖后，任意可读取的 C/C++ 源码快照都能直接进入 `源码 → AST → 基于 AST 的模式分析 → 原文片段` 主链路；它不表示项目零安装，也不保证任一抽取片段脱离上下文后可以独立编译或运行。

后续 Parser 修改必须遵守以下约束：

- 不得把目标仓库的 CMake/Make/Ninja 配置成功、依赖安装、代码生成、完整编译、链接、测试或程序执行设为解析前置条件，也不得为了“发现配置”而执行不可信项目脚本；
- Tree-sitter C++ 的静态源码路径必须始终可独立产出基础 AST、诊断、原文映射和三种粒度候选；单文件异常只能被记录和降级，不能因项目不可构建而整体遗漏；
- 已存在的 `compile_commands.json`、Clang 语义信息或可信隔离环境中的 `clang++ -fsyntax-only` 只能作为可选增强或下游模板验证。缺失或失败时必须保留零构建结果及明确能力标记，不能静默丢弃文件；
- 论文应把 ZBP 同时解释为部署约束和方法级可复用性：解析方法无需为每个仓库复现专用构建环境，因而能迁移到宏密集、依赖不全、平台不匹配及不完整源码；不得把可选 Clang 增强写成全量语料的强制门槛。

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

代码异味与 C++ 习语分类的文献事实及全局稳定编号由同级
`thesis/references/library.json` 统一维护，本仓库不得建立文献库副本。相关文档
只链接 thesis 的中英文文献库；运行时审计来源只保存 thesis 编号、资料名称和
官方 URL。

文档发生冲突时，优先采用已验证的源码行为，其次采用上述指南。应将已确认的差异记录到 `docs/guides/local-baseline.md`，不得静默改写行为。

目录名称应根据语义职责和既有 Python 约定选择，不得机械地全部使用复数。源码包包括 `agents`、`common`、`evaluation`、`idiom_judgment`、`idiom_synthesis`、`llm`、`mining`、`parser` 和 `utils`；其中 `agents` 与 `utils` 有意使用复数，流程或领域包使用单数。`idiom_judgment` 表示单簇规则/LLM 判断，`idiom_synthesis` 表示多习语上下文感知合成；不得用 `stage3`、`stage4` 等仅表达顺序的包名替代。`research` 是不可数名词。集合或产物根目录沿用 `tests`、`repos`、`outputs`、`results`、`logs` 和 `guides`。保留 `src` 作为常规源码根目录缩写，`cpp` 作为语言限定词，`.venv` 作为约定的虚拟环境名称。测试子目录必须与九个 `src` 包逐一对应。

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

所有功能都应从仓库根目录以模块方式运行。直接执行 `python src/...py` 会破坏相对导入。启动命令只维护在根 `README.md`、`repos/README.md` 及 `src/*/README.md`，详细设计文档和本文件只引用这些入口。

## 验证层级

优先执行成本最低且与改动相关的检查：

1. `.venv/bin/python -m pip check`。
2. `.venv/bin/python -m compileall -q src`。
3. `.venv/bin/python -m unittest discover -s tests -t . -v`。
4. 导入受影响的包，并运行受影响模块的 `--help` 入口。
5. 先使用最小仓库输入，再完整处理 `repos`。
6. 尽可能复用已缓存的 UniXcoder 模型。在当前解析的依赖栈中，全新机器需要向 Hugging Face 缓存下载约 738 MB。
7. 先在最小嵌入数据上运行 DBSCAN 自动调参并验证统一 Schema、三指标权重与
   硬约束；需要复核阶段2对照时再运行 HDBSCAN。DBSCAN 历史 `--optimize`
   仅优化轮廓系数；正式方案沿用标准 GP 与 EI，只将目标替换为冻结的三指标
   领域目标。
8. Agent 冒烟测试可以使用确定性的假模型客户端验证路由和 Schema。真实判断与合成需要 `OPENAI_API_KEY`，并会发起付费网络调用；运行前必须说明模型、调用次数、可能成本和隐私影响。

仓库在 `tests/` 下提供离线 `unittest` 测试套件。其子目录与 `src/` 对应；默认测试必须可确定复现，且不得下载模型或发起付费 API 调用。

## 敏感信息与外部服务

- 根目录 `.env` 已被忽略，当前包含本地中转服务凭据，以及 `OPENAI_MODEL_LOW=gpt-5.6-luna`、`OPENAI_MODEL_MEDIUM=gpt-5.6-terra` 和 `OPENAI_MODEL_HIGH=gpt-5.6-sol`。不得打印、提交或将密钥值与端点值复制到日志或文档；`.env.example` 中只能保留占位符。
- 当前代码仅默认使用 `OPENAI_MODEL_LOW`；未经后续任务明确授权，不得选择中档或高档模型。
- 将源码片段发送到 LLM 端点应视为对外披露。对非公开代码使用前，必须确认端点和数据范围。
- 下载新的嵌入模型前，应说明下载大小和运行时间。未经明确授权，不得下载 CodeLLaMA，也不得执行完整仓库嵌入或参数优化。

## 已确认的架构与数据契约

- 解析器输出 `dataset.pkl`：DataFrame 列为 `project`、`cppFile`、`func_ast`、`func_src`。`cppFile` 保留为历史 C++ 路径字段。
- Parser 模型输入输出 `fragments.pkl`：保存 `fragment_schema_version`、目标 tokenizer、token 预算、对齐的 `fragment_src`/`fragment_info`、超限拒绝清单和降级统计。真实 embedding 不再直接读取 `dataset.pkl`。
- Parser 映射合同为 v2：所有 AST 节点保留原始 `start_byte`、`end_byte` 和未经清洗的 `code_snippet`；函数根保存稳定文件身份、内容哈希、解析来源和可选 Def-Use 语义切片。`repo2data` 同时写出覆盖全部扫描文件的 `dataset.audit.json`，但不改变四列 pickle Schema。
- Parser 片段构建默认使用 `quality-v2` 候选 profile，仍只输出函数、区域和语句三种粒度；局部 Def-Use 切片以区域候选和 `candidate_origin=semantic_def_use` 表示。`legacy` profile 只用于历史数据集的候选选择兼容。
- 嵌入输出 `embeddings.pkl`：DataFrame 列为 `pros_name`、`pros_src`、`pros_emb`、`pros_info`；嵌入是位于 CPU 的 `torch.Tensor` 对象。
- 聚类输出 `clusters.pkl`：由 `{pros_name, clusters}` 构成的列表；聚类
  DataFrame 列为 `label`、`center_point`、`else_point`、`cluster_size`、
  `center_point_info`、`infos`、`loc_label`。正式产物使用 DBSCAN；
  HDBSCAN 对照产物可以附加 `clustering_metadata`，但不得改变下游必需字段。
- 习语判断输出 `idiom-judgment.pkl`：按簇保存 `accepted` 和 `rejected`，离线规则预检另存 `pending_llm`；记录规则证据、保守抽象提案、完整簇、经哈希验证的代表函数/区域上下文、LLM 的 `is_idiom` 与 `abstract/keep` 决策、实际批准集合、受控通用类型或 `仓库特有习语` 的分类、语义/类型/异味理由、最终裁决理由、语义/复用价值业务评分，以及与业务评分分离的共享代码异味审查输入、分类发现和独立门禁。拒绝抽象只表示保持代表代码不变，不得据此拒绝本来合格的习语；`agent_trace` 记录各 Agent 的逻辑尝试数、技术失败类型和回退动作。
- 习语合成输出 `idiom-synthesis.pkl`：正式消费习语判断的已接受产物，是只记录合成尝试及成功结果、不复制未合成阶段3习语的 `synthesis_delta`；只按完全相同的代表 `project + file + function_extent` 分组，以顶层 `source_judgments` 携带来源阶段3理由与类型，保存自动同区域上下文证据、合成计划、组装证据、对当前合成结果重新执行的 `is_idiom` 与习语类型判断、规划/组装/质量/类型/异味理由、最终裁决理由、质量复审业务分、与阶段3同合同但独立执行的代码异味审查输入/分类发现/门禁、确定性检查、`agent_trace`、`source_infos` 和 `synthesis_trace`。阶段2适配只保留合同和后备逻辑验证，不进入正式 CLI 或实际实验执行。
- 评估输出 `eval.json`：包含各项目及汇总的 `IC`、`ISP`、`F1`、`avg_idiom_size`。

上述阶段产物必须按仓库隔离保存和消费。评价器正式默认使用仓库内参考/测量文件
分区；`leave_one_project_out` 只为历史产物兼容保留。

习语判断直接使用 `autogen_core`：确定性规则先拒绝合同无效和确定性低价值簇，抽象规则只对至少3个结构对齐实例中至少3个不同取值、覆盖率至少60%的局部变量或低语义字面量提出候选，调用名、类型、控制条件、返回值和哨兵值不得仅因变化而抽象；随后语义/抽象 Agent 必须读取完整簇成员、规则证据、全部提案和自动加载的代表函数/区域上下文，显式返回 `is_idiom`、非空判断理由、`abstract` 或 `keep`，且只能批准规则候选。最终有效性判断使用 `src.idiom_judgment.idiom_taxonomy` 的受控目录；能精确对应时输出通用类型，不能对应但仍通过全部门禁时输出 `仓库特有习语`，不得强行匹配。正式运行使用严格上下文门禁，路径、范围或 `source_sha256` 失败时零调用拒绝。有效响应中的 `keep` 或无提案均保留代表代码不变，候选仍按语义/复用价值和异味门禁判断是否进入阶段4；整份语义/抽象响应失败时保留原代码作为审计证据，但业务分安全降级并拒绝。规则、语义和复用价值形成业务分，异味不进入业务分；分类风险达到冻结阈值或异味分析失败时由独立门禁直接拒绝。所有承担有效性、选择或生成判断的 Agent 都必须输出非空理由。

习语合成使用独立 runtime，正式接受习语判断已接受产物；阶段2簇到同一内部候选 Schema 的适配和严格阈值只作不启动正式 Agent 的合同验证。编排层在任何 LLM 调用前自动加载并验证同区域上下文；合成规划、代码组装、质量/有效性/类型复审和与阶段3相同的共享异味审查通过路由消息协作。只能合成同仓库完全相同代表函数/区域内至少两个具有数据、控制、生命周期或稳定顺序关系的习语，不得扩大到跨区域。候选超过显式上限时不得静默截断。核心确定性门禁只检查上下文合同、Tree-sitter 语法和新增调用目标。质量复审必须重新判断当前合成结果是否属于习语并重新分类，不能直接继承阶段3类型；质量分单独决定业务质量，异味按同一分类和阈值重新审查当前合成代码并可独立否决。阶段3和阶段4的异味过滤必须以分层人工审计报告总体、分阶段和逐类别准确性。

`src/llm/` 负责共享配置、模型客户端工厂、严格 JSON 解析、轻量 Schema 校验和单次 LLM 修复。习语判断与合成流程使用其底层 AutoGen 客户端；C++ 习语提示词、领域 Schema、阈值和编排逻辑分别归属 `src/idiom_judgment/` 与 `src/idiom_synthesis/`，`src/agents/` 只保留当前流程实际复用的 Agent 基类和注册函数。

阶段3/4的 `JsonLLMAgent` 单次调用超时120秒，每条消息最多执行2次逻辑尝试；每次尝试内部仍只允许
共享 `src.llm` 完成1次 JSON 修复，因此单个 Agent 最多产生4次端点请求。只有
请求异常或 JSON 修复耗尽才重试，业务上的 `keep`、拒绝或低分不得重试。全部
尝试失败后按 Agent 职责安全拒绝当前簇/组或跳过下游 Agent，不能中断其余批次；
取消信号和进程中断不得吞掉。
长时付费运行应使用 SQLite checkpoint；续跑必须校验输入哈希、模型、上下文根和
关键参数。最终产物保存提示词版本/哈希、决策政策、token 用量和校准状态；完成
人工 pilot 前不得把 synthetic smoke 写成阈值已冻结。

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
