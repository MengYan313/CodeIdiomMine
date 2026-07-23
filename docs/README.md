# 文档索引

仓库只在根目录保留项目入口文档 `README.md` 和开发约定 `AGENTS.md`。其余说明统一归档在 `docs/` 下。项目自有文档使用中文，代码、命令、路径和必要技术标识保留英文；外部论文按来源语言归档在 `docs/research/`。

## 开发文档

- [两项目共享开发约定](guides/shared-development-conventions.md)：日志、LLM、AutoGen、目录和测试的统一契约。
- [提示词优化本地指南](guides/prompt-engineering-guide.md)：日常提示词结构、JSON 契约、验证流程与官方指南刷新条件。
- [仓库架构](guides/repository-architecture.md)：模块职责、C++ 数据流、零构建解析不变量和范围边界。
- [Parser v2 设计与使用](guides/parser-design.md)：零构建输入合同、异常检测、宏恢复、源码映射、候选 profile 和局部 Def-Use 切片。
- [C++ Adapter 与模型输入治理](guides/cpp-adapter-and-model-input.md)：复杂 C++ 语法适配、宏恢复边界、UniXcoder 长度依据及 Parser 阶段降级。
- [Parser 基线与优化对比](guides/parser-quality-report.md)：4,804 个真实文件的前后统计、确定性和性能证据。
- [Parser 代表性产物审计](guides/parser-artifact-audit.md)：宏、模板、Concept、Lambda、不完整代码和语义片段样例。
- [Parser 风险与限制](guides/parser-risks.md)：失败分类、兼容策略、误切分风险和未解决事项。
- [C++ 数据集 Parser 优化与回归](guides/cpp-dataset-parser-regression.md)：27 个候选的修改前基线、通用扫描与路径修正、优化后全量结果和确定性证据。
- [评价指标规范](guides/evaluation-metrics.md)：最终指标分类、公式、聚合方式、解释边界与变更控制。
- [baseline 复现](guides/baselines.md)：三条 baseline、CIMAS-CPP、统一产物合同、运行命令与验证状态。
- [本地验证指南](guides/testing.md)：从自动化测试到完整流水线的验证顺序。
- [本地开发基线](guides/local-baseline.md)：已验证环境、实际产物、错误证据和延期事项。
- [Agent 子系统架构](guides/agent-system.md)：判断与合成流水线的详细设计。
- [Agent 开发契约](guides/agent-contracts.md)：修改或新增 Agent 时必须保持的行为约束。

## 研究文档

- [C++ 实验数据集现状报告](research/cpp-dataset-status-report.md)：26 个正式项目的构成、统计、范围、复算方法与局限。
- [C++ 实验数据集逐项目排查报告](research/cpp-dataset-project-audit.md)：27 个候选的固定版本、许可、规模、解析质量与筛选结论。
- [C++ 实验数据集结构化清单](research/cpp-dataset-manifest.json)：完整 commit、许可文件证据、复现命令、基线/最终指标与产物位置。
- [C++ 实验数据集统计](research/cpp-dataset-statistics.json)：从实际固定源码和解析产物重算的正式汇总。
- [C++ 代码习语挖掘研究稿](research/01_C++代码习语挖掘研究稿.md)
- [面向代码可复用性增强的融合研究方案](research/03_面向代码可复用性增强的融合研究方案.md)
- [Idiom Mining II](research/Idiom_Mining_II.pdf)

研究文档是论文背景和未来实验设计，不是当前实现规格。除非任务明确要求论文方案对齐，否则以源代码和开发文档中已验证的行为为准。

两份研究稿引用了 `docs/references/英文文献库.md` 和 `docs/references/中文文献库.md`，但这些文献库不在当前仓库中。现阶段保留原引用，不伪造缺失内容；补入正式文献库后再统一验证锚点。
