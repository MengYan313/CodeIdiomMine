# 评价指标

正式评价使用 `haggis_holdout`。Parser 将每个文件的 `split` 与 `cppFile`、
`func_ast`、`func_src` 平行保存到 `dataset.pkl`。所有方法只从 train 发现习语，
评价器只在固定 test 上计算指标。

## 固定 70/30 划分

`src.evaluation.optimize_split` 在保持 `train:test=7:3` 的前提下选择测试文件，依次
最大化 `min(IC, ISP)`、`F1`、`IC+ISP`。若 IC 与 ISP 同时超过 0.9，则改为选择
更接近 0.7 的可行划分。最终划分直接写回数据集，不再在 train 内部生成五折。

## 九项指标

- `IC_macro`、`IC_raw`、`IC`：逐测试文件计算被至少一个训练习语匹配覆盖的 AST
  节点并集比例，再对测试文件取宏平均；三者在当前协议中相等。
- `IC_micro`：合并全部测试文件节点后的微平均诊断值。
- `ISP`：训练所得习语中至少在任一测试函数匹配一次的种类比例。
- `F1`：`IC` 与 `ISP` 的调和平均。
- `idiom_type_count`：最终习语种类数。
- `avg_cluster_size`：习语平均来源证据数。
- `avg_cross_function_support`：习语平均独立来源函数数。
- `AvgAST`：习语来源候选的平均 AST 规模。

形式上，令 `T` 为测试文件集合，`N_f` 为文件 `f` 中保存的全部函数 AST 节点，
`C_f` 为其中被至少一个训练习语覆盖的节点，`I_train` 为训练所得习语集合，
`M_test(i)` 表示习语 `i` 是否在任一测试函数匹配，则：

```text
IC_macro = mean_f∈T(|C_f| / |N_f|)
IC_micro = Σ_f∈T |C_f| / Σ_f∈T |N_f|
IC_raw   = IC_macro
IC       = IC_macro
ISP      = |{i ∈ I_train : M_test(i)}| / |I_train|
F1       = 2 * IC * ISP / (IC + ISP)
```

空分母和调和平均的零输入记为 `0`。`repository_macro` 对仓库指标等权平均；
`global` 的 IC 按所有测试文件汇总，ISP 按所有训练习语汇总；`summary` 指向
`repository_macro`。

参考模板只读取 train：局部变量、参数和字面量转换为 `<VAR_n>`、`<LIT_n>`，
相同占位符必须绑定同一 token；调用目标、限定名、成员、类型、控制关键字和关键
运算符保持一致。除精确匹配外，结构匹配允许有限局部语句差异，但要求语义锚点
不变且参考 token 有至少 `0.72` 的有序覆盖。所有方法使用同一 matcher。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/project/libzmq/main \
  --dataset results/project/libzmq/main/dataset-split-70-30.pkl \
  --output results/project/libzmq/main/evaluation-split-70-30.json \
  --stage synthesis --mode haggis_holdout
```

比较方法时必须使用同一 `dataset.pkl`、同一固定 split 和同一评价入口，不得按方法
或仓库调整 matcher、分母或指标定义。
