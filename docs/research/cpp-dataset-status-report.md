# C++ 实验数据集现状报告

## 结论

2026-07-24 完成 26 个公开 GitHub C++ 项目的候选搜索、许可核验、固定版本、
基线解析、通用 Parser 优化、全量重解析和产物一致性校验。2026-07-29 再根据
冻结的逐仓 DBSCAN 指标和具体簇语义完成阶段2质量筛选，正式论文主数据集现为
23 个项目，其中 16 个“保留”、7 个“条件保留”。`cpp-httplib`、`entt` 和
`simdjson` 标记为“阶段2后排除”，不进入后续 LLM、合成或主结果统计，但固定
源码与历史阶段1/2产物继续保留。`microsoft/GSL` 仍为“淘汰”，本地副本不保留。

候选搜索共检查 27 个项目，其中 24 个是新增候选、3 个是原有种子项目，未超过
35 个新增候选的搜索上限。26 仓阶段1/2结果是筛选前真实实验记录；当前正式
项目及排除依据以
[聚类质量筛选报告](cpp-clustering-quality-screening.md)为准。
正式 23 仓的主领域、相对分析复杂度、选取漏斗和后续分层实验口径见
[数据集分类与选取方法](cpp-dataset-classification.md)。

## 核心统计

| 指标 | 正式数据集 |
|---|---:|
| 项目数 | 23 |
| 固定种子项目数 | 3 |
| 核心源码文件数 | 7,505 |
| 有效代码行数 | 1,013,071 |
| 文件级解析成功率 | 100% |
| 选中函数数 | 72,090 |
| 习语候选数 | 203,609 |
| 可靠 AST 字节覆盖率 | 91.09% |
| 解析失败文件数 | 0 |
| 重复仓库相对路径 | 0 |
| 越界路径 | 0 |
| 符号链接输入 | 0 |

候选按层级分为：函数 67,719 个、区域 36,668 个、局部 Def-Use 语义切片
8,600 个、语句 90,622 个。实体计数、错误分类、构建系统、许可、C++ 标准和
习语覆盖的完整分布见 `cpp-dataset-statistics.json`。

## 数据集组成

正式项目覆盖 C++11、C++14、C++17 与 C++20；包含命令行工具、桌面应用、
网络代理、Web 框架、存储系统、消息通信、布局引擎，以及格式化、日志、序列化、
解析器、并发和任务图等基础库。构建系统元数据覆盖 CMake、Make、Meson、
Bazel、Buck 与 Autotools，但本轮从未执行目标仓库的构建、安装、代码生成、
测试或其他脚本。

许可分布为 MIT 11 个、Apache-2.0 4 个、BSD-3-Clause 3 个，以及
BSD-2-Clause、BSL-1.0、GPL-2.0-or-later、GPL-3.0 和 MPL-2.0 各 1 个。
每个项目的 SPDX 判断、根目录许可文件路径及文件 SHA-256 均记录在结构化清单
中。公开可访问不等于任意再分发；后续发布源码快照或派生产物时仍须逐项目遵守
许可和署名条件。

GitHub 元数据快照中，正式项目 star 中位数为 15,315，范围为
2,107～126,249；fork 中位数为 1,857，范围为 206～25,188。23 个项目均未归档，
且在快照日前 365 天内有上游 push；最近 push 距快照日的中位数为 3 天、最大值
为 302 天。star、fork 和时间是候选质量背景，不参与 Parser 指标计算。

规模分布为：

- 4 个项目有 2,000～9,999 行有效代码；
- 18 个项目有 10,000～99,999 行；
- Envoy 超过 100,000 行；
- 文件数中位数为 97，2 个项目少于 10 个核心文件，2 个项目至少 1,000 个核心文件。

按核心生产用途，正式项目分为数据表示与泛型基础库 6 个、网络与分布式系统
5 个、应用与跨平台界面 5 个、开发工具与工程基础设施 4 个、存储与并发基础设施
3 个。按有效代码行、核心文件和阶段1候选三个指标的仓库内平均秩计算相对分析
复杂度，低、中、高三层分别有 8、8、7 个项目。该复杂度只表示当前流水线的相对
处理负荷，不表示代码质量或软件本质复杂度。

## 筛选与范围

默认只纳入 `.c`、`.cc`、`.cpp`、`.cxx`、`.c++`、`.h`、`.hh`、`.hpp` 和 `.hxx`。扫描器按完整目录段排除构建、缓存、第三方、生成、测试、示例与基准目录，并排除测试命名文件、常见生成文件、符号链接和越界路径。它保留仓库相对 POSIX 路径，不再按 basename 合并同名文件。

选取方法是有明确约束的目的性最大差异抽样，不是对 GitHub C++ 项目的随机抽样：
先按公开性、生产真实性、C++ 主体、许可、活动性及领域/规模互补性建立候选池，
再用统一源码入口与零构建 Parser 合同审查可复现性，最后仅用冻结阶段2结果检查
仓库是否适合进入 LLM 判断。star 与 fork 只作为背景，不是人气门槛；领域分类
用于检查覆盖与结果分层，不作为固定配额或算法路由。完整漏斗和合理性证据见
[数据集分类与选取方法](cpp-dataset-classification.md)。

“条件保留”用于以下情况：

- Catch2 是生产级测试框架，但其领域属于测试基础设施；
- concurrentqueue 与 magic_enum 的核心文件较少或高度集中于大型头文件；
- Envoy 与 React Native 使用固定稀疏克隆范围，不代表完整上游仓库；
- nlohmann/json 与 Yoga 的可靠 AST 字节覆盖率低于 0.5，使用时必须结合逐文件诊断；
- 上述限制不会导致文件静默丢弃，完整诊断仍保存在对应 `analysis.json` 和 `dataset.audit.json` 中。

GSL 被淘汰的原因不是质量或许可，而是核心公开头文件采用无扩展名命名；在排除 tests 后，它没有符合本轮标准扩展名约束的核心输入文件。

三个“阶段2后排除”项目均已通过 Parser 合同，排除原因来自聚类结果而不是
扩展名或许可：`entt` 与 `simdjson` 受聚合分发副本主导，`cpp-httplib` 几乎
不能形成跨文件簇。详细语义证据与筛选前后指标不在本报告重复，见
[聚类质量筛选报告](cpp-clustering-quality-screening.md)。

## 解析错误与不确定关系

优化后没有文件读取失败、解析器崩溃、JSON 失败、序列化失败、丢失文件、路径
冲突或越界。正式 23 仓诊断记录 391 个受预处理器/宏影响的文件、1,857 个其他
语法恢复文件和 1,399 个没有函数输出的文件；这些是文件分类计数，不是被静默
忽略的失败。三个类别均影响全部 23 个正式项目。逐类别项目列表保存在
`cpp-dataset-statistics.json`；筛选前 26 仓的原始诊断仍保存在历史产物中。

include 与 call 关系只按 AST 可直接观察的目标文本计数；namespace 与类型声明也保留确定性计数。跨翻译单元唯一符号绑定能力标记为 `unavailable`，循环依赖、宏条件分支和重载歧义不会被猜测成确定关系。该限制适用于全部正式项目。

## 可复现产物

- `cpp-dataset-selection.json`：人工维护的项目类型、标准、构建系统、许可判断、习语重点、阶段2筛选结论与限制。
- `cpp-dataset-manifest.json`：由实际固定仓库、GitHub 元数据快照、基线/最终解析产物生成的正式结构化清单，包含完整 commit 和逐项目复现命令。
- `cpp-dataset-statistics.json`：由正式项目实际解析产物重算的结构化统计。
- `cpp-dataset-classification.md`：正式 23 仓的主领域、相对分析复杂度、选取方法与分层实验建议。
- `cpp-dataset-project-audit.md`：逐项目结论、规模、解析质量和重点限制。
- `cpp-clustering-quality-screening.md`：三个阶段2后排除项目的聚类与语义证据，以及筛选前后指标。
- `../guides/cpp-dataset-parser-regression.md`：基线、Parser 修改、回归结果与确定性证据。
- `scripts/analyze_cpp_dataset.py`：单仓库分析、汇总、清单生成与清单—仓库—Parser 产物交叉校验入口。
- `outputs/dataset-experiment/baseline/<项目>/analysis.json`：修改 Parser 前的逐文件基线证据。
- `outputs/dataset-experiment/final/<项目>/analysis.json`：优化后的逐文件实体、候选、错误与路径证据。
- `outputs/dataset-experiment/final/<项目>/dataset.pkl`：标准四列 Parser 产物。
- `outputs/dataset-experiment/final/<项目>/dataset.audit.json`：覆盖全部扫描文件的 Parser v2 审计。

`repos/`、`outputs/` 和 `logs/` 按仓库约定保持 Git 忽略。纳入版本控制的清单保存完整 commit、远程 URL、固定 commit 的获取命令、稀疏路径和产物相对位置；在本地忽略产物被清理后，仍可按清单重建。

## 复算命令

以下命令均从仓库根目录运行：

```bash
.venv/bin/python -m scripts.analyze_cpp_dataset analyze-repo \
  --repo repos/cli11 \
  --project cli11 \
  --output outputs/dataset-experiment/final/cli11/analysis.json

.venv/bin/python -m src.parser.repo2data \
  --input repos \
  --project cli11 \
  --output outputs/dataset-experiment/final/cli11/dataset.pkl \
  --audit-output outputs/dataset-experiment/final/cli11/dataset.audit.json

.venv/bin/python -m scripts.analyze_cpp_dataset build-manifest \
  --selection docs/research/cpp-dataset-selection.json \
  --repositories-root repos \
  --metadata-root outputs/dataset-experiment/github-metadata \
  --search-snapshot outputs/dataset-experiment/github-search.json \
  --baseline-root outputs/dataset-experiment/baseline \
  --final-root outputs/dataset-experiment/final \
  --output docs/research/cpp-dataset-manifest.json \
  --statistics-output docs/research/cpp-dataset-statistics.json

.venv/bin/python -m scripts.analyze_cpp_dataset validate-manifest \
  --manifest docs/research/cpp-dataset-manifest.json
```

最后一条命令会读取并校验 23 个正式仓库及 3 个保留历史证据的仓库、对应的
26 份 `dataset.pkl` 与审计 JSON，并确认已淘汰的 GSL 本地路径不存在。它校验
commit、项目名、四列 Schema、相对路径唯一性、文件数与函数数一致性。

## 已知局限

- Tree-sitter 静态解析不解析完整编译条件、宏展开和跨翻译单元符号绑定；关系统计只记录可直接观察的 include、call、namespace 和类型出现，不猜测歧义绑定。
- 可靠 AST 字节覆盖率是诊断指标，不等同于语义正确率。宏密集、聚合头文件和平台条件源码会拉低该值。
- GitHub star、fork、描述和上游活跃时间是 2026-07-24 的快照，只用于候选背景，不是实验标签。
- Envoy 和 React Native 为明确记录的稀疏范围；研究结论不得表述为覆盖两个上游仓库的全部源码。
- 主领域是面向当前研究的操作性互斥标签，相对分析复杂度是当前 23 仓内的相对
  处理负荷；二者都不能替代具体项目语义、源码质量或真实软件复杂度判断。
- 清单的 Parser 统计来自阶段1，项目去留又结合了已冻结的阶段2 Embedding 与
  DBSCAN 结果；尚未执行正式 23 仓真实 LLM 判断或合成，也没有将代理指标冒充
  最终习语发现结果。
