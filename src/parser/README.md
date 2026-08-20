# Parser

Parser 扫描当前 C/C++ 仓库，用专用 Tree-sitter/C++ Adapter 提取函数 AST、源码范围、
解析诊断和多粒度候选。Stage 1 的目标不是通用文本切块，而是在无需配置或编译目标项目
的条件下，为复杂 C++ 源码形成边界稳定、可回到原文且可审计的候选表示。文件身份统一
使用仓库相对 POSIX 路径。

## C++ 适配能力

- 只把具有函数体的 `function_definition` 作为函数，模板、类壳和声明不会伪装成函数；
- 识别条件、循环、范围 `for`、`try/catch`、lambda、`static_assert`、异常、
  `new/delete` 及协程操作，并据此生成函数、区域和语句候选；
- 区分普通、类型、字段和限定标识符，为调用角色和局部 Def-Use 切片提供稳定语法事实；
- 原始树受宏或预处理指令干扰时，等长遮蔽预处理器文本并选择诊断更少的函数边界；遮蔽
  保留换行与字节坐标，候选源码仍从原文件提取；
- 对仍不完整的函数保存 `error-boundary-recovery` 来源，不把容错 AST 冒充干净解析；
- 每个文件审计 AST 有效源码覆盖、错误/缺失节点、宏相关诊断、恢复策略、函数数和
  semantic Def-Use 片段数。

上述机制构成当前方法面向 C++ 的解析优势：固定三层候选提供不依赖完整类型和构建环境
的召回下限，semantic Def-Use 只作为增量，不会因模板、宏或高级语义暂时不可恢复而把
整个函数排除。正式覆盖数据只保存在[全仓实验记录](../../results/README.md#11-全语料-stage-01-c解析审计)，
模块 README 不复制实验数值。

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos --project cli11 \
  --output outputs/library/cli11/stage0/dataset.pkl \
  --audit-output outputs/library/cli11/stage0/audit.json \
  --fragment-output outputs/library/cli11/stage1/fragments.pkl \
  --embedding-model unixcoder --local-files-only
```

当前只存在一套候选规则和一套数据格式。`fragments.pkl` 是嵌入阶段的唯一输入，包含原始片段、候选信息、拒绝记录和统计。

解析器允许 Tree-sitter 对不完整 C++ 产生诊断与有限恢复，但不会为旧 AST、旧字段或旧候选策略提供兼容路径。AST 覆盖率证明的是有效源码进入可用语法树的程度，不等同于完整类型、别名、宏展开或运行时语义正确率。
