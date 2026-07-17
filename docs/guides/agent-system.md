# Agent 子系统架构

`src/agents/` 实现**编程模式（代码习语）判定**与**同区域模板合成**两条流水线，与说明书实施例 **7.2（三 Agent 并行判定）**、**7.3（规划 + 组装）**、**7.4（合并后再判定与迭代）**对齐。实现基于 Microsoft **AutoGen** 的 `autogen_core` / `autogen_ext`，采用 `RoutedAgent` + `SingleThreadedAgentRuntime` 的消息驱动模型，而非对话式 `agentchat` 封装。

---

## 一、整体架构概览

系统按职责分为两层：

| 层级 | 职责 | 涉及的 Agent | 运行时 |
|------|------|----------------|--------|
| **判定子系统（7.2）** | 对**单段代码**做语义 / 语法并行评估，再综合；最终是否「有效编程模式」由**确定性分数规则**裁定 | `SemanticClarityAgent`、`SyntaxLogicAgent`、`IdiomJudgeAgent` | `CodeIdiomPipeline` 内部的 `SingleThreadedAgentRuntime` |
| **合成子系统（7.3 + 7.4）** | 按 `loc_label` 分组，在组内做**规划 → 组装 → 再判定**循环，最多 **3** 轮合并 | `PlanningSynthesisAgent`、`CodeAssemblyAgent` | `idiom_synthesis.run_synthesis` 中的**独立** `SingleThreadedAgentRuntime` |

判定与合成使用**两个不同的运行时**，原因包括：

- 注册的 Agent 名称空间互不冲突（例如合成侧不需要注册 `semantic_agent`）。
- 生命周期清晰：`CodeIdiomPipeline` 随 `initialize` / `shutdown` 管理判定用运行时；合成脚本在 `run_synthesis` 内创建/销毁合成用运行时，并单独持有一个 `CodeIdiomPipeline` 实例专门用于**合并后的再判定**。

```
                    ┌─────────────────────────────────────────┐
                    │           判定子系统 (7.2)                 │
                    │  Runtime A: semantic / syntax / judge   │
                    │  入口: CodeIdiomPipeline.evaluate()      │
                    └─────────────────────────────────────────┘
                                        ▲
                                        │ 合并后代码再判定
                    ┌───────────────────┴───────────────────────┐
                    │           合成子系统 (7.3 + 7.4)           │
                    │  Runtime B: planning_synthesis / assembly │
                    │  编排: idiom_synthesis.synthesize_group() │
                    └───────────────────────────────────────────┘
```

---

## 二、判定子系统（7.2）：三 Agent 流水线

### 2.1 数据流

1. 对同一 `code_snippet`，使用 `asyncio.gather` **并行**调用：
   - `SemanticClarityAgent` → `SemanticClarityResult`（命名、意图、可理解性，score 0–100）
   - `SyntaxLogicAgent` → `SyntaxLogicResult`（语法、控制流、逻辑与异常处理等，score 0–100）
2. 将两路结果填入 `IdiomJudgeRequest`，调用 `IdiomJudgeAgent`，由 LLM 生成**理由、置信度、习语特征**等说明性内容。
3. **最终布尔结论** `final_judgment["is_idiom"]` **不**单独采信 LLM 的 `is_idiom`，而是由 `patent_programming_pattern_valid(semantic_score, syntax_score)` 决定：
   - 较高分 ≥ 70 且较低分 ≥ 50 → 视为有效编程模式；
   - 否则无效。  
   若 LLM 与规则不一致，仍会保留 `final_judgment["llm_is_idiom"]` 便于对照；置信度在不一致时按两维 score 均值调整。

### 2.2 流程示意图

```
code_snippet
     │
     ├──────────────────────┬──────────────────────┐
     ▼                      ▼                      │
SemanticClarityAgent   SyntaxLogicAgent            │
     │                      │                      │
     └──────────┬───────────┘                      │
                ▼                                  │
         IdiomJudgeAgent（汇总说明）                │
                │                                  │
                ▼                                  │
    patent_programming_pattern_valid ←─────────────┘
                │
                ▼
        结构化 dict（含 semantic / syntax / final_judgment）
```

### 2.3 入口与批量任务

- **库内调用**：`CodeIdiomPipeline(model=..., quiet=False)`，`await pipeline.evaluate(code)`，`await pipeline.shutdown()`。  
  `quiet=True` 时关闭步骤打印，供合成流水线反复调用再判定时减少日志。
- **命令行批量**：`.venv/bin/python -m src.agents.idiom_judgement`，读取聚类产物，对每个 `center_point` 调用上述流水线，写出 `{repo}_idiom.pkl`。

---

## 三、合成子系统（7.3 + 7.4）：规划、组装与再判定

### 3.1 数据与分组

- 输入：`results/.../{repo}_idiom.pkl`（已通过 7.2 的习语列表）。
- 按 `loc_label`（项目–文件–extent 等区域标签）分组；**仅当组内条数 ≥ 2** 时尝试合成。

### 3.2 单组内迭代（最多 3 轮）

常量 `MAX_SYNTHESIS_ITERATIONS`（默认 **3**，可从 `src.agents` 导出）控制**合并轮数**上限。

每轮顺序：

1. **PlanningSynthesisAgent**：输入当前已合并代码、本组剩余候选片段列表（由编排层注入，未来可替换为工具查询结果）、当前轮次与最大轮次；输出 `should_stop`、`selected_indices`（本轮要并入的一个或多个候选下标）、`reason`。
2. **CodeAssemblyAgent**：输入 `base_code` 与按规划顺序的 `segments_to_merge`，输出 `merged_code`。
3. **CodeIdiomPipeline.evaluate(merged_code)**：与 7.2 相同的三 Agent + 规则再判定。  
   - 若无效：终止该组合成，**保留上一轮仍合法**的合并结果（若从未成功合并则该组不产出合成记录）。  
   - 若有效：更新当前代码，从池中移除已并入的候选，进入下一轮（直至规划停止、池空或达到 3 轮）。

### 3.3 入口

```bash
.venv/bin/python -m src.agents.idiom_synthesis --input-dir results/cpp --output-dir results/cpp
```

写出 `{repo}_idiom_syn.pkl`，条目中包含 `center_point`、`loc_label`、聚合后的 `cnt` / `avg_ast_num`、`source_infos`、`merge_rounds`、`synthesis_trace` 等。

---

## 四、使用 AutoGen 的实现方式（实现细节）

### 4.1 为何选用 `autogen_core`

- **`RoutedAgent` + `@message_handler`**：每个 Agent 是强类型的消息处理器，请求/响应用 **dataclass** 描述，适合**非对话、流水线式**调用。
- **`SingleThreadedAgentRuntime`**：在同一线程内调度消息，与 `asyncio` 配合简单，避免多线程与锁的复杂度。
- **`autogen_ext` 的 `OpenAIChatCompletionClient`**：统一封装 Chat Completions，与 `SystemMessage` / `UserMessage` 列表对接。

本模块**未**使用 `autogen_agentchat` 的会话 Agent，因主路径是「单次请求 → 结构化返回」，而非多轮用户–助手对话。

### 4.2 Agent 类共性

每个业务 Agent 均：

1. 业务 JSON Agent 继承 `JsonLLMAgent`，后者再继承两项目共享的 `BaseRoutedAgent`（`autogen_core.RoutedAgent`）。
2. 在类内用 `@message_handler` 声明处理函数，入参为自定义 `Request` dataclass 与 `MessageContext`，返回 `Result` dataclass。
3. 构造函数注入共享的 `OpenAIChatCompletionClient`；handler 通过 `JsonLLMAgent.ask_json(...)` 发起结构化调用。
4. `src/llm/json_output.py` 启用原生 JSON mode，对完整响应执行严格解析和 schema 校验；首次失败时使用同一模型修复一次，再次失败才由领域 Agent 返回安全默认结果。

### 4.3 运行时注册与寻址（与文档示例的差异）

当前代码通过共享的 **`register_agent`** / **`default_agent_id`** 统一封装 `register_factory` 与 `AgentId`，与早期 AutoGen 示例中的 `register` + 字符串 recipient 不同，例如：

```python
from autogen_core import SingleThreadedAgentRuntime
from src.agents.base import default_agent_id, register_agent

runtime = SingleThreadedAgentRuntime()
await register_agent(
    runtime,
    "semantic_agent",
    lambda: SemanticClarityAgent(model_client),
)
runtime.start()

result = await runtime.send_message(
    SemanticClarityRequest(code_snippet=code),
    recipient=default_agent_id("semantic_agent"),
)
```

要点：

- **工厂**：`register_agent(runtime, name, factory)` 内部调用 `register_factory`，在首次投递到该 `AgentId` 时创建实例。
- **收件人**：`default_agent_id("logical_name")` 与注册名一致并固定 `key="default"`；需要多实例时再显式构造其他 key。

### 4.4 判定流水线中的并行

在 `CodeIdiomPipeline.evaluate` 内，对语义与语法两次 `send_message` 使用 **`asyncio.gather`**，实现说明书中的「并行接收同一代码段输入」；综合判定仍为第三次 `send_message`（依赖前两路结果，天然顺序执行）。

### 4.5 双运行时与 `CodeIdiomPipeline` 复用

- `run_synthesis`：**启动**合成用 `SingleThreadedAgentRuntime`，注册 `planning_synthesis_agent`、`code_assembly_agent`。
- 同时构造 **`CodeIdiomPipeline(model, quiet=True)`**，内部再创建**第二个**运行时并注册三个判定 Agent。  
  合成循环中只通过 `pipeline.evaluate` 与判定子系统交互，不手动向 Runtime A 注册合成类 Agent。

---

## 五、文件与模块索引

| 文件 | 角色 |
|------|------|
| `src/agents/semantic_clarity_agent.py` | 语义清晰度 Agent |
| `src/agents/syntax_logic_agent.py` | 语法与逻辑 Agent |
| `src/agents/idiom_judge_agent.py` | 综合判定 Agent；**`patent_programming_pattern_valid`** |
| `src/agents/judge_pipeline.py` | **`CodeIdiomPipeline`**：并行判定 + 规则裁定 + `quiet` |
| `src/agents/planning_synthesis_agent.py` | 规划合成 Agent（7.3） |
| `src/agents/code_assembly_agent.py` | 代码组装 Agent（7.3） |
| `src/agents/idiom_judgement.py` | CLI：聚类结果 → `*_idiom.pkl` |
| `src/agents/idiom_synthesis.py` | CLI / API：`*_idiom.pkl` → 规划–组装–再判定 → `*_idiom_syn.pkl` |
| `src/agents/__init__.py` | 对外导出主要类型与 `MAX_SYNTHESIS_ITERATIONS` |

---

## 六、快速开始

### 6.1 依赖与环境

```bash
.venv/bin/python -m pip install autogen-core 'autogen-ext[openai]' python-dotenv
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="your-base-url"   # 可选
export OPENAI_MODEL_LOW="gpt-5.6-luna"
export OPENAI_MODEL_MEDIUM="gpt-5.6-terra"
export OPENAI_MODEL_HIGH="gpt-5.6-sol"
```

项目根目录可提供 `.env`，所有 LLM 入口会统一加载它。三档仅保存选项，当前默认调用固定解析到低档 `OPENAI_MODEL_LOW`。

### 6.2 单独运行各 Agent 模块（自测）

```bash
.venv/bin/python -m src.agents.semantic_clarity_agent
.venv/bin/python -m src.agents.syntax_logic_agent
.venv/bin/python -m src.agents.idiom_judge_agent
```

### 6.3 判定流水线示例

```python
import asyncio
from src.agents.judge_pipeline import CodeIdiomPipeline

async def main():
    pipeline = CodeIdiomPipeline()  # 默认读取 OPENAI_MODEL_LOW=gpt-5.6-luna
    try:
        result = await pipeline.evaluate(
            "int add_one(int x) { return x + 1; }\n"
        )
        pipeline.print_result(result)
    finally:
        await pipeline.shutdown()

asyncio.run(main())
```

### 6.4 单独向某个 Agent 发消息（正确注册方式）

```python
import asyncio
from autogen_core import SingleThreadedAgentRuntime
from src.agents import SemanticClarityAgent, SemanticClarityRequest
from src.agents.base import default_agent_id, register_agent
from src.llm import create_model_client

async def main():
    runtime = SingleThreadedAgentRuntime()
    model_client = create_model_client()
    await register_agent(
        runtime,
        "semantic_agent",
        lambda: SemanticClarityAgent(model_client),
    )
    runtime.start()
    try:
        out = await runtime.send_message(
            SemanticClarityRequest(code_snippet="int twice(int x) { return x * 2; }"),
            recipient=default_agent_id("semantic_agent"),
        )
        print(out.score, out.reason)
    finally:
        await runtime.stop()

asyncio.run(main())
```

### 6.5 批量判定与合成

```bash
.venv/bin/python -m src.agents.idiom_judgement --input outputs/cpp/clusters.pkl --limit 5 -q
.venv/bin/python -m src.agents.idiom_synthesis --input-dir results/cpp --output-dir results/cpp
```

---

## 七、LLM 输出约定

各 Agent 的业务提示词和解释字段统一使用中文，代码、必要技术术语和 JSON 字段名保留英文。每类 Agent 声明显式 JSON Schema；模型直接返回 JSON object，不使用标签或 Markdown 包装。共享层只解析完整响应，不从正文猜测 JSON 片段，并把修复次数固定为一次。

---

## 八、判定标准（与专利 7.2 一致）

- 语义 score 与语法 score 中，**较高者 ≥ 70 且较低者 ≥ 50** → `patent_programming_pattern_valid` 为真，即保留为有效编程模式。
- LLM 给出的 `is_clear`、综合 Agent 的叙述用于解释与日志；**门禁**以分数规则为准。

---

## 九、常见问题

**Q：为什么用 `autogen_core` 而不是 `autogen_agentchat`？**  
A：本场景是结构化、可重复的流水线调用，不需要会话状态机；`RoutedAgent` + 运行时消息足够清晰且易于测试。

**Q：`register` 与 `register_factory` 区别？**  
A：本仓库统一使用包装函数 **`register_agent`**，其内部调用 `register_factory`，并配合 `default_agent_id` 寻址；业务代码不再混用不同注册形式。

**Q：合成与判定能否合并为一个 Runtime？**  
A：可以技术上合并为五个 Agent 同注册在一个运行时，但当前实现**刻意分离**，以降低命名耦合并单独控制 `CodeIdiomPipeline` 生命周期。

---

## 十、关联文档

- 修改约束：`docs/guides/agent-contracts.md`
- 仓库数据契约：`docs/guides/repository-architecture.md`
- 运行与验证：`docs/guides/testing.md`
