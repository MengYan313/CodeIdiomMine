# Parser 代表性产物审计

## 审计方法

本报告交叉检查三类证据：

1. `outputs/parser-quality/final/dataset.audit.json` 的逐文件原始树与恢复记录；
2. `outputs/parser-quality/final/audit.json` 的全量映射和候选分布；
3. `dataset.pkl` 中候选的文件身份、字节范围、源码和 `dependency_summary`；
4. `fragments.pkl` 的 token 长度、Parser 降级、拒绝记录和原文映射。

抽样覆盖宏、条件编译、模板、Concept、Lambda、复杂声明、现代 C++ 和不完整代码。真实仓库样本用于检查规模和项目差异；合成样本用于固定边界条件并纳入离线回归测试。

## 真实文件审计

| 文件 | 主要场景 | 原始状态 | v2 产物 |
|---|---|---|---|
| `envoy/envoy/upstream/upstream.h` | 大量宏、条件编译、类内方法 | 164 个 `ERROR`、12 个 missing、覆盖率 2.20%、11 个原始函数定义 | 影子恢复后 19 个函数边界；18 个干净函数候选、1 个区域、9 个语句；全部候选精确回映射 |
| `qBittorrent/src/base/3rdparty/expected.hpp` | 第三方模板、宏、复杂声明 | 240 个 `ERROR`、82 个 missing、309 个原始函数定义 | 311 个可追溯函数根；242 个干净函数、19 个区域、207 个语句和 2 个 Def-Use 核心 |
| `qBittorrent/src/base/algorithm.h` | Concept、`requires`、模板 | 0 个 `ERROR`、0 个 missing、100% 覆盖 | 2 个真实函数、1 个区域、4 个语句；没有把 Concept 或模板壳伪装成函数 |
| `react-native/.../RuntimeTargetConsole.cpp` | Lambda、现代声明、较长方法 | 0 个 `ERROR`、0 个 missing、16 个函数 | 16 个函数、16 个区域、19 个语句、3 个 Def-Use 核心；语义片段共享 `it`、`label` 等局部依赖 |

`upstream.h` 的恢复不会声称宏已展开。原始 41,644 个未可靠覆盖字节和所有异常仍保存在侧车；影子树只负责提供更合理的函数边界。

## 语义核心示例

以下片段均直接来自原始文件的连续字节范围。

Envoy `file_descriptor_generator.cc:92-95`：

```cpp
google::protobuf::io::CodedOutputStream output(output_stream);
output.WriteString(contents.str());
output.Trim();
return !output.HadError();
```

切片以 `output` 的定义—使用链连接构造、写入、收尾和错误返回。它是四行完整操作序列，不需要携带所在长函数的其他准备代码。

qBittorrent `application.cpp:260-264`：

```cpp
const auto portableProfilePath =
    Path(QCoreApplication::applicationDirPath()) / DEFAULT_PORTABLE_MODE_PROFILE_DIR;
const bool portableModeEnabled =
    m_commandLineArgs.profileDir.isEmpty() && Utils::Fs::isDir(portableProfilePath);
const Path profileDir =
    portableModeEnabled ? portableProfilePath : m_commandLineArgs.profileDir;
Profile::initInstance(profileDir, m_commandLineArgs.configurationName,
                      m_commandLineArgs.relativeFastresumePaths || portableModeEnabled);
```

共享符号为 `portableProfilePath`、`portableModeEnabled` 和 `profileDir`，闭包内聚度为 1.0。片段包含配置路径的定义链及最终初始化调用，语义边界比单条声明或完整函数更清楚。

React Native `RCTConversions.h:75-84` 的语义片段围绕 `result` 聚合多项 accessibility flag，10 行、458 字节、内聚度 1.0。该例说明同一算法即使主要由条件与复合赋值组成，也能通过稳定的定义—使用关系形成核心。

全量有效 Def-Use 候选分布：

| 项目 | 数量 |
|---|---:|
| Envoy | 2,425 |
| qBittorrent | 751 |
| React Native | 492 |
| 合计 | 3,668 |

其中位数为 13 行、569 字节；P95 为 50 行、2,135 字节；最大 80 行、
3,962 字节。所有片段的文件身份、字节范围和源码匹配率均为 100%。

## 模型输入产物审计

针对 `microsoft/unixcoder-base` 的 512-token Parser 合同，全量原始候选有
1,881 条超限。`fragments.pkl` 最终保存 96,039 条 model-ready 片段，其中函数
31,966 条、基础区域 17,078 条、语句 43,605 条、Def-Use 区域 3,390 条。
最大输入为 512 tokens，超限为 0，原始文件逐字节匹配为 96,039/96,039。

每条合格片段的 `length_control.decision_stage` 都是 `parser`；每条超限原候选
都在 `fragment_rejections` 中保存文件身份、函数和候选范围、实际 token 数、
预算、动作及后备策略。两次独立构建的 SHA-256 均为
`4e9bcc98f27d0c12f61719bd71cce80729ff34969af0920f9f12cc513e41e0b2`。

长函数合成回归中，完整函数超过 40 个假 tokenizer tokens，因此函数候选在
Parser 阶段被排除；资源句 Def-Use 核心和两条短语句仍进入片段产物，均带
`degraded_from=function`。这验证的不是 embedding 截断，而是 embedding 开始前
已经完成可追溯降级。

## 合成边界回归

`tests/parser/test_cpp_parser.py` 固定了以下场景：

| 场景 | 验证点 |
|---|---|
| 模板、Concept、类内方法、局部类和 Lambda | 输出三个真实函数定义；声明与模板壳不成为函数根；Lambda 保持为区域 |
| 字符串中的 `//`、注释和宏调用 | 原始文本不被注释正则破坏；URL、注释和宏调用逐字保留 |
| 条件编译跨越控制块 | 等长影子恢复消除 missing；输出仍包含原始 `#if/#endif`，范围不漂移 |
| 未闭合函数 | 文件不失败；异常、missing 和未覆盖区间可追溯 |
| 长函数的资源操作链 | `open_resource`、`read_value(handle)`、`close_resource(handle)` 由 `handle` 的 Def-Use 边组成连续核心 |
| 超长误解析语句 | quality-v2 拒绝超过 4,000 字节或 80 行的语句候选 |
| 超长函数的模型输入降级 | Parser 片段构建排除函数根，保留合格 Def-Use/语句，并写入长度和拒绝证据 |
| 单文件失败隔离和无函数头文件 | 四列数据集不变；侧车仍包含每个扫描文件 |
| 重复运行与全量审计 | 小数据集两次 pickle 字节一致；审计映射率与实际数据一致 |

`tests/evaluation/test_metrics.py` 另验证 `semantic_slice` 可按字节范围映射回函数 AST 节点覆盖；历史数据仍走旧候选评价路径。

## 失败样本审计

全局仍有 390,243 个非空白字节位于原始 `ERROR` 子树、missing 或未可靠叶节点覆盖范围。低覆盖样本主要分为：

- 宏生成大段声明或接口，例如 Envoy `header_map.h`、`udp_proxy_filter.h`；
- 扩展名为 `.h` 但实际包含 Objective-C/Objective-C++ 声明，例如 React Native 的若干 `RCT*.h`；
- 只含 Go/C 绑定占位文本的极短 `api.h`；
- 不完整或依赖生成步骤的源码。

这些文件不会静默消失：它们的原始覆盖率、异常位置、未覆盖字节区间、恢复尝试和最终函数数都在侧车中。对于没有可信函数边界的文件，主 pickle 可以为空，而审计记录必须存在。

完整失败分类与后续方案见[Parser 风险与限制](parser-risks.md)。
