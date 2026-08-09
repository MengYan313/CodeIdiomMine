# 评价与 baseline

评价器按稳定路径把仓库文件轮转为五折。`IC_raw` 是最终接受实例在候选域 AST 中的原始覆盖足迹，主 `IC=sqrt(IC_raw)` 用无参数单调变换展开低覆盖差异，主 `ISP` 衡量至少由两个 `(仓库相对文件路径, 函数根 extent)` 支持的习语比例；每个文件只在一折贡献一次覆盖。函数域粒度允许同一文件内不同函数分别提供复用证据，但五折仍按文件隔离。`IC_raw`、`F1_raw`、只由其余折归纳模板的 `IC_generalization`、`ISP_generalization` 与完整函数 AST 的 `IC_all` 同时输出，供尺度、泛化和分母敏感性审计。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp/cli11 \
  --dataset outputs/cpp/cli11/dataset.pkl \
  --output results/cpp/cli11/eval.json \
  --mode within_project_kfold --folds 5
```

每折模板只读取参考文件，确定性抽象局部变量、参数和字面量；调用目标、限定名、成员、类型、控制关键字和关键运算符保持一致。结构近似匹配允许有限局部语句差异，但语义锚点必须一致。详细公式和全部敏感性字段见 [`docs/guides/evaluation-metrics.md`](../../docs/guides/evaluation-metrics.md)。

`haggis_cpp.py`、`llm_direct_baseline.py` 和 `idiomine_cpp.py` 提供对照方法。所有方法输出当前习语 artifact，再由同一指标入口评价。
