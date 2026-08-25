# 仓库架构

CodeIdiomMine 按单仓库运行 Stage 0～4：Parser 解析数据集，候选构建、Mining、Judgment 和 Synthesis 依次生成后续产物。评价是主流程后的独立测量步骤。

```text
repos/<scope>/<project>
  -> outputs/<scope>/<project>/stage0/dataset.pkl
  -> outputs/<scope>/<project>/stage1/fragments.pkl
  -> outputs/<scope>/<project>/stage2/embeddings.pkl / clusters.pkl
  -> outputs/<scope>/<project>/stage3/idiom-judgment.pkl
  -> outputs/<scope>/<project>/stage4/idiom-synthesis.pkl
  -> results/<scope>/<project>/main/...
  -> results/<scope>/<project>/baselines/<method>/...
  -> results/<scope>/<project>/ablations/<name>/...
```

## 目录职责

- `src/parser/`：文件扫描、AST、源码范围和候选片段。
- `src/mining/`：模型嵌入、DBSCAN 调参与簇归并。
- `src/idiom_judgment/`：规则、语义、类型和异味门禁。
- `src/idiom_synthesis/`：区域共现、组合规划和合成复核。
- `src/evaluation/`：指标、baseline 和质量消融。
- `src/llm/`：客户端、JSON 解析、一次修复和有限重试。
- `src/agents/`：共享 Agent 基类与注册辅助函数。
- `src/common/`：日志和位置式 SQLite checkpoint。

每个阶段只读取上一阶段当前产物。源码使用仓库相对路径和字节/行列范围定位，不使用内容摘要或版本字段。跨仓库数据只在最终汇总时组合，不能混入单仓库聚类和判定。

`outputs/` 保存可重建的中间结果；`results/<scope>/<project>/` 按仓库汇集
主方法、外部 baseline 和消融的最终结果。
生成的二进制产物不作为源代码提交。
