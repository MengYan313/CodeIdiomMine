"""判断与合成阶段共享的代码异味审查 Agent。"""

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
from .smell_taxonomy import (
    SEVERITY_BASE_RISK,
    SMELL_CATEGORY_BY_ID,
    SMELL_CATEGORY_IDS,
    SmellFinding,
    calculate_smell_risk_score,
    render_taxonomy_for_prompt,
)

_TAXONOMY_TEXT = render_taxonomy_for_prompt()

_SYSTEM_MESSAGE = build_json_system_prompt(
    role="你是独立的 C++ 代码异味与复用风险审查专家。",
    goal=(
        "逐项发现、定位并分类候选习语中的代码异味；你只报告发现，不负责习语"
        "质量打分或接受/拒绝裁决。"
    ),
    success_criteria=(
        "同时审查候选代码、相关代码证据与确定性证据，只报告输入中可定位的风险。",
        "每条 finding 使用一个固定 category，并分别记录 severity、confidence、evidence、impact 和 remediation。",
        "severity 表示风险一旦成立的影响，只能为 low、medium、high 或 critical；confidence 表示当前输入证据置信度，范围0–100。",
        f"固定分类表如下：\n{_TAXONOMY_TEXT}",
    ),
    constraints=(
        "代码异味是风险信号而不是已证明缺陷；不得把出现频率、语义价值或格式偏好当作异味证据。",
        "不得因为代码风格、命名偏好或缺少未展示的外围代码而虚构缺陷。",
        "需要完整函数或类才能判断的类别，只能在相关上下文确实完整时报告。",
        "聚类成员之间重复是习语发现信号，不得归为 duplicated_logic；该类别只适用于单个候选内部的重复实现。",
        "证据不足时不生成 finding；不得输出总分、通过/失败或人工复核状态。",
    ),
    field_rules=(
        (
            "category 必须逐字使用固定英文标识；evidence、impact、remediation "
            "和 reason 使用中文，reason 必须概括本次有效性审查依据且不得为空。"
        ),
    ),
    stop_rules=("没有可定位异味时 findings 返回空数组，并简要说明未发现可见异味。",),
)
SMELL_REVIEW_PROMPT_VERSION = 3
SMELL_REVIEW_PROMPT_SHA256 = hashlib.sha256(
    _SYSTEM_MESSAGE.encode("utf-8")
).hexdigest()

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": list(SMELL_CATEGORY_IDS),
                    },
                    "severity": {
                        "type": "string",
                        "enum": list(SEVERITY_BASE_RISK),
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "evidence": {"type": "string"},
                    "impact": {"type": "string"},
                    "remediation": {"type": "string"},
                },
                "required": [
                    "category",
                    "severity",
                    "confidence",
                    "evidence",
                    "impact",
                    "remediation",
                ],
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["findings", "reason"],
    "additionalProperties": False,
}


@dataclass
class SmellReviewRequest:
    project: str
    candidate_id: str
    candidate_code: str
    related_examples: List[str]
    deterministic_evidence: dict


@dataclass
class SmellReviewResult:
    analysis_status: str
    risk_score: float
    max_severity: str
    categories: List[str]
    findings: List[SmellFinding]
    reason: str
    call_status: str = "completed"
    call_attempts: int = 1
    failure_kind: str = ""


SMELL_REVIEW_AGENT_TYPE = "idiom_smell_review"


def _normalize_findings(
    values: List[dict],
) -> tuple[List[SmellFinding], bool]:
    findings: List[SmellFinding] = []
    seen = set()
    invalid_payload = False
    for value in values:
        category = value["category"]
        severity = value["severity"]
        confidence = float(value["confidence"])
        evidence = value["evidence"].strip()
        impact = value["impact"].strip()
        remediation = value["remediation"].strip()
        if (
            category not in SMELL_CATEGORY_BY_ID
            or severity not in SEVERITY_BASE_RISK
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 100
            or not evidence
            or not impact
            or not remediation
        ):
            invalid_payload = True
            continue
        identity = (category, evidence)
        if identity in seen:
            continue
        seen.add(identity)
        findings.append(
            SmellFinding(
                category=category,
                severity=severity,
                confidence=confidence,
                evidence=evidence,
                impact=impact,
                remediation=remediation,
            )
        )
    return findings, invalid_payload


class SmellReviewAgent(JsonLLMAgent):
    """独立审查候选习语中的异味与危险前提。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__(
            "SmellReviewAgent",
            _SYSTEM_MESSAGE,
            model_client,
            _RESPONSE_SCHEMA,
        )

    @message_handler
    async def handle_request(
        self,
        message: SmellReviewRequest,
        ctx: MessageContext,
    ) -> SmellReviewResult:
        examples = "\n\n".join(
            f"### 相关代码证据 {index + 1}\n```cpp\n{code}\n```"
            for index, code in enumerate(message.related_examples)
        )
        prompt = f"""请独立审查以下候选习语的代码异味和复用风险。

项目：{message.project}
候选编号：{message.candidate_id}

## 候选代码
```cpp
{message.candidate_code}
```

## 相关代码证据
{examples or "（无额外代码证据）"}

## 确定性证据
{json.dumps(message.deterministic_evidence, ensure_ascii=False, sort_keys=True)}"""
        data = await self.ask_json(prompt)
        trace = self.last_call_trace
        if data is None:
            return SmellReviewResult(
                analysis_status="failed",
                risk_score=100.0,
                max_severity="none",
                categories=[],
                findings=[],
                reason="响应解析失败，异味审查门禁按失败状态拒绝。",
                call_status=trace.status,
                call_attempts=trace.attempts,
                failure_kind=trace.failure_kind,
            )
        findings, invalid_payload = _normalize_findings(data["findings"])
        reason = data["reason"].strip()
        if invalid_payload or not reason:
            return SmellReviewResult(
                analysis_status="failed",
                risk_score=100.0,
                max_severity="none",
                categories=[],
                findings=[],
                reason=(
                    "响应缺少有效判断理由，或含不完整、越界的异味发现，"
                    "独立门禁按失败状态拒绝。"
                ),
                call_status="failed",
                call_attempts=trace.attempts,
                failure_kind="invalid_domain_payload",
            )
        severity_rank = {
            "none": 0,
            "low": 1,
            "medium": 2,
            "high": 3,
            "critical": 4,
        }
        max_severity = max(
            (finding.severity for finding in findings),
            key=lambda value: severity_rank[value],
            default="none",
        )
        return SmellReviewResult(
            analysis_status="completed",
            risk_score=calculate_smell_risk_score(findings),
            max_severity=max_severity,
            categories=sorted({finding.category for finding in findings}),
            findings=findings,
            reason=reason,
            call_status=trace.status,
            call_attempts=trace.attempts,
            failure_kind=trace.failure_kind,
        )
