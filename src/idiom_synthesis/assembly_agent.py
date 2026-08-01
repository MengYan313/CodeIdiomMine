"""按计划合成多个习语的代码组装 Agent。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import List

from autogen_core import MessageContext, message_handler
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..agents._base import JsonLLMAgent
from ..llm.prompting import build_json_system_prompt


_SYSTEM_MESSAGE = build_json_system_prompt(
    role="你是 C++ 习语代码组装 Agent，只执行已批准的多习语合成计划。",
    goal="把选定习语合成成语义更完整、顺序正确且可复用的单一候选习语。",
    success_criteria=(
        "保留每个输入习语的必要行为、占位符绑定和前置条件。",
        "按计划处理定义—使用、资源生命周期、控制边界和异常路径。",
        "优先使用当前共现区域的实际成员代码绑定模板，并保持其稳定源码顺序。",
        "只有计划允许且内容能在已验证上下文中定位时，才能补入上下文代码。",
        "merged_code 包含完整合成结果，added_from_context 准确列出补入内容的来源说明。",
    ),
    constraints=(
        "不得添加输入习语或已验证上下文中不存在的调用、依赖和业务操作。",
        "不得用注释、伪代码或省略号替代实现。",
        "不得为追求完整而改变原始行为或掩盖冲突。",
    ),
    field_rules=(
        "added_from_context 和 reason 使用中文，reason 必须说明组装依据且不得为空。",
    ),
    stop_rules=(
        "计划冲突或证据不足时 merged_code 返回空字符串，并在 reason 中说明。",
    ),
)
IDIOM_ASSEMBLY_PROMPT_VERSION = 4
IDIOM_ASSEMBLY_PROMPT_SHA256 = hashlib.sha256(
    _SYSTEM_MESSAGE.encode("utf-8")
).hexdigest()

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "merged_code": {"type": "string"},
        "used_context": {"type": "boolean"},
        "added_from_context": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reason": {"type": "string"},
    },
    "required": [
        "merged_code",
        "used_context",
        "added_from_context",
        "reason",
    ],
    "additionalProperties": False,
}


@dataclass
class IdiomAssemblyRequest:
    selected_idioms: List[dict]
    plan: dict
    context_code: str


@dataclass
class IdiomAssemblyResult:
    merged_code: str
    used_context: bool
    added_from_context: List[str]
    reason: str
    call_status: str = "completed"
    call_attempts: int = 1
    failure_kind: str = ""


class IdiomAssemblyAgent(JsonLLMAgent):
    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__(
            "IdiomAssemblyAgent",
            _SYSTEM_MESSAGE,
            model_client,
            _RESPONSE_SCHEMA,
        )

    @message_handler
    async def handle_request(
        self,
        message: IdiomAssemblyRequest,
        ctx: MessageContext,
    ) -> IdiomAssemblyResult:
        prompt = f"""请严格按计划合成以下习语。

## 合成计划
{json.dumps(message.plan, ensure_ascii=False, sort_keys=True)}

## 选定习语及其当前区域成员
{json.dumps(message.selected_idioms, ensure_ascii=False, sort_keys=True)}

## 允许使用的成员共现区域上下文
```cpp
{message.context_code}
```"""
        data = await self.ask_json(prompt)
        trace = self.last_call_trace
        if data is None:
            return IdiomAssemblyResult(
                merged_code="",
                used_context=False,
                added_from_context=[],
                reason="响应解析失败。",
                call_status=trace.status,
                call_attempts=trace.attempts,
                failure_kind=trace.failure_kind,
            )
        used_context = data["used_context"]
        reason = data["reason"].strip()
        if not reason:
            return IdiomAssemblyResult(
                merged_code="",
                used_context=False,
                added_from_context=[],
                reason="组装响应缺少有效依据，采用安全停止。",
                call_status="failed",
                call_attempts=trace.attempts,
                failure_kind="invalid_domain_payload",
            )
        return IdiomAssemblyResult(
            merged_code=data["merged_code"].strip(),
            used_context=used_context,
            added_from_context=(
                data["added_from_context"] if used_context else []
            ),
            reason=reason,
            call_status=trace.status,
            call_attempts=trace.attempts,
            failure_kind=trace.failure_kind,
        )
