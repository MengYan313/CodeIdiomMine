# 文档索引

仓库只在根目录保留项目入口文档 `README.md` 和开发约定 `AGENTS.md`。其余说明统一归档在 `docs/` 下。项目自有文档使用中文，代码、命令、路径和必要技术标识保留英文；外部论文按来源语言归档在 `docs/research/`。

## 开发文档

- [两项目共享开发约定](guides/shared-development-conventions.md)：日志、LLM、AutoGen、目录和测试的统一契约。
- [提示词优化本地指南](guides/prompt-engineering-guide.md)：日常提示词结构、JSON 契约、验证流程与官方指南刷新条件。
- [仓库架构](guides/repository-architecture.md)：模块职责、C++ 数据流和范围边界。
- [评价指标规范](guides/evaluation-metrics.md)：最终指标分类、公式、聚合方式、解释边界与变更控制。
- [baseline 复现](guides/baselines.md)：三条 baseline、CIMAS-CPP、统一产物合同、运行命令与验证状态。
- [本地验证指南](guides/testing.md)：从自动化测试到完整流水线的验证顺序。
- [本地开发基线](guides/local-baseline.md)：已验证环境、实际产物、错误证据和延期事项。
- [Agent 子系统架构](guides/agent-system.md)：判断与合成流水线的详细设计。
- [Agent 开发契约](guides/agent-contracts.md)：修改或新增 Agent 时必须保持的行为约束。

## 研究文档

- [C++ 代码习语挖掘研究稿](research/01_C++代码习语挖掘研究稿.md)
- [面向代码可复用性增强的融合研究方案](research/03_面向代码可复用性增强的融合研究方案.md)
- [Idiom Mining II](research/Idiom_Mining_II.pdf)

研究文档是论文背景和未来实验设计，不是当前实现规格。除非任务明确要求论文方案对齐，否则以源代码和开发文档中已验证的行为为准。

两份研究稿引用了 `docs/references/英文文献库.md` 和 `docs/references/中文文献库.md`，但这些文献库不在当前仓库中。现阶段保留原引用，不伪造缺失内容；补入正式文献库后再统一验证锚点。
