# 多重可信门控模块

本模块对应研究流程中的阶段3“多重可信门控”，工程包名仍为
`idiom_judgment`。它只处理单个仓库内的单个聚类簇，先执行确定性
合同和低价值规则过滤，再由抽象规则筛出仅涉及高频、结构对齐、低语义元素的
候选位置。编排层可按 `center_point_info` 自动读取并校验代表函数/区域上下文；
语义/抽象 Agent 随后接收代表代码、按 C++ 词法 token 去重后的其他真实变体、
原始成员数/变体数/文件数/源码位置数、规则初判和全部提案，
显式决定 `abstract` 或 `keep`；之后与代码异味审查共同为确定性裁决提供证据，
最后输出
`accepted` 或 `rejected`。规则、语义和复用价值形成业务总分；异味不进入总分，
而是按固定分类、严重度、置信度和证据形成独立风险门禁。任何业务硬门禁失败、
异味风险达到阈值、审查响应失败或业务总分不足都会自动拒绝。

语义/抽象 Agent 同时返回明确的 `is_idiom`、非空判断理由和
`idiom_classification`。通过有效性判断的候选若能与受控 C++ 目录精确对应，
记录为目录化通用习语；无法可靠对应时记录 `仓库特有习语`，在知识层归为仓库
专属习语，不得强行套用相近标签。专属集合也包括可能通用但尚未进入当前目录的
不常见习语。不是习语或技术失败时类型为 `not_applicable`。异味 Agent 也必须
输出非空审查理由。Schema v8 把最终 `decision_reason`、结构化类型和各 Agent
的 `agent_reasons` 一并保存；目录化通用结果可在仓库独立挖掘完成后按稳定类型
编号聚合，专属结果保持项目作用域，二者并集构成全量联合视图。具体目录和三态
合同见
[C++习语类型目录与开放分类合同](../../docs/guides/idiom-taxonomy.md)。

抽象提案默认至少需要3个对齐实例、3个不同取值和60%的簇内支持。调用名、类型、
控制条件、返回值、哨兵值和格式字符串不会仅因实例不同而自动抽象。Agent 只能
批准规则给出的提案，确定性代码负责应用交集。有效响应中的 `keep` 或无规则提案
都保留代表代码不变，不会单独导致候选被拒绝；通过质量和异味门禁后，抽象模板与
未抽象原代码都会作为阶段3的 `accepted` 产物进入阶段4。若整份语义/抽象响应
解析失败，则原代码仍作为审计证据保留，但因语义与复用分安全降为0而拒绝。产物
同时保存精简后的 `semantic_review_input`、完整 `member_codes`/`source_infos`、
`cluster_statistics`、`context_evidence`、抽象决策、批准集合和
`abstraction_applied`。代表上下文只在本地执行路径、范围和哈希门禁，不进入
阶段3 LLM 请求。正式实验应同时传入 `--source-root` 与
`--require-context`；路径、范围或 `source_sha256` 校验失败时当前簇零 LLM 调用
并拒绝。兼容运行可以不启用严格门禁，但产物会明确记录上下文缺失原因。

每个 Agent 调用有120秒超时，最多执行2次逻辑尝试；每次尝试中的非法 JSON 会先按同一 Schema
修复1次，修复仍失败或请求异常才进入下一次逻辑尝试。两次均失败时，语义/抽象
分支保持原代码但以业务0分拒绝，异味分支由独立门禁拒绝；两个并行分支互不取消。
记录中的 `agent_trace` 保存逻辑尝试数、失败类型和 `reject_cluster` 回退动作。
未预料的单簇编排异常会记录为拒绝并跳过当前簇，命令继续处理后续簇。长时运行
可以用 `--checkpoint <path>` 逐簇写入 SQLite；中断后以相同输入、模型和上下文
配置加 `--resume` 续跑，元数据不一致时拒绝复用，避免重复付费调用。

离线预检：

```bash
.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/cpp/cli11/clusters-merged.pkl \
  --output outputs/cpp/cli11/idiom-judgment.pkl \
  --report outputs/cpp/cli11/idiom-judgment-report.json \
  --rule-only
```

完整判断会把候选源码发送到配置的 LLM 端点。运行前必须确认仓库公开性、端点、
调用规模和成本，并移除 `--rule-only`。正式示例：

```bash
.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/cpp/cli11/clusters-merged.pkl \
  --source-root repos/cli11 --require-context \
  --checkpoint outputs/cpp/cli11/idiom-judgment.sqlite3 \
  --output outputs/cpp/cli11/idiom-judgment.pkl \
  --report outputs/cpp/cli11/idiom-judgment-report.json
```

批量正式运行的项目范围以
`docs/research/cpp-dataset-selection.json` 中“保留”和“条件保留”为准。
`cpp-httplib`、`entt` 和 `simdjson` 即使仍有历史 `clusters.pkl`，也不得进入
正式 LLM 判断。

产物 `run` 同时保存模型档位、提示词版本与 SHA-256、决策政策、校准状态、token
用量及 checkpoint 信息；不保存密钥或端点。

阶段3/4产物生成后，可离线准备分层异味审计样本：

```bash
.venv/bin/python -m src.idiom_judgment.smell_audit prepare \
  --artifact outputs/cpp/cli11/idiom-judgment.pkl \
  --artifact results/cpp/cli11/idiom-synthesis.pkl \
  --output results/cpp/cli11/smell-audit-samples.json \
  --limit 200
```

标注者只查看输出中的 `review_items` 和固定分类表，避免看到 `samples` 内的预测
分数、过滤结论和最终状态；填写 `label_template` 后保存为顶层含 `labels` 数组的
JSON，再计算总体、分阶段和逐类别准确性：

```bash
.venv/bin/python -m src.idiom_judgment.smell_audit evaluate \
  --samples results/cpp/cli11/smell-audit-samples.json \
  --labels results/cpp/cli11/smell-audit-labels.json \
  --output results/cpp/cli11/smell-audit-report.json
```

完整分类、风险公式和标注合同见
[代码异味审查与事后审计](../../docs/guides/code-smell-review.md)。文献编号和
完整著录由同级 thesis 仓库统一维护，审计产物只保存稳定编号、名称和官方 URL。
