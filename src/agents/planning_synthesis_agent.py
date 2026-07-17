"""
规划合成 Agent（说明书 7.3）

在暂不接入工具调用的前提下，由调用方把本区域内其余已通过判定的代码段
作为列表传入；本 Agent 决策是否继续合成、本轮合并哪些候选（可多个）、
并给出简要理由。具体合并由代码组装 Agent 完成。
"""

from dataclasses import dataclass
from typing import List

from autogen_core import MessageContext, message_handler
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ._base import JsonLLMAgent
from ..llm.prompting import build_json_system_prompt

_SYSTEM_MESSAGE = build_json_system_prompt(
    role="你是代码习语的规划合成 Agent，只处理同一文件或函数上下文中的候选。",
    goal="决定本轮是否停止；若继续，只选择能够安全补全当前代码的候选。",
    success_criteria=(
        "优先选择与当前代码共享数据依赖、控制流或成对职责的候选，例如初始化/清理和 try/finally。",
        "选择能够形成更完整习语的最小候选集合，不因候选存在就强行合并。",
        "selected_indices 只包含当前列表中的有效下标，且不重复。",
    ),
    constraints=(
        "不同源码区域、相互冲突或只具表面相似性的片段不得合并。",
        "不得改写代码；本 Agent 只作选择和停止决策。",
    ),
    field_rules=("reason 使用简洁中文。",),
    stop_rules=(
        "候选为空、当前代码已经完整或没有候选能带来明确收益时，should_stop 为 true 且 selected_indices 为空数组。",
        "决定继续时，should_stop 为 false 且 selected_indices 至少包含一个有效下标。",
    ),
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "should_stop": {"type": "boolean", "description": "是否停止合成"},
        "selected_indices": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "本轮合并的候选下标",
        },
        "reason": {"type": "string", "description": "决策理由"},
    },
    "required": ["should_stop", "selected_indices", "reason"],
    "additionalProperties": False,
}


@dataclass
class PlanningSynthesisRequest:
    """规划合成请求（候选由编排层注入，等价于工具查询结果）。"""

    current_code: str
    candidate_snippets: List[str]
    iteration_index: int
    max_iterations: int
    loc_label: str = ""


@dataclass
class PlanningSynthesisResult:
    """规划合成结果。"""

    should_stop: bool
    selected_indices: List[int]
    reason: str


class PlanningSynthesisAgent(JsonLLMAgent):
    """规划合成 Agent：决定停止或选择本轮要并入的候选下标。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__(
            "PlanningSynthesisAgent", _SYSTEM_MESSAGE, model_client, _RESPONSE_SCHEMA
        )

    @message_handler
    async def handle_request(
        self, message: PlanningSynthesisRequest, ctx: MessageContext
    ) -> PlanningSynthesisResult:
        if not message.candidate_snippets:
            return PlanningSynthesisResult(
                should_stop=True,
                selected_indices=[],
                reason="当前区域没有候选。",
            )

        numbered = "\n\n".join(
            f"### 候选下标 {i}\n```\n{c}\n```"
            for i, c in enumerate(message.candidate_snippets)
        )
        prompt = f"""源码区域标签：{message.loc_label or "（未知）"}

合并轮次：{message.iteration_index + 1} / {message.max_iterations}（硬上限）。

## 当前代码（锚点）
```
{message.current_code}
```

## 当前区域的其他有效习语（选择本轮合并的下标）
{numbered}

请判断是否停止；若继续，选择下一步要合并的下标（0..{len(message.candidate_snippets) - 1}）。"""

        data = await self.ask_json(prompt)
        if data is None:
            return PlanningSynthesisResult(
                should_stop=True, selected_indices=[], reason="JSON 解析失败"
            )

        stop = bool(data.get("should_stop", True))
        raw_idxs = data.get("selected_indices") or []
        if not isinstance(raw_idxs, list):
            raw_idxs = []
        valid: List[int] = []
        for x in raw_idxs:
            try:
                i = int(x)
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(message.candidate_snippets):
                valid.append(i)
        valid = sorted(set(valid))
        if stop:
            valid = []
        return PlanningSynthesisResult(
            should_stop=stop or not valid,
            selected_indices=valid if not stop else [],
            reason=str(data.get("reason", "")),
        )
