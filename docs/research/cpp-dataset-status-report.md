# C++ 实验数据集现状报告

## 结论

本轮于 2026-07-24 完成候选搜索、许可核验、固定版本、基线解析、通用 Parser 优化、全量重解析和产物一致性校验。最终数据集包含 26 个公开 GitHub C++ 项目，其中 17 个“保留”、9 个“条件保留”；另有 1 个候选 `microsoft/GSL` 被“淘汰”。26 个正式固定版本仓库现已直接平铺在 `repos/`；旧的三项目快照、重复 smoke 副本和已淘汰的 GSL 本地副本均已删除。

本轮检查了 27 个候选，其中 24 个是新增候选、3 个是原有种子项目，未超过 35 个新增候选的搜索上限。达到 26 个许可明确、领域和规模足够多样的正式项目后停止扩展。

## 核心统计

| 指标 | 正式数据集 |
|---|---:|
| 项目数 | 26 |
| 固定种子项目数 | 3 |
| 核心源码文件数 | 7,940 |
| 有效代码行数 | 1,290,508 |
| 文件级解析成功率 | 100% |
| 选中函数数 | 102,574 |
| 习语候选数 | 237,845 |
| 可靠 AST 字节覆盖率 | 78.52% |
| 解析失败文件数 | 0 |
| 重复仓库相对路径 | 0 |
| 越界路径 | 0 |
| 符号链接输入 | 0 |

候选按层级分为：函数 80,930 个、区域 41,596 个、局部 Def-Use 语义切片 9,254 个、语句 106,065 个。实体计数、错误分类、构建系统、许可、C++ 标准和习语覆盖的完整分布见 `cpp-dataset-statistics.json`。

## 数据集组成

正式项目覆盖 C++11、C++14、C++17 与 C++20；包含命令行工具、桌面应用、网络代理、Web 框架、存储系统、消息通信、布局引擎，以及格式化、日志、序列化、解析器、并发、ECS 和任务图等基础库。构建系统元数据覆盖 CMake、Make、Meson、Bazel、Buck 与 Autotools，但本轮从未执行目标仓库的构建、安装、代码生成、测试或其他脚本。

许可分布为 MIT 13 个、Apache-2.0 5 个、BSD-3-Clause 3 个，以及 BSD-2-Clause、BSL-1.0、GPL-2.0-or-later、GPL-3.0 和 MPL-2.0 各 1 个。每个项目的 SPDX 判断、根目录许可文件路径及文件 SHA-256 均记录在结构化清单中。公开可访问不等于任意再分发；后续发布源码快照或派生产物时仍须逐项目遵守许可和署名条件。

GitHub 元数据快照中，正式项目 star 中位数为 15,999，范围为 2,107～126,249；fork 中位数为 1,834，范围为 206～25,188。26 个项目均未归档，且在快照日前 365 天内有上游 push；最近 push 距快照日的中位数为 3 天、最大值为 302 天。star、fork 和时间是候选质量背景，不参与 Parser 指标计算。

规模分布为：

- 4 个项目有 2,000～9,999 行有效代码；
- 20 个项目有 10,000～99,999 行；
- Envoy 与 simdjson 超过 100,000 行；
- 文件数中位数为 100，3 个项目少于 10 个核心文件，2 个项目至少 1,000 个核心文件。

## 筛选与范围

默认只纳入 `.c`、`.cc`、`.cpp`、`.cxx`、`.c++`、`.h`、`.hh`、`.hpp` 和 `.hxx`。扫描器按完整目录段排除构建、缓存、第三方、生成、测试、示例与基准目录，并排除测试命名文件、常见生成文件、符号链接和越界路径。它保留仓库相对 POSIX 路径，不再按 basename 合并同名文件。

“条件保留”用于以下情况：

- Catch2 是生产级测试框架，但其领域属于测试基础设施；
- concurrentqueue、cpp-httplib 与 magic_enum 的核心文件较少或高度集中于大型头文件；
- Envoy 与 React Native 使用固定稀疏克隆范围，不代表完整上游仓库；
- nlohmann/json、simdjson 与 Yoga 的可靠 AST 字节覆盖率低于 0.5，使用时必须结合逐文件诊断；
- 上述限制不会导致文件静默丢弃，完整诊断仍保存在对应 `analysis.json` 和 `dataset.audit.json` 中。

GSL 被淘汰的原因不是质量或许可，而是核心公开头文件采用无扩展名命名；在排除 tests 后，它没有符合本轮标准扩展名约束的核心输入文件。

## 解析错误与不确定关系

优化后没有文件读取失败、解析器崩溃、JSON 失败、序列化失败、丢失文件、路径冲突或越界。诊断仍记录 611 个受预处理器/宏影响的文件、1,881 个其他语法恢复文件和 1,566 个没有函数输出的文件；这些是文件分类计数，不是被静默忽略的失败。预处理器/宏类别影响全部 26 个正式项目，其他语法恢复影响除 cpp-httplib 外的 25 个项目，无函数输出影响除 cpp-httplib 外的 25 个项目。逐类别项目列表保存在 `cpp-dataset-statistics.json`。

include 与 call 关系只按 AST 可直接观察的目标文本计数；namespace 与类型声明也保留确定性计数。跨翻译单元唯一符号绑定能力标记为 `unavailable`，循环依赖、宏条件分支和重载歧义不会被猜测成确定关系。该限制适用于全部正式项目。

## 可复现产物

- `cpp-dataset-selection.json`：人工维护的项目类型、标准、构建系统、许可判断、习语重点、筛选结论与限制。
- `cpp-dataset-manifest.json`：由实际固定仓库、GitHub 元数据快照、基线/最终解析产物生成的正式结构化清单，包含完整 commit 和逐项目复现命令。
- `cpp-dataset-statistics.json`：由正式项目实际解析产物重算的结构化统计。
- `cpp-dataset-project-audit.md`：逐项目结论、规模、解析质量和重点限制。
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

最后一条命令会读取 26 个正式本地 Git 仓库、26 份正式 `dataset.pkl`、26 份审计 JSON 和最终分析结果，并确认已淘汰项目的本地路径不存在。它校验 commit、项目名、四列 Schema、相对路径唯一性、文件数与函数数一致性。

## 已知局限

- Tree-sitter 静态解析不解析完整编译条件、宏展开和跨翻译单元符号绑定；关系统计只记录可直接观察的 include、call、namespace 和类型出现，不猜测歧义绑定。
- 可靠 AST 字节覆盖率是诊断指标，不等同于语义正确率。宏密集、聚合头文件和平台条件源码会拉低该值。
- GitHub star、fork、描述和上游活跃时间是 2026-07-24 的快照，只用于候选背景，不是实验标签。
- Envoy 和 React Native 为明确记录的稀疏范围；研究结论不得表述为覆盖两个上游仓库的全部源码。
- 本轮完成的是第一阶段静态解析与候选规模审计，没有执行 embedding、DBSCAN、真实 LLM 判断或合成，也没有将统计结果冒充最终习语发现结果。
