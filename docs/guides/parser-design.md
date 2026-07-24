# Parser v2 设计与使用

## 目标与边界

Parser v2 继续执行同一条主链路：

```text
原始 C++ 源码
  -> Tree-sitter C++ AST
  -> 基于 AST 的函数、区域、语句与局部 Def-Use 分析
  -> Parser 阶段的目标 tokenizer 计数与长度降级
  -> 原始文件中的连续字节区间
  -> model-ready fragments.pkl
```

优化对象是最终代码片段，不是把新中间表示本身当作产出。实现不展开或执行项目宏，不运行构建脚本，不加载编译数据库，也不改写、摘要或重新格式化源码。`dataset.pkl` 仍只包含 `project`、`cppFile`、`func_ast`、`func_src` 四列；Parser 另输出版本化 `fragments.pkl`，embedding 不再临时切分 AST。

### 首要输入合同：零构建解析

Parser 的首要原则是：**免目标项目编译、免链接、免执行，源码可得即可解析**。
安装好 CodeIdiomMine 后，输入只需是可读取的 C/C++ 源码目录；项目不需要成功
配置 CMake/Make/Ninja，不需要补齐依赖或生成头文件，也不需要通过编译、链接、
测试和运行。Parser 不执行目标仓库的脚本、包管理器、测试或二进制。

这一合同解释了恢复策略的优先级：原始静态源码和可追溯字节范围始终是事实来源；
Tree-sitter C++ 容错 AST 与 C++ Adapter 提供必达的基础路径；高级语义能力只能
增量叠加。未来即使加入已有 `compile_commands.json` 或 Clang 后端，也必须使用
逐文件能力标记，并在增强失败时保留当前 AST、诊断、基础候选和原文映射。下游在
可信隔离环境中对抽象模板执行 `clang++ -fsyntax-only` 属于产物验证，不是 Parser
接收源码的前置条件。

因此“开箱即用”不承诺每个原文片段都能脱离声明、宏和类型上下文独立编译，而是
承诺无需复现目标仓库的专用构建环境即可得到可审计的解析结果。这是 Parser
自身可复用性的工程定义。

## 通用核心与 C++ Adapter

`src/parser/ast_parser.py` 保留通用的 Tree-sitter 遍历、诊断、源码映射和恢复选择，
`src/parser/cpp_adapter.py` 集中提供 tree-sitter-cpp grammar、函数/区域/语句
节点类别、预处理遮蔽和 Def-Use 所需的 C++ 节点规则。公共运行时仍固定为 C++，
没有恢复语言选择器。

宏、条件编译、模板、Concept、Lambda、局部类、复杂声明、现代 C++、不完整源码和
编码坐标的逐项难点、算法与残余边界见
[C++ Adapter 与模型输入治理](cpp-adapter-and-model-input.md)。

## 解析与恢复

`src/parser/ast_parser.py` 先对原始字节执行 Tree-sitter C++ 解析，并对每个文件记录：

- `ERROR`、缺失节点和预处理节点的位置；
- 与预处理区间相交的异常数；
- 非空白源码字节数、可靠叶节点覆盖字节数和未覆盖区间；
- 原始树中的函数定义数；
- 文件读取或解析失败信息。

如果原始树存在异常，Parser 会构造一个等长的预处理影子输入：仅把 `#` 指令及其续行替换为空格，保留所有换行、字节偏移和非指令源码。只有影子树的 `ERROR + missing` 严格减少，且函数定义数不低于原始树时，才采用影子树的函数边界。最终 `code_snippet` 始终从原始文件按相同字节范围读取，影子文本不会进入数据集。

影子恢复不能替代真正的宏展开。它的职责是解除条件编译指令对周围语法边界的干扰，并通过 `parse_origin=preprocessor-shadow`、`parse_flags` 和审计侧车保留证据。未闭合但具有函数声明器和函数体起点的 `ERROR` 区间会以 `recovered_function` 保存在 Parser 数据集中；它不会冒充干净函数，也不会进入默认 quality-v2 候选。

单个文件失败由 `repo2data` 捕获并记录，其他文件继续处理。

## 函数边界

旧实现把 `class_specifier`、`function_declarator` 和模板外壳也保存为函数根，并在遇到类节点后停止向内寻找真实方法。v2 只把具有函数体的 `function_definition` 作为干净函数根，并穿过类、模板和其他外壳继续搜索。

合法的局部类内联方法会嵌套在外层函数 AST 中。v2 同时把这些真实
`function_definition` 保存为独立函数根；外层函数仍保留完整原始子树。
下游按文件身份和源码范围去重，因此局部方法不会因同时出现在外层 AST 中而
生成重复候选。每条 `func_ast` 仍只允许自己的根节点成为函数级候选。

## 原始源码映射合同

映射版本为 `mapping_version=2`。

每个 AST 节点保存：

- 历史字段 `depth`、`extent`、`kind`、`ast_num` 等；
- 原始 `code_snippet`；
- 半开区间 `start_byte`、`end_byte`；
- `subtree_size`；
- 紧凑位集 `parse_flags`。

函数根额外保存：

- 相对于单个项目仓库根的稳定 POSIX `source_path`；
- `sha256(source_path)` 生成的 `source_file_id`；
- 原始文件内容的 `source_sha256`；
- `mapping_version=2`、`mapping_exact=true`；
- `parse_origin`。

文件身份只在函数根存储一次，避免在数百万 AST 节点上重复相同字符串。候选进入嵌入阶段时会继承函数根的文件身份，因此所有下游候选都同时具有文件身份、原始字节区间和行列范围。路径移动会改变 `source_file_id`，内容变化会改变 `source_sha256`，两者分别表达位置身份和内容版本。

`repo2data` 同时写出 `dataset.audit.json`，侧车 Schema 为 v2。它覆盖所有扫描文件，包括无函数文件和失败文件；主 pickle 的四列接口不变。四列中的 `cppFile` 与函数根 `source_path` 使用相同的项目仓库相对 POSIX 身份，不以 basename 合并同名文件。多项目输入根可用可重复的 `--project <精确目录名>` 参数限定范围，省略时仍扫描全部项目。

## 三种粒度与兼容 profile

`src/parser/candidates.py` 提供两个显式 profile：

- `quality-v2`：Parser model-ready 片段的默认值；
- `legacy`：对历史数据集复现旧候选节点集合与 `ast_num` 选择规则。

quality-v2 保留三个既有下游粒度：

| 粒度 | v2 边界 |
|---|---|
| 函数 | 当前 `func_ast` 的干净 `function_definition` 根 |
| 区域 | `if`、循环、`switch`、`case`、`try/catch`、Lambda 和独立复合块 |
| 语句 | 声明、表达式、`return`、`throw`、跳转等真实语句边界 |

每个函数默认最多保留两个基础区域和两个基础语句，按核心操作、子树规模、种类多样性和源码顺序确定性排序。语句候选不得超过 4,000 字节或 80 行，避免容错 AST 把大段函数误标为单条语句。

Def-Use 语义片段仍使用 `candidate_level=region`，并以 `candidate_origin=semantic_def_use` 区分来源；没有增加第四种下游粒度。嵌入信息结构继续为 `[project, file, function_extent, node_info]`。

## 局部 Def-Use 语义切片

`src/parser/semantic_slicer.py` 对长函数和长复合区域执行轻量、确定性的局部程序分析：

1. 把容器的直接命名子节点视为语句单元；
2. 从声明、赋值、更新和范围循环中近似提取定义；
3. 从标识符引用中提取使用，并排除直接函数名；
4. 将使用连接到最近的同名先前定义，形成局部 Def-Use 边；
5. 以调用、返回、资源操作、赋值等核心操作为锚点，计算有界的两跳后向和一跳前向依赖闭包；
6. 要求至少一条依赖边、至少两个语句、闭包跨度不超过 12 个语句且内聚度至少为 0.5；
7. 输出覆盖首尾语句的连续原始字节范围，最多 4,000 字节、80 行，每个函数最多六条。

连续范围可能包含少量位于依赖语句之间的桥接语句。这是为了同时满足语义依赖和“原始源码可直接回映射”的合同；`dependency_summary` 会分别记录真正选择的语句下标、跨度、内聚度、共享符号和 Def-Use 边。

当前分析是名称级、函数内、流敏感但路径不敏感的近似，不声称等价于完整控制流图、SSA 或程序依赖图。选择这一层级是因为它无需编译数据库或执行项目代码，却能直接把长函数和长区域转换为较内聚的原始代码核心。更完整的控制依赖、别名和跨过程分析列入[Parser 风险与限制](parser-risks.md)。

## 模型长度与 Parser 降级

UniXcoder 的正式 Parser 输入上限为包含特殊 token 在内的 512 tokens。全量
97,562 条原始候选中有 1,881 条超限；字节或行数阈值不能替代真实 tokenizer。

`src/parser/fragment_builder.py` 在 Parser 阶段完成长度决策：

1. 只加载目标 tokenizer，批量计算候选的实际输入长度；
2. 函数超限时仍继续选择其区域、Def-Use 和语句后备；
3. 区域超限时继续尝试确定性排序中的下一个合格区域；
4. 仍超限的候选进入 `fragment_rejections`，不会传给 embedding；
5. 合格片段保存 `length_control.decision_stage=parser`、实际长度、预算和降级来源；
6. 输出 `fragments.pkl`，当前全量产物为 96,039 条且最大长度为 512。

embedding 只读取该产物并做失败即停的防御性复核，使用 `truncation=False`，
不承担候选降级。详细参数依据、Schema 和统计见
[C++ Adapter 与模型输入治理](cpp-adapter-and-model-input.md)。

## 运行入口

启动命令统一维护在 [Parser README](../../src/parser/README.md) 与[挖掘模块 README](../../src/mining/README.md)。Parser AST 审计是本地只读分析；片段构建使用 `--local-files-only` 时只读取缓存 tokenizer，不加载模型权重、不下载、不运行项目代码，也不调用 LLM。

## 指标定义

- 文件解析成功率：成功读取并得到 Tree-sitter 树的扫描文件数除以扫描文件数。
- AST 覆盖率：不位于 `ERROR` 子树中的可靠叶节点所覆盖的非空白原始字节数，除以全部非空白原始字节数。
- 映射完整率：候选的 `[start_byte, end_byte)` 能在原始文件中解析且切片与 `code_snippet` 逐字节相等的比例。
- 结构完整率：候选自身及其子树不含 `ERROR`、缺失节点，并且不与原始树报告的缺失位置相交的比例。影子恢复候选可能结构有效但与原始树异常位置相交，报告会保守地把它标为恢复证据。
- 重复率：除每组首次出现外，完全相同或仅空白归一化后相同的实例数除以候选数。相同源码出现在不同文件或区间时不会被删除。
- 长片段：至少 80 行或至少 4,000 字节。

## 依据

Tree-sitter 官方文档说明了 `ERROR`、缺失节点查询以及字节/点范围语义：[查询语法](https://tree-sitter.github.io/tree-sitter/using-parsers/queries/1-syntax.html)、[Node API](https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.Node.html)、[基础解析](https://tree-sitter.github.io/tree-sitter/using-parsers/2-basic-parsing.html)。

Def-Use 切片的方向来自程序切片和程序依赖图的经典定义，但本实现有意采用不依赖编译的局部近似：[Weiser 1981](https://courses.cs.washington.edu/courses/cse503/11au/readings/weiser-slicing-icse81.pdf)、[Ferrante、Ottenstein 与 Warren 1987](https://bears.ece.ucsb.edu/class/ece253/papers/ferrante87.pdf)。代码习语挖掘中使用程序依赖关系构造候选的动机可参见 [IdioMine（ICSE 2024）](https://ink.library.smu.edu.sg/sis_research/9255)。
