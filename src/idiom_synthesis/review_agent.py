"""合成结果质量增益与忠实性复审 Agent。"""

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
    role="你是多习语合成结果的独立质量复审 Agent。",
    goal="判断合成结果是否忠实覆盖所选习语，并相对独立习语产生明确、可复查的质量增益。",
    success_criteria=(
        "检查原始意图、控制顺序、数据绑定、前置条件和异常/清理职责是否保留。",
        "区分真正的语义完整性提升与单纯代码变长、拼接或重复。",
        "列出所有不能由输入习语或允许上下文支持的新增内容。",
        "quality_score 范围为 0–100。",
    ),
    constraints=(
        "不得因代码更长或格式更整齐就认定质量提高。",
        "任何未支持的业务调用、行为变化或丢失的必要职责都必须反映为低分和明确问题。",
    ),
    field_rules=(
        "unsupported_additions、issues 和 reason 使用中文。",
    ),
    stop_rules=(
        "证据不足或依赖未提供的外部语义时降低 quality_score。",
    ),
)
SYNTHESIS_REVIEW_PROMPT_VERSION = 1
SYNTHESIS_REVIEW_PROMPT_SHA256 = hashlib.sha256(
    _SYSTEM_MESSAGE.encode("utf-8")
).hexdigest()

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "quality_score": {"type": "number"},
        "improves_quality": {"type": "boolean"},
        "preserves_intents": {"type": "boolean"},
        "unsupported_additions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "issues": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reason": {"type": "string"},
    },
    "required": [
        "quality_score",
        "improves_quality",
        "preserves_intents",
        "unsupported_additions",
        "issues",
        "reason",
    ],
    "additionalProperties": False,
}


@dataclass
class SynthesisReviewRequest:
    source_idioms: List[dict]
    plan: dict
    merged_code: str
    context_code: str
    assembly_evidence: dict


@dataclass
class SynthesisReviewResult:
    quality_score: float
    improves_quality: bool
    preserves_intents: bool
    unsupported_additions: List[str]
    issues: List[str]
    reason: str
    call_status: str = "completed"
    call_attempts: int = 1
    failure_kind: str = ""


class SynthesisReviewAgent(JsonLLMAgent):
    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__(
            "SynthesisReviewAgent",
            _SYSTEM_MESSAGE,
            model_client,
            _RESPONSE_SCHEMA,
        )

    @message_handler
    async def handle_request(
        self,
        message: SynthesisReviewRequest,
        ctx: MessageContext,
    ) -> SynthesisReviewResult:
        prompt = f"""请独立复审以下合成结果。

## 来源习语
{json.dumps(message.source_idioms, ensure_ascii=False, sort_keys=True)}

## 合成计划
{json.dumps(message.plan, ensure_ascii=False, sort_keys=True)}

## 合成结果
```cpp
{message.merged_code}
```

## 允许上下文
```cpp
{message.context_code}
```

## 组装证据
{json.dumps(message.assembly_evidence, ensure_ascii=False, sort_keys=True)}"""
        data = await self.ask_json(prompt)
        trace = self.last_call_trace
        if data is None:
            return SynthesisReviewResult(
                quality_score=0.0,
                improves_quality=False,
                preserves_intents=False,
                unsupported_additions=[],
                issues=["响应解析失败"],
                reason="不能自动确认合成质量。",
                call_status=trace.status,
                call_attempts=trace.attempts,
                failure_kind=trace.failure_kind,
            )
        try:
            score = max(0.0, min(100.0, float(data.get("quality_score", 0))))
        except (TypeError, ValueError):
            score = 0.0
        return SynthesisReviewResult(
            quality_score=score,
            improves_quality=bool(data.get("improves_quality")),
            preserves_intents=bool(data.get("preserves_intents")),
            unsupported_additions=[
                str(value)
                for value in (data.get("unsupported_additions") or [])
            ],
            issues=[str(value) for value in (data.get("issues") or [])],
            reason=str(data.get("reason") or ""),
            call_status=trace.status,
            call_attempts=trace.attempts,
            failure_kind=trace.failure_kind,
        )
