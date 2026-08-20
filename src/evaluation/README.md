# 评价、baseline 与质量消融

正式评价使用 Haggis 固定留出协议。所有方法只从 `dataset.pkl` 的 train 文件发现
习语，主 `IC` 在固定 test 上逐文件计算 AST 节点并集覆盖率后取宏平均，主 `ISP`
是训练习语至少在 test 复现一次的比例，`F1` 是二者的调和平均。`IC_micro` 仅是
测试节点微平均诊断值，`IC_raw` 与主 `IC` 相等。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/main/cli11 \
  --dataset outputs/library/cli11/stage0/dataset.pkl \
  --clusters outputs/library/cli11/stage2/clusters.pkl \
  --output results/main/cli11/evaluation.json \
  --mode haggis_holdout --folds 5
```

原 Stage 2 机会域覆盖、跨函数支持、完整函数 AST 覆盖和轮转五折指标继续保留为
诊断字段；五折只在 train 文件内运行。详细公式和字段映射见
[`docs/guides/evaluation-metrics.md`](../../docs/guides/evaluation-metrics.md)。

`haggis_cpp.py`、`llm_direct_baseline.py` 和 `idiomine_cpp.py` 提供对照方法。所有
方法输出当前习语 artifact，再由同一指标入口评价。`stage2_frequency_ablation.py`
直接保留 Stage 2 高频簇，用于与 Stage 4 最终习语做盲化人工质量比较，不作为
独立 baseline 参加自动质量排名。
