# 测试指南

## 全量离线测试

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

测试不得下载模型或执行付费 LLM 调用。涉及模型的测试使用本地缓存、Fake Client 或合成向量。

## 测试重点

- Parser：扫描排除规则、源码范围、复杂声明、宏恢复和候选片段。
- Mining：token 预算、embedding 数据结构、DBSCAN 选择和簇归并。
- Judgment：规则拒绝、上下文读取、JSON 修复、checkpoint 续跑和 artifact。
- Synthesis：区域共现、有限规划、独立计划审查和输出。
- Evaluation：文件分区、覆盖计数、结构签名和 baseline 合同。

Bug 修复应增加能直接复现问题的最小测试。当前格式发生变化时直接更新 fixture 与断言，不为旧 fixture 增加兼容分支。

## 真实冒烟测试

真实 LLM 或本地大模型测试只在任务明确需要时运行，并限制样例数、调用次数与输出目录。运行前确认源码公开性、隐私和成本；测试结果不自动视为正式实验结果。
