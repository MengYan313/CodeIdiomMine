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

测试覆盖 C++ 节点集合、扫描与 AST 提取、嵌入辅助函数、DBSCAN schema、Agent 确定性门限、评价辅助函数、LLM 消息构建、JSON schema/单次修复和可读产物导出。默认测试不得下载模型或调用外部 LLM。

## 3. 导入和帮助入口

```bash
.venv/bin/python -c "import src.common, src.parser, src.mining, src.agents, src.evaluation, src.llm, src.utils"

.venv/bin/python -m src.parser.repo2data --help
.venv/bin/python -m src.mining.code_embedding --help
.venv/bin/python -m src.mining.clustering --help
.venv/bin/python -m src.agents.idiom_judgement --help
.venv/bin/python -m src.agents.idiom_synthesis --help
.venv/bin/python -m src.evaluation.idiom_metrics --help
.venv/bin/python -m src.utils.pkl2csv --help
```

部分模块会出现 `runpy` 的“模块已在 `sys.modules` 中”警告，这是包级 `__init__.py` 提前导入造成的已知现象；当前入口仍可正常完成。

parser、embedding 和 evaluation 的帮助输出不应出现 `--language`；`ASTParser()` 与 `FileScanner()` 也不接收语言参数。该检查用于防止无意恢复已经移除的多语言分发层。

## 4. 最小解析验证

优先构造只含少量真实源文件的临时输入，不要先解析完整 `repos/cpp`：

```bash
.venv/bin/python -m src.parser.repo2data \
  --input /path/to/minimal/repos \
  --output outputs/smoke/cpp/dataset.pkl
```

验证输出是包含 `project`、`cppFile`、`func_ast`、`func_src` 的 DataFrame，并确认项目、文件和函数数量符合输入。

## 5. 嵌入与聚类

UniXcoder 首次下载在当前依赖栈约占 738 MB。确认网络、磁盘和运行时间后再执行；已有缓存时优先离线复用。

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/smoke/cpp/dataset.pkl \
  --output outputs/smoke/cpp/embeddings.pkl \
  --model unixcoder --device cpu --min-project-size 1 --batch-size 8

.venv/bin/python -m src.mining.clustering \
  --input outputs/smoke/cpp/embeddings.pkl \
  --output outputs/smoke/cpp/clusters.pkl
```

先验证默认 DBSCAN。`--optimize` 会对每个处理项目进行 50 次贝叶斯优化调用，不属于低成本冒烟检查。

嵌入默认按 8 段批量推理，并按源码长度临时分组以减少 padding；结果会写回原始下标，仍保持每段 `(1, hidden_size)` CPU tensor、候选顺序和 pickle schema。内存受限时可减小 `--batch-size`，对照单段路径时可设为 `1`。

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

评价依赖固定 C++ 路径下的 dataset 和 Agent 结果。单项目或 fake-client 输入只能证明入口和 schema 可用，不能作为论文结果。

## 9. 日志、产物和证据

- 运行日志：`logs/<run-name>.log`（同一命令的模块共享，追加写入）。
- 中间产物：`outputs/`。
- 可读分析视图：`outputs/cpp/readables/`。
- Agent 与评价产物：`results/`。
- 已验证最小基线：`outputs/baselines/cpp/` 与 `results/baseline-stubs/cpp/`。

以上目录均被 Git 忽略。重要实验应另存命令、解释器和依赖版本、输入范围、输出路径、关键统计和完整错误。日志默认追加；长期实验仍应保存独立的命令与结果清单，避免不同运行混淆。

## 10. 测试目录约定

`tests/` 下的 `agents/`、`common/`、`evaluation/`、`llm/`、`mining/`、`parser/`、`utils/` 与 `src/` 一一对应。新增测试放入被测包的同名目录；临时测试产物使用 `tests/outputs/`、`tests/temp_outputs/` 或 `tests/.tmp/`，这些路径已由 `.gitignore` 排除。
