# Agent 模块

本模块完成候选习语判断与模板合成。判断阶段并行执行语义和语法评估，再按固定阈值生成最终结论；合成阶段按 `loc_label` 分组，执行规划、组装和合成后再判断，最多三轮。

## 启动命令

```bash
.venv/bin/python -m src.agents.idiom_judgement \
  --input outputs/cpp/clusters.pkl --output-dir results/cpp

.venv/bin/python -m src.agents.idiom_synthesis \
  --input-dir results/cpp --output-dir results/cpp
```

运行前必须配置 `.env`，并确认代码片段对外发送的范围、调用成本和模型档位。详细设计见 [Agent 子系统](../../docs/guides/agent-system.md)，修改约束见 [Agent 开发契约](../../docs/guides/agent-contracts.md)。
