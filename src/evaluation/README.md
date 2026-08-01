# 评价与 baseline

评价器使用仓库内文件分区测量当前习语产物，避免用同一文件既形成参考又参与测量。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp/cli11 \
  --dataset outputs/cpp/cli11/dataset.pkl \
  --output results/cpp/cli11/eval.json \
  --mode within_project_file_split --test-fraction 0.2
```

`haggis_cpp.py`、`llm_direct_baseline.py` 和 `idiomine_cpp.py` 提供对照方法。所有方法输出当前习语 artifact，再由同一指标入口评价。
