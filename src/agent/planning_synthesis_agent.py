"""
规划合成 Agent（说明书 7.3）

在暂不接入工具调用的前提下，由调用方把本区域内其余已通过判定的代码段
作为列表传入；本 Agent 决策是否继续合成、本轮合并哪些候选（可多个）、
并给出简要理由。具体合并由代码组装 Agent 完成。
"""

import json
from dataclasses import dataclass
from typing import List

from autogen_core import RoutedAgent, message_handler, MessageContext
from autogen_core.models import SystemMessage, UserMessage, LLMMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..utils.response_parser import extract_tag_content
from ..logger import get_logger

logger = get_logger(__name__)


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


class PlanningSynthesisAgent(RoutedAgent):
    """规划合成 Agent：决定停止或选择本轮要并入的候选下标。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__("PlanningSynthesisAgent")
        self._model_client = model_client
        self._system_message = """You are a planning agent for merging code idioms from the SAME source region (same file/function context).

The user message contains:
- The current merged code (anchor).
- A numbered list of other valid idioms in this region (indices 0..n-1).
- Current merge iteration index and a hard maximum number of merge rounds.

Your job:
1. Decide whether to STOP (no more beneficial merge, or no candidates left, or context already complete).
2. If not stopping, choose which candidate(s) to merge into the current code THIS round. You may select one or several indices.
3. Prefer idioms that are semantically related, common pairings (try/finally, init/cleanup), or share variables with the current code.

Output ONLY valid JSON wrapped in [JSON] and [/JSON] tags:
{
    "should_stop": boolean,
    "selected_indices": [integer, ...],
    "reason": "short explanation"
}

Rules:
- If should_stop is true, selected_indices should be [].
- selected_indices must only contain valid indices for the given candidate list (0 to n-1).
- If the candidate list is empty, set should_stop to true."""

    @message_handler
    async def handle_request(
        self,
        message: PlanningSynthesisRequest,
        ctx: MessageContext,
    ) -> PlanningSynthesisResult:
        if not message.candidate_snippets:
            return PlanningSynthesisResult(
                should_stop=True,
                selected_indices=[],
                reason="No candidates in region.",
            )

        numbered = "\n\n".join(
            f"### Candidate index {i}\n```\n{c}\n```"
            for i, c in enumerate(message.candidate_snippets)
        )
        prompt = f"""Source region label: {message.loc_label or "(unknown)"}

Merge iteration: {message.iteration_index + 1} / {message.max_iterations} (hard cap).

## Current code (anchor)
```
{message.current_code}
```

## Other valid idioms in this region (choose indices to merge this round)
{numbered}

Should you stop, or which indices (0..{len(message.candidate_snippets) - 1}) should be merged next? Return JSON in [JSON] tags."""

        messages: List[LLMMessage] = [
            SystemMessage(content=self._system_message),
            UserMessage(content=prompt, source="user"),
        ]
        response = await self._model_client.create(
            messages=messages,
            extra_create_args={"temperature": 0.0},
        )
        text = response.content
        try:
            raw = extract_tag_content(
                text, "JSON", default="", logger_instance=logger
            ) or text
            data = json.loads(raw)
            stop = bool(data.get("should_stop", True))
            idxs = data.get("selected_indices") or []
            if not isinstance(idxs, list):
                idxs = []
            out: List[int] = []
            for x in idxs:
                try:
                    i = int(x)
                except (TypeError, ValueError):
                    continue
                if 0 <= i < len(message.candidate_snippets):
                    out.append(i)
            out = sorted(set(out))
            if stop:
                out = []
            return PlanningSynthesisResult(
                should_stop=stop or not out,
                selected_indices=out if not stop else [],
                reason=str(data.get("reason", "")),
            )
        except Exception as e:
            logger.error("PlanningSynthesis parse error: %s", e)
            return PlanningSynthesisResult(
                should_stop=True,
                selected_indices=[],
                reason=f"parse_error: {e}",
            )
