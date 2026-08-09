# 评价指标

正式评价使用 `within_project_kfold`：每个仓库按稳定路径排序，第 `p` 个文件进入 `p mod K` 折，`K=min(5, 文件数)`。五轮中每个文件恰好一次作为测量文件，避免单次路径前缀切分偏差。

固定九项指标为：

- `IC_macro`：已接受习语实例在测量函数候选域 AST 节点上的函数宏平均覆盖率；
- `IC_micro`：上述节点的全仓微平均覆盖率；
- `IC`：先取前两者的算术平均 `IC_raw`，再计算 `sqrt(IC_raw)`；平方根把稀疏覆盖的低值区间展开，保持排序、零点和满覆盖不变；
- `ISP`：至少具有两个独立来源函数域的习语种类占比；函数域由
  `(仓库相对文件路径, 函数根 extent)` 精确标识，无法映射回当前数据集函数根的
  来源证据不计支持；
- `F1`：`IC` 与 `ISP` 的调和平均；
- `idiom_type_count`、`avg_cluster_size`、`avg_cross_function_support`、`AvgAST`：最终习语库结构。

候选域与发现阶段一致，由函数中的区域、语句、核心操作和语义切片候选的 AST 节点并集组成，不把函数签名和无候选包装节点强行放入分母。`IC_raw` 使用最终 artifact 的完整 `source_infos` 定位已接受实例，并补充参考折模板找到的额外实例；重叠节点只计一次。候选域节点非常多时，原始比例集中在零附近，因此主 `IC` 对 `IC_raw` 做无参数平方根变换，以拉开方法间低覆盖差异。该变换对所有方法和仓库一致，不改变覆盖排序；`IC_raw` 与 `F1_raw` 始终随结果保存。主指标衡量最终知识库在当前仓库的实际足迹，不声称未知数据泛化。主 `ISP` 衡量独立函数域支持，不是人工 Precision。

为避免尺度变换或较大的主指标掩盖过拟合，JSON 同时保存 `IC_raw`、`F1_raw` 及以下敏感性指标：

- `IC_generalization_macro`、`IC_generalization_micro`、`IC_generalization`：不使用测量折来源位置，只以其余折源码确定性归纳模板后外推；
- `ISP_generalization`：每种库习语只计一次，只要在任一测量折被参考模板复现即命中；
- `ISP_fold`：把同一种习语在各参考折的机会分别计入分母的更严格值；
- `IC_all_macro`、`IC_all_micro`、`IC_all`：把完整函数 AST 作为分母；
- `F1_generalization`、`F1_all_fold`：对应敏感性指标的调和平均。

参考模板完全由参考文件生成：局部变量、参数和字面量转换为 `<VAR_n>`、`<LIT_n>`，相同占位符必须绑定同一 token；调用目标、限定名、成员、类型、控制关键字和关键运算符保持一致。除精确匹配外，结构匹配允许有限局部语句差异，但要求语义锚点不变且参考 token 有至少 `0.72` 的有序覆盖。该规则、候选域和分母对 CIMAS 与全部 baseline 完全相同，不按方法或仓库调参。ISP 改用函数域后，五折仍按文件划分：同一文件的所有函数始终属于同一折，不能分别进入参考折和测量折。因此主 ISP 衡量仓库内跨函数复用，`ISP_generalization` 与 `ISP_fold` 仍衡量更严格的跨文件折外推。

形式上，令 `E_f` 为函数 `f` 的候选域节点，`A_f` 为已接受来源证据和参考模板额外命中的节点并集，`I` 为可定位习语集合，`S(i)` 为习语 `i` 的独立来源函数域集合，则：

```text
IC_macro = mean_f(|A_f ∩ E_f| / |E_f|)
IC_micro = Σ_f |A_f ∩ E_f| / Σ_f |E_f|
IC_raw   = (IC_macro + IC_micro) / 2
IC       = sqrt(IC_raw)
ISP      = |{i ∈ I : |S(i)| >= 2}| / |I|
F1       = 2 * IC * ISP / (IC + ISP)
F1_raw   = 2 * IC_raw * ISP / (IC_raw + ISP)
```

无候选域的函数不进入 `IC_macro`；空分母和调和平均的零输入记为 `0`。所有方法都通过 `src.evaluation.idiom_metrics` 读取当前 `idiom_judgment` 或 `idiom_synthesis` artifact。

```bash
.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/cpp/cli11 \
  --dataset outputs/cpp/cli11/dataset.pkl \
  --output results/cpp/cli11/evaluation.json \
  --mode within_project_kfold --folds 5
```

比较方法时必须使用相同仓库、折分配和指标入口。不得在查看结果后为某个方法改变阈值、分母、折或匹配器。通用目录习语按 `catalog_id` 汇总；仓库专属习语不跨仓库去重。
