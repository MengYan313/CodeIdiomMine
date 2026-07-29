# C++ 习语实验方法与 baseline 复现

- 版本：**Sol 6.1**
- 状态：当前 baseline 实现与复现规范
- 生效日期：2026-07-29
- 适用范围：四条 baseline、CIMAS-CPP 对照边界、公共产物适配和九指标验证

当前端到端比较固定为五种方法：`Haggis-CPP`、`LLM-Direct-Budget`、
`Rules-Embedding-Clustering`、`IdioMine-CPP` 和本文方法
`CIMAS-CPP`。其中 `LLM-Direct-Budget` 是仅 LLM 的端点消融，
`Rules-Embedding-Clustering` 是不经过 LLM 判断与合成的端点消融；
`IdioMine-CPP` 是论文 IdioMine 核心操作、独立 ChatGPT 判断和同区域
直接合成的 C++ 简化迁移，不是完整复现。DCC-lite 与 DBSCAN 只是该方法内部的
判断前候选阶段，不作为独立方法、入口或评价对象。
它们与更细粒度的模块消融可以同时保留，但不应重复计为两个不同方法。

本文只定义方法、产物和运行入口；九项固定指标的公式与聚合口径以[评价指标规范](evaluation-metrics.md)为唯一事实来源。

五种方法都以单个完整仓库为独立发现单元。各仓库的候选、embedding、聚类和
方法输出不得混合；发现前不做训练/开发/测试划分。多仓库比较只在各仓独立评价
完成后汇总。

## 1. 五种方法

| 方法 | 发现输入 | 核心处理 | 明确不使用 |
|---|---|---|---|
| Haggis-CPP | 当前函数级 Tree-sitter C++ AST | DP-pTSG、PCFG 基分布、collapsed Gibbs、burn-in 后片段累计 | Embedding、DBSCAN、LLM、Agent、合成 |
| LLM-Direct-Budget | 机械分块的原始 C++ 函数源码 | 同一模型 map/reduce，严格 JSON Schema，总 token 预算 | AST/CFG、Embedding、聚类、多 Agent |
| Rules-Embedding-Clustering | 当前 `clusters.pkl` | 簇大小过滤、比例截断、每项目种类上限；保留簇直接作为习语 | LLM 判断、Agent、习语合成 |
| IdioMine-CPP | 当前 `embeddings.pkl` 中的 `semantic_def_use` 片段 | DCC-lite 候选、预训练代码嵌入、仓库隔离的余弦 DBSCAN、逐簇独立判断、同区域直接合成 | Java DvCFG、精确 DCC、原实现的关联启发式、多 Agent 评分与合成后复审 |
| CIMAS-CPP | 当前完整流水线输入 | Tree-sitter、Embedding、DBSCAN、多重可信门控与关联闭环融合 | — |

四条 baseline 分别回答不同问题：Haggis-CPP 衡量概率语法方法在 C++ AST 上的
能力；LLM-Direct-Budget 衡量在相同模型与成本边界下，绕过结构分析和聚类的直接
LLM 能力；Rules-Embedding-Clustering 衡量只保留规则候选、嵌入和聚类时的端点
表现；IdioMine-CPP 衡量本文前身方法的“依赖链候选、代码表示、密度
聚类、独立判断、同区域合成”简化链路在 C++ 上的能力。CIMAS-CPP 是待比较的
完整方法，不应被称为第五条 baseline。

### 1.1 公平比较边界

正式实验必须遵守以下公共边界：

- 使用相同的仓库版本、文件过滤和完整合格源码；
- 各方法都在单个仓库的完整语料上独立发现习语，仓库间不得交换候选或结果；
- 方法参数在运行前按论文来源、固定资源预算、统一固定值或预先规定的无监督内部统计规则冻结；不得根据最终 IC、ISP、F1 或人工标签反复选择；
- 参考/测量文件分区只在全仓发现结束后的最终评价阶段形成，不触发重新发现；
- 公共适配器只做字段映射、来源证据规范化、精确去重和统一测量，不为某条 baseline 补做 AST 反统一、聚类、LLM 判断或合成；
- 自动指标使用每个方法的完整有效输出，允许习语种类数不同；
- Haggis-CPP、LLM-Direct-Budget、IdioMine-CPP 和 CIMAS-CPP 不设置最终种类数量上限；只有规则 baseline 使用其方法定义内的组合截断；
- smoke 的函数数、候选数或迭代限制必须写进独立 manifest 和输出目录，不能作为正式实验结果。

只有 `Rules-Embedding-Clustering` 对最终习语种类执行数量截断。其顺序固定为：过滤 `cluster_size < min_cluster_size` 的簇；按 `cluster_size` 降序、`label` 稳定打破并列；保留合格簇的 `selection_ratio`；最后施加每项目 `max_types` 上限。`selection_ratio` 必须显式设置且位于 `(0, 1)`，正式数值必须在运行前作为统一固定值，或由只观察本仓聚类支持度分布的预注册无监督规则确定；默认 `min_cluster_size=3`、`max_types=100`。因此 100 只是比例截断后的硬上限，并不表示每个项目固定取 Top100。

`Haggis-CPP` 输出所有通过 C++ 投影及后验支持、出现次数、文件数和节点数阈值的
片段；`LLM-Direct-Budget` 输出预算内 reduce 阶段返回且能映射到真实证据的全部
习语；`IdioMine-CPP` 输出全部独立判断通过项与全部成功的同区域直接
合成项；`CIMAS-CPP` 输出多重可信门控或关联闭环融合阶段的全部通过项。四者均不接受公共
Top100 或习语种类数量上限。LLM 的
`token_budget` 和 `max_output_tokens` 分别约束总调用成本和单次响应长度，不是
最终习语种类截断。

此前 `src.evaluation.mock_idioms` 生成的聚类 Top100 只用于检查指标分子、分母和聚合逻辑，带有 `mock_provenance`。它不能作为 CIMAS-CPP 结果，也不能混入正式 baseline。正式规则基线由 `src.evaluation.rules_embedding_baseline` 生成，不带 mock 标记。

## 2. Haggis-CPP 的复现边界

实现固定参考 Haggis 论文与原作者归档仓库 `mast-group/codemining-treelm` 的 commit `8b241a195fe860713c8dbbee387710533b97258c`。当前端口保留以下统计核心：

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

因此当前结果可以用于验证 DP-pTSG C++ 路径、产物合同和评价兼容性；正式论文数值仍需冻结语料、迭代数、burn-in、多个随机种子和收敛诊断，不能把小规模 smoke 写成完整 Haggis 复现实验。

## 3. LLM-Direct-Budget 的预算合同

LLM 发现阶段只看到原始函数源码和机械生成的 `evidence_id`。AST 仅在 LLM 完成发现后，由公共评价适配器把模型逐字返回的 `source_code` 映射回当前评价器需要的 `source_infos`；映射顺序为“精确候选源码匹配，其次最小包含候选”，不参与候选发现。

### 3.1 处理流程

1. 按项目读取原始函数源码，附加稳定的 `evidence_id`，不读取 AST、Embedding 或聚类结果；
2. 按固定输入顺序和 `chunk_tokens` 机械分块；
3. map 调用让同一个模型从每块源码中直接返回模板、中文意图、置信度和原文证据；
4. reduce 调用只归并 map 候选中的语义重复项，不允许增加新的证据或读取额外源码；
5. 严格校验 JSON Schema，失败时同模型最多修复一次，修复请求也计入全局预算；
6. 完成发现后才把逐字证据映射为公共 `source_infos`；当前适配器要求证据能精确匹配或包含于函数/块/语句且 `ast_num >= 5` 的评价候选，无法核验来源的项不进入正式产物；
7. 保存预算内全部可核验 reduce 结果，不施加最终习语数量上限。

这种设计中的 `Budget` 指总 token/调用成本边界，而不是输出 Top-K。预算耗尽会停止后续模型请求；它不允许在已经得到的有效习语中再按数量裁剪。

预算是整个输入数据集上的全局上限，估算同时计入 system prompt、带 JSON Schema 的 user prompt 和实际 JSON 输出。每次真实端点请求都先按完整输入和最大输出预留检查剩余额度，因此 JSON 单次修复也不能绕过上限。manifest 分别保存逻辑 map/reduce `call_count` 与包含修复的 `endpoint_request_count`，并记录模型、prompt hash、估算输入输出 token、分块大小和逐项目调用统计。正式实验应另外保存端点实际 usage/账单，因为本地近似计数不能替代服务端计量。

默认模型只读取 `OPENAI_MODEL_LOW`。正式对比时必须与 CIMAS-CPP 使用同一基础模型，并先确定 CIMAS 的总输入输出 token，再把该预算显式传给 `--token-budget`。

### 3.2 主要参数与审计字段

| 参数/字段 | 含义 | 约束 |
|---|---|---|
| `token_budget` | 整个输入数据集的近似总输入输出 token 上限 | 正式实验与 CIMAS-CPP 匹配 |
| `chunk_tokens` | 机械源码块的近似输入规模 | 顺序和数值必须固定 |
| `max_output_tokens` | 单次响应长度上限 | 不是习语种类数量上限 |
| `max_functions_per_project` | 有界 smoke 的输入函数限制 | 正式运行必须为不限制 |
| `call_count` | 成功完成的逻辑 map/reduce 数 | 写入 manifest |
| `endpoint_request_count` | 含 JSON 修复在内的实际请求数 | 写入 manifest |
| `estimated_input_output_tokens` | 本地近似累计用量 | 不能替代服务端 usage/账单 |

若预算不足以执行某项目的 reduce，该项目输出为空并记录警告，不能把未经统一归并的 map 候选悄悄当成正式结果。真实调用还必须记录模型标识、prompt hash、日期、端点用量和源码披露范围。

证据映射使用 AST 只是为了满足当前评价器的数据合同，不会把节点类型或聚类信息反馈给 LLM。不过，这项投影会使无法落到当前候选粒度的 LLM 结果被丢弃，正式报告必须把它作为公共测量适配限制，而不能宣称纯 LLM 自身主动进行了 AST 过滤。

## 4. IdioMine-CPP 的简化迁移边界

IdioMine [E006] 的正式论文为
[Streamlining Java Programming: Uncovering Well-Formed Idioms with IdioMine](https://doi.org/10.1145/3597503.3639135)。
实现分析固定参考[作者公开仓库](https://github.com/Yanming-Yang/idioMine)的
commit `b9961c9fe85203eff16351d470b11b381572467f`。文献稳定编号由同级
`thesis/references/library.json` 维护，本仓库不复制文献库。

原方法的核心处理链为：从 Java 方法构造包含数据与控制关系的精简 DvCFG；沿
Data-driven Control Chain（DCC）抽取子习语；使用 GraphCodeBERT 表示子习语并
执行 DBSCAN；在同一项目、文件和函数中关联相关子习语；最后用 ChatGPT 合成、
判断并过滤完整习语。作者代码依赖 `javalang`，并包含 Java 节点类型、DvCFG
构造和 ChatGPT 提示，因此不能直接声称支持 C++。

### 4.1 保留与删减

| 原 IdioMine 操作 | 当前 C++ 迁移 | 实验解释 |
|---|---|---|
| Java DvCFG 与 DCC | 复用 Parser `def-use-v1` 产生的 `candidate_origin=semantic_def_use` 局部 Def-Use 片段 | 只近似数据依赖链，没有完整控制依赖，称为 DCC-lite |
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

### 4.2 处理流程与参数

1. 读取一个或多个仓库隔离的 `embeddings.pkl`，拒绝重复项目或未对齐字段；
2. 只保留 `semantic_def_use + def-use-v1` 且具有非空源码的候选；
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

当前 CLI 默认 `eps=0.25`、`min_samples=2`，只用于与现有缓存基线保持一致，不能
解释为从 IdioMine 论文直接复现的正式参数。正式多仓实验应在查看最终 IC、ISP、
F1 和人工标签前，统一冻结 embedding 模型、`eps` 与 `min_samples`，或为所有
仓库预注册相同的无监督参数选择规则。GraphCodeBERT 与 UniXcoder 结果应分开
标记；若将来下载 GraphCodeBERT 并复现精确 DCC，应建立新的完整复现实验，而不是
静默覆盖本 baseline。

简化 LLM 层只设“判断”和“合成”两种请求。两者均通过共享 `src.llm` 使用原生
JSON 模式、明确 JSON Schema 和一次 JSON 修复，默认读取低档模型。判断失败或
返回 `false` 时不进入合成；合成失败或返回 `false` 时只保留原有独立习语。全局
`token_budget` 同时约束判断、合成及 JSON 修复请求，预算耗尽的运行属于不完整
产物，统一验证器会拒绝。

## 5. Rules-Embedding-Clustering 的组合截断

该 baseline 直接使用当前 Tree-sitter 规则候选、预训练代码嵌入和 DBSCAN 聚类结果。它不调用 LLM，不执行多 Agent 判断、代码异味审查、AST 反统一、习语合成或回流复审。每个保留簇直接对应一个习语种类，簇中心作为代表代码，完整 `infos` 作为出现证据。

### 5.1 选择算法

对某项目的聚类集合 `C`，选择过程固定为：

1. 最小簇过滤：`E = {c ∈ C | cluster_size(c) >= min_cluster_size}`；
2. 稳定排序：按 `cluster_size` 降序，再按字符串化 `label` 升序打破并列；
3. 比例数量：`k_ratio = ceil(|E| × selection_ratio)`，只要 `E` 非空就至少为1；
4. 最终数量：`k = min(k_ratio, max_types)`；
5. 输出排序后的前 `k` 个簇。

默认 `min_cluster_size=3`、`max_types=100`；`selection_ratio` 没有隐式默认值，CLI 强制显式传入且要求 `0 < selection_ratio < 1`。比例必须在正式运行前固定，或由预先规定且只使用聚类内部支持度分布的无监督规则确定，不能查看最终 IC、ISP、F1 或人工标签后选择。旧的 `selection_ratio=1` 只执行数量上限，不符合当前组合截断合同。

manifest 对每个项目保存 `input_cluster_count`、`minimum_size_eligible_count`、`ratio_selected_count_before_cap`、`selected_cluster_count` 和 `selected_idiom_count`，从而可以核对每一步实际删除了多少簇。100 只是比例选择后的硬上限，并不保证每个项目输出100类。

### 5.2 方法边界与风险

- 簇大小是唯一原生排序分数，不引入 LLM 评分或 CIMAS 判定结果；
- 最小簇大小、比例和数量上限必须作为一个整体配置报告；
- 聚类必须观察该仓库的全部合格候选；最终参考/测量分区不回溯改变 embedding 或聚类；
- 大簇可能来自样板代码或密度塌缩，因此该 baseline 只能说明规则+表示学习端点表现，不能把频率直接解释为习语有效性；
- 历史 `clusters.top100.json` 是人工预览/公式模拟清单，不是正式规则 baseline 的输入接口。

## 6. 统一产物与指标证明

四条 baseline 都输出 `results/.../{repo}_idiom.pkl`，并保留当前判断阶段的公共字段：

- `center_point`、`info`、完整 `source_infos`；
- `cnt`、`avg_ast_num`、`avg_subtree_size`、`loc_label`；
- `baseline_provenance`，记录方法、参数和来源。

`src.evaluation.baseline_validation` 会先拒绝缺失来源证据、`cnt` 不一致或带
`mock_provenance` 的产物；它还拒绝 Haggis/LLM/IdioMine-CPP 的最终种类
数量上限、IdioMine-CPP 缺失 DCC-lite/DBSCAN/迁移声明、未按
“独立判断→同区域直接合成”执行或预算耗尽的配置，以及缺少
“最小簇大小→比例→数量上限”组合或比例不小于1的旧规则配置。随后才调用现有
`src.evaluation.idiom_metrics`。验证只有在逐项目、仓库宏平均和全局三个层次都
包含下列九个有限数值时才通过：

`IC_macro`、`IC_micro`、`IC`、`ISP`、`F1`、`idiom_type_count`、`avg_cluster_size`、`avg_cross_file_support`、`AvgAST`。

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
| `baseline_provenance` | 方法、参数、适配差异、预算或选择规则 |

评价器允许各方法的 `idiom_type_count` 不同。它不会做公共 Top100、补齐、重排或按最小方法数量对齐；IC、ISP、F1 和结构指标均以每个方法自己的完整有效集合为分母。

## 7. 复现命令

### Haggis-CPP

```bash
.venv/bin/python -m src.evaluation.haggis_cpp \
  --dataset outputs/cpp/dataset.pkl \
  --output-dir results/baselines/haggis-cpp/cpp \
  --iterations 50 --burn-in-fraction 0.75 --alpha 1.0 \
  --min-posterior-support 0.5 --min-occurrences 3 \
  --min-files 2 --min-fragment-nodes 3

.venv/bin/python -m src.evaluation.baseline_validation \
  --method haggis-cpp \
  --idiom-dir results/baselines/haggis-cpp/cpp \
  --dataset outputs/cpp/dataset.pkl
```

`--max-functions-per-project` 和 `--max-nodes-per-function` 只用于有界 smoke 或资源保护；正式运行必须在 manifest 中说明是否使用。

### LLM-Direct-Budget

```bash
.venv/bin/python -m src.evaluation.llm_direct_baseline \
  --dataset outputs/cpp/dataset.pkl \
  --output-dir results/baselines/llm-direct-budget/cpp \
  --token-budget <与CIMAS匹配的总输入输出token预算> \
  --chunk-tokens 3000 --max-output-tokens 2048

.venv/bin/python -m src.evaluation.baseline_validation \
  --method llm-direct-budget \
  --idiom-dir results/baselines/llm-direct-budget/cpp \
  --dataset outputs/cpp/dataset.pkl
```

真实入口会发送源码到配置的模型端点。先用合成代码与 `--max-functions-per-project` 做 smoke，再单独审批公开语料范围、调用数和成本。

### Rules-Embedding-Clustering

```bash
.venv/bin/python -m src.evaluation.rules_embedding_baseline \
  --clusters outputs/cpp/clusters.pkl \
  --output-dir results/baselines/rules-embedding-clustering/cpp \
  --min-cluster-size 3 \
  --selection-ratio <预注册固定值或无监督规则确定值> --max-types 100

.venv/bin/python -m src.evaluation.baseline_validation \
  --method rules-embedding-clustering \
  --idiom-dir results/baselines/rules-embedding-clustering/cpp \
  --dataset outputs/cpp/dataset.pkl
```

运行 manifest 同时记录原始簇数、最小簇大小过滤后的合格簇数、比例截断数量、数量上限和最终产物数。比例与阈值不得用最终参考/测量指标或人工标签调参。

### IdioMine-CPP

```bash
.venv/bin/python -m src.evaluation.idiomine_cpp \
  --embeddings outputs/cpp/cli11/embeddings.pkl \
  --embedding-model microsoft/unixcoder-base \
  --eps 0.25 --min-samples 2 \
  --estimate-only --max-output-tokens 512 --max-examples-per-judgment 5

.venv/bin/python -m src.evaluation.idiomine_cpp \
  --embeddings outputs/cpp/cli11/embeddings.pkl \
  --output-dir results/baselines/idiomine-cpp/cpp \
  --embedding-model microsoft/unixcoder-base \
  --eps 0.25 --min-samples 2 \
  --token-budget <审批后的总输入输出token预算> \
  --max-output-tokens 512 --max-examples-per-judgment 5

.venv/bin/python -m src.evaluation.baseline_validation \
  --method idiomine-cpp \
  --idiom-dir results/baselines/idiomine-cpp/cpp \
  --dataset outputs/cpp/cli11/dataset.pkl
```

`--embeddings` 可以重复传入，但每个项目只能出现一次。正式实验应逐仓生成输入并
使用同一套预注册参数；`--embedding-model` 必须与输入向量的真实模型一致。该
单一入口在内部依次完成候选聚类、独立判断和直接合成；不下载 embedding 模型，
但会把候选源码发送到配置端点。必须先用 `--estimate-only` 固定候选数、模型、
调用上界、token 预算、费用风险和披露范围，再执行真实批次。

### CIMAS-CPP

```bash
.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/cpp/cli11/clusters.pkl \
  --source-root repos/cli11 --require-context \
  --output results/cpp/cli11_idiom.pkl

.venv/bin/python -m src.idiom_synthesis.synthesize_idioms \
  --input results/cpp/cli11_idiom.pkl \
  --source-root repos/cli11 \
  --output results/cpp/cli11_idiom_syn.pkl

.venv/bin/python -m src.evaluation.baseline_validation \
  --method cimas-cpp --idiom-dir results/cpp \
  --dataset outputs/cpp/dataset.pkl --allow-main-method
```

上面的主方法评价示例使用阶段3完整 `accepted` 产物。阶段4是
`synthesis_delta`，使用 `--stage synthesis` 只能分析合成增量本身，不能把该
增量误当作包含未合成习语的完整知识库。不能把 `results/evaluation-mock/`
传给 `--allow-main-method`。

## 8. 当前验证状态

- 离线端到端测试使用三个确定性合成项目，真实运行四条 baseline，并以当前
  `idiom_judgment` artifact 验证 CIMAS-CPP 与九指标入口的兼容性；Agent 编排由
  阶段3和阶段4各自的专门测试覆盖。五种方法都在逐项目、仓库宏平均和全局层通过
  九指标合同。
- `Rules-Embedding-Clustering` 的三段组合截断已由确定性测试覆盖；旧的 `selection_ratio=1` 本地产物不再符合当前合同，不能作为正式规则 baseline。
- `Haggis-CPP` 已在当前三个项目上完成每项目 20 个函数、6 轮采样的有界 smoke。
- `LLM-Direct-Budget` 已用两个合成 C++ 短函数完成低档模型的 1 次 map + 1 次 reduce smoke；没有发送仓库源码。
- IdioMine-CPP 的判断前候选阶段已复用26个冻结仓库的缓存 UniXcoder embedding
  完成全输入诊断：233,912 个输入候选中有8,413个 DCC-lite 候选，形成1,083个
  非噪声簇、3,617个簇内实例。仓库宏平均九指标为
  `IC_macro=0.0021`、`IC_micro=0.0076`、`IC=0.0048`、`ISP=0.0765`、
  `F1=0.0085`、`idiom_type_count=41.65`、`avg_cluster_size=3.0779`、
  `avg_cross_file_support=1.6257`、`AvgAST=182.46`；全局九指标也已通过合同。
  该运行使用当前默认 `eps=0.25`、`min_samples=2`；指标只是进入 ChatGPT
  判断前的诊断值，不是 `IdioMine-CPP` 最终指标。
- `IdioMine-CPP` 已通过 fake client 确定性测试，覆盖逐簇独立判断、
  精确同区域分组、成功合成直接接受、理由审计和统一九指标。对上述26仓候选
  产物按与代表代码对应的来源位置离线估算为1,083次判断、至多122次合成，即
  至多1,205次逻辑调用；若每次都触发一次 JSON 修复，则端点请求上界为2,410次。
- 少量真实付费测试只发送完全合成的 C++：第一批3个过短候选均被拒绝，因此未
  调用合成；第二批2个带重复证据的并发候选均通过，随后1次同区域合成成功并
  直接接受。两批共6次端点请求、近似3,064 token，无 JSON 修复或技术失败。
  第二批最终3项已通过九指标合同；单文件 smoke 的 IC/ISP/F1 为0，不代表正式
  质量。26仓真实付费运行尚未执行。

以上证明代码路径与九项指标兼容，不是正式方法优劣结论。被忽略的 smoke/评价产物及精确运行统计记录在[本地开发基线](local-baseline.md)。
