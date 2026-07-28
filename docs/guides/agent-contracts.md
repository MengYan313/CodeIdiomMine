# 习语判断与合成开发契约

设计见 [`agent-system.md`](agent-system.md)。修改相关代码时必须遵守以下合同。

## 公共 Agent 基础设施

- 统一使用 `src.agents.base.BaseRoutedAgent`、`register_agent(...)` 和
  `default_agent_id(...)`。
- JSON Agent 复用 `src.agents._base.JsonLLMAgent`；业务提示词使用
  `build_json_system_prompt(...)`，声明完整 `_RESPONSE_SCHEMA`。
- Runtime 使用 `SingleThreadedAgentRuntime`、强类型 dataclass 消息和
  `start → try/finally → stop/close` 生命周期。
- 未显式选模型时只能使用低档模型。失败回退必须是拒绝或停止，不能静默接受。
- 每个 `JsonLLMAgent` 最多执行2次逻辑尝试；每次尝试由共享 `src.llm` 完成
  严格解析、Schema 校验和至多1次 JSON 修复。只有请求异常或修复耗尽才重试，
  有效业务拒绝不得重试；单次调用超时为120秒，单个 Agent 的端点请求硬上限为4。
- 每条正式记录必须保存 `agent_trace.status`、`logical_attempts`、
  `failure_kind` 和 `failure_action`。技术失败不写入业务分，也不得伪装成
  `keep`、无异味或“无需合成”。
- 每个承担选择、生成、语义判断、质量判断或异味审查的 Agent 都必须返回非空中文
  `reason`。领域载荷缺少理由时必须标记技术失败并安全拒绝或停止，不能把空理由
  写入正式审计链。

## `idiom_judgment` 不变量

- 一次只处理一个仓库的单个聚类产物，禁止跨仓证据。
- 确定性规则先于 LLM；合同无效和确定性低价值簇不得消耗 LLM 调用。
- 默认抽象至少需要3个对齐实例、3个不同取值和60%支持率。
- 调用名、类型、控制条件、返回值、哨兵值和格式字符串不得只因变化而自动抽象。
- 规则只负责筛出可能抽象的位置；语义/抽象 Agent 必须接收完整簇成员、规则初判
  和全部提案，并显式返回 `is_idiom`、`abstract` 或 `keep`、判断理由及
  `idiom_classification`。
- `is_idiom=false` 是业务硬拒绝。`is_idiom=true` 时只能选择受控目录中的
  `cataloged` 类型，或在无法可靠对应时选择 `repository_specific` 并输出
  `仓库特有习语`；不得把未知目录编号、空理由或自相矛盾字段当作有效响应。
- `abstract` 只能批准规则给出的 `proposal_id`，由确定性代码应用其交集；
  有效响应中的 `keep` 或无提案必须保留代表代码不变，不得单独导致习语被拒绝。
- 整份语义/抽象响应经修复与有界重试后仍失败时，保留原代码作为审计证据，但
  语义与复用分必须安全降为0并拒绝，不能把技术失败伪装成正常的 `keep`。
- 语义/复用价值与异味 Agent 并行；阶段3必须为当前簇单独发起异味请求。
- 正式运行应自动加载并哈希校验代表函数/区域上下文，同时提供给语义/抽象和异味
  Agent；严格上下文模式失败时必须零调用拒绝，不得回退到未经验证源码。
- 任一并行 Agent 失败不得取消另一分支；语义/抽象失败按业务0分拒绝，异味失败
  按独立门禁拒绝。Runtime 路由失败采用同一回退，未预料的单簇编排异常记录为
  `skip_cluster` 后继续处理后续簇。
- 最终产物只允许 `accepted` 与 `rejected`。业务 `scorecard` 只按规则20%、
  语义45%和复用35%计算；异味不得进入业务总分。
- Schema v7 必须保存标准化 `idiom_classification`、语义/类型/异味
  `agent_reasons` 和汇总后的 `decision_reason`；分类不进入业务分。
- 异味只输出固定分类表内的结构化 findings；风险分由确定性代码计算。
  `risk_score >= 60` 或分析失败时，独立 `smell_gate` 必须覆盖业务结论并拒绝。
- `--rule-only` 产物必须为 `pending_llm`，不得进入正式合成的 `accepted` 输入。

## `idiom_synthesis` 不变量

- 正式 CLI 只消费习语判断已接受产物；阶段2适配分支仅用于
  验证它能够归一化为同一 Schema，不启动正式阶段4 Agent。
- 只合成同一函数/区域内至少两个候选，不按仓库名或纯 embedding 相似度路由。
- 区域身份固定为代表位置的 `project + file + function_extent`；不得使用其他成员
  位置、跨区域共现或语义相似度扩大合成分组。
- 阶段4是 `synthesis_delta`，只保存合成尝试和成功增量；不得复制未合成的阶段3
  习语作为 passthrough，也不得把缺少 passthrough 解释为数据丢失。
- 正式 CLI 必须提供 `--source-root`；编排层在 LLM 调用前自动读取候选所在函数，
  并通过路径边界和 `source_sha256` 校验，失败时零调用拒绝。
- 规划 Agent 只选择与排序，组装 Agent 才能生成代码；二者均须输出非空理由。
- 组装不得引入输入习语或允许上下文不存在的调用与业务操作。
- 同区域候选超过显式上限时不得静默截断；必须零调用拒绝并要求提高上限。
- 核心确定性门禁只检查已验证上下文、Tree-sitter 语法和新增调用目标；失败时
  跳过两个复审 Agent。
- 规划技术失败时拒绝并跳过当前组的组装与复审；组装技术失败、空输出、语法失败
  或出现不受支持调用时拒绝并跳过质量/异味复审，避免无意义调用。
- 质量复审和异味审查并行；异味审查必须复用阶段3同一 Agent 类型、Request、
  Result 和 JSON Schema，自动函数上下文和来源习语通过共享
  `related_examples` 字段提供，但必须针对当前合成代码重新独立执行。
- 质量复审必须重新输出 `is_idiom`、非空判断理由和当前合成结果的
  `idiom_classification`，不得直接继承来源阶段3类型；`is_idiom=false` 必须
  触发业务硬拒绝。
- 质量复审失败必须把业务质量安全降为0；异味复审失败必须触发独立门禁。一个
  并行分支失败不得取消另一分支。未预料的候选组编排异常记录为 `skip_group`
  后继续处理后续组。
- 最终产物只允许 `accepted` 与 `rejected`。业务 `scorecard` 只使用质量复审分；
  异味不得进入质量分，独立 `smell_gate` 使用与阶段3相同的风险算法和阈值。
- Schema v7 必须以顶层 `source_judgments` 携带来源阶段3的判断理由和类型，
  并保存当前规划、组装、质量、类型、异味理由及汇总后的 `decision_reason`。
- 阶段2合同分支保留更严格质量阈值的确定性测试，但不得纳入正式实验执行。
- 长时真实运行应使用 SQLite checkpoint；续跑必须验证输入哈希、模型、上下文和
  关键参数一致。正式 artifact 必须保存模型、提示词版本/哈希、决策政策、token
  用量和校准状态，不得暗示 synthetic smoke 已完成人工阈值冻结。

## 代码异味专项合同

- 固定分类、证据边界、严重度、风险公式和审计口径只在
  `src.idiom_judgment.smell_taxonomy` 定义；阶段4不得复制或修改另一套合同。
- 每条已审查记录必须保存完整 `smell_review_input`、结构化 `smell` 和独立
  `smell_gate`，以便复现模型实际看到的代码和上下文。
- 异味 Agent 的 `reason` 必须概括有或没有 finding 的证据；空理由属于无效领域
  载荷，并按分析失败触发独立门禁。
- 审查失败是技术失败，不得伪造为某个异味类别；运行时采用安全拒绝，事后审计
  则单独统计并排除检测准确率。
- 正式实验必须分层抽取被过滤、未过滤和分析失败样本，报告过滤
  Precision/Recall/F1、误过滤率、漏报率，以及逐类别 TP/FP/FN/P/R/F1。
- 完整分类、风险公式和审计流程见
  [`code-smell-review.md`](code-smell-review.md)。

## 习语类型专项合同

- 固定目录、三态 `kind`、开放分类边界和确定性标准化只在
  `src.idiom_judgment.idiom_taxonomy` 定义；阶段4复用同一目录。
- 类型分类只在最终业务有效性 Agent 中执行，不参与 embedding、DBSCAN、业务分
  或异味分，也不能按仓库名路由。
- 已知类型必须使用目录稳定编号；无法精确对应的已接受候选必须归为
  `repository_specific`，而不是创造未受控类型编号。
- `cataloged` 在知识层称为目录化通用习语，以
  `taxonomy_version + catalog_id` 为跨仓库聚合身份；`repository_specific`
  在知识层称为仓库专属习语，保留项目和阶段内记录身份。后者明确包括当前目录
  尚未总结的不常见通用习语。
- 分类是相对于目录版本的操作性判断。目录升级前不得静默重解释历史专属记录；
  若后续归入新目录类型，必须通过显式版本迁移保留原分类和迁移依据。
- 最终报告必须能够分别形成目录化通用、仓库专属和二者并集的全量联合视图。
  跨仓库通用类型聚合只能发生在各仓库独立完成阶段3/4之后，不得成为发现输入、
  判断证据或跨仓泛化结论。
- 完整合同见
  [`idiom-taxonomy.md`](idiom-taxonomy.md)。

## 新增或修改 Agent

1. 在所属功能包中定义 Request/Result dataclass、`_SYSTEM_MESSAGE` 和
   `_RESPONSE_SCHEMA`。
2. handler 只组装动态输入、调用 `ask_json()` 并映射安全回退。
3. 在流水线中用 `register_agent(...)` 注册并通过路由消息通信；有独立证据的
   专项审查使用 `asyncio.gather()`。
4. 把新提示词加入 `tests/agents/test_prompt_contracts.py`，把确定性裁决和适配器
   测试放在对应功能包测试目录。
5. 真实 LLM 冒烟前说明模型、逻辑调用数、可能的修复请求、成本和源码披露范围。
