# C++ “15+15”实验语料

`repos/` 保存两个不同观察尺度的正式语料，共 30 个实验分组：

- `project/`：15 个完整上游仓库分组。每个仓库单独研究项目内部重复出现的项目特定习语。
- `library/`：15 个目标库分组。每组聚合多个外部客户端仓库中“引入且实际使用”该库 API 的 C/C++ 文件，不包含目标库实现。

这种划分沿用 Haggis 的 Project/Library 数据集理念：Project 保留项目边界，Library 保留 API 边界并跨客户端聚合。IdioMine 的依赖链、表示、聚类和判断流程是后续待运行的方法，不改变语料分组单位。本轮已有聚类只用于筛选 Project 名单，不作为新语料的正式实验结果。

源码仓库和客户端文件均由 Git 忽略；版本控制只保存本说明、两个语料 README 及 `docs/research/` 下的结构化研究记录。本地逐文件清单分别位于 `project/dataset-manifest.json` 和 `library/dataset-manifest.json`。

两个 `dataset-manifest.json` 是正式实验的唯一文件边界和划分依据。不得以通用目录递归扫描结果替代清单：Project 保留完整仓库但只研究清单文件，Library 允许客户端手写 test/example，而通用扫描器的目录过滤与这两项合同并不等价。实验入口必须显式读取清单中的文件身份和 `train`/`test`，再进入 Parser 与后续阶段。

正式名单、筛选漏斗、API 证据规则、去重、规模和划分见：

- [Project Corpus](project/README.md)
- [Library Corpus](library/README.md)
- [数据集分类与选取方法](../docs/research/cpp-dataset-classification.md)
- [结构化选择清单](../docs/research/cpp-dataset-selection.json)
- [30 组统计](../docs/research/cpp-dataset-statistics.json)

`repos/` 根目录只保留本说明与 `project/`、`library/` 两套正式语料；旧候选仓库不再保留，后续实验入口不得扫描两套语料之外的目录。
