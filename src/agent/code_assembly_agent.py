"""
代码组装 Agent（说明书 7.3）

接收规划合成 Agent 选定的若干代码段与当前代码，合并为语法连贯、
尽量自包含的单一代码块。
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
class CodeAssemblyRequest:
    """代码组装请求。"""

    base_code: str
    segments_to_merge: List[str]


@dataclass
class CodeAssemblyResult:
    """代码组装结果。"""

    merged_code: str
    reason: str


class CodeAssemblyAgent(RoutedAgent):
    """将基座代码与若干片段按依赖与常见搭配合并为一块代码。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__("CodeAssemblyAgent")
        self._model_client = model_client
        self._system_message = """You are a code assembly agent. Merge the given base code snippet with additional snippet(s) from the same source region into ONE coherent code block.

Rules:
- Preserve logical order and dependencies (definitions before use, try/finally structure, etc.).
- Remove redundant duplicate declarations when merging.
- Keep the result as self-contained as possible for the merged logic.
- Do not add unrelated code or comments that change behavior.

Respond with JSON inside [JSON] and [/JSON] only:
{
    "merged_code": "full merged source string",
    "reason": "brief note on ordering / merge decisions"
}"""

    @message_handler
    async def handle_request(
        self,
        message: CodeAssemblyRequest,
        ctx: MessageContext,
    ) -> CodeAssemblyResult:
        parts = [f"### Base\n```\n{message.base_code}\n```"]
        for i, seg in enumerate(message.segments_to_merge):
            parts.append(f"### Segment {i + 1}\n```\n{seg}\n```")
        prompt = (
            "Merge the following into a single code block.\n\n"
            + "\n\n".join(parts)
            + "\n\nReturn JSON with [JSON] tags."
        )
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
            merged = str(data.get("merged_code", "")).strip()
            reason = str(data.get("reason", ""))
            return CodeAssemblyResult(merged_code=merged, reason=reason)
        except Exception as e:
            logger.error("CodeAssembly parse error: %s", e)
            return CodeAssemblyResult(merged_code="", reason=f"parse_error: {e}")
