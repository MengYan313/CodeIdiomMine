"""合成结果质量增益与忠实性复审 Agent。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import List

from autogen_core import MessageContext, message_handler
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..agents.base import JsonLLMAgent
from ..idiom_judgment.idiom_taxonomy import (
    IDIOM_CLASSIFICATION_RESPONSE_SCHEMA,
    IdiomClassification,
    empty_idiom_classification,
    normalize_idiom_classification,
    render_idiom_catalog_for_prompt,
)
from ..llm.prompting import build_json_system_prompt

_IDIOM_CATALOG_TEXT = render_idiom_catalog_for_prompt()

_SYSTEM_MESSAGE = build_json_system_prompt(
    role="你是多习语合成结果的独立质量、有效性与类型复审 Agent。",
    goal=(
        "判断合成结果是否仍属于代码习语、是否忠实覆盖所选习语，并相对"
        "独立习语产生明确、可复查的质量增益。"
    ),
    success_criteria=(
        (
            "结合 matched_occurrences 检查当前区域中的原始意图、控制顺序、"
            "数据绑定、前置条件和异常/清理职责是否保留。"
        ),
        "区分真正的语义完整性提升与单纯代码变长、拼接或重复。",
        "列出所有不能由输入习语或允许上下文支持的新增内容。",
        "quality_score 范围为 0–100。",
        "is_idiom 明确表示合成结果是否属于代码习语，reason 简要给出可复查依据。",
        (
            "若 is_idiom 为 true，idiom_classification 必须选择至多三个"
            "确切目录类型；无法可靠对应时归为 repository_specific。"
        ),
        f"已知 C++ 习语目录：\n{_IDIOM_CATALOG_TEXT}",
    ),
    constraints=(
        "不得因代码更长或格式更整齐就认定质量提高。",
        "任何未支持的业务调用、行为变化或丢失的必要职责都必须反映为低分和明确问题。",
        (
            "is_idiom 为 false 时 idiom_classification.kind 必须为 "
            "not_applicable 且 catalog_ids 为空。"
        ),
        (
            "is_idiom 为 true 且无法与目录精确对应时，kind 必须为 "
            "repository_specific 且 catalog_ids 为空，不得强行套用相近标签。"
        ),
    ),
    field_rules=(
        (
            "unsupported_additions、issues、reason 和 "
            "idiom_classification.reason 使用中文，reason 不得为空。"
        ),
    ),
    stop_rules=(
        "证据不足或依赖未提供的外部语义时降低 quality_score。",
    ),
)
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_idiom": {"type": "boolean"},
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
        "idiom_classification": IDIOM_CLASSIFICATION_RESPONSE_SCHEMA,
        "reason": {"type": "string"},
    },
    "required": [
        "is_idiom",
        "quality_score",
        "improves_quality",
        "preserves_intents",
        "unsupported_additions",
        "issues",
        "idiom_classification",
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
    is_idiom: bool
    quality_score: float
    improves_quality: bool
    preserves_intents: bool
    unsupported_additions: List[str]
    issues: List[str]
    idiom_classification: IdiomClassification
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
                is_idiom=False,
                quality_score=0.0,
                improves_quality=False,
                preserves_intents=False,
                unsupported_additions=[],
                issues=["响应解析失败"],
                idiom_classification=empty_idiom_classification(
                    "响应解析失败，未执行合成习语类型判断。"
                ),
                reason="不能自动确认合成质量。",
                call_status=trace.status,
                call_attempts=trace.attempts,
                failure_kind=trace.failure_kind,
            )
        score = data["quality_score"]
        score = max(0.0, min(100.0, score)) if math.isfinite(score) else 0.0
        is_idiom = data["is_idiom"]
        classification, invalid_classification = (
            normalize_idiom_classification(
                data["idiom_classification"],
                is_idiom=is_idiom,
            )
        )
        reason = data["reason"].strip()
        if invalid_classification or not reason:
            return SynthesisReviewResult(
                is_idiom=False,
                quality_score=0.0,
                improves_quality=False,
                preserves_intents=False,
                unsupported_additions=[],
                issues=["习语类型或判断理由字段无效"],
                idiom_classification=empty_idiom_classification(
                    "响应中的合成习语类型字段未通过确定性校验。"
                ),
                reason="质量复审缺少有效理由或类型字段无效，采用安全拒绝。",
                call_status="failed",
                call_attempts=trace.attempts,
                failure_kind="invalid_domain_payload",
            )
        return SynthesisReviewResult(
            is_idiom=is_idiom,
            quality_score=score,
            improves_quality=data["improves_quality"],
            preserves_intents=data["preserves_intents"],
            unsupported_additions=data["unsupported_additions"],
            issues=data["issues"],
            idiom_classification=classification,
            reason=reason,
            call_status=trace.status,
            call_attempts=trace.attempts,
            failure_kind=trace.failure_kind,
        )
