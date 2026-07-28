"""多习语选择与合成规划 Agent。"""

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
    role="你是多习语合成规划 Agent，负责选择相关习语并描述可验证的合成目标。",
    goal="从同一函数或区域的候选中选择至少两个真正互补的习语，形成最小且有明确质量增益的合成计划。",
    success_criteria=(
        "选择依据是数据依赖、控制关系、资源配对、异常路径或稳定源码顺序，而不是表面相似。",
        "selected_indices 不重复且全部指向输入候选；合成时至少选择两个。",
        "计划说明顺序、共享绑定、如何使用已自动填充的同代表区域上下文及预期质量增益。",
    ),
    constraints=(
        "不得为了减少候选数量而强行合成。",
        "不得提出输入代码和允许上下文都不支持的新业务操作。",
        "阶段2合同候选若用于离线逻辑验证必须更保守，不得把聚类频率当成习语质量；正式流程不执行该分支。",
    ),
    field_rules=(
        (
            "synthesis_goal、ordering_constraints、expected_improvement 和 "
            "reason 使用中文；reason 必须说明选择或停止依据且不得为空。"
        ),
    ),
    stop_rules=(
        "找不到至少两个互补候选时 should_synthesize 为 false、selected_indices 为空。",
    ),
)
SYNTHESIS_PLANNING_PROMPT_VERSION = 3
SYNTHESIS_PLANNING_PROMPT_SHA256 = hashlib.sha256(
    _SYSTEM_MESSAGE.encode("utf-8")
).hexdigest()

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "should_synthesize": {"type": "boolean"},
        "selected_indices": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "synthesis_goal": {"type": "string"},
        "ordering_constraints": {
            "type": "array",
            "items": {"type": "string"},
        },
        "expected_improvement": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "should_synthesize",
        "selected_indices",
        "synthesis_goal",
        "ordering_constraints",
        "expected_improvement",
        "reason",
    ],
    "additionalProperties": False,
}


@dataclass
class SynthesisPlanningRequest:
    candidates: List[dict]
    context_code: str


@dataclass
class SynthesisPlanningResult:
    should_synthesize: bool
    selected_indices: List[int]
    synthesis_goal: str
    ordering_constraints: List[str]
    expected_improvement: str
    reason: str
    call_status: str = "completed"
    call_attempts: int = 1
    failure_kind: str = ""


class SynthesisPlanningAgent(JsonLLMAgent):
    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__(
            "SynthesisPlanningAgent",
            _SYSTEM_MESSAGE,
            model_client,
            _RESPONSE_SCHEMA,
        )

    @message_handler
    async def handle_request(
        self,
        message: SynthesisPlanningRequest,
        ctx: MessageContext,
    ) -> SynthesisPlanningResult:
        prompt = f"""请为以下候选制定一次合成计划。

## 候选
{json.dumps(message.candidates, ensure_ascii=False, sort_keys=True)}

## 自动填充且已验证的同代表区域上下文
```cpp
{message.context_code}
```"""
        data = await self.ask_json(prompt)
        trace = self.last_call_trace
        if data is None:
            return SynthesisPlanningResult(
                should_synthesize=False,
                selected_indices=[],
                synthesis_goal="",
                ordering_constraints=[],
                expected_improvement="",
                reason="响应解析失败，采用安全停止。",
                call_status=trace.status,
                call_attempts=trace.attempts,
                failure_kind=trace.failure_kind,
            )
        raw_indices = data.get("selected_indices") or []
        indices = sorted(
            {
                int(value)
                for value in raw_indices
                if isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value < len(message.candidates)
            }
        )
        should_synthesize = bool(data.get("should_synthesize")) and len(indices) >= 2
        if not should_synthesize:
            indices = []
        reason = str(data.get("reason") or "").strip()
        if not reason:
            return SynthesisPlanningResult(
                should_synthesize=False,
                selected_indices=[],
                synthesis_goal="",
                ordering_constraints=[],
                expected_improvement="",
                reason="规划响应缺少有效判断理由，采用安全停止。",
                call_status="failed",
                call_attempts=trace.attempts,
                failure_kind="invalid_domain_payload",
            )
        return SynthesisPlanningResult(
            should_synthesize=should_synthesize,
            selected_indices=indices,
            synthesis_goal=str(data.get("synthesis_goal") or ""),
            ordering_constraints=[
                str(value)
                for value in (data.get("ordering_constraints") or [])
            ],
            expected_improvement=str(data.get("expected_improvement") or ""),
            reason=reason,
            call_status=trace.status,
            call_attempts=trace.attempts,
            failure_kind=trace.failure_kind,
        )
