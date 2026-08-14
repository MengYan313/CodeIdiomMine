# C++ “15+15”数据集设计

## 1. 数据集结构

CodeIdiomMine 使用 15 个 Project 分组和 15 个 Library 分组，共 30 个实验单位，而不是 30 个仓库。

Project Corpus 以完整 C++ 仓库为边界，研究同一项目内部由架构、领域模型和工程约定形成的重复习语。Library Corpus 以目标库 API 为边界，聚合多个外部客户端仓库中实际使用该库的文件，研究跨项目复现的 API 使用习语；目标库本身的实现源码不进入该分组。

两类语料共享文件扩展名、解析质量、第三方代码过滤和训练—测试原则，划分统一命名为 `train`/`test`，但保持不同的统计单位：Project 不跨仓聚类，Library 只在同一目标库内跨客户端聚合。15 个 Project 仓库也从 Library 客户端候选中排除，避免两类语料在仓库身份上重叠。

## 2. 方法学依据

[Haggis](https://homepages.inf.ed.ac.uk/csutton/publications/idioms.pdf)区分完整项目语料和围绕流行库组织的使用语料，分别考察项目特定模式和跨项目 API 模式，并采用训练—测试划分。本研究沿用这一数据集思想，将语言前端和 API 判定改为 C++。

[IdioMine](https://doi.org/10.1145/3597503.3639135)通过依赖链、代码表示和聚类补充纯连续 AST 片段，说明控制/数据依赖与 API 使用关系是习语发现的重要证据。它影响后续候选构造与评价方法，但不改变本研究的 Project/Library 数据单位。已有 CodeIdiomMine 聚类仅用于筛选 Project 名单，不能作为新数据集的正式结果。

## 3. Project Corpus 选择

Project 候选来自原有 23 个 C++ 仓库。选择同时考虑项目流行度、统一过滤后的有效源码规模，以及冻结聚类所反映的有效簇数量、跨文件支持、簇内一致性、项目特定性和污染率。真实 LLM 判断、合成结果与最终评价指标不参与名单选择，以避免结果导向的样本选择。

最终保留：`btop`、`catch2`、`drogon`、`envoy`、`fmt`、`leveldb`、`libzmq`、`mosh`、`ninja`、`polybar`、`qbittorrent`、`spdlog`、`taskflow`、`yaml-cpp`、`yoga`。

排除的 `cereal`、`cli11`、`concurrentqueue`、`json`、`magic_enum`、`react-native`、`tomlplusplus`、`uwebsockets` 主要受到头文件/单头发行结构、有效源码过小、跨文件支持不足、外部实现边界或稀疏工作树等因素影响。逐仓理由见 [`repos/project/README.md`](../../repos/project/README.md)。Envoy 原 sparse checkout 已在保持原提交的前提下补全为完整工作树。

统一扫描后，Project Corpus 包含 6,248 个文件和 748,364 eLOC。仓库内同 stem 的头文件、实现文件和平台变体构成不可分割文件组，再按 eLOC 确定性划分为约 70% `train` 和 30% `test`。

## 4. Library Corpus 选择

Library 候选范围冻结于 `T0 = 2026-08-13T16:54:48Z`，检索此前 60 个月内保持活动的 GitHub 公共仓库。候选仓库须非 fork、archive、mirror 或 template，默认分支可读取，至少具有 1 个 fork 或 10 stars，可识别 license，并在统一过滤后包含至少 5 个有效 C/C++ 文件。

目标库依据流行度、API 边界清晰度、外部客户端可得性和 C++ 领域覆盖选取：`abseil`、`boost-asio`、`catch2`、`cli11`、`eigen`、`fmt`、`glm`、`googletest`、`grpc`、`nlohmann-json`、`opencv`、`pybind11`、`rocksdb`、`spdlog`、`yaml-cpp`。

每个文件必须在移除注释后同时包含目标 include 和明确的 namespace、类型、调用或宏证据。只有 include、依赖声明或文字提及不算使用。API 白名单见 [`repos/library/README.md`](../../repos/library/README.md)。所有目标使用相同检索范围、仓库门槛、路径过滤、解析阈值和规模控制。

统一排除目标库本体及其 fork/mirror、客户端中的 vendored 或源码副本、生成代码、amalgamated/single-header 文件、复制的官方示例和解析质量不足的文件。每个客户端最多保留 50 个文件，每个目标最多保留 5,000 个文件；排序同时考虑解析质量、API 证据强度、客户端多样性和 production 文件优先级。正式冻结前再以同一规则审计全部目标，覆盖 `deps/3rd/Pods` 路径变体、嵌入式依赖/目标源码树、跨目标混入的其他库源码副本、框架复制头文件及明确生成标头，从初筛语料中统一剔除 1,125 个文件成员。

最终 Library Corpus 包含 1,257 个唯一客户端、29,941 个目标-文件成员和 8,301,170 eLOC。CLI11 与 RocksDB 分别只有 238 和 306 个文件，但仍覆盖 44 和 37 个独立客户端。二者作为明确接受的小样本组保留，不放宽规则，也不根据采集结果更换目标；分析时单独报告其不确定性。Googletest 在规模控制阶段达到 5,000 文件上限，最终验收后保留 4,837 个文件。

## 5. 去重与数据划分

客户端身份使用小写规范 `owner/repo`，文件记录和目录名可以保留 GitHub 展示大小写；不使用提交 SHA 或内容哈希。fork、mirror 和 template 由仓库元数据排除；未标记重复项目通过候选源码集合重合度识别。文件副本通过去除注释和空白后的源码文本直接比较。

Library 以完整客户端仓库为不可分割单位建立一次全局 70/30 划分。分配同时约束各目标的客户端比例，并最小化各组 eLOC 偏差。同一客户端使用多个目标库时始终位于同一侧。最终验收不重排剩余客户端；清除空客户端后为 881 个 `train` 客户端和 376 个 `test` 客户端。

## 6. 最终规模与解释边界

两类语料共包含 36,189 个文件成员和 9,049,534 eLOC。Project 与 Library 的观察边界不同，正式分析应分别报告两类语料的组宏平均，不能把全部文件混合后只报告微平均。Library 中同一物理文件可以因使用多个目标 API 而属于多个分组，因此总文件数是目标-文件成员数。

该数据集是受约束的目的性样本，不代表全部 GitHub C++ 工程。公共代码索引覆盖、API 白名单、统一路径过滤和每客户端文件上限均可能产生假阴性；相反，严格排除源码副本和生成文件降低了由机械重复造成的污染。小样本目标和达到上限的目标均应在稳健性分析中单独报告。
