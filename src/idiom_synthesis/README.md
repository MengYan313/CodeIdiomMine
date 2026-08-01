# 关联闭环融合模块

本模块对应研究流程中的阶段4“关联闭环融合”，工程包名仍为
`idiom_synthesis`。它从阶段3完整簇成员位置中发现同一仓库、同一函数或区域内
两个及以上习语的真实共现，再把具有明确关系的习语融合为质量更高的习语，不负责
重新判断单个聚类簇。阶段4产物是
`synthesis_delta`：只记录合成尝试及其成功增量，不复制单例、未选择或未成功
合成的阶段3习语；这些习语仍以阶段3 `accepted` 产物为准。

正式输入是 `idiom_judgment` 的已接受产物，其中可抽象习语已经抽象，LLM拒绝
抽象或没有规则提案的习语保持原代码。阶段2 `clusters.pkl` 到内部候选的适配和
更严格阈值仍保留离线合同测试，证明逻辑后备兼容，但正式 CLI 不接受阶段2输入，
实际实验也不执行阶段2直通合成。程序化传入 `input_kind="stage2"` 时只完成适配、
分组和合同检查，输出 `execution_status=contract_only_not_executed` 的空 artifact；
该路径不创建 Agent、不要求 API key，也不产生 LLM 调用。

协作顺序为：

1. 编排层遍历每个已接受习语的完整 `source_infos`，按成员
   `project + file + function/region extent` 建立区域倒排索引；同一簇在一个区域
   内只形成一个区域绑定候选，但可参与多个真实共现区域。候选自身字节范围只用于
   局部代码与源码顺序，不要求不同习语的代码区间相交；
2. 编排层自动读取并校验成员共现区域；上下文不可用时直接拒绝，不调用 LLM；
3. 规划 Agent 每区域只调用一次，同时审查全部候选，在显式上限内以 `plans`
   一次性返回所有具有数据、控制、生命周期、异常处理或稳定顺序关系且值得尝试
   的组合；
4. 编排层对每项 `selected_indices` 排序、去重和范围校验，以规范化候选集合生成
   稳定 `combination_key`，过滤重复或非法计划；
5. 每个合法计划独立调用组装 Agent，使用选定习语、当前区域实际成员代码和自动
   填充的共现区域上下文；
6. 每个成功组装的计划分别由质量复审 Agent 与阶段3共享的代码异味 Agent 并行
   复核；共享 Agent 沿用相同
   Request/Result，并通过 `related_examples` 同时接收共现区域上下文和来源习语；
7. 核心确定性门禁只检查已验证上下文、Tree-sitter 语法和新增调用白名单；质量分
   再评价合成增益，代码异味按独立风险门禁过滤，二者不混合计分，最后给出
   `accepted` 或 `rejected`。

### 组合搜索设计原则

规划 Agent 的职责是用语义关系缩小组合空间，避免对同一区域的 \(n\) 个候选执行
\(2^n-n-1\) 个数学子集的全量枚举；否则组装、质量复审和异味审查的调用量不可
接受。“返回所有可能组合”在本模块中专指：一次审查区域内全部候选，并在显式
`max_plans_per_region` 上限内返回所有具有明确数据、控制、生命周期、异常处理或
稳定顺序关系且值得尝试的组合，不包括缺乏关系的任意子集。

多计划实现采用一次批量规划，而不是让规划 Agent 每次返回一组并循环到模型自行
停止。规划 Agent 每区域一次返回 `plans`；不同计划可以共享候选，但完全相同的
候选集合不得重复。编排层负责索引范围校验、候选集合规范化、稳定键和确定性去重，
再对每个合法计划独立执行组装和复审。调用上限、去重和停止均由编排层控制，不能
依赖模型声称“没有更多组合”。一个计划失败只拒绝该计划，不取消同区域其他计划。

规划、组装、质量和异味 Agent 都必须返回非空理由。质量复审 Agent 还重新判断
合成结果是否仍属于代码习语，并独立输出受控目录类型或 `仓库特有习语`；前者
进入目录化通用习语视图，后者进入仓库专属习语视图，二者共同构成全量联合视图。
它不能直接继承来源阶段3类型。即使来源均为通用类型，当前合成结果无法与目录
精确对应时也必须归为专属；反之只有当前代码本身证据充分时才能归入通用目录。
Schema v9 携带来源阶段3的理由与分类，并在当前合成记录顶层
`source_judgments` 中直接保存来源证据；`matched_source_infos`、
`matched_occurrences`、`region_identity` 和 `source_order_candidate_ids`
记录本次合成实际使用的区域成员，完整 `source_infos` 继续保存簇级支持证据。
`region_planning` 保存本区域一次规划的总理由、上限、调用状态和非法/重复计划
校验摘要；每个执行记录保存单项 `synthesis_plan` 与 `combination_key`。产物同时保存
新的
`decision_reason`、`idiom_classification` 和 `agent_reasons`。完整类型目录见
[C++习语类型目录与开放分类合同](../../docs/guides/idiom-taxonomy.md)。

每个 Agent 单次调用有120秒超时，最多执行2次逻辑尝试，每次尝试允许1次 JSON 修复。规划技术失败会
跳过当前组的组装与复审；组装失败、空输出、语法错误或不受支持调用会跳过质量与
异味复审；质量复审失败以0分拒绝，异味复审失败由独立门禁拒绝，两个并行分支
互不取消。未预料的组级编排异常只跳过当前组，不中断后续组。`agent_trace` 和
汇总中的 `technical_failure_count` 保存这些技术失败及回退证据。同区域候选超过
`--max-group-candidates` 时不截断、不调用 Agent，而是拒绝该次增量尝试并要求
显式提高上限。规划响应不得超过 `--max-plans-per-region`；默认上限为8，超过时
不截断也不执行。长时运行支持 `--checkpoint` 和配置一致性校验后的 `--resume`。

```bash
.venv/bin/python -m src.idiom_synthesis.synthesize_idioms \
  --input outputs/cpp/cli11/idiom-judgment.pkl \
  --input-kind judgment \
  --source-root repos/cli11 \
  --max-plans-per-region 8 \
  --checkpoint results/cpp/cli11/idiom-synthesis.sqlite3 \
  --output results/cpp/cli11/idiom-synthesis.pkl \
  --report results/cpp/cli11/idiom-synthesis-report.json
```

该命令会把选定习语、当前区域实际成员和自动读取的共现区域上下文发送到配置的
LLM 端点。正式运行前必须确认输入公开性、端点、调用组数、成本和源码披露范围。
批量正式运行只消费
`docs/research/cpp-dataset-selection.json` 中“保留”和“条件保留”项目的阶段3
产物；三个“阶段2后排除”仓库不得通过历史判断产物重新进入主数据集。产物
`run` 保存模型、
提示词哈希、决策政策、尚需 pilot 校准的状态、token 用量和 checkpoint 信息。
