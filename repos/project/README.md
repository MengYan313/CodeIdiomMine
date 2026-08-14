# Project Corpus

## 研究单位

Project Corpus 以单个完整 C++ 仓库为独立实验分组，用于研究同一工程内部反复出现、受项目架构与编码约定影响的习语。15 个仓库分别执行扫描、训练和测试，不跨仓合并候选、向量或聚类。

## 选择方法

从原有 23 个候选仓库中，综合考虑工程流行度、统一过滤后的有效源码规模，以及已有聚类所反映的有效簇、跨文件支持、簇内一致性、项目特定性与污染率。已有聚类只用于冻结名单，不作为新数据集的实验结果。

入选仓库须具有完整工作树和足够的第一方生产源码。统一排除 vendored 依赖、生成代码、amalgamated/single-header 发行文件及可确认的源码副本；过滤结果记录在本地 `dataset-manifest.json`，不改变仓库源码。

完整工作树中的非清单文件只用于保留项目上下文，不属于实验输入。正式运行必须按 `dataset-manifest.json` 的 `files[].path` 取文件，不能重新递归扫描整个仓库替代冻结清单。

## 正式分组

| 分组 | 上游仓库 | 文件 | eLOC | train 文件/eLOC | test 文件/eLOC |
|---|---|---:|---:|---:|---:|
| `btop` | `aristocratos/btop` | 33 | 17,241 | 20 / 12,044 | 13 / 5,197 |
| `catch2` | `catchorg/Catch2` | 240 | 17,060 | 133 / 11,940 | 107 / 5,120 |
| `drogon` | `drogonframework/drogon` | 251 | 44,987 | 144 / 31,495 | 107 / 13,492 |
| `envoy` | `envoyproxy/envoy` | 4,063 | 440,438 | 2,214 / 308,307 | 1,849 / 132,131 |
| `fmt` | `fmtlib/fmt` | 19 | 13,646 | 10 / 9,561 | 9 / 4,085 |
| `leveldb` | `google/leveldb` | 96 | 12,108 | 53 / 8,476 | 43 / 3,632 |
| `libzmq` | `zeromq/libzmq` | 280 | 37,797 | 158 / 26,453 | 122 / 11,344 |
| `mosh` | `mobile-shell/mosh` | 64 | 9,657 | 38 / 6,760 | 26 / 2,897 |
| `ninja` | `ninja-build/ninja` | 93 | 12,692 | 48 / 8,882 | 45 / 3,810 |
| `polybar` | `polybar/polybar` | 221 | 22,330 | 122 / 15,631 | 99 / 6,699 |
| `qbittorrent` | `qbittorrent/qBittorrent` | 526 | 74,241 | 280 / 51,968 | 246 / 22,273 |
| `spdlog` | `gabime/spdlog` | 100 | 8,136 | 55 / 5,695 | 45 / 2,441 |
| `taskflow` | `taskflow/taskflow` | 70 | 14,107 | 40 / 9,874 | 30 / 4,233 |
| `yaml-cpp` | `jbeder/yaml-cpp` | 93 | 12,708 | 49 / 8,894 | 44 / 3,814 |
| `yoga` | `facebook/yoga` | 99 | 11,216 | 51 / 7,852 | 48 / 3,364 |
| **合计** | **15 个仓库** | **6,248** | **748,364** | **3,415 / 523,832** | **2,833 / 224,532** |

Envoy 在本阶段补全了原 shallow partial sparse checkout 的缺失路径；工作树现已完整且保持原提交，因此其旧实验产物已删除，等待后续重新实验。

## 未入选仓库

| 候选 | 主要理由 |
|---|---|
| `cereal` | 头文件模板与 archive 适配代码集中，跨文件聚类证据弱于入选组。 |
| `cli11` | Project 核心范围较小，single-header 与示例副本容易主导重复。 |
| `concurrentqueue` | 核心文件过少，内联模板集中，难以形成稳定的跨文件测量。 |
| `json` | header-only 与 single-header 发行形态带来较高源码副本污染。 |
| `magic_enum` | 有效源码规模过小，模式高度集中于单一模板头文件。 |
| `react-native` | 原本地输入是 `ReactCommon` 稀疏范围，不满足完整 Project 合同。 |
| `tomlplusplus` | header-only/单头结构明显，已有有效簇产量偏低。 |
| `uwebsockets` | 核心规模较小，且与外部 `uSockets` 的实现边界紧密。 |

本地额外候选 `cpp-httplib`、`entt`、`simdjson` 不属于原 23 仓选择池，也未进入正式 Project Corpus。

## 数据划分

每个仓库内部将同 stem 的头文件、实现文件和平台变体组成不可分割的文件组，再按 eLOC 确定性分配，目标为约 70% `train`（训练集）、30% `test`（测试集）。正式习语只能从 `train` 侧发现和冻结，`test` 侧用于检验项目内跨文件复现。
