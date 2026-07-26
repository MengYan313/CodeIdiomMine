"""单簇语义、复用价值与规则候选抽象决策 Agent。"""

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
    role="你是 C++ 代码习语语义与抽象决策专家，审查一个聚类簇是否表达稳定且值得复用的单一意图。",
    goal=(
        "判断该簇能否成为候选习语，并在规则已经筛出的候选范围内决定保持原代码"
        "或执行语义安全的抽象。"
    ),
    success_criteria=(
        "区分高频代码与具有稳定意图、完整边界和复用价值的代码习语。",
        "semantic_score 衡量意图稳定性与完整性，reuse_score 衡量复用价值，范围均为 0–100。",
        "审查完整簇成员、规则初步证据和全部抽象提案，而不是只根据代表代码判断。",
        "abstraction_decision 为 abstract 时，approved_abstraction_ids 至少包含一个输入提案中确实不影响意图、约束、API 与控制语义的编号。",
        "不应抽象或规则没有提案时返回 keep；keep 只拒绝抽象，不代表拒绝该习语。",
        "明确给出 intent 和可由输入证据支持的 preconditions。",
    ),
    constraints=(
        "调用名、类型、控制条件、返回值、哨兵值和错误码默认具有语义，不因多个实例不同就批准抽象。",
        "只能批准规则提供的 proposal_id，不得自行新增抽象位置、占位符或改写代码。",
        "不得编造源码外的业务背景、类型关系或运行时行为。",
        "纯样板、过度项目化、语义不完整或只有表面词法相似的簇必须反映为低分。",
    ),
    field_rules=(
        "intent、preconditions、abstraction_reason 和 reason 使用中文。",
    ),
    stop_rules=(
        "证据不足或依赖未提供的项目约定时降低 semantic_score 与 reuse_score。",
    ),
)
SEMANTIC_REVIEW_PROMPT_VERSION = 1
SEMANTIC_REVIEW_PROMPT_SHA256 = hashlib.sha256(
    _SYSTEM_MESSAGE.encode("utf-8")
).hexdigest()

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "semantic_score": {"type": "number"},
        "reuse_score": {"type": "number"},
        "intent": {"type": "string"},
        "preconditions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "abstraction_decision": {
            "type": "string",
            "enum": ["abstract", "keep"],
        },
        "approved_abstraction_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "abstraction_reason": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "semantic_score",
        "reuse_score",
        "intent",
        "preconditions",
        "abstraction_decision",
        "approved_abstraction_ids",
        "abstraction_reason",
        "reason",
    ],
    "additionalProperties": False,
}


def _score(value: object) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


@dataclass
class SemanticReviewRequest:
    project: str
    cluster_id: str
    representative_code: str
    cluster_members: List[str]
    rule_evidence: dict
    abstraction_proposals: List[dict]
    context_code: str = ""


@dataclass
class SemanticReviewResult:
    semantic_score: float
    reuse_score: float
    intent: str
    preconditions: List[str]
    abstraction_decision: str
    approved_abstraction_ids: List[str]
    abstraction_reason: str
    reason: str
    call_status: str = "completed"
    call_attempts: int = 1
    failure_kind: str = ""


class SemanticReviewAgent(JsonLLMAgent):
    """审查单个簇的稳定语义、复用价值和抽象安全性。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__(
            "SemanticReviewAgent",
            _SYSTEM_MESSAGE,
            model_client,
            _RESPONSE_SCHEMA,
        )

    @message_handler
    async def handle_request(
        self,
        message: SemanticReviewRequest,
        ctx: MessageContext,
    ) -> SemanticReviewResult:
        members = "\n\n".join(
            f"### 簇成员 {index + 1}\n```cpp\n{code}\n```"
            for index, code in enumerate(message.cluster_members)
        )
        prompt = f"""请审查以下同仓库单个聚类簇。

项目：{message.project}
簇编号：{message.cluster_id}

## 代表代码
```cpp
{message.representative_code}
```

## 完整簇成员（共 {len(message.cluster_members)} 个）
{members or "（簇成员缺失）"}

## 确定性规则证据
{json.dumps(message.rule_evidence, ensure_ascii=False, sort_keys=True)}

## 保守抽象提案
{json.dumps(message.abstraction_proposals, ensure_ascii=False, sort_keys=True)}

## 自动填充且通过来源哈希验证的代表函数/区域上下文
```cpp
{message.context_code or "（未提供经验证的源码上下文）"}
```

若规则提案为空，或任何提案会损害稳定语义，请返回 keep。只有确实属于高频、
无意义局部差异的提案才可返回 abstract 并列入 approved_abstraction_ids。"""
        data = await self.ask_json(prompt)
        trace = self.last_call_trace
        if data is None:
            return SemanticReviewResult(
                semantic_score=0.0,
                reuse_score=0.0,
                intent="",
                preconditions=[],
                abstraction_decision="keep",
                approved_abstraction_ids=[],
                abstraction_reason="响应解析失败，保持代表代码不变。",
                reason="响应解析失败，不能自动接受该簇。",
                call_status=trace.status,
                call_attempts=trace.attempts,
                failure_kind=trace.failure_kind,
            )
        allowed = {
            str(proposal.get("proposal_id"))
            for proposal in message.abstraction_proposals
        }
        approved_ids = sorted(
            {
                str(value)
                for value in (data.get("approved_abstraction_ids") or [])
                if str(value) in allowed
            }
        )
        decision = str(data.get("abstraction_decision") or "keep")
        if (
            decision != "abstract"
            or not message.abstraction_proposals
            or not approved_ids
        ):
            decision = "keep"
            approved_ids = []
        return SemanticReviewResult(
            semantic_score=_score(data.get("semantic_score")),
            reuse_score=_score(data.get("reuse_score")),
            intent=str(data.get("intent") or ""),
            preconditions=[
                str(value) for value in (data.get("preconditions") or [])
            ],
            abstraction_decision=decision,
            approved_abstraction_ids=approved_ids,
            abstraction_reason=str(data.get("abstraction_reason") or ""),
            reason=str(data.get("reason") or ""),
            call_status=trace.status,
            call_attempts=trace.attempts,
            failure_kind=trace.failure_kind,
        )
