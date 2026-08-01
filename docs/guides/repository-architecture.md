# 仓库架构

CodeIdiomMine 按单仓库、四阶段运行：Parser 构建候选，Mining 生成嵌入与簇，Judgment 判定习语，Synthesis 合成关联习语。评价是主流程后的独立测量步骤。

```text
repos/<project>
  -> dataset.pkl / fragments.pkl
  -> embeddings.pkl / clusters.pkl / clusters-merged.pkl
  -> idiom-judgment.pkl
  -> idiom-synthesis.pkl
  -> evaluation.json
```

## 目录职责

- `src/parser/`：文件扫描、AST、源码范围和候选片段。
- `src/mining/`：模型嵌入、DBSCAN 调参与簇归并。
- `src/idiom_judgment/`：规则、语义、类型和异味门禁。
- `src/idiom_synthesis/`：区域共现、组合规划和合成复核。
- `src/evaluation/`：指标和 baseline。
- `src/llm/`：客户端、JSON 解析、一次修复和有限重试。
- `src/agents/`：共享 Agent 基类与注册辅助函数。
- `src/common/`：日志和位置式 SQLite checkpoint。

每个阶段只读取上一阶段当前产物。源码使用仓库相对路径和字节/行列范围定位，不使用内容摘要或版本字段。跨仓库数据只在最终汇总时组合，不能混入单仓库聚类和判定。

`outputs/` 保存可重建的中间结果，`results/` 保存最终结果；两者都不作为源代码提交。
