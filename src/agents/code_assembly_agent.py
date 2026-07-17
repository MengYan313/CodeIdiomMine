"""
代码组装 Agent（说明书 7.3）

接收规划合成 Agent 选定的若干代码段与当前代码，合并为语法连贯、
尽量自包含的单一代码块。
"""

from dataclasses import dataclass
from typing import List

from autogen_core import MessageContext, message_handler
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ._base import JsonLLMAgent
from ..llm.prompting import build_json_system_prompt

_SYSTEM_MESSAGE = build_json_system_prompt(
    role="你是代码组装 Agent，负责合并同一源码区域内已经选定的片段。",
    goal="生成保持原始行为、依赖顺序正确且尽量自包含的单一代码块。",
    success_criteria=(
        "保留基座代码与补充片段的有效行为，并按先定义后使用等依赖关系排序。",
        "保留 try/finally 等不可拆分结构，删除合并造成的重复声明。",
        "merged_code 是完整代码块，不省略未修改内容。",
    ),
    constraints=(
        "不得添加输入中不存在的业务逻辑、依赖或无关代码。",
        "不得用注释替代实现或掩盖语义冲突。",
    ),
    field_rules=("reason 使用简洁中文，说明关键排序、去重或冲突处理。",),
    stop_rules=(
        "若补充片段与基座代码冲突且无法在不改变行为的前提下合并，保留基座代码并在 reason 中说明。",
    ),
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "merged_code": {"type": "string", "description": "完整的合并后源码"},
        "reason": {"type": "string", "description": "排序与合并决策说明"},
    },
    "required": ["merged_code", "reason"],
    "additionalProperties": False,
}


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


class CodeAssemblyAgent(JsonLLMAgent):
    """将基座代码与若干片段按依赖与常见搭配合并为一块代码。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__(
            "CodeAssemblyAgent", _SYSTEM_MESSAGE, model_client, _RESPONSE_SCHEMA
        )

    @message_handler
    async def handle_request(
        self, message: CodeAssemblyRequest, ctx: MessageContext
    ) -> CodeAssemblyResult:
        parts = [f"### 基座代码\n```\n{message.base_code}\n```"]
        for i, seg in enumerate(message.segments_to_merge):
            parts.append(f"### 补充片段 {i + 1}\n```\n{seg}\n```")
        prompt = (
            "请把以下内容合并为一个代码块。\n\n"
            + "\n\n".join(parts)
        )

        data = await self.ask_json(prompt)
        if data is None:
            return CodeAssemblyResult(merged_code="", reason="JSON 解析失败")
        return CodeAssemblyResult(
            merged_code=str(data.get("merged_code", "")).strip(),
            reason=str(data.get("reason", "")),
        )
