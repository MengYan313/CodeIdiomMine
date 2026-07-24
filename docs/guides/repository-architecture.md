# 仓库架构

CodeIdiomMine 从 C++ 仓库中提取候选 AST 片段，经代码嵌入和 DBSCAN 聚类后，使用 AutoGen Agent 判断候选是否为代码习语，并尝试合成可复用模板。

本文描述当前实现。论文研究路线位于 `docs/research/`，不作为现有代码必须满足的规格。

## 最高优先级架构不变量：仓库隔离挖掘

每个 C++ 仓库是完整且独立的挖掘单元。Parser、片段构建、embedding、DBSCAN、
判断、合成和评价必须按仓库分别执行和保存；任何两个仓库的候选、向量或聚类
输入都不得合并。单仓库完整合格源码是发现阶段的语料边界，不在 embedding 或
DBSCAN 前拆为训练、开发、测试区域。

最终评价可以在全仓发现结束后，根据来源文件确定性地形成参考分区和测量分区。
该分区只用于计算仓库内部覆盖性、重复性和分区复现性，不触发重新解析、嵌入或
聚类，也不表示未知仓库泛化。多仓库统计只能在各仓独立完成指标后做宏平均或
必要的全局汇总。历史 `leave_one_project_out` 入口不属于正式架构。

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
| `src/mining/` | 对 Parser 已准备片段执行预训练模型嵌入、DBSCAN 聚类和可选贝叶斯调参 |
| `src/agents/` | 通用 AutoGen 基类，以及习语判断、规划、代码组装与合成后再判断 |
| `src/evaluation/` | 固定评价指标、三条 baseline、统一产物/指标合同、按仓库与全局聚合及明确标注的离线模拟验证 |
| `src/llm/` | 两项目统一的模型分档、`.env`、AutoGen 客户端、JSON schema/单次修复与轻量对话封装 |
| `src/utils/` | 原始 pickle/CSV 转换和流水线可读 JSON 投影 |
| `tests/` | 与上述七个源码子包一一对应的离线自动化测试 |

## 数据流与契约

```text
repos/<project>/...
  -> outputs/cpp/<project>/dataset.pkl
       \-> outputs/cpp/<project>/dataset.audit.json  # 全扫描文件异常与恢复侧车
  -> outputs/cpp/<project>/fragments.pkl             # Parser 长度降级后的模型输入
       \-> outputs/cpp/<project>/token-length-audit.json
  -> outputs/cpp/<project>/embeddings.pkl
  -> outputs/cpp/<project>/clusters.pkl
       \-> outputs/cpp/<project>/readables/...
  -> results/cpp/<project>/{project}_idiom.pkl
  -> results/cpp/<project>/{project}_idiom_syn.pkl
  -> results/cpp/<project>/eval.json
```

- `dataset.pkl`：DataFrame 列为 `project`、`cppFile`、`func_ast`、`func_src`。`cppFile` 是保留的数据契约字段，其值为项目仓库相对 POSIX 路径，不能退化为 basename 或绝对路径。映射 v2 为每个节点保存原始字节范围和原文，为函数根保存文件身份、内容哈希、解析来源和可选语义切片。
- `dataset.audit.json`：Parser 侧车 Schema v2，覆盖所有扫描文件，包括无函数和失败文件；记录 `ERROR`、missing、未覆盖区间、宏影子恢复和函数范围。它是审计证据，不是下一阶段输入。
- `fragments.pkl`：Parser 片段 Schema v1；保存目标 tokenizer、token 预算、`quality-v2` 原文片段、既有 `fragment_info` 映射结构、超限拒绝清单和降级统计。embedding 的规范输入是该产物。
- `embeddings.pkl`：DataFrame 列为 `pros_name`、`pros_src`、`pros_emb`、`pros_info`；嵌入以 CPU `torch.Tensor` 保存。
- `clusters.pkl`：`list[{pros_name, clusters}]`；簇表包含 `label`、`center_point`、`else_point`、`cluster_size`、`center_point_info`、`infos`、`loc_label`。
- `{repo}_idiom.pkl`：包含 `center_point`、与代表代码一致的 `info`、完整簇证据 `source_infos`、`cnt`、兼容字段 `avg_ast_num`、完整子树统计 `avg_subtree_size` 和 `loc_label`。
- `{repo}_idiom_syn.pkl`：继续保留合并后全部 `source_infos`，并增加 `merge_rounds`、`synthesis_trace`。
- `eval.json`：正式默认在每个仓库完成全仓发现后，对来源文件做确定性的参考/测量分区，并在测量分区上计算 `IC_macro`、`IC_micro`、最终 `IC=(IC_macro+IC_micro)/2`、集合复现率 `ISP` 及使用最终 IC 的 `F1`；另报告习语种类数、平均聚类簇大小、平均跨文件支持数和 `AvgAST`，并保留必要分子分母。兼容字段 `training_*`、`test_*` 只表示参考/测量分区。留一项目模式只作历史兼容，聚类模拟模式只作公式验证。

指标的正式公式、统计单位、仓库宏平均、全局汇总和解释边界统一见[评价指标规范](evaluation-metrics.md)；其他文档只保留入口或实验记录，不另行定义不同口径。

三条正式 baseline 分别由 `haggis_cpp.py`、`llm_direct_baseline.py` 和 `rules_embedding_baseline.py` 生成与判断阶段兼容的 `*_idiom.pkl`。`baseline_common.py` 维护公共记录与九指标名单，`baseline_validation.py` 拒绝 mock/不完整证据并调用现有评价器。方法定义、算法适配边界和完整命令见[Baseline 复现](baselines.md)。

这些 pickle schema 是阶段间接口。Parser v2 不改变四列外层 Schema，
并保留历史 `extent` 和 `ast_num`；`mapping_version=2`、字节范围、文件身份、
`subtree_size` 和 `candidate_origin` 是向后兼容证据字段。Parser 片段构建默认
使用 `quality-v2`，也可显式用 `legacy` 复查历史选择规则；真实 embedding
不再直接从四列 AST 数据集临时选择或截断候选。评价器自动识别 v2，并把
`semantic_slice` 的原始字节范围映射回 AST 节点；旧数据仍使用历史规则。
`source_infos` 和 `avg_subtree_size` 是为可复现评价增加的向后兼容证据字段；
旧产物缺少它们时，评估器退回代表实例和数据集定位。其他任务不得顺手改变字段
或嵌套层级。

Parser 的恢复、映射、候选 profile 和 Def-Use 算法见
[Parser v2 设计](parser-design.md)，全量证据见
[Parser 基线与优化对比](parser-quality-report.md)。复杂 C++ 节点策略、宏边界和
Parser 长度降级见[C++ Adapter 与模型输入治理](cpp-adapter-and-model-input.md)。

`src.utils.export_artifacts` 不改变上述接口：PKL 保留完整嵌套 AST、CPU tensor 和簇成员，JSON 只作为可重新生成的人工分析投影。每阶段的 `*.summary.json` 统计全量输入；`dataset.preview.json` 和 `embeddings.preview.json` 默认各取前 100 条，`clusters.top100.json` 默认按项目分别取簇大小 Top100。真实 Agent 运行后还可按需导出 `judgment` 和 `synthesis` 的摘要及前 100 条。预览中的长源码会显式截断，嵌入只展示形状、范数和向量头部，因此这些 JSON 不得回流为下一阶段输入，也不得作为 Haggis、LLM-Direct 或 CIMAS-CPP 的产物截断清单。

## C++ 范围边界

项目不再提供语言扩展点：

1. `src/common/node_kinds.py` 直接导出 C++ 节点集合，不维护语言映射；
2. `src/parser/ast_parser.py` 固定装配 `src/parser/cpp_adapter.py`，Adapter 固定加载 `tree-sitter-cpp`；
3. `src/parser/file_scanner.py` 确定性扫描标准 C/C++ 扩展名，以完整目录段排除构建、缓存、第三方、生成、测试、示例和基准输入，并拒绝符号链接与越界路径；
4. parser、embedding 和 evaluation CLI 均无 `--language` 参数。

`repos`、`outputs/cpp` 和 `results/cpp` 中的 `cpp` 是固定的现有产物命名空间，不是可切换语言参数。扫描器接受 `.c`、`.cc`、`.cpp`、`.cxx`、`.c++`、`.h`、`.hh`、`.hpp` 和 `.hxx`，具体清洗规则及排除计数以源码和 `dataset.audit.json` 为准。`repo2data --project <目录名>` 可从多项目输入根中精确选择一个或多个项目，不构成语言选择器。重新引入其他语言属于新的架构变更，不能通过增加一个 CLI 选项或静默回退实现。

## Agent 子系统

Agent 基于 `autogen_core` 的 `RoutedAgent`、强类型 dataclass 消息和 `SingleThreadedAgentRuntime`，不是 `autogen_agentchat`。

- 判断：语义与语法 Agent 通过 `asyncio.gather` 并行执行，再由 judge Agent 汇总。
- 最终 `is_idiom` 由确定性规则决定：较高分至少 70，较低分至少 50。
- 合成：规划与组装使用独立 runtime，并持有第二个 quiet 判断流水线做合并后再判断。
- 每个区域最多合并三轮；无成功合并的组不产生合成记录。

详细设计见 `docs/guides/agent-system.md`，修改约束见 `docs/guides/agent-contracts.md`。

## 日志和生成物

`src/common/logging.py` 将 INFO 及以上写到控制台，将 DEBUG 及以上追加到 `logs/<run-name>.log`。同一命令的所有模块共享运行日志，后续导入不会截断旧证据；`src/logger.py` 仅保留旧导入兼容。

`logs/`、`outputs/`、`results/`、虚拟环境和密钥文件由 `.gitignore` 排除。`docs/` 中的开发与研究资料应进入版本控制。

第一方集合目录采用复数职责名。`src/`、`cpp/` 和 `.venv/` 分别是 source root、语言限定符和虚拟环境约定，不属于需要复数化的集合名称。

共享文件列表与同步检查命令见 `docs/guides/shared-development-conventions.md`；`scripts/check_shared_infrastructure.py` 可与相邻 WPF2React checkout 做逐文件哈希检查。
