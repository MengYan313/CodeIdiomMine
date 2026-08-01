# 习语判定

阶段三对单仓库候选簇执行离线规则、受约束抽象、语义价值判断、类型归类和异味审查。

```bash
.venv/bin/python -m src.idiom_judgment.judge_clusters \
  --input outputs/cpp/cli11/clusters-merged.pkl \
  --source-root repos/cli11 --require-context \
  --checkpoint outputs/cpp/cli11/idiom-judgment.sqlite3 \
  --output outputs/cpp/cli11/idiom-judgment.pkl \
  --report outputs/cpp/cli11/idiom-judgment-report.json
```

`--require-context` 在源码路径或范围无效时拒绝当前簇。LLM 调用使用当前源码上下文、一次 JSON 修复和有限重试。`--resume` 仅跳过 checkpoint 中已有的位置。

输出 `idiom-judgment.pkl` 是阶段四和评价器接受的当前判定产物。
