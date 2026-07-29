# 本地验证指南

仓库包含不依赖网络、模型下载或付费 API 的 `unittest` 套件。验证应按成本从低到高进行，并在运行模型下载、全量计算或付费 Agent 前明确输入范围和成本。

## 1. 环境与静态检查

从仓库根目录运行：

```bash
.venv/bin/python --version
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q src
```

已验证环境为 Python 3.12.10。不要使用 `/usr/bin/python3` 安装或运行项目依赖。

## 2. 自动化测试

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

测试覆盖 C++ Adapter、预处理续行遮蔽、扫描与 AST 提取、Parser token 预算与
超长函数降级、正式数据集领域/复杂度分类复算、embedding 合同、DBSCAN 自动调参、DBSCAN/HDBSCAN Schema、
多重可信门控、精简簇视图语义抽象决策、抽象拒绝后原样保留、二态评分裁决、
阶段2合同适配与阶段3正式合成输入、自动代表区域上下文、
通用习语/仓库特有习语开放分类、Agent 非空理由链、
共享异味分类/独立门禁/事后审计、合成确定性门限、评价辅助函数、LLM
消息构建、JSON Schema/单次修复、Agent 有界逻辑重试、并行失败隔离、下游跳过
和可读产物导出。
默认测试使用假 tokenizer，不得下载模型或调用外部 LLM。

数据集实验还应运行清单交叉校验。该命令只读取本地固定仓库和产物，不执行目标仓库代码：

```bash
.venv/bin/python -m scripts.analyze_cpp_dataset validate-manifest \
  --manifest docs/research/cpp-dataset-manifest.json
```

它验证 23 个正式项目和 3 个历史项目的固定 commit、四列 pickle Schema、
项目身份、仓库相对路径安全与唯一性，以及审计文件数/函数数和独立分析结果的
一致性；同时复算正式项目的主领域、相对分析复杂度和汇总分布，并确认已淘汰的
GSL 本地路径不存在。

## 3. 导入和帮助入口

```bash
.venv/bin/python -c "import src.common, src.parser, src.mining, src.idiom_judgment, src.idiom_synthesis, src.agents, src.evaluation, src.llm, src.utils"

.venv/bin/python -m src.parser.repo2data --help
.venv/bin/python -m src.parser.audit --help
.venv/bin/python -m src.parser.fragment_builder --help
.venv/bin/python -m src.parser.token_length_audit --help
.venv/bin/python -m src.mining.code_embedding --help
.venv/bin/python -m src.mining.clustering --help
.venv/bin/python -m src.mining.dbscan_tuning --help
.venv/bin/python -m src.mining.hdbscan_clustering --help
.venv/bin/python -m src.idiom_judgment.judge_clusters --help
.venv/bin/python -m src.idiom_judgment.smell_audit --help
.venv/bin/python -m src.idiom_synthesis.synthesize_idioms --help
.venv/bin/python -m src.evaluation.idiom_metrics --help
.venv/bin/python -m src.utils.pkl2csv --help
```

部分模块会出现 `runpy` 的“模块已在 `sys.modules` 中”警告，这是包级 `__init__.py` 提前导入造成的已知现象；当前入口仍可正常完成。

parser、embedding 和 evaluation 的帮助输出不应出现 `--language`；`ASTParser()` 与 `FileScanner()` 也不接收语言参数。该检查用于防止无意恢复已经移除的多语言分发层。

## 4. 最小解析验证

优先构造只含少量真实源文件的临时输入，不要先解析完整 `repos`：

```bash
.venv/bin/python -m src.parser.repo2data \
  --input /path/to/minimal/repos \
  --output outputs/smoke/cpp/dataset.pkl \
  --fragment-output outputs/smoke/cpp/fragments.pkl \
  --embedding-model unixcoder \
  --local-files-only
```

验证输出是包含 `project`、`cppFile`、`func_ast`、`func_src` 的 DataFrame，并确认项目、文件和函数数量符合输入。

同时检查同目录的 `dataset.audit.json`：

- `summary.scanned_file_count` 等于扫描器输入数；
- 无函数和解析失败文件仍出现在 `files`；
- 每个异常都有原始字节范围；
- `recovery.used` 为真时保留原始树和影子树两组统计；
- 函数根的 `code_snippet` 等于原始 `[start_byte, end_byte)`。

对同一输入运行两次后执行可重复审计：

```bash
.venv/bin/python -m src.parser.audit \
  --source-root /path/to/minimal/repos \
  --dataset outputs/smoke/cpp/dataset.pkl \
  --repeat-dataset outputs/smoke/cpp/dataset-repeat.pkl \
  --candidate-profile quality-v2 \
  --output outputs/smoke/cpp/parser-audit.json
```

要求 `performance.byte_identical_repeat=true`，AST 和候选
`exact_mapping_rate=1.0`。合成样本应覆盖模板、Concept、Lambda、复杂声明、
条件编译和未闭合函数；具体断言见 `tests/parser/test_cpp_parser.py`。

在真实 tokenizer 已缓存时，检查 Parser 长度产物：

```bash
.venv/bin/python -m src.parser.token_length_audit \
  --dataset outputs/smoke/cpp/dataset.pkl \
  --output outputs/smoke/cpp/token-length-audit.json \
  --model unixcoder --local-files-only
```

要求 `fragments.pkl` 的 `decision_stage=parser`，每条
`length_control.token_count <= max_input_tokens`，`fragment_src` 与
`fragment_info` 数量一致，所有 `fragment_rejections` 都具有文件身份、范围和
拒绝理由。相同输入重复构建的 pickle SHA-256 必须一致。

## 5. 嵌入与聚类

UniXcoder 首次下载在当前依赖栈约占 738 MB。确认网络、磁盘和运行时间后再执行；已有缓存时优先离线复用。

每次命令只处理一个仓库，并把该仓库的 `fragments.pkl`、`embeddings.pkl` 和
`clusters.pkl` 保存到同一独立目录。不得把不同仓库的片段或 embedding 合并后
聚类。以下 `outputs/smoke/cpp/` 只代表一个最小仓库：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/smoke/cpp/fragments.pkl \
  --output outputs/smoke/cpp/embeddings.pkl \
  --model unixcoder --device cpu --min-project-size 1 --batch-size 8 \
  --candidate-profile quality-v2

.venv/bin/python -m src.mining.dbscan_tuning \
  --input outputs/smoke/cpp/embeddings.pkl \
  --output outputs/smoke/cpp/clusters.pkl \
  --report outputs/smoke/cpp/dbscan-tuning.json

.venv/bin/python -m src.mining.cluster_merge \
  --clusters outputs/smoke/cpp/clusters.pkl \
  --embeddings outputs/smoke/cpp/embeddings.pkl \
  --output outputs/smoke/cpp/clusters-merged.pkl \
  --report outputs/smoke/cpp/cluster-merge-report.json

.venv/bin/python -m src.mining.hdbscan_clustering \
  --input outputs/smoke/cpp/embeddings.pkl \
  --output outputs/smoke/cpp/clusters-hdbscan.pkl \
  --min-cluster-size 2 --min-samples 1 \
  --cluster-selection-method leaf
```

先验证 DBSCAN 自动调参对未知项目名仍使用相同搜索空间、硬约束和三指标目标，
并检查权重和为 1、所选簇的七列 Schema 与 `dbscan-tuning.json`。正式算法在
聚类前固定为 DBSCAN，不按仓库名或聚类结果路由。HDBSCAN 对照默认对 L2 归一化向量执行
确定性 PCA-32，再在欧氏空间使用 `leaf` 选簇；代表代码仍按原始向量的余弦
中心选择。DBSCAN 历史 `--optimize` 会执行 50 次贝叶斯优化调用，不属于
低成本冒烟检查。不得根据最终 IC、ISP、F1 或人工标签反向修改聚类参数。

归并冒烟还应检查输入输出成员数一致、输出继续使用七列 Schema、来源 label 与
理由完整、代表代码属于合并后的真实成员，以及调用名、类型、运算符、字面量、
控制条件、返回值或非局部标识不同时保持分离。测试和正式运行都应写入新派生路径，
不得覆盖冻结 DBSCAN 产物。

嵌入默认按 8 段批量推理，并按源码长度临时分组以减少 padding；结果会写回原始下标，仍保持每段 `(1, hidden_size)` CPU tensor、候选顺序和 pickle schema。内存受限时可减小 `--batch-size`，对照单段路径时可设为 `1`。tokenizer 使用 `truncation=False`；超限、模型名不一致或预算不一致必须失败，不能在此阶段重新切分。

quality-v2 的区域、语句和 Def-Use 选择发生在 Parser 片段构建阶段；历史数据集
对照在 `src.parser.fragment_builder` 使用 `--candidate-profile legacy`。
embedding 的同名参数只校验产物 profile，不重新选择候选。运行完整嵌入前必须先
检查 Parser token 审计。筛选前 26 仓阶段2语料共有 233,912 个 model-ready
候选；聚类质量筛选后的 23 仓正式语料共有 200,047 个。`cpp-httplib`、`entt`
和 `simdjson` 的产物只用于筛选复核或边界案例，不得进入阶段3/4与正式主结果。
更早的三个仓库快照共 96,039 条，只用于旧基线复核，也不得与正式产物混用。

## 6. 可读产物导出

PKL 是阶段间的规范格式；不要用原样 CSV 替换嵌套 AST、tensor 或簇成员。使用统一导出器生成全量统计与限量 JSON 分析视图：

```bash
.venv/bin/python -m src.utils.export_artifacts \
  --input-dir outputs/cpp --output-dir outputs/cpp/readables \
  --limit 100 --cluster-top 100 --text-limit 2000 --vector-head 8
```

输出包括 `manifest.json`、阶段 `*.summary.json`、解析/嵌入前 100 条预览，以及每项目聚类 Top100。验证 JSON 可解析、记录数符合限制、聚类按 `cluster_size` 降序、汇总计数与 PKL 一致，并确认没有遗留 `*.tmp` 文件。只导出某一阶段可使用 `--stages dataset`、`--stages embeddings` 或 `--stages clusters`。

正式语义产物存在后可运行
`--input-dir outputs/cpp --result-dir results/cpp --stages judgment synthesis`。
它会分别递归扫描逐仓 `idiom-judgment.pkl` 与 `idiom-synthesis.pkl`，只把 `accepted`
记录投影为习语预览，同时保留各状态计数、AST 大小、合成轮数和前100条轨迹。
`judgment`、`synthesis` 仍可读取旧 `*_idiom.pkl` 与 `*_idiom_syn.pkl`。
这些导出都只读取本地文件，不会发起新的 LLM 请求。

## 7. 多重可信门控与关联闭环融合

无付费验证先运行：

```bash
.venv/bin/python -m unittest \
  tests.idiom_judgment.test_judgment \
  tests.idiom_judgment.test_smell_audit \
  tests.idiom_synthesis.test_synthesis \
  tests.agents.test_prompt_contracts -v
```

它检查 C++ 词法等价、仓库内保守簇归并与重算真实代表、确定性单簇规则、代表代码/
词法去重变体/四项统计进入语义 Prompt、完整成员只留在产物、只抽象规则筛出的高频
局部换名、LLM `keep` 后保持原代码、判断/合成二态评分、阶段2合同适配与阶段3
正式输入、同区域分组、自动上下文与零调用失败、共享异味分类、独立过滤门禁、
分层事后审计与逐类别指标、跨区域禁止分组、合成增量产物、新增调用拒绝、
候选上限零调用拒绝、SQLite checkpoint 配置一致性续跑、
阶段2非执行分支的严格阈值、`contract_only_not_executed` 空 artifact 和零
LLM调用、受控目录与仓库特有分类的确定性标准化、阶段3 Schema v8 理由传播，
以及所有 Agent 的中文提示词和完整 Schema。故障注入用例还验证：

- 请求异常时最多重试1次，成功恢复后 `logical_attempts=2`；
- 每次逻辑尝试只修复 JSON 1次，两次逻辑尝试耗尽时单 Agent 最多4次端点请求；
- 阶段3一个并行 Agent 失败不会取消另一个分支，当前簇安全拒绝；
- 阶段4规划失败后不调用组装和两个复审 Agent，当前组跳过而非中断整批；
- 阶段3严格上下文门禁失败时两个 Agent 均不运行；成功时经哈希验证的代表函数/
  区域只写入本地审计证据，不进入两个 Agent 的提示词；
- 阶段4同区域候选超过上限时保留整组证据而不静默截断，四个 Agent 均不运行；
- `is_idiom=false`、未知目录编号、矛盾分类、非有限置信度或空判断理由都不能
  进入已接受产物；
- artifact 的 `agent_trace` 与 `technical_failure_count` 能复现技术失败。

还可对真实聚类
执行不调用 LLM 的预检：

```bash
.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/cpp/cli11/clusters-merged.pkl \
  --output outputs/cpp/cli11/idiom-judgment-rule-only.pkl \
  --report outputs/cpp/cli11/idiom-judgment-rule-only.json \
  --rule-only --limit 20
```

该产物状态为 `pending_llm`，不能作为已接受习语。真实入口需要 `.env` 中的端点、
密钥和模型分档；不传 `--model` 时只使用 `OPENAI_MODEL_LOW`：

```bash
.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/cpp/cli11/clusters-merged.pkl \
  --source-root repos/cli11 --require-context \
  --checkpoint outputs/cpp/cli11/idiom-judgment.sqlite3 \
  --output outputs/cpp/cli11/idiom-judgment.pkl \
  --report outputs/cpp/cli11/idiom-judgment-report.json --limit 1

.venv/bin/python -m src.idiom_synthesis.synthesize_idioms \
  --input outputs/cpp/cli11/idiom-judgment.pkl \
  --input-kind judgment --source-root repos/cli11 \
  --checkpoint results/cpp/cli11/idiom-synthesis.sqlite3 \
  --output results/cpp/cli11/idiom-synthesis.pkl \
  --report results/cpp/cli11/idiom-synthesis-report.json --max-groups 1
```

单个规则合格簇通常包含语义/复用价值与共享异味审查两次并行逻辑调用；每个合成
组最多包含规划、组装、质量复审和共享异味审查四次逻辑调用。上下文在调用前由
编排层自动读取和校验，失败时零调用拒绝。每个 Agent 单次请求最多等待120秒，
每次逻辑尝试在 JSON
首次失败时可能增加1次修复请求；修复耗尽或请求异常后最多再执行1次逻辑尝试，
故单 Agent 最多4次端点请求。阶段3理论端点上限为每簇8次，阶段4为每组16次；
规划或组装失败时会跳过下游，实际失败路径上限随之降低。执行前必须按端点请求
上限确认模型、簇/组范围、费用和源码披露风险。真实 smoke 应使用合成短代码和
独立的 `results/llm-smoke/`，并至少覆盖一个目录通用习语、一个仓库特有习语、
一个非习语和一个阶段4组合；不得把 smoke 结果当作研究实验结果或据此冻结类型
目录与评分阈值。

长时运行应显式传入 `--checkpoint`。首次运行若 checkpoint 已存在会拒绝覆盖；
中断后使用相同命令增加 `--resume`，只有输入 SHA-256、模型、上下文根和关键
参数完全一致时才会跳过已完成记录。artifact 的 `run` 还必须检查提示词哈希、
token 用量和 `calibration_status`；在人工 pilot 完成前，状态应保持
`synthetic_smoke_only_pilot_required`。

异味审计样本准备和人工标签评价命令统一维护在
[`src/idiom_judgment/README.md`](../../src/idiom_judgment/README.md)。审计只读
已有阶段3/4产物，不会发起 LLM 调用。

## 8. 评价入口

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp --dataset outputs/cpp/dataset.pkl \
  --stage synthesis --output results/cpp/eval.json
```

正式默认模式是仓库内参考/测量文件分区。待每个仓库使用全部合格源码完成
Parser、embedding、逐仓聚类、多重可信门控和关联闭环融合后，评价器按稳定哈希划分来源文件，
只用参考分区中的已发现实例构造匹配变体，在测量分区计算 IC 与 ISP。该分区不
重新运行任何发现阶段。当前未参数化的候选通过保留关键字/运算符、抽象标识符和
字面量的结构化词法签名匹配，并要求候选 AST 节点类型一致。v2 的
`semantic_slice` 按显式字节范围映射回其中完整包含的 DFS AST 节点；历史数据
仍走旧候选路径。`IC_macro` 是函数覆盖率宏平均，`IC_micro` 是节点覆盖率微平均，
最终 `IC=(IC_macro+IC_micro)/2`；F1 使用最终 IC。习语库结构另按仓库报告习语
种类数、平均聚类簇大小、平均跨文件支持数和 AvgAST。

兼容字段 `training_*`、`test_*` 在该模式中只表示参考/测量分区。显式模式
`leave_one_project_out` 只用于复核历史产物，不属于正式研究流程。
`--stage judgment` 可直接评价阶段3接受习语，`--stage synthesis` 评价阶段4
合成结果；新 artifact 从 `accepted` 分区读取。同名阶段也会自动识别历史
`*_idiom.pkl` 与 `*_idiom_syn.pkl` 列表产物。

最终指标的分类理由、完整公式、全部成员计入规则、仓库宏平均与全局汇总方式、空分母处理及结论边界统一见[评价指标规范](evaluation-metrics.md)。本节只说明如何运行评价，不定义第二套口径。

没有真实 Agent 结果时，可把现有聚类 Top100 明确构造成模拟习语，验证指标分子、分母、extent 并集和多项目汇总：

```bash
.venv/bin/python -m src.evaluation.mock_idioms \
  --clusters outputs/cpp/clusters.pkl \
  --selection-manifest outputs/cpp/readables/clusters.top100.json \
  --output-dir results/evaluation-mock/cpp

.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/evaluation-mock/cpp \
  --dataset outputs/cpp/dataset.pkl \
  --output results/evaluation-mock/cpp/eval-mock-evidence.json \
  --mode mock_cluster_file_split --test-fraction 0.2
```

`clusters.top100.json` 在这里仅作为已存在的冻结语料清单：构造器只读取
`project/label` 集合，不读取或输出 `rank`，评价器也不计算任何排序或 Top-K
指标。`mock_cluster_file_split` 把每个冻结簇在参考/测量文件中的**全部成员**
当作已知匹配证据，专用于检查指标分子分母、extent 并集和多项目汇总；输出带
`is_mock_evaluation` 和 `mock_warning`。该结果不能作为模型质量或论文结果，
原因是冻结簇未经真实判断、合成或人工质量核验，并被直接当作 evidence oracle；
聚类使用完整仓库本身符合正式发现目标，不是泄漏。

## 9. Baseline 与主方法的统一验证

确定性离线集成测试会实际运行 Haggis-CPP、LLM-Direct-Budget（fake client）、
规则+嵌入聚类、IdioMine-CPP（fake client），以及 CIMAS-CPP 的兼容判断产物，并要求五种
产物都通过同一个九指标合同：

```bash
.venv/bin/python -m unittest tests.evaluation.test_baselines -v
```

每条 baseline 生成正式产物后都要运行统一验证器；CIMAS-CPP 额外使用 `--allow-main-method`，因为主方法不写 `baseline_provenance`：

```bash
.venv/bin/python -m src.evaluation.baseline_validation \
  --method <method> --idiom-dir <result-dir> \
  --dataset outputs/cpp/dataset.pkl
```

验证器拒绝 `mock_provenance`、空来源证据、`cnt` 不一致和缺失 baseline
provenance；它还拒绝 Haggis/LLM/IdioMine-CPP 的最终种类数量上限、
IdioMine-CPP 缺失 DCC-lite/DBSCAN/迁移声明、独立判断、精确同区域分组、
直接合成或预算完整性
证据的 manifest，以及没有执行三段
组合截断的旧规则配置。评价器直接接受各方法不同数量的完整产物，不要求公共
Top100 或相同习语种类数，并确认逐项目、仓库宏平均、全局三层都包含九项有限
数值。各方法的定义、参数和完整命令见[Baseline 复现](baselines.md)。

Haggis smoke 使用 `--max-functions-per-project`、较少 `--iterations` 和独立输出
目录，参数必须标成 smoke；正式 Haggis 不限制最终习语种类数。LLM smoke 只使用
合成代码，预先说明基础模型、最大逻辑调用数、JSON 修复上限、token 预算、可能
费用和披露范围；正式 LLM-Direct 不限制最终习语种类数。IdioMine-CPP 可以
复用缓存 embedding，不下载模型；embedding 模型、DCC-lite 候选版本和 DBSCAN
参数必须写入最终 manifest。真实运行前还要使用 `--estimate-only` 审批模型、判断/合成
调用上界、token 预算、费用和源码披露范围。CIMAS 的
`--limit` 只允许用于独立 smoke，正式结果必须省略。只有规则 baseline 使用
“最小簇大小→比例→数量上限”的产物截断；`results/evaluation-mock/` 的历史
Top100 模拟不能伪装成任何正式方法产物。

## 10. 日志、产物和证据

- 运行日志：`logs/<run-name>.log`（同一命令的模块共享，追加写入）。
- 中间产物：`outputs/`。
- 可读分析视图：`outputs/cpp/readables/`。
- Agent 与评价产物：`results/`。
- 已验证最小基线：`outputs/baselines/cpp/` 与 `results/baseline-stubs/cpp/`。

以上目录均被 Git 忽略。重要实验应另存命令、解释器和依赖版本、输入范围、输出路径、关键统计和完整错误。日志默认追加；长期实验仍应保存独立的命令与结果清单，避免不同运行混淆。

## 11. 测试目录约定

`tests/` 下的 `agents/`、`common/`、`evaluation/`、`idiom_synthesis/`、
`idiom_judgment/`、`llm/`、`mining/`、`parser/`、`utils/` 与 `src/` 一一
对应。新增测试放入被测包的同名目录；临时测试产物使用 `tests/outputs/`、
`tests/temp_outputs/` 或 `tests/.tmp/`，这些路径已由 `.gitignore` 排除。
