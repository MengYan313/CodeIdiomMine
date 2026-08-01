# 仓库架构

CodeIdiomMine 从 C++ 仓库中提取候选 AST 片段，经代码嵌入和 DBSCAN 聚类后，
由阶段3“多重可信门控”筛选、抽象并定型单个候选簇，再由阶段4“关联闭环融合”
把同一区域内具有明确关系的习语组织为质量更高的模板。工程代码包仍分别命名为
`idiom_judgment` 和 `idiom_synthesis`。HDBSCAN 仅保留为阶段2对照实现。

本文描述当前实现。论文研究路线位于 `docs/research/`，不作为现有代码必须满足的规格。

## 最高优先级架构不变量：仓库隔离挖掘

每个 C++ 仓库是完整且独立的挖掘单元。Parser、片段构建、embedding、聚类、
多重可信门控、关联闭环融合和评价必须按仓库分别执行和保存；任何两个仓库的候选、向量或聚类
输入都不得合并。单仓库完整合格源码是发现阶段的语料边界，不在 embedding 或
聚类前拆为训练、开发、测试区域。

最终评价可以在全仓发现结束后，根据来源文件确定性地形成参考分区和测量分区。
该分区只用于计算仓库内部覆盖性、重复性和分区复现性，不触发重新解析、嵌入或
聚类，也不表示未知仓库泛化。多仓库统计只能在各仓独立完成指标后做宏平均或
必要的全局汇总。历史 `leave_one_project_out` 入口不属于正式架构。

## 最终知识组织不变量：通用、专属与联合视图

仓库隔离约束的是发现证据；阶段3和阶段4完成后的习语库另按受控目录进行双层知识
组织：

- 能够精确对应当前目录稳定编号的已接受结果是**目录化通用习语**，其类型身份为
  `taxonomy_version + catalog_id`。所有仓库分别完成流水线后，可以按这一身份
  跨仓库汇总、比较，并在满足适用前提时作为复用候选；
- 无法可靠对应当前目录的已接受结果是**仓库专属习语**，其身份保留
  项目和阶段内记录作用域。该集合也收纳可能具有一般意义、但当前目录尚未总结的
  不常见习语，不得因此临时创造类型编号或跨仓库合并；
- **全量联合视图**是上述两个集合的并集，用于总体规模、覆盖和结构分析，但必须
  保留 `kind`、目录版本、项目和来源，不得把联合统计解释为类型身份相同。

上述分类属于最终知识层，不得反向影响 Parser、embedding、DBSCAN 或 Agent 的
仓库内证据边界。阶段4必须针对合成结果重新分类。详细合同见
[C++习语类型目录与开放分类合同](idiom-taxonomy.md)。

## 架构不变量：零构建解析

Parser 的固定入口合同是：**免目标项目编译、免链接、免执行，源码可得即可解析**。
目标仓库可以只是源码快照，不需要准备可工作的构建目录、第三方依赖、生成文件、
工具链或运行环境。Tree-sitter C++ 路径独立完成 AST 构建、异常与覆盖统计、C++
Adapter 恢复、片段分析和原文映射；一个文件异常不会终止其他文件。

这一定义只约束被分析项目。CodeIdiomMine 自身仍需安装文档所列 Python 依赖，
抽取出的原文片段也可能依赖其所在作用域。已有编译数据库或 Clang 能力可以作为
可选语义增强，可信隔离环境中的静态编译可以验证阶段3/4模板，但二者都不能成为
Parser 基础结果的门禁。任何后端失败都应以能力掩码、诊断或降级记录显式呈现，
不能把“项目不可完整构建”转换成“项目没有候选”。

该不变量使解析器本身成为可迁移的软件复用能力：面对不同构建系统、平台、宏环境
和依赖完整度时，通用 AST 操作与 C++ Adapter 仍能按同一合同工作，而无需为每个
仓库开发一次性构建集成。

## 运行约定

- 从仓库根目录运行所有命令。
- 使用项目解释器 `.venv/bin/python`。
- 入口必须采用 `python -m src.<package>.<module>`；源码使用相对导入，直接执行文件会失败。
- `.env` 由 `src/llm/config.py` 从仓库根目录统一加载，提供 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 与 `OPENAI_MODEL_LOW/MEDIUM/HIGH`；当前默认调用只取低档模型。

完整命令见根目录 `README.md`，验证顺序见 `docs/guides/testing.md`。

## 模块职责

| 路径 | 职责 |
|---|---|
| `src/common/` | 统一日志、LLM 配置兼容导出与 C++ 函数、块、语句节点类型集合 |
| `src/parser/` | 通用 Tree-sitter 操作、C++ Adapter、异常/宏恢复、原文映射、Def-Use、目标 tokenizer 长度治理及 model-ready 片段 |
| `src/mining/` | 对 Parser 已准备片段执行预训练模型嵌入和正式 DBSCAN 聚类，提供仓库无关、仅改进领域目标函数的标准 GP+EI warm-start 调参；HDBSCAN 保留为实验对照 |
| `src/idiom_judgment/` | 单簇合同/低价值规则、保守抽象提案、经哈希验证的代表区域上下文、语义/复用价值业务评分、目录化通用习语与仓库专属习语分类、共享异味分类与独立门禁、Agent 理由链、失败回退和事后审计 |
| `src/idiom_synthesis/` | 阶段3正式输入、阶段2合同适配、完整簇成员位置的同区域共现发现、区域成员与源码顺序绑定、自动验证上下文、每区域一次批量规划、有界计划规范化与稳定键、逐计划代码组装、对当前结果重新执行质量与习语类型复审、理由链、合成增量产物、计划级失败隔离，以及独立执行的共享异味门禁 |
| `src/agents/` | 当前判断与合成流程复用的 Agent 基类、结构化调用状态和注册函数 |
| `src/evaluation/` | 固定评价指标、四条 baseline、统一产物/指标合同、按仓库与全局聚合及明确标注的离线模拟验证 |
| `src/llm/` | 两项目统一的模型分档、`.env`、AutoGen 客户端、JSON schema/单次修复与轻量对话封装 |
| `src/utils/` | 原始 pickle/CSV 转换和流水线可读 JSON 投影 |
| `tests/` | 与上述九个源码子包一一对应的离线自动化测试 |

## 数据流与契约

```text
repos/<project>/...
  -> outputs/cpp/<project>/dataset.pkl
       \-> outputs/cpp/<project>/dataset.audit.json  # 全扫描文件异常与恢复侧车
  -> outputs/cpp/<project>/fragments.pkl             # Parser 长度降级后的模型输入
       \-> outputs/cpp/<project>/token-length-audit.json
  -> outputs/cpp/<project>/embeddings.pkl
  -> outputs/cpp/<project>/clusters.pkl             # DBSCAN 正式聚类出口
       \-> outputs/cpp/<project>/dbscan-tuning.json # 无监督参数选择证据
       \-> outputs/cpp/<project>/readables/...
  -> outputs/cpp/<project>/clusters-merged.pkl      # 仓库内保守归并，阶段3输入
  -> outputs/cpp/<project>/idiom-judgment.pkl     # 多重可信门控，阶段3
  -> results/cpp/<project>/idiom-synthesis.pkl    # 关联闭环融合，阶段4
  -> results/cpp/<project>/eval.json
```

- `dataset.pkl`：DataFrame 列为 `project`、`cppFile`、`func_ast`、`func_src`。`cppFile` 是保留的数据契约字段，其值为项目仓库相对 POSIX 路径，不能退化为 basename 或绝对路径。映射 v2 为每个节点保存原始字节范围和原文，为函数根保存文件身份、内容哈希、解析来源和可选语义切片。
- `dataset.audit.json`：Parser 侧车 Schema v2，覆盖所有扫描文件，包括无函数和失败文件；记录 `ERROR`、missing、未覆盖区间、宏影子恢复和函数范围。它是审计证据，不是下一阶段输入。
- `fragments.pkl`：Parser 片段 Schema v1；保存目标 tokenizer、token 预算、`quality-v2` 原文片段、既有 `fragment_info` 映射结构、超限拒绝清单和降级统计。embedding 的规范输入是该产物。
- `embeddings.pkl`：DataFrame 列为 `pros_name`、`pros_src`、`pros_emb`、`pros_info`；嵌入以 CPU `torch.Tensor` 保存。
- `clusters.pkl`：`list[{pros_name, clusters}]`；簇表包含 `label`、`center_point`、`else_point`、`cluster_size`、`center_point_info`、`infos`、`loc_label`。正式产物使用 DBSCAN；HDBSCAN 对照产物可以附加 `clustering_metadata`，但不改变上述下游必需字段。
- `clusters-merged.pkl`：冻结 DBSCAN 之后、阶段3之前的单仓派生产物。中心代码
  词法等价时直接归并；AST同构且高相似的候选只有在全部差异均为已声明局部变量
  一致换名时才归并。完整成员和 `infos` 不变，并用归并后全部原始 embedding
  重算质心与真实代表。簇表继续使用相同七列 Schema，来源 label 和归并理由写入
  顶层 `clustering_metadata.postprocessing`。
- `dbscan-tuning.json`：保存目标函数改进的贝叶斯搜索空间、warm-start 观测、
  无监督可行性条件、三指标目标权重和最终 incumbent；标准 GP 代理模型与 EI
  采集函数不作改动。选择器不读取仓库身份、人工标签或最终评价指标；该 JSON
  是选择证据，不替代阶段间 pickle。
- `idiom-judgment.pkl`：Schema v8。正式结果按 `accepted`、`rejected` 分区，离线预检另有 `pending_llm`；每条记录保存完整 `member_codes`/`source_infos`、四项 `cluster_statistics`、规则证据、抽象提案、只含代表代码和词法去重变体的精简 `semantic_review_input`、独立 `context_evidence`、LLM `is_idiom` 与 `abstract/keep` 决策、实际批准集合与 `abstraction_applied`、目录化通用习语或仓库专属习语的 `idiom_classification`、语义/类型/异味 `agent_reasons`、最终 `decision_reason`、语义/复用价值业务 `scorecard`、精简 `smell_review_input`、结构化异味 findings 与独立 `smell_gate`、各 Agent 尝试/失败/回退的 `agent_trace`，以及 `center_point`、`info`、`cnt`、`avg_ast_num`、`avg_subtree_size` 和 `loc_label` 兼容投影。经路径/范围/哈希验证的代表上下文只用于本地门禁和审计，不进入阶段3 LLM 请求。
- `idiom-synthesis.pkl`：Schema v9，语义固定为 `synthesis_delta`。正式读取习语判断的 `accepted` 记录，以完整 `source_infos` 按成员 `project + source_path + function_extent` 的交集发现同区域共现；同一簇在一个区域内只形成一个区域绑定候选，但可参与多个真实共现区域。候选自身 `extent` 和 `start_byte/end_byte` 提供局部代码与稳定源码顺序，不要求不同习语片段的字节区间相交；缺少可验证成员位置时不使用历史 `loc_label` 猜测分组。规划 Agent 每区域一次返回有界 `plans`，编排层规范化索引并按候选集合去重，以稳定 `combination_key` 逐计划执行；`region_planning` 保存总理由、调用状态和校验摘要。产物只保存合成尝试和成功增量，不复制未合成、未选择或合成失败的阶段3习语；它们继续由阶段3产物持有。每次尝试以顶层 `source_judgments` 携带来源阶段3判断理由和类型，以 `matched_source_infos`、`matched_occurrences`、`region_identity` 和 `source_order_candidate_ids` 保存实际使用的成员共现证据，完整 `source_infos` 继续保存簇级支持证据；同时保存自动同区域 `context_evidence`、单项合成计划、组装来源、针对合成结果重新执行的 `is_idiom` 与 `idiom_classification`、规划/组装/质量/类型/异味 `agent_reasons`、最终 `decision_reason`、质量复审业务 `scorecard`、当前合成代码的 `smell_review_input`/分类 findings/独立 `smell_gate`、Tree-sitter 语法与新增调用门禁、各 Agent 尝试/失败/跳过的 `agent_trace`、`merge_rounds` 和 `synthesis_trace`。阶段2 `clusters.pkl` 只验证适配和严格阈值逻辑，程序化调用生成 `contract_only_not_executed` 空 artifact，不进入正式 CLI 或实验执行。
- `eval.json`：正式默认在每个仓库完成全仓发现后，对来源文件做确定性的参考/测量分区，并在测量分区上计算 `IC_macro`、`IC_micro`、最终 `IC=(IC_macro+IC_micro)/2`、集合复现率 `ISP` 及使用最终 IC 的 `F1`；另报告习语种类数、平均聚类簇大小、平均跨文件支持数和 `AvgAST`，并保留必要分子分母。兼容字段 `training_*`、`test_*` 只表示参考/测量分区。留一项目模式只作历史兼容，聚类模拟模式只作公式验证。

当前九项正式指标默认计算全量联合视图。阶段3/4的分类字段还允许在报告层对
目录化通用与仓库专属子集分别复算同口径分布，并按稳定目录编号生成跨仓库通用
类型统计；这些分层视图不是新的调参目标，也不得改变原始记录身份。

指标的正式公式、统计单位、仓库宏平均、全局汇总和解释边界统一见[评价指标规范](evaluation-metrics.md)；其他文档只保留入口或实验记录，不另行定义不同口径。

四条正式 baseline 分别由 `haggis_cpp.py`、`llm_direct_baseline.py`、
`rules_embedding_baseline.py` 和 `idiomine_cpp.py` 生成与判断阶段兼容的
`*_idiom.pkl`。`idiomine_cpp.py` 在单一入口内复用 `semantic_def_use`
片段作为 DCC-lite 候选，按仓库独立执行 DBSCAN，再逐簇独立判断，并只对代表
位置完全相同的已接受习语尝试一次直接合成。候选聚类是私有实现步骤，不构成
额外 baseline。`baseline_common.py` 维护公共记录与九指标名单，
`baseline_validation.py` 拒绝 mock/不完整证据并调用现有评价器。方法定义、
算法适配边界和完整命令见[Baseline 复现](baselines.md)。

这些 pickle schema 是阶段间接口。Parser v2 不改变四列外层 Schema，
并保留历史 `extent` 和 `ast_num`；`mapping_version=2`、字节范围、文件身份、
`subtree_size` 和 `candidate_origin` 是向后兼容证据字段。Parser 片段构建默认
使用 `quality-v2`，也可显式用 `legacy` 复查历史选择规则；真实 embedding
不再直接从四列 AST 数据集临时选择或截断候选。评价器自动识别 v2，并把
`semantic_slice` 的原始字节范围映射回 AST 节点；旧数据仍使用历史规则。
`source_infos` 是阶段4成员共现发现和可复现评价的共同证据字段，
`avg_subtree_size` 是评价使用的向后兼容证据字段；旧产物缺少它们时，评估器
退回代表实例和数据集定位，但阶段4不得用 `loc_label` 猜测成员共现。其他任务
不得顺手改变字段或嵌套层级。

Parser 的恢复、映射、候选 profile 和 Def-Use 算法见
[Parser v2 设计](parser-design.md)，全量证据见
[Parser 基线与优化对比](parser-quality-report.md)。复杂 C++ 节点策略、宏边界和
Parser 长度降级见[C++ Adapter 与模型输入治理](cpp-adapter-and-model-input.md)。

`src.utils.export_artifacts` 不改变上述接口：PKL 保留完整嵌套 AST、CPU tensor 和簇成员，JSON 只作为可重新生成的人工分析投影。每阶段的 `*.summary.json` 统计全量输入；`dataset.preview.json` 和 `embeddings.preview.json` 默认各取前 100 条，`clusters.top100.json` 默认按项目分别取簇大小 Top100。真实语义产物生成后可按需导出 `judgment` 和 `synthesis` 的状态汇总及前100条已接受记录；同名阶段也自动兼容旧 `*_idiom.pkl` 与 `*_idiom_syn.pkl` 列表产物。预览中的长源码会显式截断，嵌入只展示形状、范数和向量头部，因此这些 JSON 不得回流为下一阶段输入，也不得作为 Haggis、LLM-Direct 或 CIMAS-CPP 的产物截断清单。

## C++ 范围边界

项目不再提供语言扩展点：

1. `src/common/node_kinds.py` 直接导出 C++ 节点集合，不维护语言映射；
2. `src/parser/ast_parser.py` 固定装配 `src/parser/cpp_adapter.py`，Adapter 固定加载 `tree-sitter-cpp`；
3. `src/parser/file_scanner.py` 确定性扫描标准 C/C++ 扩展名，以完整目录段排除构建、缓存、第三方、生成、测试、示例和基准输入，并拒绝符号链接与越界路径；
4. parser、embedding 和 evaluation CLI 均无 `--language` 参数。

`repos`、`outputs/cpp` 和 `results/cpp` 中的 `cpp` 是固定的现有产物命名空间，不是可切换语言参数。扫描器接受 `.c`、`.cc`、`.cpp`、`.cxx`、`.c++`、`.h`、`.hh`、`.hpp` 和 `.hxx`，具体清洗规则及排除计数以源码和 `dataset.audit.json` 为准。`repo2data --project <目录名>` 可从多项目输入根中精确选择一个或多个项目，不构成语言选择器。重新引入其他语言属于新的架构变更，不能通过增加一个 CLI 选项或静默回退实现。

## 可信门控与闭环融合 Agent

两个领域包均基于 `autogen_core` 的 `RoutedAgent`、强类型 dataclass 消息和
`SingleThreadedAgentRuntime`，不是 `autogen_agentchat`。

- 多重可信门控（`idiom_judgment`）：确定性规则与抽象提案先运行，编排层验证代表函数/区域上下文后，
  语义/复用价值 Agent 和共享代码异味 Agent 并行；业务评分与不可抵消的异味
  门禁自动给出二态结果。
- 关联闭环融合（`idiom_synthesis`）：阶段3已接受产物 → 完整成员位置的同区域共现分组 → 绑定当前区域实际成员与源码顺序 → 自动加载同区域上下文
  → 有界语义组合规划 → 代码组装
  → 质量/共享异味并行复审；异味针对当前合成代码独立重审且不进入质量分。
  输出为不含阶段3透传项的合成增量。阶段2只运行不调用 Agent 的适配合同测试，
  禁止跨仓或跨区域合成。
- 有界语义组合规划的目的，是避免对同一区域候选执行指数级全子集枚举。规划
  Agent 每区域一次返回显式上限内所有有明确关系且值得尝试的组合；编排层排序并
  去重索引、校验范围与必填理由、生成稳定组合键，再逐计划独立执行。不同计划可
  共享候选，完全相同的候选集合只执行一次；不采用逐组询问模型并由模型控制停止
  的开放循环。
- 阶段3上下文只读取代表源码范围；阶段4只读取成员共现区域，二者都校验文件哈希。合成结果新增的调用目标必须来自
  输入习语或该上下文。

详细设计见 `docs/guides/agent-system.md`，修改约束见
`docs/guides/agent-contracts.md`。

## 日志和生成物

`src/common/logging.py` 将 INFO 及以上写到控制台，将 DEBUG 及以上追加到 `logs/<run-name>.log`。同一命令的所有模块共享运行日志，后续导入不会截断旧证据；`src/logger.py` 仅保留旧导入兼容。

`logs/`、`outputs/`、`results/`、虚拟环境和密钥文件由 `.gitignore` 排除。`docs/` 中的开发与研究资料应进入版本控制。

第一方集合目录采用复数职责名。`src/`、`cpp/` 和 `.venv/` 分别是 source root、语言限定符和虚拟环境约定，不属于需要复数化的集合名称。

共享文件列表与同步检查命令见 `docs/guides/shared-development-conventions.md`；`scripts/check_shared_infrastructure.py` 可与相邻 WPF2React checkout 做逐文件哈希检查。
