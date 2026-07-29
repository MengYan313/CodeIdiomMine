"""习语判断流水线：规则与抽象提案后，并行执行语义和异味审查。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Optional

from autogen_core import SingleThreadedAgentRuntime
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..agents._base import create_model_client
from ..agents.base import default_agent_id, register_agent
from .abstraction import (
    AbstractionPolicy,
    apply_approved_abstractions,
    propose_abstractions,
)
from .rules import evaluate_cluster_rules
from .source_context import load_verified_source_context
from .idiom_taxonomy import (
    IDIOM_TAXONOMY_VERSION,
    KNOWN_IDIOM_TYPES,
    REPOSITORY_SPECIFIC_IDIOM_LABEL,
    empty_idiom_classification,
)
from .schema import (
    ClusterCandidate,
    SemanticAssessment,
    SmellAssessment,
    IdiomJudgmentResult,
)
from .semantic_review_agent import (
    SEMANTIC_REVIEW_PROMPT_SHA256,
    SEMANTIC_REVIEW_PROMPT_VERSION,
    SemanticReviewAgent,
    SemanticReviewRequest,
    SemanticReviewResult,
)
from .smell_review_agent import (
    SMELL_REVIEW_AGENT_TYPE,
    SMELL_REVIEW_PROMPT_SHA256,
    SMELL_REVIEW_PROMPT_VERSION,
    SmellReviewAgent,
    SmellReviewRequest,
    SmellReviewResult,
)
from .smell_taxonomy import build_smell_gate


JUDGMENT_ACCEPTANCE_SCORE = 70.0


def _agent_trace(result: object, failure_action: str) -> dict[str, object]:
    status = str(getattr(result, "call_status", "failed"))
    return {
        "status": status,
        "logical_attempts": int(getattr(result, "call_attempts", 0) or 0),
        "failure_kind": str(getattr(result, "failure_kind", "") or ""),
        "failure_action": (
            failure_action if status == "failed" else "continue"
        ),
    }


def _not_run_trace(reason: str) -> dict[str, object]:
    return {
        "status": "not_run",
        "logical_attempts": 0,
        "failure_kind": reason,
        "failure_action": "skip_agent",
    }


def build_judgment_scorecard(
    *,
    rule_score: float,
    semantic_score: float,
    reuse_score: float,
) -> dict[str, float]:
    """只组合习语价值维度，不混入代码异味风险。"""

    final_score = (
        0.20 * rule_score
        + 0.45 * semantic_score
        + 0.35 * reuse_score
    )
    return {
        "rule_score": round(rule_score, 4),
        "semantic_score": round(semantic_score, 4),
        "reuse_score": round(reuse_score, 4),
        "final_score": round(final_score, 4),
        "acceptance_threshold": JUDGMENT_ACCEPTANCE_SCORE,
    }


def decide_judgment_status(
    *,
    rule_eligible: bool,
    rule_score: float,
    semantic_is_idiom: bool,
    semantic_score: float,
    reuse_score: float,
) -> tuple[str, str]:
    """只根据规则与习语价值给出裁决；异味由独立门禁处理。"""

    if not rule_eligible:
        return "rejected", "确定性规则门禁失败。"
    if not semantic_is_idiom:
        return "rejected", "语义有效性 Agent 判断该候选不属于代码习语。"
    if semantic_score < 50 or reuse_score < 50:
        return "rejected", "语义稳定性或复用价值低于最低门槛。"
    scorecard = build_judgment_scorecard(
        rule_score=rule_score,
        semantic_score=semantic_score,
        reuse_score=reuse_score,
    )
    if scorecard["final_score"] >= JUDGMENT_ACCEPTANCE_SCORE:
        return (
            "accepted",
            f"单簇总分 {scorecard['final_score']:.2f} 达到自动接受门槛。",
        )
    return (
        "rejected",
        f"单簇总分 {scorecard['final_score']:.2f} 未达到自动接受门槛。",
    )


class IdiomJudgmentPipeline:
    """单簇习语判断流水线。"""

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        model_client: Optional[OpenAIChatCompletionClient] = None,
        abstraction_policy: Optional[AbstractionPolicy] = None,
        source_root: Optional[str] = None,
        require_context: bool = False,
    ) -> None:
        self.model = model
        self.model_client = model_client
        self._owns_model_client = model_client is None
        self.abstraction_policy = abstraction_policy or AbstractionPolicy()
        self.source_root = source_root
        self.require_context = bool(require_context)
        self.runtime: Optional[SingleThreadedAgentRuntime] = None
        self._initialized = False

    def run_contract(self) -> dict[str, object]:
        return {
            "decision_policy": {
                "acceptance_score": JUDGMENT_ACCEPTANCE_SCORE,
                "score_weights": {
                    "rule": 0.20,
                    "semantic": 0.45,
                    "reuse": 0.35,
                },
                "calibration_status": (
                    "synthetic_smoke_only_pilot_required"
                ),
            },
            "abstraction_policy": asdict(self.abstraction_policy),
            "idiom_taxonomy": {
                "version": IDIOM_TAXONOMY_VERSION,
                "known_type_count": len(KNOWN_IDIOM_TYPES),
                "repository_specific_label": (
                    REPOSITORY_SPECIFIC_IDIOM_LABEL
                ),
            },
            "prompt_contracts": {
                "semantic_review": {
                    "version": SEMANTIC_REVIEW_PROMPT_VERSION,
                    "sha256": SEMANTIC_REVIEW_PROMPT_SHA256,
                },
                "smell_review": {
                    "version": SMELL_REVIEW_PROMPT_VERSION,
                    "sha256": SMELL_REVIEW_PROMPT_SHA256,
                },
            },
        }

    def usage_snapshot(self) -> dict[str, int]:
        if self.model_client is None:
            return {"prompt_tokens": 0, "completion_tokens": 0}
        usage = self.model_client.actual_usage()
        return {
            "prompt_tokens": int(usage.prompt_tokens),
            "completion_tokens": int(usage.completion_tokens),
        }

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self.model_client is None:
            self.model_client = create_model_client(self.model)
        self.runtime = SingleThreadedAgentRuntime()
        await register_agent(
            self.runtime,
            "idiom_semantic_review",
            lambda: SemanticReviewAgent(self.model_client),
        )
        await register_agent(
            self.runtime,
            SMELL_REVIEW_AGENT_TYPE,
            lambda: SmellReviewAgent(self.model_client),
        )
        self.runtime.start()
        self._initialized = True

    async def evaluate(
        self,
        candidate: ClusterCandidate,
        *,
        rule_only: bool = False,
    ) -> IdiomJudgmentResult:
        rules = evaluate_cluster_rules(candidate)
        proposals = propose_abstractions(candidate, self.abstraction_policy)
        if not rules.eligible_for_llm:
            return IdiomJudgmentResult(
                candidate=candidate,
                rules=rules,
                proposals=proposals,
                status="rejected",
                template_code=candidate.representative_code,
                agent_trace={
                    "semantic_review": _not_run_trace("rule_gate_rejected"),
                    "smell_review": _not_run_trace("rule_gate_rejected"),
                },
                decision_reason="；".join(rules.hard_failures),
            )
        if rule_only:
            return IdiomJudgmentResult(
                candidate=candidate,
                rules=rules,
                proposals=proposals,
                status="pending_llm",
                template_code=candidate.representative_code,
                agent_trace={
                    "semantic_review": _not_run_trace("rule_only"),
                    "smell_review": _not_run_trace("rule_only"),
                },
                decision_reason="规则检查通过，尚未执行语义和异味审查。",
            )
        context_code, context_evidence = load_verified_source_context(
            project=candidate.project,
            representative_info=candidate.representative_info,
            source_root=self.source_root,
        )
        context_evidence["required"] = self.require_context
        if self.require_context and not context_code:
            return IdiomJudgmentResult(
                candidate=candidate,
                rules=rules,
                proposals=proposals,
                status="rejected",
                template_code=candidate.representative_code,
                context_evidence=context_evidence,
                agent_trace={
                    "semantic_review": _not_run_trace(
                        "context_gate_rejected"
                    ),
                    "smell_review": _not_run_trace(
                        "context_gate_rejected"
                    ),
                },
                decision_reason=(
                    "未能自动加载并验证代表函数/区域上下文，严格上下文门禁拒绝。"
                ),
            )
        if not self._initialized:
            await self.initialize()
        assert self.runtime is not None

        proposal_data = [asdict(proposal) for proposal in proposals]
        rule_data = asdict(rules)
        code_variants = candidate.lexical_variants
        cluster_statistics = candidate.cluster_statistics
        semantic_request = SemanticReviewRequest(
            project=candidate.project,
            cluster_id=candidate.cluster_id,
            representative_code=candidate.representative_code,
            code_variants=code_variants,
            cluster_statistics=cluster_statistics,
            rule_evidence=rule_data,
            abstraction_proposals=proposal_data,
        )
        smell_request = SmellReviewRequest(
            project=candidate.project,
            candidate_id=f"cluster:{candidate.cluster_id}",
            candidate_code=candidate.representative_code,
            related_examples=code_variants,
            deterministic_evidence=cluster_statistics,
        )
        semantic_result, smell_result = await asyncio.gather(
            self.runtime.send_message(
                semantic_request,
                recipient=default_agent_id("idiom_semantic_review"),
            ),
            self.runtime.send_message(
                smell_request,
                recipient=default_agent_id(SMELL_REVIEW_AGENT_TYPE),
            ),
            return_exceptions=True,
        )
        if isinstance(semantic_result, asyncio.CancelledError):
            raise semantic_result
        if isinstance(semantic_result, BaseException):
            semantic_result = SemanticReviewResult(
                is_idiom=False,
                semantic_score=0.0,
                reuse_score=0.0,
                intent="",
                preconditions=[],
                abstraction_decision="keep",
                approved_abstraction_ids=[],
                abstraction_reason="Runtime 路由失败，保持代表代码不变。",
                idiom_classification=empty_idiom_classification(
                    "Runtime 路由失败，未执行习语类型判断。"
                ),
                reason="语义/抽象 Agent 未能完成，采用安全拒绝。",
                call_status="failed",
                call_attempts=0,
                failure_kind="runtime_dispatch_error",
            )
        if isinstance(smell_result, asyncio.CancelledError):
            raise smell_result
        if isinstance(smell_result, BaseException):
            smell_result = SmellReviewResult(
                analysis_status="failed",
                risk_score=100.0,
                max_severity="none",
                categories=[],
                findings=[],
                reason="代码异味 Agent Runtime 路由失败，采用安全拒绝。",
                call_status="failed",
                call_attempts=0,
                failure_kind="runtime_dispatch_error",
            )
        semantic = SemanticAssessment(
            is_idiom=semantic_result.is_idiom,
            semantic_score=semantic_result.semantic_score,
            reuse_score=semantic_result.reuse_score,
            intent=semantic_result.intent,
            preconditions=semantic_result.preconditions,
            abstraction_decision=semantic_result.abstraction_decision,
            approved_abstraction_ids=(
                semantic_result.approved_abstraction_ids
            ),
            abstraction_reason=semantic_result.abstraction_reason,
            idiom_classification=semantic_result.idiom_classification,
            reason=semantic_result.reason,
        )
        smell = SmellAssessment(
            analysis_status=smell_result.analysis_status,
            risk_score=smell_result.risk_score,
            max_severity=smell_result.max_severity,
            categories=smell_result.categories,
            findings=smell_result.findings,
            reason=smell_result.reason,
        )
        status, reason = decide_judgment_status(
            rule_eligible=rules.eligible_for_llm,
            rule_score=rules.score,
            semantic_is_idiom=semantic.is_idiom,
            semantic_score=semantic.semantic_score,
            reuse_score=semantic.reuse_score,
        )
        scorecard = build_judgment_scorecard(
            rule_score=rules.score,
            semantic_score=semantic.semantic_score,
            reuse_score=semantic.reuse_score,
        )
        smell_gate = build_smell_gate(
            analysis_status=smell.analysis_status,
            risk_score=smell.risk_score,
            max_severity=smell.max_severity,
            categories=smell.categories,
            finding_count=len(smell.findings),
        )
        if smell_gate["rejected"]:
            status = "rejected"
            if smell_gate["trigger_kind"] == "analysis_failure":
                reason = "代码异味审查失败，独立门禁采用安全拒绝。"
            else:
                categories = "、".join(smell.categories) or "未分类"
                reason = (
                    f"代码异味风险分 {smell.risk_score:.2f} 达到独立过滤阈值；"
                    f"类别：{categories}。"
                )
        reason = (
            f"{reason} 语义判断依据：{semantic.reason} "
            f"异味审查依据：{smell.reason}"
        ).strip()
        requested_ids = (
            set(semantic.approved_abstraction_ids)
            if semantic.abstraction_decision == "abstract"
            else set()
        )
        approved = [
            proposal.proposal_id
            for proposal in proposals
            if proposal.proposal_id in requested_ids
        ]
        template = apply_approved_abstractions(
            candidate.representative_code,
            proposals,
            approved,
        )
        return IdiomJudgmentResult(
            candidate=candidate,
            rules=rules,
            proposals=proposals,
            status=status,
            template_code=template,
            approved_abstraction_ids=approved,
            abstraction_applied=bool(approved),
            semantic=semantic,
            semantic_review_input=asdict(semantic_request),
            context_evidence=context_evidence,
            smell=smell,
            smell_gate=smell_gate,
            smell_review_input=asdict(smell_request),
            agent_trace={
                "semantic_review": _agent_trace(
                    semantic_result,
                    "reject_cluster",
                ),
                "smell_review": _agent_trace(
                    smell_result,
                    "reject_cluster",
                ),
            },
            scorecard=scorecard,
            decision_reason=reason,
        )

    async def shutdown(self) -> None:
        try:
            if self.runtime is not None and self._initialized:
                await self.runtime.stop()
                await self.runtime.close()
        finally:
            if self.model_client is not None and self._owns_model_client:
                await self.model_client.close()
            self.runtime = None
            self.model_client = None
            self._initialized = False
