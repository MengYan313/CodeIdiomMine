"""多习语选择与合成规划 Agent。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

from autogen_core import MessageContext, message_handler
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..agents.base import JsonLLMAgent
from ..llm.prompting import build_json_system_prompt


_SYSTEM_MESSAGE = build_json_system_prompt(
    role="你是多习语合成规划 Agent，负责一次审查同一区域的全部候选。",
    goal=(
        "在显式计划上限内，一次性返回所有具有明确语义关系且值得尝试的"
        "候选组合。"
    ),
    success_criteria=(
        (
            "每个计划由数据依赖、控制关系、生命周期配对、异常处理关系或稳定"
            "源码顺序支持，不以表面相似或数学子集枚举代替语义判断。"
        ),
        "每个计划的 selected_indices 至少标识两个不同候选。",
        "不同计划可以共享候选，但候选集合完全相同的计划只返回一次。",
        "使用 matched_occurrences 判断候选在当前共现区域中的局部代码和源码顺序。",
        (
            "每个计划分别说明 relation_kind、合成目标、顺序约束、预期质量增益"
            "和选择依据。"
        ),
    ),
    constraints=(
        "必须同时审查输入区域内的全部候选，不得每次只返回一组后要求继续调用。",
        "不得为了减少候选数量而强行合成或枚举缺乏语义关系的任意子集。",
        "不得提出输入代码和允许上下文都不支持的新业务操作。",
        "阶段2合同候选若用于离线逻辑验证必须更保守，不得把聚类频率当成习语质量；正式流程不执行该分支。",
    ),
    field_rules=(
        (
            "plans 中每项的 relation_kind、synthesis_goal、ordering_constraints、"
            "expected_improvement 和 reason 均不得为空并使用中文。"
        ),
        "顶层 reason 概括计划覆盖情况或没有有效计划的原因且不得为空。",
    ),
    stop_rules=(
        "一次返回不超过 max_plans_per_region 的 plans 后停止；找不到有效组合时返回空 plans。",
    ),
)
DEFAULT_MAX_PLANS_PER_REGION = 8


def planning_response_schema(max_plans_per_region: int) -> dict:
    plan_properties = {
        "selected_indices": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "relation_kind": {"type": "string", "minLength": 1},
        "synthesis_goal": {"type": "string", "minLength": 1},
        "ordering_constraints": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "expected_improvement": {"type": "string", "minLength": 1},
        "reason": {"type": "string", "minLength": 1},
    }
    return {
        "type": "object",
        "properties": {
            "plans": {
                "type": "array",
                "maxItems": max_plans_per_region,
                "items": {
                    "type": "object",
                    "properties": plan_properties,
                    "required": list(plan_properties),
                    "additionalProperties": False,
                },
            },
            "reason": {"type": "string", "minLength": 1},
        },
        "required": ["plans", "reason"],
        "additionalProperties": False,
    }


_RESPONSE_SCHEMA = planning_response_schema(DEFAULT_MAX_PLANS_PER_REGION)


@dataclass
class SynthesisPlanningRequest:
    candidates: List[dict]
    context_code: str
    max_plans_per_region: int


@dataclass(frozen=True)
class SynthesisPlan:
    selected_indices: List[int]
    relation_kind: str
    synthesis_goal: str
    ordering_constraints: List[str]
    expected_improvement: str
    reason: str


@dataclass
class SynthesisPlanningResult:
    plans: List[SynthesisPlan]
    reason: str
    call_status: str = "completed"
    call_attempts: int = 1
    failure_kind: str = ""


class SynthesisPlanningAgent(JsonLLMAgent):
    def __init__(
        self,
        model_client: OpenAIChatCompletionClient,
        max_plans_per_region: int = DEFAULT_MAX_PLANS_PER_REGION,
    ):
        super().__init__(
            "SynthesisPlanningAgent",
            _SYSTEM_MESSAGE,
            model_client,
            planning_response_schema(max_plans_per_region),
        )

    @message_handler
    async def handle_request(
        self,
        message: SynthesisPlanningRequest,
        ctx: MessageContext,
    ) -> SynthesisPlanningResult:
        prompt = f"""请一次审查以下区域内的全部候选，并批量制定合成计划。

最多返回 {message.max_plans_per_region} 个计划。不要枚举缺乏明确语义关系的数学子集。

## 候选
{json.dumps(message.candidates, ensure_ascii=False, sort_keys=True)}

## 自动填充且已验证的成员共现区域上下文
```cpp
{message.context_code}
```"""
        data = await self.ask_json(prompt)
        trace = self.last_call_trace
        if data is None:
            return SynthesisPlanningResult(
                plans=[],
                reason="响应解析失败，采用安全停止。",
                call_status=trace.status,
                call_attempts=trace.attempts,
                failure_kind=trace.failure_kind,
            )
        reason = data["reason"].strip()
        if not reason:
            return SynthesisPlanningResult(
                plans=[],
                reason="规划响应缺少有效判断理由，采用安全停止。",
                call_status="failed",
                call_attempts=trace.attempts,
                failure_kind="invalid_domain_payload",
            )
        plans = [
            SynthesisPlan(
                selected_indices=plan["selected_indices"],
                relation_kind=plan["relation_kind"].strip(),
                synthesis_goal=plan["synthesis_goal"].strip(),
                ordering_constraints=[
                    constraint.strip()
                    for constraint in plan["ordering_constraints"]
                ],
                expected_improvement=(
                    plan["expected_improvement"].strip()
                ),
                reason=plan["reason"].strip(),
            )
            for plan in data["plans"]
        ]
        if len(plans) > message.max_plans_per_region:
            return SynthesisPlanningResult(
                plans=plans,
                reason="规划响应超过显式计划上限，未执行任何计划。",
                call_status="failed",
                call_attempts=trace.attempts,
                failure_kind="plan_limit_exceeded",
            )
        return SynthesisPlanningResult(
            plans=plans,
            reason=reason,
            call_status=trace.status,
            call_attempts=trace.attempts,
            failure_kind=trace.failure_kind,
        )
