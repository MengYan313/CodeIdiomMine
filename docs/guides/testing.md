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
超长函数降级、embedding 合同、DBSCAN 自动调参、DBSCAN/HDBSCAN Schema、Agent
确定性门限、评价辅助函数、LLM 消息构建、JSON Schema/单次修复和可读产物导出。
默认测试使用假 tokenizer，不得下载模型或调用外部 LLM。

数据集实验还应运行清单交叉校验。该命令只读取本地固定仓库和产物，不执行目标仓库代码：

```bash
.venv/bin/python -m scripts.analyze_cpp_dataset validate-manifest \
  --manifest docs/research/cpp-dataset-manifest.json
```

它验证正式项目数量、固定 commit、四列 pickle Schema、项目身份、仓库相对路径安全与唯一性，以及审计文件数/函数数和独立分析结果的一致性。

## 3. 导入和帮助入口

```bash
.venv/bin/python -c "import src.common, src.parser, src.mining, src.agents, src.evaluation, src.llm, src.utils"

.venv/bin/python -m src.parser.repo2data --help
.venv/bin/python -m src.parser.audit --help
.venv/bin/python -m src.parser.fragment_builder --help
.venv/bin/python -m src.parser.token_length_audit --help
.venv/bin/python -m src.mining.code_embedding --help
.venv/bin/python -m src.mining.clustering --help
.venv/bin/python -m src.mining.dbscan_tuning --help
.venv/bin/python -m src.mining.hdbscan_clustering --help
.venv/bin/python -m src.agents.idiom_judgement --help
.venv/bin/python -m src.agents.idiom_synthesis --help
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

嵌入默认按 8 段批量推理，并按源码长度临时分组以减少 padding；结果会写回原始下标，仍保持每段 `(1, hidden_size)` CPU tensor、候选顺序和 pickle schema。内存受限时可减小 `--batch-size`，对照单段路径时可设为 `1`。tokenizer 使用 `truncation=False`；超限、模型名不一致或预算不一致必须失败，不能在此阶段重新切分。

quality-v2 的区域、语句和 Def-Use 选择发生在 Parser 片段构建阶段；历史数据集
对照在 `src.parser.fragment_builder` 使用 `--candidate-profile legacy`。
embedding 的同名参数只校验产物 profile，不重新选择候选。运行完整嵌入前必须先
检查 Parser token 审计。当前冻结的 26 仓正式语料共有 233,912 个 model-ready
候选；历史三个仓库快照的 96,039 条只用于旧基线复核，不得与正式产物混用。

## 6. 可读产物导出

PKL 是阶段间的规范格式；不要用原样 CSV 替换嵌套 AST、tensor 或簇成员。使用统一导出器生成全量统计与限量 JSON 分析视图：

```bash
.venv/bin/python -m src.utils.export_artifacts \
  --input-dir outputs/cpp --output-dir outputs/cpp/readables \
  --limit 100 --cluster-top 100 --text-limit 2000 --vector-head 8
```

输出包括 `manifest.json`、阶段 `*.summary.json`、解析/嵌入前 100 条预览，以及每项目聚类 Top100。验证 JSON 可解析、记录数符合限制、聚类按 `cluster_size` 降序、汇总计数与 PKL 一致，并确认没有遗留 `*.tmp` 文件。只导出某一阶段可使用 `--stages dataset`、`--stages embeddings` 或 `--stages clusters`。

Agent 结果存在后可运行 `--result-dir results/cpp --stages judgment synthesis`。它会扫描 `*_idiom.pkl` 与 `*_idiom_syn.pkl`，生成全量计数、AST 大小、合并轮数和前 100 条代码/trace 预览；这一导出是本地读取，不会发起新的 LLM 请求。

## 7. Agent 判断与合成

无付费验证可以注入确定性 fake model client，检查：

- `RoutedAgent` 注册与消息路由；
- 语义/语法并行与最终门限；
- 判断和合成 pickle schema；
- 合并失败后的回退行为。

真实入口需要 `.env` 中的端点、密钥和模型分档；不传 `--model` 时只使用 `OPENAI_MODEL_LOW`：

```bash
.venv/bin/python -m src.agents.idiom_judgement \
  --input outputs/cpp/clusters.pkl --output-dir results/cpp --limit 1

.venv/bin/python -m src.agents.idiom_synthesis \
  --input-dir results/cpp --output-dir results/cpp
```

单个判断候选通常包含语义、语法和综合三次模型调用；一次成功合成还会增加规划、组装及合并后再判断五次调用。执行前必须确认模型、端点、调用范围、费用和源码披露风险。真实 smoke 应使用合成短代码和独立的 `results/llm-smoke/`，不得把 smoke 结果当作研究实验结果。

## 8. 评价入口

```bash
.venv/bin/python -m src.evaluation.idiom_metrics
```

正式默认模式是仓库内参考/测量文件分区。当前仓库已经使用全部合格源码完成
Parser、embedding、逐仓聚类、判断和合成；评价器随后按稳定哈希划分来源文件，
只用参考分区中的已发现实例构造匹配变体，在测量分区计算 IC 与 ISP。该分区不
重新运行任何发现阶段。当前未参数化的候选通过保留关键字/运算符、抽象标识符和
字面量的结构化词法签名匹配，并要求候选 AST 节点类型一致。v2 的
`semantic_slice` 按显式字节范围映射回其中完整包含的 DFS AST 节点；历史数据
仍走旧候选路径。`IC_macro` 是函数覆盖率宏平均，`IC_micro` 是节点覆盖率微平均，
最终 `IC=(IC_macro+IC_micro)/2`；F1 使用最终 IC。习语库结构另按仓库报告习语
种类数、平均聚类簇大小、平均跨文件支持数和 AvgAST。

兼容字段 `training_*`、`test_*` 在该模式中只表示参考/测量分区。显式模式
`leave_one_project_out` 只用于复核历史产物，不属于正式研究流程。

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

确定性离线集成测试会实际运行 Haggis-CPP、LLM-Direct-Budget（fake client）、规则+嵌入聚类，以及 CIMAS-CPP 的三 Agent 判断路径（fake client），并要求四种产物都通过同一个九指标合同：

```bash
.venv/bin/python -m unittest tests.evaluation.test_baselines -v
```

每条 baseline 生成正式产物后都要运行统一验证器；CIMAS-CPP 额外使用 `--allow-main-method`，因为主方法不写 `baseline_provenance`：

```bash
.venv/bin/python -m src.evaluation.baseline_validation \
  --method <method> --idiom-dir <result-dir> \
  --dataset outputs/cpp/dataset.pkl
```

验证器拒绝 `mock_provenance`、空来源证据、`cnt` 不一致和缺失 baseline provenance；它还拒绝 Haggis/LLM 的最终种类数量上限，以及没有执行三段组合截断的旧规则配置。评价器直接接受各方法不同数量的完整产物，不要求公共 Top100 或相同习语种类数，并确认逐项目、仓库宏平均、全局三层都包含九项有限数值。各方法的定义、参数和完整命令见[Baseline 复现](baselines.md)。

Haggis smoke 使用 `--max-functions-per-project`、较少 `--iterations` 和独立输出目录，参数必须标成 smoke；正式 Haggis 不限制最终习语种类数。LLM smoke 只使用合成代码，预先说明基础模型、最大逻辑调用数、JSON 修复上限、token 预算、可能费用和披露范围；正式 LLM-Direct 不限制最终习语种类数。CIMAS 的 `--limit` 只允许用于独立 smoke，正式结果必须省略。只有规则 baseline 使用“最小簇大小→比例→数量上限”的产物截断；`results/evaluation-mock/` 的历史 Top100 模拟不能伪装成任何正式方法产物。

## 10. 日志、产物和证据

- 运行日志：`logs/<run-name>.log`（同一命令的模块共享，追加写入）。
- 中间产物：`outputs/`。
- 可读分析视图：`outputs/cpp/readables/`。
- Agent 与评价产物：`results/`。
- 已验证最小基线：`outputs/baselines/cpp/` 与 `results/baseline-stubs/cpp/`。

以上目录均被 Git 忽略。重要实验应另存命令、解释器和依赖版本、输入范围、输出路径、关键统计和完整错误。日志默认追加；长期实验仍应保存独立的命令与结果清单，避免不同运行混淆。

## 11. 测试目录约定

`tests/` 下的 `agents/`、`common/`、`evaluation/`、`llm/`、`mining/`、`parser/`、`utils/` 与 `src/` 一一对应。新增测试放入被测包的同名目录；临时测试产物使用 `tests/outputs/`、`tests/temp_outputs/` 或 `tests/.tmp/`，这些路径已由 `.gitignore` 排除。
