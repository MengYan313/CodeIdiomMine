# 评价指标

正式评价使用 `within_project_kfold`：每个仓库按稳定路径排序，第 `p` 个文件进入 `p mod K` 折，`K=min(5, 文件数)`。五轮中每个文件恰好一次作为测量文件，避免单次路径前缀切分偏差。

固定九项指标为：

- `IC_macro`：已接受习语实例在测量函数聚类机会域 AST 节点上的函数宏平均覆盖率；
- `IC_micro`：上述节点的全仓微平均覆盖率；
- `IC`：前两者的算术平均，不做平方根、对数或其他数值变换；`IC_raw` 与 `IC` 相等；
- `ISP`：至少具有两个独立来源函数域的习语种类占比；函数域由
  `(仓库相对文件路径, 函数根 extent)` 精确标识，无法映射回当前数据集函数根的
  来源证据不计支持；
- `F1`：`IC` 与 `ISP` 的调和平均；
- `idiom_type_count`、`avg_cluster_size`、`avg_cross_function_support`、`AvgAST`：最终习语库结构。

聚类机会域在 Stage 3 裁决前从 Stage 3 实际消费的 Stage 2 聚类产物冻结。评价器只读取非噪声簇的全部 `infos`，以 `(仓库相对路径, 函数根 extent)` 精确定位函数；函数至少含一个聚类成员才进入分母。函数 `f` 的 `E_f` 是该函数所有聚类成员对应 AST 节点的去重并集：噪声候选、同函数内未进入聚类的其他候选和没有聚类成员的函数均不计入，重叠成员节点只计一次。文件、函数根或成员 AST 节点无法精确映射时直接报错，不回退到全函数或旧候选域。最终 artifact 的完整 `source_infos` 提供已接受来源证据，参考折模板只补充在测量折找到的额外实例，分子最后与 `E_f` 取交集。

同一仓库的所有方法、裁决策略和消融必须显式传入同一份冻结聚类产物，不能根据最终接受习语反向筛选函数或节点。主指标衡量最终知识库在当前仓库预先存在的聚类机会中的实际足迹，不声称未知数据泛化。主 `ISP` 衡量独立函数域支持，不是人工 Precision。

`Stage2-Frequency-Ablation` 直接从定义机会域的 Stage 2 聚类中选择最大簇，其来源证据天然覆盖同一分母，大簇也天然具有较高跨函数支持。因此该消融的 IC、ISP、F1 只作为 Stage 2 覆盖上界诊断，不参加外部 baseline 的自动指标质量排名。Stage 2 高频簇与 Stage 4 最终习语的质量差异必须通过等量、分层、盲化人工标注验证，不能用自动覆盖指标单独证明。

JSON 保留与主指标相等的 `IC_raw` 及以下敏感性指标：

- `IC_generalization_macro`、`IC_generalization_micro`、`IC_generalization`：不使用测量折来源位置，只以其余折源码确定性归纳模板后外推；
- `ISP_generalization`：每种库习语只计一次，只要在任一测量折被参考模板复现即命中；
- `ISP_fold`：把同一种习语在各参考折的机会分别计入分母的更严格值；
- `IC_all_macro`、`IC_all_micro`、`IC_all`：把完整函数 AST 作为分母；
- `F1_generalization`、`F1_all_fold`：对应敏感性指标的调和平均。

参考模板完全由参考文件生成：局部变量、参数和字面量转换为 `<VAR_n>`、`<LIT_n>`，相同占位符必须绑定同一 token；调用目标、限定名、成员、类型、控制关键字和关键运算符保持一致。除精确匹配外，结构匹配允许有限局部语句差异，但要求语义锚点不变且参考 token 有至少 `0.72` 的有序覆盖。该规则、冻结机会域和分母对 CIMAS、全部 baseline 与 Stage 2 消融完全相同，不按方法或仓库调参。ISP 使用函数域，五折仍按文件划分：同一文件的所有函数始终属于同一折，不能分别进入参考折和测量折。因此主 ISP 衡量仓库内跨函数复用，`ISP_generalization` 与 `ISP_fold` 仍衡量更严格的跨文件折外推。

形式上，令 `E_f` 为函数 `f` 的冻结聚类机会域节点，`A_f` 为已接受来源证据和参考模板额外命中的节点并集，`I` 为可定位习语集合，`S(i)` 为习语 `i` 的独立来源函数域集合，则：

```text
IC_macro = mean_f(|A_f ∩ E_f| / |E_f|)
IC_micro = Σ_f |A_f ∩ E_f| / Σ_f |E_f|
IC_raw   = (IC_macro + IC_micro) / 2
IC       = IC_raw
ISP      = |{i ∈ I : |S(i)| >= 2}| / |I|
F1       = 2 * IC * ISP / (IC + ISP)
```

无聚类成员的函数不进入 `IC_macro`；有聚类成员但最终没有接受习语的函数仍以零覆盖进入分母。空分母和调和平均的零输入记为 `0`。所有方法都通过 `src.evaluation.idiom_metrics` 读取当前 `idiom_judgment` 或 `idiom_synthesis` artifact。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/main/leveldb \
  --dataset outputs/leveldb/stage0/dataset.pkl \
  --clusters outputs/leveldb/stage2/clusters.pkl \
  --output results/main/leveldb/evaluation.json \
  --mode within_project_kfold --folds 5
```

比较方法时必须使用相同仓库、同一 Stage 2 冻结聚类产物、折分配和指标入口。不得在查看结果后为某个方法改变阈值、分母、折或匹配器。通用目录习语按 `catalog_id` 汇总；仓库专属习语不跨仓库去重。
