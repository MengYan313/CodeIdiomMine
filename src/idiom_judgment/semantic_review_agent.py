"""单簇语义、复用价值与规则候选抽象决策 Agent。"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import List

from autogen_core import MessageContext, message_handler
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..agents._base import JsonLLMAgent
from ..llm.prompting import build_json_system_prompt
from .idiom_taxonomy import (
    IDIOM_CLASSIFICATION_RESPONSE_SCHEMA,
    IdiomClassification,
    empty_idiom_classification,
    normalize_idiom_classification,
    render_idiom_catalog_for_prompt,
)

_IDIOM_CATALOG_TEXT = render_idiom_catalog_for_prompt()

_SYSTEM_MESSAGE = build_json_system_prompt(
    role=(
        "你是 C++ 代码习语语义、类型与抽象决策专家，审查一个聚类簇是否"
        "表达稳定且值得复用的单一意图。"
    ),
    goal=(
        "判断该簇能否成为候选习语，并在规则已经筛出的候选范围内决定保持原代码"
        "或执行语义安全的抽象。"
    ),
    success_criteria=(
        "区分高频代码与具有稳定意图、完整边界和复用价值的代码习语。",
        "semantic_score 衡量意图稳定性与完整性，reuse_score 衡量复用价值，范围均为 0–100。",
        "审查代表代码、按 C++ 词法 token 去重的代码变体和支持度统计。",
        "规则初步证据和抽象提案只用于约束裁决，不得把它们当作额外源码实例。",
        "abstraction_decision 为 abstract 时，approved_abstraction_ids 至少包含一个输入提案中确实不影响意图、约束、API 与控制语义的编号。",
        "不应抽象或规则没有提案时返回 keep；keep 只拒绝抽象，不代表拒绝该习语。",
        "明确给出 intent 和可由输入证据支持的 preconditions。",
        "is_idiom 明确表示语义审查结论，reason 简要说明支持该结论的输入证据。",
        (
            "若 is_idiom 为 true，idiom_classification 必须在以下目录中选择"
            "至多三个确切匹配，或在无法可靠对应时归为 repository_specific；"
            "不得为了获得已知标签而强行近似匹配。"
        ),
        f"已知 C++ 习语目录：\n{_IDIOM_CATALOG_TEXT}",
    ),
    constraints=(
        "调用名、类型、控制条件、返回值、哨兵值和错误码默认具有语义，不因多个实例不同就批准抽象。",
        "只能批准规则提供的 proposal_id，不得自行新增抽象位置、占位符或改写代码。",
        "不得编造源码外的业务背景、类型关系或运行时行为。",
        "纯样板、过度项目化、语义不完整或只有表面词法相似的簇必须反映为低分。",
        (
            "is_idiom 为 false 时 idiom_classification.kind 必须为 "
            "not_applicable 且 catalog_ids 为空。"
        ),
        (
            "is_idiom 为 true 且不能与目录精确对应时，kind 必须为 "
            "repository_specific 且 catalog_ids 为空。"
        ),
    ),
    field_rules=(
        (
            "intent、preconditions、abstraction_reason、reason 和 "
            "idiom_classification.reason 使用中文，reason 不得为空。"
        ),
    ),
    stop_rules=(
        "证据不足或依赖未提供的项目约定时降低 semantic_score 与 reuse_score。",
    ),
)
SEMANTIC_REVIEW_PROMPT_VERSION = 3
SEMANTIC_REVIEW_PROMPT_SHA256 = hashlib.sha256(
    _SYSTEM_MESSAGE.encode("utf-8")
).hexdigest()

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_idiom": {"type": "boolean"},
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
        "idiom_classification": IDIOM_CLASSIFICATION_RESPONSE_SCHEMA,
        "reason": {"type": "string"},
    },
    "required": [
        "is_idiom",
        "semantic_score",
        "reuse_score",
        "intent",
        "preconditions",
        "abstraction_decision",
        "approved_abstraction_ids",
        "abstraction_reason",
        "idiom_classification",
        "reason",
    ],
    "additionalProperties": False,
}


def _score(value: float) -> float:
    return max(0.0, min(100.0, value)) if math.isfinite(value) else 0.0


@dataclass
class SemanticReviewRequest:
    project: str
    cluster_id: str
    representative_code: str
    code_variants: List[str]
    cluster_statistics: dict
    rule_evidence: dict
    abstraction_proposals: List[dict]


@dataclass
class SemanticReviewResult:
    is_idiom: bool
    semantic_score: float
    reuse_score: float
    intent: str
    preconditions: List[str]
    abstraction_decision: str
    approved_abstraction_ids: List[str]
    abstraction_reason: str
    idiom_classification: IdiomClassification
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
        variants = "\n\n".join(
            f"### 代码变体 {index + 1}\n```cpp\n{code}\n```"
            for index, code in enumerate(message.code_variants)
        )
        prompt = f"""请审查以下同仓库单个聚类簇。

项目：{message.project}
簇编号：{message.cluster_id}

## 代表代码
```cpp
{message.representative_code}
```

## 去重后的其他代码变体（共 {len(message.code_variants)} 个）
{variants or "（无其他词法变体）"}

## 簇统计
{json.dumps(message.cluster_statistics, ensure_ascii=False, sort_keys=True)}

## 确定性规则证据
{json.dumps(message.rule_evidence, ensure_ascii=False, sort_keys=True)}

## 保守抽象提案
{json.dumps(message.abstraction_proposals, ensure_ascii=False, sort_keys=True)}

若规则提案为空，或任何提案会损害稳定语义，请返回 keep。只有确实属于高频、
无意义局部差异的提案才可返回 abstract 并列入 approved_abstraction_ids。"""
        data = await self.ask_json(prompt)
        trace = self.last_call_trace
        if data is None:
            return SemanticReviewResult(
                is_idiom=False,
                semantic_score=0.0,
                reuse_score=0.0,
                intent="",
                preconditions=[],
                abstraction_decision="keep",
                approved_abstraction_ids=[],
                abstraction_reason="响应解析失败，保持代表代码不变。",
                idiom_classification=empty_idiom_classification(
                    "响应解析失败，未执行习语类型判断。"
                ),
                reason="响应解析失败，不能自动接受该簇。",
                call_status=trace.status,
                call_attempts=trace.attempts,
                failure_kind=trace.failure_kind,
            )
        allowed = {
            proposal["proposal_id"]
            for proposal in message.abstraction_proposals
        }
        approved_ids = sorted(
            {
                proposal_id
                for proposal_id in data["approved_abstraction_ids"]
                if proposal_id in allowed
            }
        )
        decision = data["abstraction_decision"]
        if (
            decision != "abstract"
            or not message.abstraction_proposals
            or not approved_ids
        ):
            decision = "keep"
            approved_ids = []
        is_idiom = data["is_idiom"]
        classification, invalid_classification = (
            normalize_idiom_classification(
                data["idiom_classification"],
                is_idiom=is_idiom,
            )
        )
        reason = data["reason"].strip()
        if invalid_classification or not reason:
            return SemanticReviewResult(
                is_idiom=False,
                semantic_score=0.0,
                reuse_score=0.0,
                intent=data["intent"],
                preconditions=data["preconditions"],
                abstraction_decision="keep",
                approved_abstraction_ids=[],
                abstraction_reason=(
                    "响应缺少有效判断理由或习语类型合同不一致，"
                    "保持代表代码不变。"
                ),
                idiom_classification=empty_idiom_classification(
                    "响应中的习语类型字段未通过确定性校验。"
                ),
                reason="语义判断缺少有效理由或类型字段无效，采用安全拒绝。",
                call_status="failed",
                call_attempts=trace.attempts,
                failure_kind="invalid_domain_payload",
            )
        return SemanticReviewResult(
            is_idiom=is_idiom,
            semantic_score=_score(data["semantic_score"]),
            reuse_score=_score(data["reuse_score"]),
            intent=data["intent"],
            preconditions=data["preconditions"],
            abstraction_decision=decision,
            approved_abstraction_ids=approved_ids,
            abstraction_reason=data["abstraction_reason"],
            idiom_classification=classification,
            reason=reason,
            call_status=trace.status,
            call_attempts=trace.attempts,
            failure_kind=trace.failure_kind,
        )
