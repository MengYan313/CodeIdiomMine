# C++ 适配与模型输入

模型输入统一来自 Parser 当前生成的 `fragments.pkl`，不直接从旧 AST 数据或任意源码片段生成 embedding。

每条记录包含：

- `project`：项目名；
- `fragment_src`：送入模型的源码；
- `fragment_info`：文件相对路径、候选类型、范围和必要 AST 信息；
- `model_name` 与 `max_input_tokens`：本次片段构建所采用的模型预算。

DataFrame attrs 只记录源数据路径和构建统计。被拒绝的候选及原因保存在 `rejections`，便于定位 token 超限或无效源码。

默认候选包括函数、基础区域、真实语句和 Def-Use 语义片段。片段必须保留原始源码顺序，并在模型总预算内。嵌入阶段直接消费该结构，不提供 profile、Schema 或旧数据兼容开关。
