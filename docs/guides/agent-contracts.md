# Agent 子系统开发契约

设计动机见 [`agent-system.md`](agent-system.md)；本文件只讲**改代码时必须遵守的契约**。

## 公共基础设施 `_base.py`

所有与业务无关的样板都集中在这里，新增/修改 Agent 时复用，不要再复制粘贴：

- `load_project_env()` — 幂等加载仓库根 `.env`；`judge_pipeline`、`idiom_judgement`、`idiom_synthesis` 在初始化或导入时各调用一次即可，不要再写 `try: from dotenv ...` 块。
- `create_model_client(model=None)` — 构造共享 `OpenAIChatCompletionClient`（读端点、密钥和模型分档）；未显式传入模型时只能解析到 `OPENAI_MODEL_LOW`。
- `JsonLLMAgent(RoutedAgent)` — Agent 基类。子类 `__init__` 调 `super().__init__(agent_name, SYSTEM_MESSAGE, model_client, RESPONSE_SCHEMA)`；在 `@message_handler` 里构造中文 user prompt 后 `data = await self.ask_json(prompt)`。
- `complete_json(...)` — `ask_json` 的实现：原生 JSON mode 调用 → 严格解析 → schema 校验 → 失败时同模型修复一次 → 再失败返回 `None`。不得记录可能含源码的完整响应。
- `run_agent_selftest(title, agent_name, agent_factory, requests)` — 单 Agent 独立自测入口，供各 Agent 文件的 `if __name__ == "__main__"` 复用（`python -m src.agents.<x>`）。

## 不可改动的核心逻辑（重构等价性边界）

- **`idiom_judge_agent.patent_programming_pattern_valid(sem, syn)`** —— `is_idiom` 的真值由它决定，不是 LLM 输出。规则：`max(sem,syn) >= 70 and min(sem,syn) >= 50`。
- 每个 Agent 的**打分档位、结果 dataclass 字段和解析失败默认值**（如 `score=0`、`should_stop=True`、`merged_code=""`）属于业务契约。提示词使用中文，并为所有输出字段声明 `_RESPONSE_SCHEMA`；新增 Agent 时 `ask_json` 返回 `None` 必须显式映射到安全默认结果。
- `judge_pipeline` 与 `idiom_synthesis` **各自独立 runtime**；synthesis 内部额外持有一个 `CodeIdiomPipeline(quiet=True)` 做合并后再判定。每区域最多 `MAX_SYNTHESIS_ITERATIONS`（=3）轮合并，遇非法即停并保留上一合法结果。

## 新增一个 Agent 的步骤

1. 新建 `xxx_agent.py`：定义 `XxxRequest`/`XxxResult` dataclass + 模块级 `_SYSTEM_MESSAGE`。
2. 定义 `_RESPONSE_SCHEMA`；`class XxxAgent(JsonLLMAgent)` 的 `__init__` 调 `super().__init__("XxxAgent", _SYSTEM_MESSAGE, model_client, _RESPONSE_SCHEMA)`。
3. `@message_handler` 内构造 prompt → `await self.ask_json(prompt)` → `None` 与正常 dict 各自映射到 `XxxResult`。
4. 在 `__init__.py` 导出；如需独立自测，`__main__` 里调 `run_agent_selftest(...)`。
5. 在使用方调用 `register_agent(runtime, "xxx_agent", lambda: XxxAgent(client))`，并用 `default_agent_id("xxx_agent")` 寻址。
