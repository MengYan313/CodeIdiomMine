# Agent 公共基础设施

本包只保留阶段3与阶段4实际复用的 AutoGen 基类、Agent 注册函数、JSON 调用的
超时/单次修复/有界重试和简洁调用状态。所有领域提示词、消息 Schema、评分和
流程分别位于
[`src/idiom_judgment`](../idiom_judgment/README.md) 与
[`src/idiom_synthesis`](../idiom_synthesis/README.md)。

本包没有独立业务 CLI。阶段3和阶段4入口见根目录
[`README.md`](../../README.md)。
