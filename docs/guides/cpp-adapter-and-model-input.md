# C++ Adapter 与模型输入治理

## 开箱即用的解析边界

C++ Adapter 服从 Parser 的零构建解析原则：**免目标项目编译、免链接、免执行，
源码可得即可解析**。它直接面对原始 C/C++ 字节，不要求项目可配置、依赖齐全、
生成文件存在或目标平台可用，也不会调用仓库中的构建脚本、包管理器、测试和
二进制。对于宏环境、类型或头文件缺失造成的不确定性，Adapter 选择“保留基础
语法与诊断、显式降低能力”，而不是“构建失败即丢弃文件”。

零构建不等于拒绝所有编译器信息。若调用方已经安全地提供编译数据库或 Clang
结果，后续 Adapter 可以把它们作为带 `capability` 标记的可选增强；可信隔离环境
也可以在下游验证抽象模板。任何增强都不得改变原始文件身份和字节映射，也不得
覆盖 Tree-sitter 基础结果。这个边界把通用 AST 算法的可迁移性与 C++ 特有恢复
集中起来，使 Parser 能复用于不同构建系统和不完整源码。

## 为什么单独设置 C++ Adapter

Parser 的多数操作并不依赖 C++：Tree-sitter 节点的深度优先遍历、错误统计、
候选排序、源码区间校验、Def-Use 闭包、token 预算和降级流程都可以复用于其他
具有 Tree-sitter grammar 的语言。真正不能通用的是 grammar 装配、节点名称、
预处理器语义和 C++ 声明结构。

`src/parser/cpp_adapter.py` 因此集中保存以下 C++ 策略：

- 固定加载 `tree-sitter-cpp`，但不提供公共语言选择器；
- 函数定义、函数声明器、复合语句、标识符和名称节点的类别；
- `if`、循环、`switch`、异常处理、Lambda、语句和核心操作类别；
- C/C++ 预处理节点识别及等长预处理影子构造；
- Def-Use 分析所需的调用目标、声明器、赋值和范围循环规则。

通用核心与 C++ Adapter 的边界如下：

| 职责 | 通用核心 | C++ Adapter |
|---|---|---|
| AST 遍历与子树规模 | 深度优先遍历、深度、直接子节点数、子树节点数 | 提供哪些节点是函数根或语法容器 |
| 异常与覆盖 | 统计错误、缺失、可靠叶节点和未覆盖字节 | 识别 `ERROR`、`preproc_*` 与可恢复函数声明器 |
| 源码映射 | 使用半开字节区间读取原始文件并校验哈希 | 保证影子输入与 C++ 原文等长 |
| 候选生成 | 完整性过滤、种类多样性、确定性排序和去重 | 提供 C++ 区域、语句和核心操作集合 |
| 语义切片 | 定义—使用边、依赖闭包、连续范围和内聚度 | 提供 C++ 声明、赋值、调用和标识符规则 |
| 模型长度 | 实际 tokenizer 计数、预算过滤、降级和拒绝记录 | 无；长度治理不应写成 C++ 特例 |

这种拆分不是恢复多语言公共接口。当前 `ASTParser()`、扫描器和 CLI 仍然只支持
C++，也没有 `--language` 参数。Adapter 是内部可维护性边界，避免把
`function_definition`、`preproc_*` 等 C++ grammar 细节散落到通用算法中。

## C++ 复杂语法的主要难点与处理

### 宏定义与条件编译

C/C++ 宏发生在真正语法分析之前，而 Tree-sitter 直接面对未预处理源码。函数式
宏可以把参数放到类型、声明器、属性或语句位置；条件编译还可能让同一个源码文件
在静态文本上同时出现互斥的半个 `if`、半个类或半个函数体。若直接相信单棵容错
AST，常见后果是：

- 一个宏污染的错误节点吞并几百行源码；
- 后续真实函数成为错误节点的子节点而被整体漏掉；
- `#if` 两侧的大括号被错误配对；
- 宏生成的声明无法获得真实语法类别。

Parser 首先保留原始树及全部诊断，然后由 C++ Adapter 构造等长影子：

1. 识别行首经空白后的 `#`；
2. 同时遮蔽以反斜杠续行的后续物理行；
3. 只把非换行字节替换为空格，文件长度、换行位置和字节坐标完全不变；
4. 再解析影子文本；
5. 只有影子树的 `ERROR + missing` 严格减少，且函数定义数不低于原始树时，
   才采用影子树的函数边界；
6. 所有最终 `code_snippet` 仍从原始文件的相同字节区间读取。

因此 `#define`、`#if` 和宏调用本身不会被改写或从最终片段删除。
`parse_origin=preprocessor-shadow`、`parse_flags`、遮蔽区间和原始/影子诊断都可
追溯。该方案不要求目标项目编译、链接或执行，不执行构建脚本，也不展开项目宏，
避免编译参数缺失和不可信构建逻辑带来的副作用。

边界也必须明确：如果一个函数完全由宏展开生成，未展开源码中没有可识别的函数
边界，影子策略不能虚构它。此时文件仍出现在逐文件审计中，相关错误、未覆盖区间和
宏相关异常不会被静默隐藏。后续若引入 Clang 预处理，应把编译数据库、宏环境和
展开后到原文的映射作为另一种显式 Adapter，而不能替换当前原文证据。

### 模板、Concept 与 `requires`

模板声明是包裹函数或类的外壳，Concept 和 `requires` 表达式又会包含看似函数体
的参数列表与复合要求。旧逻辑把模板壳、类或 `function_declarator` 当成函数，
导致函数数量膨胀、范围过宽和真实模板函数遗漏。

C++ Adapter 只把具有函数体的 `function_definition` 认作干净函数根。通用遍历
不会在模板或类外壳处停止，因此能继续找到类内方法、函数模板、运算符重载和局部类
方法。纯声明、Concept 定义和 `requires` 子表达式保留在 AST 与覆盖统计中，但不
伪装成函数片段。

### Lambda 与局部类

Lambda 在 C++ grammar 中是表达式而不是独立顶层函数。Parser 把完整
`lambda_expression` 作为区域候选，保留捕获列表、参数、限定符和函数体的连续
原文；不会只截取 Lambda 的复合语句而丢掉捕获语义。

函数内局部类的内联方法是真实 `function_definition`。Parser 会同时保留外层函数
和局部方法的独立函数根；候选阶段使用稳定文件身份、范围、粒度和来源去重，避免同一
局部方法因嵌套表示重复进入 model-ready 产物。

### 复杂声明、属性和运算符重载

指针/引用、函数指针、尾置返回类型、`decltype`、限定名、属性、构造/析构函数和
`operator()` 会形成多层声明器。Parser 不使用字符串正则猜函数名或大括号，而是
依赖 grammar 的 `function_definition` 和字节边界。名称提取只作为展示字段，
即使复杂声明没有简单 `identifier`，函数范围和原文映射仍然有效。

Def-Use 层面对 `init_declarator`、普通声明器、赋值左值、更新表达式和范围循环
声明器提取定义；复杂别名、重载解析和类型推导不在本地名称级分析中冒充精确语义。

### 现代 C++ 控制结构

C++ Adapter 显式覆盖范围循环、Lambda、`try/catch`、`static_assert`、
`co_await` 和 `co_return`。结构化绑定仍按声明节点进入 Def-Use 近似；协程操作
可作为语义核心锚点。模块声明、编译器扩展和 grammar 新增节点即使暂未进入候选
集合，也仍会进入完整 AST、错误统计和源码覆盖审计，不会从文件级证据中消失。

### 不完整源码与生成代码

编辑中代码、截断 fixture 和缺失生成头文件会产生容错 AST。Parser 对包含函数
声明器且已经出现 `{` 的错误边界生成 `recovered_function`，保留原始范围和
`error-boundary-recovery` 来源，但默认 `quality-v2` 不把它当成干净候选。
单文件失败只记录在侧车，不中断其他文件。

扩展名为 `.h` 的文件可能实际包含 Objective-C/Objective-C++ 或生成 DSL。
当前项目固定按 C++ 解析，不通过扩展名猜第二种语言；这类文件的覆盖率、错误和未覆盖
字节会如实降低，详见风险文档。

### 编码、行列和字节坐标

Tree-sitter 的范围以字节为准，而 Unicode 字符数和终端列数并不等价。Parser 的
权威映射使用 `[start_byte, end_byte)`，`extent` 只用于可读展示。影子恢复保持
字节长度，最终验证直接比较
`source_bytes[start_byte:end_byte] == code_snippet.encode(...)`。UTF-8 失败时
保留 Latin-1 一一映射后备，避免因解码异常让整个文件消失。

## 为什么 UniXcoder 使用 512 tokens

项目的默认后续模型是 `microsoft/unixcoder-base`。其官方模型卡在
encoder-only 示例中明确调用
`model.tokenize(..., max_length=512, mode="<encoder-only>")`，因此本项目把
512 作为经过文档验证的总输入合同，而不是从字符数猜测：
[UniXcoder 官方模型卡](https://huggingface.co/microsoft/unixcoder-base)、
[UniXcoder 官方仓库](https://github.com/microsoft/CodeBERT/tree/master/UniXcoder)、
[UniXcoder 论文](https://arxiv.org/abs/2203.03850)。

本地 `RobertaTokenizer.model_max_length` 是 Hugging Face 的巨大哨兵值，不能当作
真实上限；本地模型配置中的 `max_position_embeddings=1026` 也不应覆盖官方
wrapper 示例和项目既有 512 合同。当前直接 tokenizer 会加入 `<s>`、`</s>` 两个
特殊 token，因此 512 是“代码 BPE token 加特殊 token”的总数，代码内容最多占
510 个 token。若日后改变 tokenizer、编码模式或模型，Parser 会按新 tokenizer
重新计数和重建片段，而不是复用旧长度标签。

`CodeLLaMA`、CodeBERT 和自定义模型使用各自的 Parser 配置上限。
`--max-input-tokens` 只能收紧、不能扩大已验证上限，避免用 CLI 绕过模型合同。

## 全量 token 审计

在 2026-07-23 的 97,562 条 `quality-v2` 原始候选上，用本地缓存的官方
UniXcoder tokenizer 计数，长度包含特殊 token：

| 类型 | 数量 | P50 | P95 | 最大值 | 超过 512 |
|---|---:|---:|---:|---:|---:|
| 函数 | 33,203 | 49 | 425 | 12,724 | 1,237 |
| 基础区域 | 17,083 | 53 | 326 | 7,592 | 341 |
| 语句 | 43,608 | 13 | 50 | 1,108 | 25 |
| Def-Use 区域 | 3,668 | 158 | 582 | 1,191 | 278 |
| 合计 | 97,562 | 27 | 303 | 12,724 | 1,881（1.9280%） |

这说明原来的 4,000 字节/80 行规则只能防止极端误切分，不能替代模型 tokenizer
预算；尤其 Def-Use 片段中仍有 7.58% 超过 512。

## Parser 阶段的长度降级

长度决策发生在 `src/parser/fragment_builder.py`，而不是 embedding 阶段：

```text
dataset.pkl 中的 AST
  -> quality-v2 候选与 Def-Use 分析
  -> 目标 tokenizer 精确计数
  -> 函数超过预算：排除函数，保留合格区域 / Def-Use / 语句
  -> 区域超过预算：尝试排序中的下一个合格区域，并保留 Def-Use 核心
  -> Def-Use 或语句仍超限：显式拒绝
  -> fragments.pkl
  -> embedding 只校验并编码，不切分
```

候选过滤被放进多样性排序内部，因此排名第一的区域超限时，会继续寻找同函数中
排名靠后的可用区域，而不是先选两个再全部丢弃。函数超限不会阻止其子候选继续分析。
Def-Use 仍以连续原文字节区间输出，不能为了凑长度拼接不连续语句或生成摘要。

每条 model-ready 片段的 `node_info.length_control` 保存：

- `policy_version=parser-token-budget-v1`；
- `decision_stage=parser`；
- tokenizer 模型名、预算和实际 token 数；
- `strategy=function|region|semantic_def_use|statement`；
- 若由超长函数降级，保存 `degraded_from=function`。

每条超限原候选进入 `fragment_rejections`，包含文件身份、函数范围、候选范围、
实际长度、预算、拒绝原因、动作和函数级后备策略。85 个没有任何合格后备的超长函数
因此也有逐条证据，不会静默消失。

全量 Parser 产物包含 96,039 条 model-ready 片段：

| 类型 | model-ready 数量 | 最大 token | 超限 |
|---|---:|---:|---:|
| 函数 | 31,966 | 512 | 0 |
| 基础区域 | 17,078 | 512 | 0 |
| 语句 | 43,605 | 509 | 0 |
| Def-Use 区域 | 3,390 | 512 | 0 |
| 合计 | 96,039 | 512 | 0 |

1,310 条函数记录超过预算，其中 1,225 条至少得到一个区域、Def-Use 或语句后备，
85 条没有合格后备。这里的函数记录数高于去重后的 1,237 条超长函数候选，是因为
局部方法既存在于外层函数 AST，也有自己的独立函数记录；最终片段和拒绝清单均按
文件身份与范围去重。

## 产物合同与 embedding 防线

`dataset.pkl` 的四列 AST Schema 不变。新增 `fragments.pkl` 是 Parser 到
embedding 之间的版本化兼容层，列包括：

- `project`、`fragment_schema_version`、`source_dataset_schema`；
- `candidate_profile`、`model_name`、`max_input_tokens`；
- 对齐的 `fragment_src` 与 `fragment_info`；
- `fragment_rejections` 与 `fragment_stats`。

DataFrame attrs 还保存源 AST 数据集路径、SHA-256 和
`decision_stage=parser`。`fragment_info` 继续使用既有
`[project, file, function_extent, node_info]` 结构，因此 `embeddings.pkl`、
聚类和 Agent 接口不变。

embedding 不再接受四列 AST 数据集作为真实模型输入。它要求
`fragment_schema_version`、profile、模型名和 token 预算与当前模型完全一致，
重新计数只作为防御性校验；任何超限立即报错，tokenizer 使用
`truncation=False`，不在该阶段补切、摘要或静默截断。

## 运行入口

Parser 与 embedding 的启动命令统一维护在 [Parser README](../../src/parser/README.md) 和[挖掘模块 README](../../src/mining/README.md)，本文不重复命令。`--local-files-only` 用于证明 Parser 阶段不下载模型；片段构建只加载 tokenizer，不加载 embedding 权重、不运行项目代码，也不调用 LLM。
