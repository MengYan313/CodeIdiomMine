# 习语合成

阶段四读取当前 `idiom-judgment.pkl`，按同一源码区域中的已接受习语共现关系生成组合计划，再执行组装、复核、分类和异味审查。

```bash
.venv/bin/python -m src.idiom_synthesis.synthesize_idioms \
  --input outputs/cpp/cli11/idiom-judgment.pkl \
  --source-root repos/cli11 \
  --max-plans-per-region 8 \
  --checkpoint outputs/cpp/cli11/idiom-synthesis.sqlite3 \
  --output results/cpp/cli11/idiom-synthesis.pkl \
  --report results/cpp/cli11/idiom-synthesis-report.json
```

每个区域只规划一次，每个合法计划独立审查。`--resume` 只按已经完成的区域续跑，不维护输入或模型摘要。
