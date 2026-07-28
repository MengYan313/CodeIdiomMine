# 习语合成模块

本模块对应研究流程中的阶段4，只尝试把同一仓库、同一函数或区域内的两个及以上
相关习语合成为质量更高的习语。它不负责判断单个聚类簇是否为习语。阶段4产物是
`synthesis_delta`：只记录合成尝试及其成功增量，不复制单例、未选择或未成功
合成的阶段3习语；这些习语仍以阶段3 `accepted` 产物为准。

正式输入是 `idiom_judgment` 的已接受产物，其中可抽象习语已经抽象，LLM拒绝
抽象或没有规则提案的习语保持原代码。阶段2 `clusters.pkl` 到内部候选的适配和
更严格阈值仍保留离线合同测试，证明逻辑后备兼容，但正式 CLI 不接受阶段2输入，
实际实验也不执行阶段2直通合成。程序化传入 `input_kind="stage2"` 时只完成适配、
分组和合同检查，输出 `execution_status=contract_only_not_executed` 的空 artifact；
该路径不创建 Agent、不要求 API key，也不产生 LLM 调用。

协作顺序为：

1. 编排层只按完全相同的代表 `project + file + function/region extent` 分组，
   不根据跨区域共现或语义相似度扩大合成范围；随后自动读取并校验该上下文；
   上下文不可用时直接拒绝，
   不调用 LLM；
2. 规划 Agent 只选择具有数据、控制、生命周期或稳定顺序关系的至少两个习语；
3. 组装 Agent 使用选定习语和自动填充的代表区域上下文；
4. 质量复审 Agent 与阶段3共享的代码异味 Agent 并行复核；共享 Agent 沿用相同
   Request/Result，并通过 `related_examples` 同时接收代表区域上下文和来源习语；
5. 核心确定性门禁只检查已验证上下文、Tree-sitter 语法和新增调用白名单；质量分
   再评价合成增益，代码异味按独立风险门禁过滤，二者不混合计分，最后给出
   `accepted` 或 `rejected`。

规划、组装、质量和异味 Agent 都必须返回非空理由。质量复审 Agent 还重新判断
合成结果是否仍属于代码习语，并独立输出受控目录类型或 `仓库特有习语`；前者
进入目录化通用习语视图，后者进入仓库专属习语视图，二者共同构成全量联合视图。
它不能直接继承来源阶段3类型。即使来源均为通用类型，当前合成结果无法与目录
精确对应时也必须归为专属；反之只有当前代码本身证据充分时才能归入通用目录。
Schema v7 会携带来源阶段3的理由与分类，并在当前合成
记录顶层 `source_judgments` 中直接保存来源证据，同时保存新的
`decision_reason`、`idiom_classification` 和 `agent_reasons`。完整类型目录见
[C++习语类型目录与开放分类合同](../../docs/guides/idiom-taxonomy.md)。

每个 Agent 单次调用有120秒超时，最多执行2次逻辑尝试，每次尝试允许1次 JSON 修复。规划技术失败会
跳过当前组的组装与复审；组装失败、空输出、语法错误或不受支持调用会跳过质量与
异味复审；质量复审失败以0分拒绝，异味复审失败由独立门禁拒绝，两个并行分支
互不取消。未预料的组级编排异常只跳过当前组，不中断后续组。`agent_trace` 和
汇总中的 `technical_failure_count` 保存这些技术失败及回退证据。同区域候选超过
`--max-group-candidates` 时不截断、不调用 Agent，而是拒绝该次增量尝试并要求
显式提高上限。长时运行支持 `--checkpoint` 和配置一致性校验后的 `--resume`。

```bash
.venv/bin/python -m src.idiom_synthesis.synthesize_idioms \
  --input outputs/cpp/cli11/idiom-judgment.pkl \
  --input-kind judgment \
  --source-root repos/cli11 \
  --checkpoint results/cpp/cli11/idiom-synthesis.sqlite3 \
  --output results/cpp/cli11/idiom-synthesis.pkl \
  --report results/cpp/cli11/idiom-synthesis-report.json
```

该命令会把选定习语和自动读取的代表区域上下文发送到配置的 LLM 端点。正式运行前
必须确认输入公开性、端点、调用组数、成本和源码披露范围。产物 `run` 保存模型、
提示词哈希、决策政策、尚需 pilot 校准的状态、token 用量和 checkpoint 信息。
