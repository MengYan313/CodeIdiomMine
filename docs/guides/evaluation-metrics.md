# 评价指标

正式评价使用 `haggis_holdout`。Parser 直接读取语料根目录的
`dataset-manifest.json`，把每个文件的 `split` 与 `cppFile`、`func_ast`、
`func_src` 平行保存到 `dataset.pkl`。Project Corpus 沿用按组和 eLOC 冻结的
70/30 分配；Library Corpus 沿用按客户端仓库冻结的分配，同一客户端不能同时
进入 train 和 test。

所有方法只从 train 发现习语。CIMAS-CPP、Stage 2 消融与 IdioMine-CPP 通过
train-only fragments/embeddings 运行；Haggis-CPP 与 LLM-Direct-Budget 在入口
直接选择 train。评价器只用 train 来源归纳参数化模板，并在固定 test 上计算
Haggis 主指标：

- `IC_macro`、`IC_raw`、`IC`：逐测试文件计算被至少一个训练习语匹配覆盖的
  AST 节点并集比例，再对测试文件取宏平均；
- `IC_micro`：把全部测试文件节点合并后的微平均诊断值，不参与 `IC`；
- `ISP`：训练所得习语中至少在 test 匹配一次的种类比例；
- `F1`：`IC` 与 `ISP` 的调和平均。F1 是本项目为统一比较派生的指标，Haggis
  原论文没有定义该项；
- `idiom_type_count`、`avg_cluster_size`、`avg_cross_function_support`、
  `AvgAST`：原有习语库结构指标，保持不变。

当前 C++ 适配以 Parser 保存的函数 AST 节点作为源码 AST 节点域。Parser 已过滤
没有有效函数的文件，因此 IC 的文件集合是 test 中至少保留一个有效函数的文件。
同一习语在同一节点重复命中、不同习语覆盖同一节点时，节点都只计一次。
测试匹配枚举完整函数 AST 的节点根，不再次应用发现阶段的候选大小阈值。

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
`global` 的 IC 按所有测试文件汇总，ISP 按所有训练习语汇总；`summary` 继续指向
`repository_macro`。

原评价指标没有删除，改用明确名称作为诊断字段：

- `IC_opportunity_macro`、`IC_opportunity_micro`、`IC_opportunity`：原 Stage 2
  非噪声聚类机会域覆盖；
- `ISP_support`：原“至少两个独立来源函数域”比例；
- `F1_opportunity_support`：上述两项的调和平均；
- `IC_generalization*`、`ISP_generalization`、`ISP_fold`、`IC_all*`、
  `F1_generalization`、`F1_all_fold`：公式保持不变，但稳定轮转五折只在 train
  文件内执行，不接触固定 test。

参考模板只读取 train：局部变量、参数和字面量转换为 `<VAR_n>`、`<LIT_n>`，
相同占位符必须绑定同一 token；调用目标、限定名、成员、类型、控制关键字和关键
运算符保持一致。除精确匹配外，结构匹配允许有限局部语句差异，但要求语义锚点
不变且参考 token 有至少 `0.72` 的有序覆盖。该 matcher 对 CIMAS、全部 baseline
与 Stage 2 消融相同，不按方法或仓库调参。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/main/leveldb \
  --dataset outputs/project/leveldb/stage0/dataset.pkl \
  --clusters outputs/project/leveldb/stage2/clusters.pkl \
  --output results/main/leveldb/evaluation.json \
  --mode haggis_holdout --folds 5
```

比较方法时必须使用同一 `dataset.pkl`、同一冻结 split、同一 Stage 2 产物和同一
评价入口。不得在查看结果后为某个方法改变阈值、分母或 matcher。
