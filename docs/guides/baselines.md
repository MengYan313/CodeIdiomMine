# C++ 习语 baseline 与质量消融

- 状态：当前 baseline 实现与复现规范
- 生效日期：2026-08-01
- 适用范围：三条外部 baseline、Stage 2 高频聚类消融、CIMAS-CPP 对照边界和统一验证

当前外部 baseline 固定为 `Haggis-CPP`、`LLM-Direct-Budget` 和
`IdioMine-CPP`，与本文方法 `CIMAS-CPP` 做同口径自动指标比较。
`Stage2-Frequency-Ablation` 直接保留 Stage 2 高频簇，与 IC 机会域共享来源，
因此不作为独立 baseline 参加自动指标优劣排名；它与 CIMAS-CPP 的主要比较是
盲化人工习语质量标注，用于检验 Stage 3 判断和 Stage 4 合成是否提高质量。
`IdioMine-CPP` 是论文 IdioMine 核心操作、独立 ChatGPT 判断和同区域
直接合成的 C++ 简化迁移，不是完整复现。DCC-lite 与 DBSCAN 只是该方法内部的
判断前候选阶段，不作为独立方法、入口或评价对象。
它们与更细粒度的模块消融可以同时保留，但不应重复计为两个不同方法。

本文只定义方法、产物和运行入口；九项固定指标的公式与聚合口径以[评价指标规范](evaluation-metrics.md)为唯一事实来源。

三条 baseline、质量消融与本文方法都以单个完整仓库为独立发现单元。各仓库的候选、embedding、聚类和
方法输出不得混合；发现前不做训练/开发/测试划分。多仓库比较只在各仓独立评价
完成后汇总。

## 1. 三条 baseline、一条质量消融与本文方法

| 方法 | 发现输入 | 核心处理 | 明确不使用 |
|---|---|---|---|
| Haggis-CPP | 当前函数级 Tree-sitter C++ AST | DP-pTSG、PCFG 基分布、collapsed Gibbs、burn-in 后片段累计 | Embedding、DBSCAN、LLM、Agent、合成 |
| LLM-Direct-Budget | 机械分块的原始 C++ 函数源码 | 同一模型 map/reduce，严格 JSON Schema，总 token 预算 | AST/CFG、Embedding、聚类、多 Agent |
| Stage2-Frequency-Ablation | 当前 `clusters.pkl` | 簇大小过滤、比例截断、每项目种类上限；保留簇直接作为人工质量对照 | Stage 3 判断、Stage 4 合成 |
| IdioMine-CPP | 当前 `embeddings.pkl` 中的 `semantic_def_use` 片段 | DCC-lite 候选、预训练代码嵌入、仓库隔离的余弦 DBSCAN、逐簇独立判断、同区域直接合成 | Java DvCFG、精确 DCC、原实现的关联启发式、多 Agent 评分与合成后复审 |
| CIMAS-CPP | 当前完整流水线输入 | Tree-sitter、Embedding、DBSCAN、多重可信门控与关联闭环融合 | — |

三条 baseline 分别回答不同问题：Haggis-CPP 衡量概率语法方法在 C++ AST 上的
能力；LLM-Direct-Budget 衡量在相同模型与成本边界下，绕过结构分析和聚类的直接
LLM 能力；IdioMine-CPP 衡量本文前身方法的“依赖链候选、代码表示、密度
聚类、独立判断、同区域合成”简化链路在 C++ 上的能力。CIMAS-CPP 是待比较的
完整方法。Stage2-Frequency-Ablation 单独回答“没有后两阶段时高频簇中有多少是真正
高质量习语”，不应被称为第四条 baseline。

### 1.1 公平比较边界

正式实验必须遵守以下公共边界：

- 使用相同的仓库源码、文件过滤和完整合格源码；
- 各方法都在单个仓库的完整语料上独立发现习语，仓库间不得交换候选或结果；
- 方法参数在运行前按论文来源、固定资源预算、统一固定值或预先规定的无监督内部统计规则冻结；不得根据最终 IC、ISP、F1 或人工标签反复选择；
- 参考/测量文件分区只在全仓发现结束后的最终评价阶段形成，不触发重新发现；
- 公共适配器只做字段映射、来源证据规范化、精确去重和统一测量，不为某条 baseline 补做 AST 反统一、聚类、LLM 判断或合成；
- 自动指标使用每个方法的完整有效输出，允许习语种类数不同；
- Haggis-CPP、LLM-Direct-Budget、IdioMine-CPP 和 CIMAS-CPP 不设置最终种类数量上限；只有 Stage 2 高频聚类消融使用预注册的组合截断；
- smoke 的函数数、候选数或迭代限制必须写进独立 manifest 和输出目录，不能作为正式实验结果。

只有 `Stage2-Frequency-Ablation` 对输出种类执行数量截断。其顺序固定为：过滤 `cluster_size < min_cluster_size` 的簇；按 `cluster_size` 降序、`label` 稳定打破并列；保留合格簇的 `selection_ratio`；最后施加每项目 `max_types` 上限。`selection_ratio` 必须显式设置且位于 `(0, 1)`，正式数值必须在查看自动指标和人工标签前冻结；默认 `min_cluster_size=3`、`max_types=100`。因此 100 只是比例截断后的硬上限，并不表示每个项目固定取 Top100。

`Haggis-CPP` 输出所有通过 C++ 投影及后验支持、出现次数、文件数和节点数阈值的
片段；`LLM-Direct-Budget` 输出预算内 reduce 阶段返回且能映射到真实证据的全部
习语；`IdioMine-CPP` 输出全部独立判断通过项与全部成功的同区域直接
合成项；`CIMAS-CPP` 输出多重可信门控或关联闭环融合阶段的全部通过项。四者均不接受公共
Top100 或习语种类数量上限。LLM 的
`token_budget` 和 `max_output_tokens` 分别约束总调用成本和单次响应长度，不是
最终习语种类截断。

此前 `src.evaluation.mock_idioms` 生成的聚类 Top100 只用于检查指标分子、分母和聚合逻辑，带有 `mock_provenance`。它不能作为 CIMAS-CPP 结果，也不能混入正式实验。正式质量消融由 `src.evaluation.stage2_frequency_ablation` 生成，不带 mock 标记。

## 2. Haggis-CPP 的复现边界

实现参考 Haggis 原论文
[Mining Idioms from Source Code](https://doi.org/10.1145/2635868.2635901) 与
[原作者归档仓库](https://github.com/mast-group/codemining-treelm)。当前端口保留以下统计核心：

- AST 边上的隐式片段边界；
- PCFG 基分布；
- Dirichlet-process 后验预测概率；
- collapsed Gibbs 采样；
- burn-in 后按后验样本支持、出现次数、文件数和片段节点数筛选。

### 2.1 处理流程

当前实现按项目独立执行以下过程：

1. 从 `dataset.pkl` 读取函数级 Tree-sitter C++ AST，并将扁平深度序列恢复为有序树；
2. 将非叶节点编码为语法节点类型，将标识符和字面量叶子抽象为节点类别，保留必要的固定符号；
3. 在 AST 边上初始化片段根边界，形成由多个树片段组成的当前状态；
4. 从完整 AST 语料估计 PCFG 基分布，并用 Dirichlet-process 后验预测计算片段概率；
5. 使用逐点 collapsed Gibbs 依次重新采样可切分节点的边界状态；
6. 丢弃 burn-in 区间，在剩余样本中累计片段的样本出现、站点证据和文件支持；当前工程输出投影只接收函数/块/语句根、`ast_num >= 5` 且源码非空的片段；
7. 再用后验支持、最小出现次数、最小文件数和最小节点数阈值过滤；
8. 对全部合格片段生成 `*_idiom.pkl`，不执行 Top100 或其他种类数量截断。

确定性排序只保证产物稳定：依次按后验支持、唯一出现次数、片段节点数降序，再按模板文本打破并列。排序不会删除候选。

### 2.2 主要参数

| 参数 | 当前默认值 | 作用 | 正式实验要求 |
|---|---:|---|---|
| `iterations` | 50 | Gibbs 总迭代数 | 应结合原论文配置、收敛诊断和资源预算冻结 |
| `burn_in_fraction` | 0.75 | 丢弃的前段采样比例 | 与迭代数共同记录 |
| `alpha` | 1.0 | DP 集中参数 | 依据论文或预注册配置冻结，不查看最终指标 |
| `percent_roots_init` | 0.9 | 初始片段根比例 | 固定随机种子并记录 |
| `min_posterior_support` | 0.5 | 后验样本支持阈值 | 属于 Haggis 方法内过滤，不是数量截断 |
| `min_occurrences` | 3 | 最小唯一站点数 | 依据方法内支持度规则预先冻结 |
| `min_files` | 2 | 最小来源文件数 | 当前 C++ 输出质量过滤，需披露 |
| `min_fragment_nodes` | 3 | 最小片段节点数 | 对应最小结构规模过滤 |

`max_functions_per_project` 和 `max_nodes_per_function` 只用于 smoke 或资源保护，默认均不限制。正式结果若使用二者，必须降级标记为有界实验。

这是 C++ 算法复现，不是原 Java/JDT 程序直接支持 C++。当前适配差异会写进每条记录和运行 manifest：

- Tree-sitter C++ AST 替代 Java/JDT AST；
- 采用原仓库同样提供的逐点 collapsed Gibbs，未移植原命令用于混合加速的 type-blocked sampler；
- 保留有序子节点，未复用 JDT property binarization；
- 标识符与字面量按 Tree-sitter 节点类别抽象。

| 原方法要素 | 当前 C++ 适配 | 影响判断 |
|---|---|---|
| Java Eclipse JDT AST | Tree-sitter C++ AST | 必要的语言适配，节点词汇和树形会变化 |
| type-blocked sampler | pointwise collapsed Gibbs | 后验模型一致，但混合速度与收敛表现可能不同 |
| JDT structural property binarization | 有序子节点直接编码 | 会改变可学习片段空间，需作为复现差异披露 |
| 类型感知 MetaVariable | Tree-sitter 节点类别抽象 | 当前类型信息较弱，不能声称与 Java 输出等价 |
| Java 专用不可切分边界 | 未移植 C++ 对应约束 | 可能产生不同粒度的候选片段 |
| 原方法后验片段集合 | 仅投影为函数/块/语句根且 `ast_num >= 5` | 当前评价适配限制，不属于 Haggis 原方法，正式论文必须披露或做敏感性分析 |

### 2.3 Java 原实验与当前 C++ 结果的解释边界

Haggis 的 DP-pTSG 在数学上不绑定语言，但原论文的成功并非来自“任意 AST 直接输入”。
论文先用 Eclipse JDT 把 Java AST 转成专门的语法树：节点类型和 simple property 组成
语法符号，structural property 用来组织孩子；多孩子属性被二叉化以降低规则稀疏性；
`SimpleName` 之上插入带静态类型的 `MetaVariable`，使同一模式能够忽略局部变量名而
保留 `Cursor` 等类型角色。作者还删除 import，并把方法实参、限定/参数化类型孩子、
控制语句的非 block 子节点、括号/前后缀/中缀表达式和变量声明等固定为不可切分边界。
这些并非 DP-pTSG 公式本身，却直接决定 sampler 能否看到稳定且有语义的 Java 片段。

原实验也提供了更有利于后验学习的语料与验证条件：PROJECTS 含 13 个大型流行 Java
项目，LIBRARY 按 15 个常用 Java 库收集使用方文件；各组按 70/30 划分训练与测试，
运行 100 次 MCMC、前 75 次作为 burn-in。论文的 coverage 是测试 AST 中可匹配节点的
比例，precision 是已挖习语在测试语料中复现的比例；跨库实验还把多项目文件汇入同一
库集合。以 LIBRARY 挖得习语做外部验证时，论文报告 StackOverflow Java/Android
片段的 coverage/precision 为 31%/67%，PROJECTS 为 22%/50%，说明原方法在其 Java
表示和评价设计中并非低召回方法。它们与本文以 Stage 2 冻结聚类机会域计算的 IC、以
独立函数支持计算的 ISP 不是同一指标，原论文数值不能直接作为本文 Haggis-CPP 的预期下限。

当前 C++ 适配存在四个会系统性压低 IC 的因素：

1. Tree-sitter C++ 的模板、声明器、限定名、重载表达式和宏恢复形态使 AST 词汇与树形
   比 Java/JDT 更异质；当前有序树编码没有 JDT structural property 二叉化，同一语义
   容易因孩子数量和声明形态不同被拆成不同片段；
2. 当前叶子只按节点类别抽象，缺少 JDT binding 提供的类型化 `MetaVariable`。而 C++
   的 RAII、智能指针、迭代器、模板约束和所有权习语往往需要类型与调用关系才能把不同
   表面语法归为同一角色，纯局部语法后验会低估它们；
3. 当前未移植一套经验证的 C++ 不可切分边界，却又只把函数/块/语句根且满足规模条件的
   后验片段投影为最终习语；sampler 学到的细粒度或表达式级片段可能在投影时被丢弃；
4. 正式运行每仓独立采样 50 次并丢弃前 75%，使用逐点 sampler，实际用于累计的后验
   样本少于原论文的 100/75 配置；随后 `min_occurrences=3`、`min_files=2` 和
   `min_posterior_support=0.5` 又偏向少量跨文件稳定片段。因此三仓结果出现
   `ISP=1.0` 而 IC 很低，首先表示输出集合保守，不表示原 Haggis 在 Java 上无效。

这个差异也说明 CIMAS-CPP 的设计优势：Stage 1 同时保留语句、区域、函数及 L-CSDC
语义依赖候选；Stage 2 用代码表示和密度聚类吸收非同构语法变体；Stage 3 结合完整成员、
工程上下文、语义判断、受控抽象和独立异味门禁；Stage 4 再按共享区域关联、合成并复审。
因此主方法不要求一个 C++ 习语先在完全一致的局部 AST 分割下获得高 DP-pTSG 后验，
更适合当前以语义稳定、跨函数复用和最终质量为目标的评价。该结论解释的是任务、表示和
评价对齐优势，不把 Haggis-CPP 的低分误写成对原 Java 方法的否定。

因此当前结果可以用于验证 DP-pTSG C++ 路径、产物合同和评价兼容性；正式论文数值仍需
结合上述适配边界解释，不能宣称这是原版 Haggis 在 C++ 上的等价复现。

## 3. LLM-Direct-Budget 的预算合同

LLM 发现阶段只看到原始函数源码和机械生成的 `evidence_id`。AST 仅在 LLM 完成发现后，由公共评价适配器把模型逐字返回的 `source_code` 映射回当前评价器需要的 `source_infos`；映射顺序为“精确候选源码匹配，其次最小包含候选”，不参与候选发现。

### 3.1 处理流程

1. 按项目读取原始函数源码，附加稳定的 `evidence_id`，不读取 AST、Embedding 或聚类结果；
2. 按固定输入顺序和 `chunk_tokens` 机械分块；
3. map 调用让同一个模型从每块源码中直接返回模板、中文意图、置信度和原文证据；每块成功后立即写入 SQLite checkpoint；
4. 进入 reduce 前，按 map 顺序为每个唯一 `(evidence_id, source_code)` 机械分配稳定 `evidence_ref`；独立注册表保存完整原文，reduce 输入和输出只携带 `template、intent、confidence、evidence_refs`；
5. reduce 每层按稳定顺序机械分块，每块输出进入下一层；所有层的完整 system/user/schema 输入都不得超过 `reduce_chunk_tokens`，输出 refs 集合必须与当前输入块完全相等，遗漏或新增 ref 均明确报错；
6. 每层先对输出执行规范化模板去重并合并 refs，再重新分块；分块数严格减少时继续归并，若不再减少则停止额外调用并把当前稳定并集作为最终结果。每个保留项已经经过块内 LLM 归并，跨块只做确定性去重，语义不同项完整保留，因此这不是未归并 map，也不形成隐式数量截断；
7. 严格校验 map/reduce 各自的 JSON Schema，失败时同模型最多修复一次，修复请求也计入全局预算；map 按 `(project, chunk)`、reduce 按 `(project, level, chunk)`、项目完成状态按 `project` checkpoint，数据集重排不会串仓；
8. 最终按注册表把 refs 完整还原为 `evidence_id/source_code`，再由公共适配器映射为 `source_infos`；无法核验来源的项不进入正式产物，项目产物完成后写入项目级 checkpoint。

这种设计中的 `Budget` 指总 token/调用成本边界，而不是输出 Top-K。预算耗尽会停止后续模型请求；它不允许在已经得到的有效习语中再按数量裁剪。

预算是整个输入数据集上的全局上限，估算同时计入 system prompt、带 JSON Schema 的 user prompt 和实际 JSON 输出。每次真实端点请求都先按完整输入和最大输出预留检查剩余额度，因此 JSON 单次修复也不能绕过上限。checkpoint 在每条模型记录中保存累计近似 token 和端点请求数，续跑从最后记录恢复累计值而不是重新获得整笔预算；首响应已耗费 token、但修复请求在预算预检时被拒绝的情况也立即保存，续跑不会回退用量。连接失败的请求计入端点次数和已知输入 token，未知输出仍只能由服务端 usage/账单补充。manifest 分别保存逻辑 map/reduce `call_count` 与包含修复、失败尝试的 `endpoint_request_count`，并记录模型、估算输入输出 token、分块大小和逐项目调用统计。正式实验应另外保存端点实际 usage/账单，因为本地近似计数不能替代服务端计量。

默认模型只读取 `OPENAI_MODEL_LOW`。正式对比时必须与 CIMAS-CPP 使用同一基础模型，并先确定 CIMAS 的总输入输出 token，再把该预算显式传给 `--token-budget`。

### 3.2 主要参数与审计字段

| 参数/字段 | 含义 | 约束 |
|---|---|---|
| `token_budget` | 整个输入数据集的近似总输入输出 token 上限 | 正式实验与 CIMAS-CPP 匹配 |
| `chunk_tokens` | 机械源码块的近似输入规模 | 顺序和数值必须固定 |
| `reduce_chunk_tokens` | 任意层单个 reduce 完整 system/user/schema 输入的近似 token 上限 | 默认 4,000；稳定顺序机械分块 |
| `max_output_tokens` | 单次响应长度上限 | 不是习语种类数量上限 |
| `max_functions_per_project` | 有界 smoke 的输入函数限制 | 正式运行必须为不限制 |
| `call_count` | 成功完成的逻辑 map/reduce 数 | 写入 manifest |
| `endpoint_request_count` | 含 JSON 修复在内的实际请求数 | 写入 manifest |
| `estimated_input_output_tokens` | 本地近似累计用量 | 不能替代服务端 usage/账单 |
| `checkpoint` | 当前 SQLite checkpoint 路径 | 每个 map 块、reduce 和项目完成后立即提交 |
| `resumed` | 本次是否从 checkpoint 续跑 | 不改变分块、模型或预算合同 |
| `complete` | 全部项目是否完成 map、reduce 和产物写入 | 正式评价必须为 `true` |
| `processed_function_count` | 已完成 map 块覆盖的函数数 | 与输入函数总数共同审计完整性 |
| `token_budget_exhausted` | 本次是否因全局预算停止 | 为 `true` 时 validator 拒绝正式评价 |

若预算在 map 或 reduce 中耗尽，manifest 会记录不完整项目、已处理块/函数数和 `token_budget_exhausted=true`，不写该项目最终产物；统一 validator 拒绝其进入正式评价。真实调用还必须记录模型标识、日期、端点用量和源码披露范围。默认 checkpoint 位于 `outputs/leveldb/llm-direct-budget/checkpoint.sqlite3`，不会写入 `results/`。

证据映射使用 AST 只是为了满足当前评价器的数据合同，不会把节点类型或聚类信息反馈给 LLM。不过，这项投影会使无法落到当前候选粒度的 LLM 结果被丢弃，正式报告必须把它作为公共测量适配限制，而不能宣称纯 LLM 自身主动进行了 AST 过滤。

## 4. IdioMine-CPP 的简化迁移边界

IdioMine [E006] 的正式论文为
[Streamlining Java Programming: Uncovering Well-Formed Idioms with IdioMine](https://doi.org/10.1145/3597503.3639135)。
实现分析参考[作者公开仓库](https://github.com/Yanming-Yang/idioMine)。文献稳定编号由同级
`thesis/references/library.json` 维护，本仓库不复制文献库。

原方法的核心处理链为：从 Java 方法构造包含数据与控制关系的精简 DvCFG；沿
Data-driven Control Chain（DCC）抽取子习语；使用 GraphCodeBERT 表示子习语并
执行 DBSCAN；在同一项目、文件和函数中关联相关子习语；最后用 ChatGPT 合成、
判断并过滤完整习语。作者代码依赖 `javalang`，并包含 Java 节点类型、DvCFG
构造和 ChatGPT 提示，因此不能直接声称支持 C++。

### 4.1 保留与删减

| 原 IdioMine 操作 | 当前 C++ 迁移 | 实验解释 |
|---|---|---|
| Java DvCFG 与 DCC | 复用 Parser 产生的 `candidate_origin=semantic_def_use` 局部 Def-Use 片段 | 只近似数据依赖链，没有完整控制依赖，称为 DCC-lite |
| GraphCodeBERT 表示 | 复用输入 `embeddings.pkl` 的实际预训练模型向量，并强制记录 `--embedding-model` | 允许使用当前已缓存 UniXcoder；模型差异必须披露 |
| 密度聚类 | 每个仓库独立执行余弦 DBSCAN | 保留原方法的密度发现核心，不混合仓库 |
| ChatGPT 判断 | 对每个 DBSCAN 簇执行一次相互独立的结构化判断，只返回 `is_idiom` 和理由 | 不共享其他簇判断，不使用 CIMAS 的分类、评分或异味门禁 |
| 同函数子习语关联 | 以代表位置的 `project + file + function_extent` 完全相同作为同区域条件 | 不复现原作者代码中的字符串公共子串启发式 |
| ChatGPT 合成 | 对每个至少含两个已接受习语的同区域组尝试一次结构化合成 | `can_synthesize=true` 的结果直接作为习语，不做合成后判断 |

因此 `IdioMine-CPP` 是原方法操作顺序在 C++ 上的简化迁移，不是 IdioMine
的完整 C++ 复现。论文比较表必须使用这一完整名称，并披露 DCC-lite、Embedding
模型、区域关联规则和判断/合成简化差异；不能只标为 `IdioMine` 后暗示算法等价。
判断前候选统计只能作为 IdioMine-CPP 内部诊断，不得独立命名或替代正式
baseline 的判断与合成结果。

### 4.2 Java 原实验与当前 C++ 结果的解释边界

原版 IdioMine 的 DCC 不是对任意源码做局部 Def-Use 截取。论文先把 Java 方法转换为
同时保留数据流和控制流的精简 PDG，再从中构造具有连续语义的 DCC 子习语；该表示与
Java 节点类型、调用和控制结构共同决定聚类前能产生多少完整候选。原论文在 Java 项目
和库上报告其 ISP、IC 及习语产量多数优于 Haggis 和直接 ChatGPT，用户研究也认为输出
具有较好的完整性和语义清晰度。这说明 DCC 在论文所验证的 Java 表示上能够有效形成
聚类输入，不能用当前 C++ 适配结果否定原方法。

当前 `IdioMine-CPP` 的瓶颈首先出现在聚类之前。它只把 Parser 已产生的局部
`semantic_def_use` 片段当作 DCC-lite，没有建立原版 Java DvCFG/PDG，也没有完整控制
依赖、跨语句调用角色和原实现的子习语关联。在 C++ 中，模板实例与声明器、宏展开、
运算符重载、别名、RAII 获取—释放和隐式析构会让定义—使用及控制关系比普通 Java
局部变量链更难由零构建的局部近似恢复。因此当前 DCC-lite 只能形成很窄的候选子集；
后续 DBSCAN 无法重新发现未进入该子集的控制流、错误处理、资源管理和完整函数区域。
正式三仓候选漏斗、聚类数量和最终产量只记录在
[全仓实验记录](../../results/README.md#41-已完成外部-baseline-主指标及消融诊断)。

固定 `eps=0.5` 又会通过 DBSCAN 密度连通把少量 DCC-lite 片段合并为更少的宽簇，
而当前合同中每簇只对应一个独立判断对象。于是“聚类前候选少”和“聚类后宽簇合并”
共同限制最终习语数；这不是 LLM 判断阶段能够补回的召回损失。

CIMAS-CPP 针对此问题不把依赖链设为唯一入口：Stage 1 以语句、区域和函数三层候选
提供稳定产量下限，再用 L-CSDC 增量补充非连续语义关系；Stage 2 在完整多粒度候选上
选择仓库内密度尺度；Stage 3/4 再过滤偶然相似、补充上下文并形成最终习语。因此本文
能够得出的结论是：原版 DCC 适合其 Java PDG 前端，而当前简化 DCC-lite 不能单独承担
C++ 候选召回；多粒度保底加依赖增强的设计在当前 C++ 任务中产生了更多非噪声簇和
最终习语。不能进一步泛化为“DCC 原理不适用于任何 C++ 前端”；若实现完整 C++ PDG、
类型/别名分析和精确 DCC，应作为新的完整复现实验验证。

### 4.3 处理流程与参数

1. 读取一个或多个仓库隔离的 `embeddings.pkl`，拒绝重复项目或未对齐字段；
2. 只保留 `candidate_origin=semantic_def_use` 且具有非空源码的候选；
3. 拒绝非有限、零向量或维度不一致的 embedding；
4. 对每个仓库独立执行 `DBSCAN(metric="cosine")`；
5. 将每个非噪声簇转换为一个候选习语，以最接近簇质心的实例作为代表代码；
6. 对每个候选习语独立调用一次判断，保存全部判断理由，只接受
   `is_idiom=true`；
7. 按代表位置的 `project + file + function_extent` 精确分组，对同区域内至少
   两个已接受习语调用一次合成；
8. 接受 `can_synthesize=true` 且代码非空的合成结果，不执行合成后再判断；
9. 最终产物等于“全部独立判断通过项 + 全部成功的直接合成项”，不执行 Top-K
   或数量上限。

正式配置固定 `eps=0.5`、`min_samples=2`。相较旧试跑的 `eps=0.25`，较大的余弦
邻域减少 DCC-lite 单点噪声并把语义邻近片段合并为更完整的候选簇；它同时可能合并
边界相邻但语义不同的片段，因此仍由独立 ChatGPT 判断过滤，而不能解释为从 IdioMine
论文直接复现的参数。每簇最多提供 10 个代表实例，单次输出上限为 1024 token，避免
大簇只暴露少量变体或合成代码被 512 token 截断。所有仓库使用同一配置，不能根据最终
IC、ISP、F1 或人工标签逐仓调参。GraphCodeBERT 与 UniXcoder 结果应分开
标记；若将来下载 GraphCodeBERT 并复现精确 DCC，应建立新的完整复现实验，而不是
静默覆盖本 baseline。

简化 LLM 层只设“判断”和“合成”两种请求。两者均通过共享 `src.llm` 使用原生
JSON 模式、明确 JSON Schema 和一次 JSON 修复，默认读取低档模型。判断失败或
返回 `false` 时不进入合成；合成失败或返回 `false` 时只保留原有独立习语。全局
`token_budget` 同时约束判断、合成及 JSON 修复请求，预算耗尽的运行属于不完整
产物，统一验证器会拒绝。

## 5. Stage2-Frequency-Ablation 质量消融

该消融直接使用当前 Tree-sitter 规则候选、预训练代码嵌入和 DBSCAN 聚类结果。它不调用 LLM，不执行 Stage 3 多重可信门控或 Stage 4 关联闭环融合。每个保留簇直接对应一个待标注习语，簇中心作为代表代码，完整 `infos` 作为出现证据。

### 5.1 选择算法

对某项目的聚类集合 `C`，选择过程固定为：

1. 最小簇过滤：`E = {c ∈ C | cluster_size(c) >= min_cluster_size}`；
2. 稳定排序：按 `cluster_size` 降序，再按字符串化 `label` 升序打破并列；
3. 比例数量：`k_ratio = ceil(|E| × selection_ratio)`，只要 `E` 非空就至少为1；
4. 最终数量：`k = min(k_ratio, max_types)`；
5. 输出排序后的前 `k` 个簇。

默认 `min_cluster_size=3`、`max_types=100`；`selection_ratio` 没有隐式默认值，CLI 强制显式传入且要求 `0 < selection_ratio < 1`。比例必须在正式运行前固定，或由预先规定且只使用聚类内部支持度分布的无监督规则确定，不能查看最终 IC、ISP、F1 或人工标签后选择。旧的 `selection_ratio=1` 只执行数量上限，不符合当前组合截断合同。

manifest 对每个项目保存 `input_cluster_count`、`minimum_size_eligible_count`、`ratio_selected_count_before_cap`、`selected_cluster_count` 和 `selected_idiom_count`，从而可以核对每一步实际删除了多少簇。100 只是比例选择后的硬上限，并不保证每个项目输出100类。

### 5.2 评价边界与人工质量比较

- 簇大小是唯一原生排序分数，不引入 LLM 评分或 CIMAS 判定结果；
- 最小簇大小、比例和数量上限必须作为一个整体配置报告；
- 聚类必须观察该仓库的全部合格候选；最终参考/测量分区不回溯改变 embedding 或聚类；
- 该消融与主 IC 分母使用同一 Stage 2 聚类来源，IC、ISP、F1 只作为覆盖上界诊断，不能进入外部 baseline 自动指标排名；
- 大簇可能来自样板代码或密度塌缩，频率不能直接解释为习语有效性；
- 主要比较采用与 CIMAS-CPP 等量、分层、隐藏方法名和原生分数的人工样本，两名 C++ 标注者独立判断 `valid_idiom`、`invalid_idiom`、`context_dependent` 和严重异味，分歧由第三人裁决；
- 报告有效习语率、反模式泄漏率、样本数、置信区间和标注一致性；只有该人工结果可以支持“Stage 3/4 提高习语质量”的结论；
- Stage 2 与 Stage 4 的两组比较只估计 Stage 3+4 的合并质量增益；若要分别归因于两个阶段，使用同一抽样与盲评合同增加 Stage 3 `accepted` 第三组，进行 Stage 2/3/4 三组比较；
- 历史 `clusters.top100.json` 是人工预览/公式模拟清单，不是正式质量消融输入接口。

## 6. 统一产物与指标证明

三条 baseline 与 Stage 2 质量消融都输出 `{repo}_idiom.pkl`，并保留当前判断阶段的公共字段：

- `center_point`、`info`、完整 `source_infos`；
- `cnt`、`avg_ast_num`、`avg_subtree_size`、`loc_label`；
- 三条外部 baseline 使用 `baseline_provenance`，Stage 2 质量消融使用
  `ablation_provenance`，分别记录方法、参数和来源；
- 外部 baseline 写入 `baseline-manifest.json`，质量消融写入
  `ablation-manifest.json`，避免把内部消融误列为外部方法。

`src.evaluation.baseline_validation` 会先拒绝缺失来源证据、`cnt` 不一致或带
`mock_provenance` 的产物；它还拒绝 Haggis/LLM/IdioMine-CPP 的最终种类
数量上限、IdioMine-CPP 缺失 DCC-lite/DBSCAN/迁移声明、未按
“独立判断→同区域直接合成”执行或预算耗尽的配置，以及缺少质量实验定位、
“最小簇大小→比例→数量上限”组合或比例不小于1的消融配置。随后才调用现有
`src.evaluation.idiom_metrics`。所有方法必须显式传入同一份 Stage 3 裁决前冻结的
Stage 2 非噪声聚类产物；IC 的函数和节点分母由该产物固定，不随各方法最终输出
变化。验证只有在逐项目、仓库宏平均和全局三个层次都
包含下列九个有限数值时才通过：

`IC_macro`、`IC_micro`、`IC`、`ISP`、`F1`、`idiom_type_count`、`avg_cluster_size`、`avg_cross_function_support`、`AvgAST`。

### 6.1 公共记录字段

| 字段 | 含义 |
|---|---|
| `center_point` | 代表代码或可供当前匹配器使用的实例文本 |
| `template` | 方法能够提供时保存的参数化/树片段模板 |
| `info` | 与代表代码对应的来源信息 |
| `source_infos` | 该习语全部可核验来源证据，评价时不得只保留中心点 |
| `cnt` | 去重后的来源证据数量，必须等于 `len(source_infos)` |
| `avg_ast_num` / `avg_subtree_size` | 兼容的 AST 规模统计 |
| `loc_label` | 项目、文件和候选范围组成的稳定位置标签 |
| `baseline_provenance` / `ablation_provenance` | 外部 baseline / 内部质量消融的方法、参数、适配差异、预算或选择规则 |

评价器允许各方法的 `idiom_type_count` 不同。它不会做公共 Top100、补齐、重排或按最小方法数量对齐；ISP 和结构指标使用每个方法自己的完整有效集合，IC 则统一使用同一仓库预先冻结的聚类机会域。Stage 2 消融虽通过同一指标入口进行审计，但其自动数值不得解释为相对外部 baseline 或 CIMAS-CPP 的质量优劣。

## 7. 复现命令

以下命令以 `leveldb` 展示单仓运行。正式 baseline 使用
`outputs/<repo>/stage0` 和 `outputs/<repo>/stage2` 的标准输入，输出到
`results/baselines/<method>/<repo>`；所有正式结果只追加到
[全仓实验记录](../../results/README.md)。

### Haggis-CPP

```bash
.venv/bin/python -m src.evaluation.haggis_cpp \
  --dataset outputs/leveldb/stage0/dataset.pkl \
  --output-dir results/baselines/haggis-cpp/leveldb \
  --iterations 50 --burn-in-fraction 0.75 --alpha 1.0 \
  --min-posterior-support 0.5 --min-occurrences 3 \
  --min-files 2 --min-fragment-nodes 3

.venv/bin/python -m src.evaluation.baseline_validation \
  --method haggis-cpp \
  --idiom-dir results/baselines/haggis-cpp/leveldb \
  --dataset outputs/leveldb/stage0/dataset.pkl \
  --clusters outputs/leveldb/stage2/clusters.pkl
```

`--max-functions-per-project` 和 `--max-nodes-per-function` 只用于有界 smoke 或资源保护；正式运行必须在 manifest 中说明是否使用。

### LLM-Direct-Budget

```bash
.venv/bin/python -m src.evaluation.llm_direct_baseline \
  --dataset outputs/leveldb/stage0/dataset.pkl \
  --output-dir results/baselines/llm-direct-budget/leveldb \
  --checkpoint outputs/leveldb/llm-direct-budget/checkpoint.sqlite3 \
  --token-budget <与CIMAS匹配的总输入输出token预算> \
  --chunk-tokens 3000 --reduce-chunk-tokens 4000 \
  --max-output-tokens 2048

# 中断后使用完全相同的输入、分块和预算续跑
.venv/bin/python -m src.evaluation.llm_direct_baseline \
  --dataset outputs/leveldb/stage0/dataset.pkl \
  --output-dir results/baselines/llm-direct-budget/leveldb \
  --checkpoint outputs/leveldb/llm-direct-budget/checkpoint.sqlite3 \
  --resume \
  --token-budget <与CIMAS匹配的总输入输出token预算> \
  --chunk-tokens 3000 --reduce-chunk-tokens 4000 \
  --max-output-tokens 2048

.venv/bin/python -m src.evaluation.baseline_validation \
  --method llm-direct-budget \
  --idiom-dir results/baselines/llm-direct-budget/leveldb \
  --dataset outputs/leveldb/stage0/dataset.pkl \
  --clusters outputs/leveldb/stage2/clusters.pkl
```

真实入口会发送源码到配置的模型端点。先用合成代码与 `--max-functions-per-project` 做 smoke，再单独审批公开语料范围、调用数和成本。

### Stage2-Frequency-Ablation

```bash
.venv/bin/python -m src.evaluation.stage2_frequency_ablation \
  --clusters outputs/leveldb/stage2/clusters.pkl \
  --output-dir results/ablations/stage2-frequency/leveldb \
  --min-cluster-size 3 \
  --selection-ratio <预注册固定值或无监督规则确定值> --max-types 100

.venv/bin/python -m src.evaluation.baseline_validation \
  --method stage2-frequency-ablation \
  --idiom-dir results/ablations/stage2-frequency/leveldb \
  --dataset outputs/leveldb/stage0/dataset.pkl \
  --clusters outputs/leveldb/stage2/clusters.pkl
```

运行 manifest 同时记录质量消融定位、原始簇数、最小簇大小过滤后的合格簇数、比例截断数量、数量上限和最终产物数。比例与阈值不得用最终参考/测量指标或人工标签调参；输出进入统一盲化人工质量池。

### IdioMine-CPP

```bash
.venv/bin/python -m src.evaluation.idiomine_cpp \
  --embeddings outputs/leveldb/stage2/embeddings.pkl \
  --embedding-model microsoft/unixcoder-base \
  --eps 0.5 --min-samples 2 \
  --estimate-only --max-output-tokens 1024 --max-examples-per-judgment 10

.venv/bin/python -m src.evaluation.idiomine_cpp \
  --embeddings outputs/leveldb/stage2/embeddings.pkl \
  --output-dir results/baselines/idiomine-cpp/leveldb \
  --embedding-model microsoft/unixcoder-base \
  --eps 0.5 --min-samples 2 \
  --token-budget <审批后的总输入输出token预算> \
  --max-output-tokens 1024 --max-examples-per-judgment 10

.venv/bin/python -m src.evaluation.baseline_validation \
  --method idiomine-cpp \
  --idiom-dir results/baselines/idiomine-cpp/leveldb \
  --dataset outputs/leveldb/stage0/dataset.pkl \
  --clusters outputs/leveldb/stage2/clusters.pkl
```

`--embeddings` 可以重复传入，但每个项目只能出现一次。正式实验应逐仓生成输入并
使用同一套预注册参数；`--embedding-model` 必须与输入向量的真实模型一致。该
单一入口在内部依次完成候选聚类、独立判断和直接合成；不下载 embedding 模型，
但会把候选源码发送到配置端点。必须先用 `--estimate-only` 固定候选数、模型、
调用上界、token 预算、费用风险和披露范围，再执行真实批次。

### CIMAS-CPP

```bash
.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/leveldb/stage2/clusters.pkl \
  --source-root repos/project/leveldb --require-context \
  --output outputs/leveldb/stage3/idiom-judgment.pkl

.venv/bin/python -m src.idiom_synthesis.synthesize_idioms \
  --input outputs/leveldb/stage3/idiom-judgment.pkl \
  --source-root repos/project/leveldb \
  --output outputs/leveldb/stage4/idiom-synthesis.pkl

mkdir -p results/main/leveldb
cp outputs/leveldb/stage4/idiom-synthesis.pkl \
  results/main/leveldb/idiom-synthesis.pkl

.venv/bin/python -m src.evaluation.baseline_validation \
  --method cimas-cpp --idiom-dir results/main/leveldb \
  --dataset outputs/leveldb/stage0/dataset.pkl \
  --clusters outputs/leveldb/stage2/clusters.pkl --allow-main-method
```

阶段4的 `accepted` 是阶段3基础习语与去重后新增合成的最终知识库；
`synthesized` 单独保留新增合成，来源候选只作证据。正式主方法评价使用
`--stage synthesis`。不能把 `outputs/leveldb/mock/` 传给
`--allow-main-method`。

## 8. 当前验证状态

- 离线端到端测试使用三个确定性合成项目，真实运行三条 baseline 和一条 Stage 2 质量消融，并以当前
  `idiom_judgment` artifact 验证 CIMAS-CPP 与九指标入口的兼容性；Agent 编排由
  阶段3和阶段4各自的专门测试覆盖。三条 baseline、质量消融与本文方法都在逐项目、仓库宏平均和全局层通过
  九指标合同。
- `Stage2-Frequency-Ablation` 的三段组合截断与质量实验定位已由确定性测试覆盖；`selection_ratio=1` 不符合当前合同。
- `Haggis-CPP` 与 `LLM-Direct-Budget` 的有界 smoke 只验证代码路径，不保留为正式
  实验结果。
- IdioMine-CPP 的候选构建、逐簇判断、同区域直接合成和九指标合同均有确定性
  测试。任何筛选前仓库集合或旧指标定义产生的本地产物都不得作为当前论文结果；
  正式运行须使用当前项目清单和[评价指标规范](evaluation-metrics.md)。
- `IdioMine-CPP` 已通过 fake client 确定性测试，覆盖逐簇独立判断、精确同区域分组、
  成功合成直接接受、理由审计和统一九指标。正式多仓真实付费运行前必须按当前清单
  重新计算调用预算。

以上证明代码路径与九项指标兼容，不是正式方法优劣结论。smoke 和 mock 产物不作为
全量实验的可复用输入，正式仓库比较只以全仓实验记录为准。
