# src/agent/ — Agent 子系统约定（嵌套，覆盖根 CLAUDE.md 同名内容）

设计动机见 `README.md`；本文件只讲**改代码时必须遵守的契约**。

## 公共基础设施 `_base.py`

所有与业务无关的样板都集中在这里，新增/修改 Agent 时复用，不要再复制粘贴：

- `load_project_env()` — 幂等加载仓库根 `.env`；`judge_pipeline`、`idiom_judgement`、`idiom_synthesis` 在初始化或导入时各调用一次即可，不要再写 `try: from dotenv ...` 块。
- `create_model_client(model)` — 构造共享 `OpenAIChatCompletionClient`（读 `OPENAI_API_KEY` / `OPENAI_BASE_URL`）。
- `JsonLLMAgent(RoutedAgent)` — Agent 基类。子类 `__init__` 调 `super().__init__(agent_name, SYSTEM_MESSAGE, model_client)`；在 `@message_handler` 里构造 user prompt 后 `data = await self.ask_json(prompt)`。
- `complete_json(...)` — `ask_json` 的实现：temperature=0 调用 → `extract_tag_content(_, "JSON")` → `json.loads` → 解析失败返回 `None`（已记录原始响应）。
- `run_agent_selftest(title, agent_name, agent_factory, requests)` — 单 Agent 独立自测入口，供各 Agent 文件的 `if __name__ == "__main__"` 复用（`python -m src.agent.<x>`）。

## 不可改动的核心逻辑（重构等价性边界）

- **`idiom_judge_agent.patent_programming_pattern_valid(sem, syn)`** —— `is_idiom` 的真值由它决定，不是 LLM 输出。规则：`max(sem,syn) >= 70 and min(sem,syn) >= 50`。
- 每个 Agent 的 **system prompt 文本、打分档位、结果 dataclass 字段、解析失败默认值**（如 `score=0`、`should_stop=True`、`merged_code=""`）必须与重构前逐字一致。新增 Agent 时 `ask_json` 返回 `None` 必须显式映射到该 Agent 的安全默认结果。
- `judge_pipeline` 与 `idiom_synthesis` **各自独立 runtime**；synthesis 内部额外持有一个 `CodeIdiomPipeline(quiet=True)` 做合并后再判定。每区域最多 `MAX_SYNTHESIS_ITERATIONS`（=3）轮合并，遇非法即停并保留上一合法结果。

## 新增一个 Agent 的步骤

1. 新建 `xxx_agent.py`：定义 `XxxRequest`/`XxxResult` dataclass + 模块级 `_SYSTEM_MESSAGE`。
2. `class XxxAgent(JsonLLMAgent)`，`__init__` 调 `super().__init__("XxxAgent", _SYSTEM_MESSAGE, model_client)`。
3. `@message_handler` 内构造 prompt → `await self.ask_json(prompt)` → `None` 与正常 dict 各自映射到 `XxxResult`。
4. 在 `__init__.py` 导出；如需独立自测，`__main__` 里调 `run_agent_selftest(...)`。
5. 在使用方 runtime `register_factory("xxx_agent", lambda: XxxAgent(client))`，`AgentId("xxx_agent", key="default")` 寻址。
