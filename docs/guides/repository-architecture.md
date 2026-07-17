# 仓库架构

CodeIdiomMine 从 C++ 仓库中提取候选 AST 片段，经代码嵌入和 DBSCAN 聚类后，使用 AutoGen Agent 判断候选是否为代码习语，并尝试合成可复用模板。

本文描述当前实现。论文研究路线位于 `docs/research/`，不作为现有代码必须满足的规格。

## 运行约定

- 从仓库根目录运行所有命令。
- 使用项目解释器 `.venv/bin/python`。
- 入口必须采用 `python -m src.<package>.<module>`；源码使用相对导入，直接执行文件会失败。
- `.env` 由 `src/llm/config.py` 从仓库根目录统一加载，提供 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 与 `OPENAI_MODEL_LOW/MEDIUM/HIGH`；当前默认调用只取低档模型。

完整命令见根目录 `README.md`，验证顺序见 `docs/guides/testing.md`。

## 模块职责

| 路径 | 职责 |
|---|---|
| `src/common/` | 统一日志、LLM 配置兼容导出与 C++ 函数、块、语句节点类型集合 |
| `src/parser/` | C++ 文件扫描、Tree-sitter C++ 初始化、AST 与源码片段提取 |
| `src/mining/` | 预训练模型嵌入、DBSCAN 聚类和可选贝叶斯调参 |
| `src/agents/` | 通用 AutoGen 基类，以及习语判断、规划、代码组装与合成后再判断 |
| `src/evaluation/` | IC、留一项目 ISP、F1 与平均习语大小 |
| `src/llm/` | 两项目统一的模型分档、`.env`、AutoGen 客户端、JSON schema/单次修复与轻量对话封装 |
| `src/utils/` | 原始 pickle/CSV 转换和流水线可读 JSON 投影 |
| `tests/` | 与上述七个源码子包一一对应的离线自动化测试 |

## 数据流与契约

```text
repos/cpp/<project>/...
  -> outputs/cpp/dataset.pkl
  -> outputs/cpp/embeddings.pkl
  -> outputs/cpp/clusters.pkl
       \-> outputs/cpp/readables/{summary,preview,top100}.json  # 可再生成的分析视图
  -> results/cpp/{repo}_idiom.pkl
  -> results/cpp/{repo}_idiom_syn.pkl
  -> results/cpp/eval.json
```

- `dataset.pkl`：DataFrame 列为 `project`、`cppFile`、`func_ast`、`func_src`。`cppFile` 是保留的数据契约字段。
- `embeddings.pkl`：DataFrame 列为 `pros_name`、`pros_src`、`pros_emb`、`pros_info`；嵌入以 CPU `torch.Tensor` 保存。
- `clusters.pkl`：`list[{pros_name, clusters}]`；簇表包含 `label`、`center_point`、`else_point`、`cluster_size`、`center_point_info`、`infos`、`loc_label`。
- `{repo}_idiom.pkl`：包含 `center_point`、`info`、`cnt`、`avg_ast_num`、`loc_label`。
- `{repo}_idiom_syn.pkl`：额外包含 `source_infos`、`merge_rounds`、`synthesis_trace`。
- `eval.json`：包含逐项目及汇总的 `IC`、`ISP`、`F1`、`avg_idiom_size`。

这些 pickle schema 是阶段间接口。结构调整任务不得顺手改变字段或嵌套层级。

`src.utils.export_artifacts` 不改变上述接口：PKL 保留完整嵌套 AST、CPU tensor 和簇成员，JSON 只作为可重新生成的人工分析投影。每阶段的 `*.summary.json` 统计全量输入；`dataset.preview.json` 和 `embeddings.preview.json` 默认各取前 100 条，`clusters.top100.json` 默认按项目分别取簇大小 Top100。真实 Agent 运行后还可按需导出 `judgment` 和 `synthesis` 的摘要及前 100 条。预览中的长源码会显式截断，嵌入只展示形状、范数和向量头部，因此这些 JSON 不得回流为下一阶段输入。

## C++ 范围边界

项目不再提供语言扩展点：

1. `src/common/node_kinds.py` 直接导出 C++ 节点集合，不维护语言映射；
2. `src/parser/ast_parser.py` 固定加载 `tree-sitter-cpp`；
3. `src/parser/file_scanner.py` 固定扫描 C/C++ 扩展名；
4. parser、embedding 和 evaluation CLI 均无 `--language` 参数。

`repos/cpp`、`outputs/cpp` 和 `results/cpp` 中的 `cpp` 是固定的现有产物命名空间，不是可切换语言参数。当前扫描器会过滤路径中的测试、缓存和版本控制目录；具体规则以源码为准。重新引入其他语言属于新的架构变更，不能通过增加一个 CLI 选项或静默回退实现。

## Agent 子系统

Agent 基于 `autogen_core` 的 `RoutedAgent`、强类型 dataclass 消息和 `SingleThreadedAgentRuntime`，不是 `autogen_agentchat`。

- 判断：语义与语法 Agent 通过 `asyncio.gather` 并行执行，再由 judge Agent 汇总。
- 最终 `is_idiom` 由确定性规则决定：较高分至少 70，较低分至少 50。
- 合成：规划与组装使用独立 runtime，并持有第二个 quiet 判断流水线做合并后再判断。
- 每个区域最多合并三轮；无成功合并的组不产生合成记录。

详细设计见 `docs/guides/agent-system.md`，修改约束见 `docs/guides/agent-contracts.md`。

## 日志和生成物

`src/common/logging.py` 将 INFO 及以上写到控制台，将 DEBUG 及以上追加到 `logs/<run-name>.log`。同一命令的所有模块共享运行日志，后续导入不会截断旧证据；`src/logger.py` 仅保留旧导入兼容。

`logs/`、`outputs/`、`results/`、虚拟环境和密钥文件由 `.gitignore` 排除。`docs/` 中的开发与研究资料应进入版本控制。

第一方集合目录采用复数职责名。`src/`、`cpp/` 和 `.venv/` 分别是 source root、语言限定符和虚拟环境约定，不属于需要复数化的集合名称。

共享文件列表与同步检查命令见 `docs/guides/shared-development-conventions.md`；`scripts/check_shared_infrastructure.py` 可与相邻 WPF2React checkout 做逐文件哈希检查。
