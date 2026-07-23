# Parser 基线与优化对比报告

## 实验范围

实验日期为 2026-07-23，输入是本地 `repos/cpp` 的三个仓库快照。`FileScanner` 共选择 4,804 个文件：

| 项目 | 扫描文件数 |
|---|---:|
| Envoy | 2,924 |
| qBittorrent | 465 |
| React Native | 1,415 |
| 合计 | 4,804 |

基线在修改 Parser 前完整运行两次；优化版本在元数据压缩后完整运行两次。每组两次 pickle 的 SHA-256 均完全一致。没有下载模型、执行项目代码或调用 LLM。

规范产物位于：

- `outputs/parser-quality/baseline/dataset.pkl`
- `outputs/parser-quality/baseline/audit.json`
- `outputs/parser-quality/final/dataset.pkl`
- `outputs/parser-quality/final/dataset.audit.json`
- `outputs/parser-quality/final/audit.json`

这些路径受 Git 忽略，是本机可重复生成的实验产物，不是随源码提交的数据集。

## 复现命令

Parser 运行：

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos/cpp \
  --output outputs/parser-quality/final/dataset.pkl \
  --fragment-output outputs/parser-quality/final/fragments.pkl \
  --embedding-model unixcoder \
  --local-files-only
```

重复运行把输出改为 `dataset-repeat.pkl`。统计命令：

```bash
.venv/bin/python -m src.parser.audit \
  --source-root repos/cpp \
  --dataset outputs/parser-quality/final/dataset.pkl \
  --repeat-dataset outputs/parser-quality/final/dataset-repeat.pkl \
  --candidate-profile quality-v2 \
  --output outputs/parser-quality/final/audit.json
```

历史基线审计使用相同命令，但数据集路径指向 `baseline/`，并指定 `--candidate-profile legacy`。冻结基线数据集 SHA-256 为 `05acec5d266812793c78f436a1c4fee0b50c1ed7c3241aed0d0ab8269336da14`；最终数据集 SHA-256 为 `33cfb3224e295ba2564a3ca807da410bf9d71bfc04cf7188ae8e57a264ff9f30`。

Parser 长度报告可独立复现：

```bash
.venv/bin/python -m src.parser.token_length_audit \
  --dataset outputs/parser-quality/final/dataset.pkl \
  --output outputs/parser-quality/final/token-length-audit.json \
  --model unixcoder \
  --candidate-profile quality-v2 \
  --local-files-only
```

## 原始解析完整性

原始 Tree-sitter 树的统计不因候选优化而改写，因此它同时作为前后共同的输入质量事实：

| 指标 | 结果 |
|---|---:|
| 文件读取/解析成功 | 4,804 / 4,804（100%） |
| 无异常文件 | 3,341 |
| 含 `ERROR` 或 missing 的文件 | 1,463 |
| AST 节点 | 4,920,509 |
| 命名节点 | 2,969,541 |
| 原始 `function_definition` | 33,693 |
| `ERROR` | 11,376 |
| missing | 2,261 |
| 预处理节点 | 44,765 |
| 宏相关异常 | 702 |
| 非空白源码字节 | 19,889,854 |
| 可靠覆盖字节 | 19,499,611 |
| AST 覆盖率 | 98.0380% |
| 未覆盖字节 | 390,243 |
| 未覆盖连续区间 | 45,201 |

按项目的 AST 覆盖率为 Envoy 98.6567%、qBittorrent 97.2350%、React Native 96.2100%。React Native 的 `.h` 输入中包含 Objective-C/Objective-C++ 声明，Envoy 还包含宏生成接口；这些低覆盖文件不能全部解释为标准 C++ 语法退化。

## 函数根质量

| 指标 | 旧基线 | Parser v2 |
|---|---:|---:|
| 数据集文件 | 4,445 | 3,589 |
| 函数根 | 28,495 | 33,720 |
| 函数 AST 节点 | 4,449,866 | 3,686,548 |
| 真正 `function_definition` 根 | 19,421（68.16%） | 33,705（99.956%） |
| 可追溯不完整函数根 | 0 | 15 |
| 类节点误作函数根 | 5,074 | 0 |
| 函数声明器误作函数根 | 2,445 | 0 |
| 模板壳误作函数根 | 1,555 | 0 |

旧数据集包含更多文件，是因为类、声明器和模板壳会使本来没有函数定义的文件通过过滤。v2 的 1,215 个未入主 pickle 文件中，绝大多数没有可保存的函数定义；所有文件仍存在于审计侧车。v2 还从七个原始树未识别出函数定义的文件中恢复了可追溯函数边界。

逐文件集合比对确认：原始树含至少一个 `function_definition` 的 3,582 个文件
全部进入 v2 数据集，整体遗漏数为 0；另有七个原始计数为零的文件通过恢复进入。

v2 会把合法的局部类内联方法也保存为独立函数根，同时保留外层函数的完整
AST。原始函数定义计数仍不是人工标注的召回率：容错树可能包含错误嵌套定义，
只能用于检测大规模遗漏。

## 宏与条件编译恢复

预处理影子策略在 189 个文件上满足保守启用条件：

| 项目 | 启用恢复的文件 |
|---|---:|
| Envoy | 41 |
| qBittorrent | 24 |
| React Native | 124 |

这些文件的 `ERROR + missing` 总数从 1,922 降至 1,413，减少 26.48%；
共记录 55 个由影子或边界恢复改变的函数范围。八个文件的选中函数数高于
原始树。恢复文件的原始函数总数为 2,343，最终选中 2,360；净增 17 个，
但数量不是独立质量目标，恢复还会用多个真实小函数替换宏污染的巨大伪边界。

代表性案例 `envoy/envoy/upstream/upstream.h`：

| 指标 | 原始树 | 影子恢复 |
|---|---:|---:|
| `ERROR` | 164 | 127 |
| missing | 12 | 3 |
| 函数定义/选中函数 | 11 | 19 |
| AST 覆盖率 | 2.20% | 82.95% |

最终保存 19 个函数边界，其中 9 个带恢复来源；旧树曾把 1,200 余行类区域吞并为伪函数。

## 原始源码映射

| 指标 | 旧基线 | Parser v2 |
|---|---:|---:|
| AST extent 可解析 | 100% | 100% |
| AST `code_snippet` 与原始字节完全一致 | 98.0347% | 100% |
| AST 节点显式字节范围 | 0% | 100% |
| 函数根显式文件身份 | 0% | 100% |
| quality-v2 候选显式文件身份与范围 | 不适用 | 100% |
| quality-v2 候选原始字节精确匹配 | 不适用 | 100% |

旧实现会删除注释、空行并 `.strip()`，因此只能重建一个变换后的版本。v2 的
3,686,548 个 AST 节点全部逐字节匹配原始文件。为控制 pickle 体积，文件身份
只存于 33,720 个函数根，并在候选输出时继承；这不是映射缺失。

## 候选片段质量

旧候选和 v2 候选的选择规则不同。下表用于描述最终输入分布，而不是宣称数量越多越好：

| 类型 | 旧数量 | v2 数量 | 旧中位行数 | v2 中位行数 | 旧 P95 行数 | v2 P95 行数 | 旧长片段 | v2 长片段 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 函数 | 652 | 33,203 | 7 | 4 | 68.45 | 37 | 27 | 380 |
| 基础区域 | 3,451 | 17,083 | 6 | 5 | 30 | 28 | 25 | 90 |
| 语句 | 17,638 | 43,608 | 7 | 1 | 40 | 3 | 214 | 1 |
| Def-Use 语义区域 | 0 | 3,668 | — | 13 | — | 50 | — | 3 |

旧“语句”中有 11,172 个 `compound_statement` 和 6,341 个 `field_declaration`，只有 119 个声明和 1 个返回语句；最长达 740 行。v2 语句来自真实语句边界，最长 80 行、3,780 字节，99.998% 通过保守结构完整检查。

v2 基础区域的最长值上升，是因为旧选择规则漏掉大量真实 `if`、`switch`、
Lambda 和嵌套区域。v2 不删除这些可追溯大区域，而是为适合的长函数或区域
额外生成有界语义核心。3,668 个有效语义候选中位数 13 行、569 字节，
完全相同内容重复率 1.20%，全部精确回映射。

候选结构完整率和映射率：

| 类型 | 旧结构完整率 | v2 结构完整率 | 旧精确映射率 | v2 精确映射率 |
|---|---:|---:|---:|---:|
| 函数 | 77.147% | 99.967% | 51.380% | 100% |
| 区域 | 99.073% | 99.947% | 71.342% | 100% |
| 语句 | 78.722% | 99.998% | 54.575% | 100% |
| Def-Use 语义区域 | — | 99.918% | — | 100% |

少量 v2 候选未通过“原始树结构完整”口径，主要是影子恢复的候选与原始树 missing 位置相交；它们的选中 AST 和映射仍有明确恢复标记。

quality-v2 总候选数为 97,562，是旧 21,741 的 4.49 倍。每函数的基础区域
和语句均有上限，但真实函数根不再因直接子节点不足而被大规模漏掉。下游完整
嵌入成本会相应增加，见风险文档。

## 模型长度与 Parser 阶段降级

UniXcoder 官方 encoder-only 示例使用 `max_length=512`，本项目因此把包含特殊
token 的 512 作为 Parser 片段合同。实际 tokenizer 审计结果：

| 类型 | 原始候选 | P50 token | P95 token | 最大 token | 超限 |
|---|---:|---:|---:|---:|---:|
| 函数 | 33,203 | 49 | 425 | 12,724 | 1,237 |
| 基础区域 | 17,083 | 53 | 326 | 7,592 | 341 |
| 语句 | 43,608 | 13 | 50 | 1,108 | 25 |
| Def-Use 区域 | 3,668 | 158 | 582 | 1,191 | 278 |
| 合计 | 97,562 | 27 | 303 | 12,724 | 1,881（1.9280%） |

`src.parser.fragment_builder` 在 Parser 阶段把超长函数降级为符合预算的基础区域、
Def-Use 或语句，并在区域超限时继续选择后续合格区域。它不生成摘要或拼接不连续
代码。结果如下：

| 类型 | model-ready 数量 | 最大 token | 超限 |
|---|---:|---:|---:|
| 函数 | 31,966 | 512 | 0 |
| 基础区域 | 17,078 | 512 | 0 |
| 语句 | 43,605 | 509 | 0 |
| Def-Use 区域 | 3,390 | 512 | 0 |
| 合计 | 96,039 | 512 | 0 |

1,310 条超长函数记录中，1,225 条具有至少一种后备，85 条没有合格后备。
最终 1,881 条被排除的去重原候选全部进入 `fragment_rejections`。96,039 条
model-ready 片段逐字节回映射率为 100%，`length_control.decision_stage` 全部
为 `parser`。两次 `fragments.pkl` SHA-256 均为
`4e9bcc98f27d0c12f61719bd71cce80729ff34969af0920f9f12cc513e41e0b2`。

embedding 现在拒绝直接读取四列 AST 数据集，要求模型名、profile 和预算与
Parser 片段一致，并以 `truncation=False` 编码。它的重新计数只是防御性合同
校验，不再决定如何切分。详细依据和拒绝 Schema 见
[C++ Adapter 与模型输入治理](cpp-adapter-and-model-input.md)。

## 程序分析增强的选择依据

实施了局部 Def-Use 语义切片，未在本轮实现完整 CFG、SSA、别名或跨过程调用图，原因是：

1. 基线最突出的问题是函数边界错误、旧“语句”不是语句以及长函数缺少可用核心；
2. 局部 Def-Use 能直接把定义、使用和核心调用连接到连续原始源码片段；
3. 它不需要编译数据库，不执行不可信项目代码，对模板和不完整工程仍可运行；
4. 每条边、共享符号、语句闭包和回映射范围都可审计；
5. 全量三个项目均产生了语义片段：Envoy 2,425、qBittorrent 751、React Native 492 个有效 quality-v2 候选。

## 性能与确定性

| 指标 | 旧基线 | Parser v2 | 变化 |
|---|---:|---:|---:|
| 单次全量运行 | 23.16 秒 | 34.89 秒 | +50.63% |
| 峰值 RSS | 3.185 GB | 4.047 GB | +27.07% |
| pickle 大小 | 578,991,920 字节 | 576,492,303 字节 | -0.43% |
| 重复运行 SHA-256 | 一致 | 一致 | 无退化 |

性能开销来自第二次条件解析、逐字节异常覆盖和语义切片。函数根元数据压缩后，产物体积没有随新增证据膨胀。

在冻结 AST 数据集上，单独构建 UniXcoder model-ready 片段耗时 23.56 秒，
产物约 46 MB；该开销发生在 Parser 阶段且只加载 tokenizer。完整 embedding
模型推理尚未运行，因此不能把此数值解释为端到端嵌入耗时。

## 结论

本轮提升不是“让 Tree-sitter 原始覆盖率虚增”，而是把异常显式化、恢复一部分共性宏边界、消除伪函数根、恢复原始源码，并用可追溯 Def-Use 关系为长代码生成内聚核心。主四列 Schema、三种粒度和历史 `ast_num` 均保留；下游默认使用 quality-v2，也可显式选择 `legacy` 读取历史数据。

最终 `pip check`、编译检查、54 项离线测试、相关模块导入和 CLI 帮助入口
全部通过。唯一环境提示是用户级 pip 缓存目录不可写；pip 自动禁用缓存后确认
不存在损坏依赖。UniXcoder tokenizer 已用于全量 Parser 长度审计；完整模型推理
和真实 LLM 不属于本轮适用验证，未运行。

代表性文件与片段见[Parser 产物审计](parser-artifact-audit.md)，失败类型和未解决问题见[Parser 风险与限制](parser-risks.md)。
