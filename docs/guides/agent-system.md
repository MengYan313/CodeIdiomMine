# 习语判断与合成 Agent 架构

当前正式 Agent 流程按功能职责拆为两个领域包：

- `src/idiom_judgment/`：判断单个 DBSCAN 聚类簇能否成为代码习语；
- `src/idiom_synthesis/`：尝试把同一区域内多个相关习语合成为质量更高的习语。

`src/agents/` 只保留当前流程实际复用的 `BaseRoutedAgent`、结构化调用基类和
注册函数。
数字阶段名只描述论文顺序，不作为源码包名。

## 一、总体数据流

```text
阶段2 clusters.pkl
   ├─→ idiom_judgment
   │     规则/合同过滤
   │       → 可抽象位置规则提案
   │       → 自动读取并验证代表函数/区域上下文
   │       → 完整簇 + 规则证据 + 提案 + 上下文
   │       → 语义/抽象 Agent：abstract 或 keep ─┐
   │       → 代码异味 Agent ───────┤
   │       → 业务评分与质量门禁 ──┘
   │       → 独立异味门禁
   │       → accepted / rejected
   ▼
 idiom_synthesis 阶段3正式输入
   → 完全相同代表 project/path/extent 分组
   → 自动读取并验证代表区域上下文
   → 合成规划 Agent
   → 代码组装 Agent
   → 质量复审 Agent + 共享异味审查 Agent（对合成结果独立重审）
   → Tree-sitter / 上下文 / 新增调用确定性门禁
   → 质量分门禁 + 独立异味门禁
   → accepted / rejected 合成增量

阶段2 clusters.pkl
   → 适配为内部 IdiomCandidate
   → 验证分组、Schema 与严格阈值逻辑
   → 不启动正式阶段4 Agent，不产生实际合成结果
```

阶段2直通只保留为合同与后备设计验证：代码可以将其归一化为阶段4内部候选，且
确定性约束不会因 Schema 不兼容而报错；正式 CLI 和实验只消费阶段3的
`accepted` 产物，不实际执行阶段2到阶段4的 LLM 合成。程序化传入阶段2产物只
生成 `execution_status=contract_only_not_executed` 的空 artifact，不创建 Agent、
不读取 API key，也不发起 LLM 调用。

## 二、单簇习语判断

### 2.1 确定性规则

`src.idiom_judgment.rules.evaluate_cluster_rules()` 首先验证：

- 聚类支持数至少为2；
- 代表代码和成员代码非空；
- `cluster_size` 与完整 `infos` 数量一致；
- 所有来源属于同一仓库；
- 不是只包含 `break;`、`continue;`、裸 `return;` 等确定性低价值控制语句。

完全相同源码、单文件复现、缺少源码变体和 Parser 诊断只形成警告，不会被单条
启发式规则自动拒绝。规则评分是可解释证据，不替代后续语义判定。

### 2.2 保守抽象

`src.idiom_judgment.abstraction` 不执行“所有差异元素全部占位”。默认提案必须同时
满足：

- 至少3个可解析且结构对齐的实例；
- 同一结构角色至少3个不同取值；
- 对齐组覆盖至少60%的簇成员；
- 元素是片段内已声明的局部变量，或不位于控制条件、返回值、下标、哨兵值和格式
  字符串中的低语义字面量。

调用目标、类型、外部实体、控制条件、返回值、`0/1/-1/nullptr/true/false` 和
格式字符串不会仅因变化而抽象。相同局部实体的定义和使用共享同一占位符。
规则只产生 `AbstractionProposal`，不修改代码。随后语义/抽象 Agent 接收：

- 代表代码和同一簇的全部成员代码；
- 完整规则初判和警告；
- 所有规则抽象提案、候选位置、取值、支持数与覆盖率。

Agent 必须显式返回 `abstract` 或 `keep`。`abstract` 时只能批准输入中的
`proposal_id`，确定性代码再应用批准集合与规则提案的交集；`keep`、规则无提案
或抽象决策无法解析时，代表代码保持不变。拒绝抽象不是拒绝习语：只要后续业务
质量和异味门禁通过，未抽象代码与成功抽象模板都会进入阶段4。

正式运行还应从 `center_point_info` 自动读取代表函数/区域，校验仓库身份、相对
路径、范围和整文件 `source_sha256`。该上下文同时进入语义/抽象与异味请求；
`--require-context` 下任何校验失败都零调用拒绝当前簇。非严格兼容运行不会把
缺失上下文伪装为已验证，`context_evidence.failure_kind` 会保留原因。

### 2.3 两个专项 Agent、类型分类与裁决

语义/抽象 Agent 在同一次完整簇审查中判断稳定意图、完整性、复用价值、前置条件
和规则候选抽象安全性，并分别输出 `is_idiom`、非空理由、业务分与独立抽象决策。
通过习语有效性判断时，它还把候选分类为受控目录中的目录化通用习语，或在无法
可靠对应时分类为仓库专属习语（运行时标签为 `仓库特有习语`）；不能为了获得
已知标签强行匹配。后者也包括可能通用但尚未进入当前目录的不常见习语，这一归属
相对于目录版本成立。
共享异味 Agent 按固定分类表独立检查资源/内存生命周期、错误与异常处理、并发、
未定义行为、危险接口、控制流、耦合等风险，只输出带类别、严重度、置信度和可定位
证据的 findings 及非空审查理由。风险分和过滤结论由确定性代码计算。两个请求使用
`asyncio.gather()` 并行，但互不读取或抵消对方结论。

裁决只产生 `accepted` 或 `rejected`，不会把边界样本转交运行时人工。业务总分为：

- `0.20 × 规则分 + 0.45 × 语义分 + 0.35 × 复用分`；
- 规则失败、`is_idiom=false` 或语义/复用任一低于50时，业务门禁直接
  `rejected`；
- 通过硬门禁且总分至少70时 `accepted`，否则 `rejected`；
- 异味不进入总分；确定性 `risk_score >= 60` 或异味分析失败时，由独立
  `smell_gate` 直接覆盖业务结论为 `rejected`；
- `--rule-only` 只生成规则与抽象提案，状态为 `pending_llm`，不能冒充已接受习语。

Schema v7 保存标准化 `idiom_classification`、各 Agent 的 `agent_reasons` 和汇总
后的 `decision_reason`。目录、三态分类和无效载荷回退见
[C++习语类型目录与开放分类合同](idiom-taxonomy.md)。
目录化通用结果可在各仓库独立完成流水线后按 `taxonomy_version + catalog_id`
汇总；仓库专属结果保留项目和阶段内记录作用域；全量分析使用二者并集，但不消除
类别边界。

## 三、多习语合成

### 3.1 正式输入、合同适配与关系分组

`src.idiom_synthesis.sources` 支持：

- `idiom_judgment` artifact 的 `accepted` 记录，作为正式输入；
- 单仓阶段2 `clusters.pkl`，仅用于内部适配与门槛合同测试。

两者归一化为 `IdiomCandidate`。合成只在代表位置完全相同的
`project + file + function_extent` 下形成候选组，不使用其他成员位置扩大范围，
也不因 embedding 相似就跨区域或跨仓强行合并。阶段4 artifact 明确标记为
`synthesis_delta`，只记录合成尝试与成功增量；单例、未选择和未成功合成的习语
继续由阶段3 `accepted` 产物持有，不作为 passthrough 复制到阶段4。

每组默认上限为12。超过上限时不再静默截取高支持候选：整个同区域组以
`candidate_limit_exceeded` 零调用拒绝，并保存完整候选编号；调用者必须显式
提高 `--max-group-candidates` 后重试。正式 CLI 的 `--input-kind` 只接受
`judgment`，因此阶段2合同分支不会发起实际 LLM 调用。

### 3.2 自动上下文与多 Agent 协作

1. **确定性上下文加载器**：在调用 LLM 前，根据候选文件、代表范围和
   `source_sha256` 自动读取同一代表区域；上下文缺失或校验失败时直接拒绝。
2. **合成规划 Agent**：选择至少两个真正互补的习语，声明合成目标、顺序、上下文
   使用、预期质量增益和选择理由；找不到关系时说明原因并停止。
3. **代码组装 Agent**：严格按计划组装，只能使用选定习语和已验证上下文，并说明
   实际组装依据。
4. **质量复审 Agent**：检查来源意图、绑定、前置条件和职责是否保留，判断合成
   结果是否仍是代码习语、是否比简单拼接产生明确增益，并重新输出通用目录类型
   或 `仓库特有习语` 及理由；不得直接继承来源阶段3类型。该结果随后按同一合同
   进入目录化通用、仓库专属或全量联合知识视图。
5. **共享异味审查 Agent**：直接复用阶段3的 Agent 类型、Request/Result、JSON
   Schema、分类和阈值；阶段4通过同一 `related_examples` 字段传入已验证区域
   上下文和来源习语及其阶段3理由，但对当前合成代码发起新的独立审查，检查是否
   传播或引入反模式，并输出当前审查理由。

上下文加载、规划和组装顺序执行；质量与异味复审并行。各 Agent 都使用强类型
消息、显式 JSON Schema、原生 JSON mode、严格解析和单次修复；请求异常或修复
耗尽时最多再执行1次完整逻辑尝试。Schema v7 以顶层 `source_judgments` 保存
来源阶段3理由和类型，并为当前合成结果另存规划、组装、质量、类型、异味理由
及最终裁决理由。

### 3.3 上下文与确定性门禁

`--source-root` 是正式 CLI 的必需输入。编排层只读取候选 `info` 指向的代表源码行区间，
拒绝路径越界、仓库身份不一致、文件缺失、内容 SHA 不一致、超过300行或
12,000字符的上下文。任一检查失败时结果直接 `rejected`，且不会产生 LLM 调用。

合成后门禁检查：

- 模板占位符替换为哑元后，Tree-sitter 直接解析或函数包装解析无错误；
- 通过 Tree-sitter 提取的新增调用目标必须存在于来源习语或允许上下文；
- 编排层已经成功加载并验证代表区域上下文；
- 质量复审确认意图保留且没有不受支持的新增内容。

阶段4业务分就是 `quality_score`，正式阶段3输入至少70才可接受。阶段2合同分支
仍以80作为严格阈值进行离线逻辑测试，但不进入正式执行。异味不进入业务分；业务门禁通过后，
`risk_score >= 60` 或异味分析失败仍由独立 `smell_gate` 直接拒绝。

## 四、代码异味分类与事后审计

阶段3和阶段4共享同一份17类 C++异味分类与风险算法，但两个阶段分别审查自己的
候选，不复用上一步结论。每条记录保存模型实际看到的 `smell_review_input`、
结构化 findings 和 `smell_gate`。风险分由 finding 严重度、置信度及多异味累积项
确定性计算，模型不输出总分或接受/拒绝结论。

正式实验从两个阶段的 artifact 分层抽取 `risk_threshold`、`none` 和
`analysis_failure` 样本，由人工标注是否存在阻断复用的异味及其类别。审计报告
总体、分阶段和逐类别指标；分析失败单列，不混入检测准确性。完整分类、公式和
入口见[代码异味审查与事后审计](code-smell-review.md)。该指南同时维护运行时
来源到 thesis 全局文献编号的映射；本仓库不复制文献库。

## 五、运行时与失败回退

两个领域流程各自创建 `SingleThreadedAgentRuntime`，使用
`register_agent(...)` 和 `default_agent_id(...)`。生命周期固定为
`start → try/finally → stop/close`，模型客户端只由创建它的流水线关闭。

### 5.1 调用级恢复

`JsonLLMAgent` 对每条路由消息采用以下固定顺序：

1. 首次端点请求使用原生 JSON mode 和明确 Schema；
2. 完整响应解析或 Schema 校验失败时，同一模型按同一 Schema 修复1次；
3. 单次请求超过120秒、发生请求异常或修复仍失败时，等待固定短间隔后再执行
   1次完整逻辑尝试；
4. 第二次逻辑尝试仍失败时停止，不再请求端点，并返回领域安全默认值。

因此 `logical_attempts` 最大为2；每次逻辑尝试最多包含“首次响应+一次修复”，单个
Agent 的端点请求上限为4。有效业务结果中的 `keep`、低分、无异味或
`should_synthesize=false` 不属于技术失败，不会重试。日志只记录 Agent 名称、
尝试序号和异常类型，不记录源码、完整响应、密钥或端点。

### 5.2 阶段3失败矩阵

| 失败点 | 回退 | 后续动作 |
| --- | --- | --- |
| 规则/合同门禁 | 不调用 Agent | 拒绝当前簇，继续下一簇 |
| 语义/抽象 Agent 两次失败 | 保留代表代码，语义/复用分置0 | 拒绝当前簇；异味并行分支仍独立完成 |
| 异味 Agent 两次失败 | `analysis_status=failed`、风险安全值100 | 独立异味门禁拒绝；语义并行分支仍独立完成 |
| Runtime 路由异常 | 映射为对应 Agent 的技术失败结果 | 拒绝当前簇，不抛弃另一并行分支 |
| 未预料的单簇编排异常 | 写入 `unexpected_orchestration_error` | `skip_cluster`，命令继续后续簇 |

正常的抽象 `keep` 只保留原代码，不触发失败回退。阶段3 artifact Schema v7 在
每条记录的 `agent_trace` 保存 `status`、`logical_attempts`、`failure_kind` 和
`failure_action`，并保存 `idiom_classification`、`agent_reasons` 和
`decision_reason`；汇总中的 `technical_failure_count` 按含技术失败的记录计数。

### 5.3 阶段4失败矩阵

| 失败点 | 回退 | 被跳过的工作 |
| --- | --- | --- |
| 上下文加载/哈希门禁 | 零调用拒绝当前组 | 全部 Agent |
| 同区域候选超过显式上限 | 不截断、零调用拒绝当前组 | 全部 Agent |
| 规划 Agent 两次失败 | 无计划并拒绝当前组 | 组装、质量复审、异味复审 |
| 规划正常返回无需合成 | 业务拒绝当前组 | 组装、质量复审、异味复审 |
| 组装 Agent 两次失败或空输出 | 空结果并拒绝当前组 | 质量复审、异味复审 |
| 语法失败或新增调用越界 | 确定性拒绝当前组 | 质量复审、异味复审 |
| 质量复审两次失败 | `quality_score=0` | 异味并行分支仍独立完成，最终拒绝 |
| 异味复审两次失败 | 独立异味门禁拒绝 | 质量并行分支仍独立完成 |
| 未预料的组级编排异常 | 写入 `unexpected_orchestration_error` | `skip_group`，命令继续后续组 |

阶段4 artifact Schema v7 使用同一 `agent_trace` 合同，并对当前合成结果保存新的
类型和完整理由链。取消信号和进程中断不会被转换为业务拒绝；只有当前簇/组内的
普通技术异常会被隔离。

两个 CLI 都可选择 SQLite `--checkpoint`，每完成一个簇或组立即提交结果；中断后
只有在输入 SHA-256、模型、范围、上下文根和关键参数完全一致时才允许
`--resume`。最终 artifact 的 `run` 保存模型别名、提示词版本与 SHA-256、决策
政策、token 用量、checkpoint 状态和
`calibration_status=synthetic_smoke_only_pilot_required`。这避免把当前 synthetic
smoke 误写为阈值已经经过人工 pilot 冻结；正式实验仍必须完成盲审校准。

规则预检不需要模型。正常路径中，完整习语判断每个合格簇发起2个并行逻辑调用；
习语合成每组最多发起规划、组装、质量复审和共享异味审查4个逻辑调用。最坏情况下
每个 Agent 各产生4次端点请求，但规划或组装耗尽时会跳过下游，避免继续付费调用。

运行命令分别见：

- [习语判断 README](../../src/idiom_judgment/README.md)
- [习语合成 README](../../src/idiom_synthesis/README.md)

[Agent README](../../src/agents/README.md) 说明公共基础设施边界。
