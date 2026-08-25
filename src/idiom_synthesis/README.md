# 习语合成

阶段四读取当前 `idiom-judgment.pkl`，按同一源码区域中的已接受习语共现关系生成组合计划，再执行组装、复核、分类和异味审查。

```bash
.venv/bin/python -m src.idiom_synthesis.synthesize_idioms \
  --input outputs/library/cli11/stage3/idiom-judgment.pkl \
  --source-root repos/library/cli11 \
  --max-plans-per-region 8 \
  --checkpoint outputs/library/cli11/stage4/checkpoint.sqlite3 \
  --output outputs/library/cli11/stage4/idiom-synthesis.pkl \
  --report outputs/library/cli11/stage4/report.json
```

完成后将最终库复制到 `results/library/cli11/main/idiom-synthesis.pkl`，供正式评价和汇总使用。

相同候选集合跨区域只保留一个稳定代表，候选组合在全局只执行一次。合成代码必须能在已核验上下文中定位、不同于每个单独来源、包含多个来源的新增组合语义，并通过语法、调用边界、质量与异味门禁；复核或异味审查出现阻断问题即拒绝。输出 `accepted` 是阶段三基础习语与去重后新增合成的最终库，`synthesized` 仅包含新增合成；来源候选只保存在证据字段中，不计作合成实例。`--resume` 只按已经完成的区域续跑，不维护输入或模型摘要。
