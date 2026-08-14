# Library Corpus

## 研究单位

Library Corpus 以目标 C++ 库为实验分组，聚合多个外部客户端仓库中实际使用该库 API 的 C/C++ 文件：

```text
repos/library/<library>/<owner>__<client-repo>/<original/relative/path>
```

目标库实现、其 fork/mirror、客户端中的 vendored 副本和复制的官方示例均不属于语料。一个客户端文件可以使用多个目标库并进入多个分组，但其规范 `owner/repo` 身份和 `train`/`test` 归属在全部分组中保持一致。身份比较与全局划分查表使用小写 `owner/repo`；文件记录和目录名保留 GitHub 展示大小写。

本地 `dataset-manifest.json` 是文件身份、客户端边界和划分的唯一正式入口。实验时按清单读取 `repos/library/<target>/<owner>__<repo>/<path>`；不能重新套用通用目录扫描器，因为本语料明确允许客户端手写 test/example。

## 候选仓库

候选范围冻结于 `T0 = 2026-08-13T16:54:48Z`，活动窗口为此前 60 个月。候选来自 GitHub 公共仓库的默认分支，并统一满足：

- 非 fork、archive、mirror 或 template；
- 活动窗口内存在默认分支提交，默认分支可读取；
- 至少 1 个 fork 或 10 stars；本次索引候选均满足 10 stars；
- license 可识别；
- 统一过滤后至少包含 5 个有效 C/C++ 文件。

15 个目标采用相同候选范围、时间窗口、仓库门槛、路径过滤和规模控制，不针对单个库改变标准。

## API 使用判定

文件必须在移除注释后同时具有目标 include 和明确的类型、namespace、调用或宏证据。只有 include、构建依赖或文字提及不算实际使用。

| 目标 | include 证据 | API 使用证据示例 |
|---|---|---|
| `abseil` | `absl/<component>.h` | `absl::Status/StatusOr`、strings、hash containers、`Mutex/Time/Span/Cleanup` |
| `boost-asio` | `boost/asio*` | `boost::asio::*` 或明确的 event-loop/networking API |
| `catch2` | `catch2/*` 或 `catch.hpp` | `TEST_CASE`、`SCENARIO`、`REQUIRE`、`CHECK`、`SECTION` |
| `cli11` | `CLI/*.hpp` | `CLI::App/Option/Validator` 或 `CLI11_PARSE` |
| `eigen` | `Eigen/*` 或 `eigen3/Eigen/*` | `Eigen::Matrix/Array/Map/Ref/Quaternion/Sparse` |
| `fmt` | `fmt/*` | `fmt::format/print/format_to/join/formatter` |
| `glm` | `glm/*` | `glm::vec/mat/quat`、变换、投影或向量运算 |
| `googletest` | `gtest/*` 或 `gmock/*` | `TEST*`、`EXPECT_*`、`ASSERT_*`、`MOCK_METHOD`、`testing::*` |
| `grpc` | `grpcpp/*` | context、status、builder、channel、reader/writer API |
| `nlohmann-json` | `nlohmann/json*.hpp` | `nlohmann::json/ordered_json`、转换宏或 `_json` |
| `opencv` | `opencv2/*` | 明确的 `cv::` image/video/geometry/dnn/cuda/ml API |
| `pybind11` | `pybind11/*` | `PYBIND11_MODULE`、`pybind11::*` 或明确的 `py::*` binding API |
| `rocksdb` | `rocksdb/*` | `rocksdb::DB/Options/Status/Slice/WriteBatch/Iterator` |
| `spdlog` | `spdlog/*` | `spdlog::*` 或 `SPDLOG_*` 日志宏 |
| `yaml-cpp` | `yaml-cpp/*` | `YAML::Node/Load/Emitter/convert/Exception` |

## 文件过滤与规模控制

准入扩展名为 `.c/.cc/.cpp/.cxx/.c++/.h/.hh/.hpp/.hxx`。文件须由当前 tree-sitter-cpp 解析器有效解析，AST coverage 不低于 0.50。优先选择第一方 production 文件，允许客户端自有的手写 test 和 example。

统一排除 third-party/vendor/external/deps/dependencies/libs/libraries/submodule、build/generated、protobuf/gRPC 生成文件、moc/ui 文件、single-header/amalgamated 文件和递归目标源码路径。规范化源码直接比较用于去除文件副本，不保存内容哈希；未标记重复项目以源码集合重合度识别。

每个客户端最多保留 50 个文件。超过上限时按解析质量、API 证据强度、错误数及 production/test/example 优先级确定性排序。每个目标最多 5,000 个文件，超限时以客户端轮转方式控制大型仓库支配效应。

正式冻结前对全部目标执行同一轮验收过滤：再次排除 `deps/3rd/Pods` 等变体路径、嵌入式依赖与目标源码树、跨目标混入的其他库源码副本、框架内复制头文件、amalgamated 文件、复制的外部示例，以及文件前 25 行带明确生成标头的代码。该轮从初筛的 31,066 个文件成员中剔除 1,125 个；手写 test、客户端自己的 example 和实际执行 API 的 package test 不因目录类型而单独排除。

## 最终分组

| 目标 | 客户端 | 文件 | eLOC | train 客户端/文件/eLOC | test 客户端/文件/eLOC |
|---|---:|---:|---:|---:|---:|
| `abseil` | 139 | 3,537 | 1,018,059 | 99 / 2,526 / 723,600 | 40 / 1,011 / 294,459 |
| `boost-asio` | 122 | 877 | 205,950 | 85 / 567 / 141,735 | 37 / 310 / 64,215 |
| `catch2` | 138 | 2,766 | 677,775 | 97 / 2,246 / 460,757 | 41 / 520 / 217,018 |
| `cli11` | 44 | 238 | 59,089 | 31 / 171 / 41,361 | 13 / 67 / 17,728 |
| `eigen` | 275 | 3,460 | 646,633 | 192 / 2,398 / 451,145 | 83 / 1,062 / 195,488 |
| `fmt` | 215 | 3,467 | 1,537,267 | 152 / 2,417 / 1,075,803 | 63 / 1,050 / 461,464 |
| `glm` | 98 | 1,395 | 458,381 | 67 / 956 / 318,412 | 31 / 439 / 139,969 |
| `googletest` | 379 | 4,837 | 1,316,718 | 269 / 3,578 / 915,960 | 110 / 1,259 / 400,758 |
| `grpc` | 60 | 518 | 113,753 | 44 / 355 / 80,018 | 16 / 163 / 33,735 |
| `nlohmann-json` | 226 | 2,306 | 815,279 | 159 / 1,703 / 566,211 | 67 / 603 / 249,068 |
| `opencv` | 207 | 2,496 | 478,601 | 145 / 1,724 / 330,354 | 62 / 772 / 148,247 |
| `pybind11` | 253 | 1,980 | 341,341 | 178 / 1,467 / 239,604 | 75 / 513 / 101,737 |
| `rocksdb` | 37 | 306 | 126,870 | 26 / 204 / 88,892 | 11 / 102 / 37,978 |
| `spdlog` | 131 | 1,217 | 351,797 | 90 / 890 / 245,999 | 41 / 327 / 105,798 |
| `yaml-cpp` | 112 | 541 | 153,657 | 78 / 364 / 107,247 | 34 / 177 / 46,410 |
| **合计** | **1,257 个唯一客户端** | **29,941** | **8,301,170** | **881 / 21,566 / 5,787,098** | **376 / 8,375 / 2,514,072** |

CLI11 与 RocksDB 低于预期的 500 文件，但仍具有 44 和 37 个独立客户端。为避免根据采集结果事后替换目标，本研究明确接受两组为小样本分组，保持全部统一规则，并在组宏平均之外单独报告其不确定性。Googletest 在规模控制阶段达到 5,000 文件上限，经最终验收过滤后保留 4,837 个文件。

## 数据划分

客户端仓库是不可分割的划分单位。对最终 1,257 个规范 `owner/repo` 保留统一的全局分配，其中 881 个属于 `train`、376 个属于 `test`。各目标和全局均接近 70/30，同一客户端使用多个目标库时始终位于同一侧，从而避免跨库数据泄漏。最终验收只删除违规文件和空客户端，不重排剩余客户端。
