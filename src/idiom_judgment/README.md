# 习语判定

阶段三对单仓库候选簇执行离线规则、受约束抽象、语义价值判断、类型归类和异味审查。

```bash
.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/library/cli11/stage2/clusters.pkl \
  --source-root repos/cli11 --require-context \
  --checkpoint outputs/library/cli11/stage3/checkpoint.sqlite3 \
  --output outputs/library/cli11/stage3/idiom-judgment.pkl \
  --report outputs/library/cli11/stage3/report.json
```

`--require-context` 在源码路径或范围无效时拒绝当前簇。已核验源码上下文同时进入语义与异味审查，但只用于核验代表代码，不替代码段补充缺失操作。调用目标、成员、字段、类型和关键运算符保持不变；仅高频结构角色中的局部变量、参数与低语义字面量可形成提案，并须由语义 Agent 显式批准后写成 `<VAR_n>`、`<LIT_n>`，相同逻辑值复用同一占位符。

阶段三只把合同无效、确定性平凡、`is_idiom=false`、业务总分低于60、技术失败或达到异味门禁的候选拒绝。语义分和复用分不再各设重复硬下限，动作数量、代码长度、是否跨文件和是否属于通用目录也不单独否决；单个完整语句和仓库专属模式可以凭稳定意图与重复证据入库。LLM 调用保留一次 JSON 修复和有限重试。`--resume` 仅跳过 checkpoint 中已有的位置。

输出 `idiom-judgment.pkl` 是阶段四和评价器接受的当前判定产物。

若只调整确定性裁决，可复用已有 Agent 响应执行零调用重放：

```bash
.venv/bin/python -m src.idiom_judgment.replay_judgment \
  --input outputs/library/cli11/stage3/idiom-judgment.pkl \
  --output outputs/library/cli11/stage3/idiom-judgment-replayed.pkl \
  --report outputs/library/cli11/stage3/replay-report.json
```

重放只更新当前规则分区、总分、异味门禁和理由，不重新生成 `is_idiom`、语义分、
复用分、模板或源码证据；产物明确记录 `llm_call_count=0`。
