"""多习语自动上下文、规划、组装、质量与共享异味审查流水线。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Optional, Sequence

from autogen_core import SingleThreadedAgentRuntime
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..agents._base import (
    agent_trace,
    create_model_client,
    dispatch_with_fallback,
    not_run_trace,
)
from ..agents.base import default_agent_id, register_agent
from ..idiom_judgment.smell_review_agent import (
    SMELL_REVIEW_AGENT_TYPE,
    SMELL_REVIEW_PROMPT_SHA256,
    SMELL_REVIEW_PROMPT_VERSION,
    SmellReviewAgent,
    SmellReviewRequest,
    SmellReviewResult,
)
from ..idiom_judgment.smell_taxonomy import build_smell_gate
from ..idiom_judgment.idiom_taxonomy import (
    IDIOM_TAXONOMY_VERSION,
    KNOWN_IDIOM_TYPES,
    REPOSITORY_SPECIFIC_IDIOM_LABEL,
    empty_idiom_classification,
)
from .assembly_agent import (
    IDIOM_ASSEMBLY_PROMPT_SHA256,
    IDIOM_ASSEMBLY_PROMPT_VERSION,
    IdiomAssemblyAgent,
    IdiomAssemblyRequest,
    IdiomAssemblyResult,
)
from .context import (
    SYNTHESIS_CONTEXT_MODE,
    load_group_context_with_evidence,
    syntax_structure_valid,
    unsupported_call_targets,
)
from .planning_agent import (
    SYNTHESIS_PLANNING_PROMPT_SHA256,
    SYNTHESIS_PLANNING_PROMPT_VERSION,
    SynthesisPlanningAgent,
    SynthesisPlanningRequest,
    SynthesisPlanningResult,
)
from .review_agent import (
    SYNTHESIS_REVIEW_PROMPT_SHA256,
    SYNTHESIS_REVIEW_PROMPT_VERSION,
    SynthesisReviewAgent,
    SynthesisReviewRequest,
    SynthesisReviewResult,
)
from .schema import SynthesisResult, IdiomCandidate


SYNTHESIS_ACCEPTANCE_SCORE = 70.0
STAGE2_SYNTHESIS_ACCEPTANCE_SCORE = 80.0
_SYNTHESIS_AGENT_STAGES = (
    "planning",
    "assembly",
    "quality_review",
    "smell_review",
)


def _not_run_traces(reason: str) -> dict[str, dict[str, object]]:
    return {
        stage: not_run_trace(reason)
        for stage in _SYNTHESIS_AGENT_STAGES
    }


def build_synthesis_scorecard(
    *,
    contains_stage2_input: bool,
    quality_score: float,
) -> dict[str, float]:
    """只记录合成质量门槛，不混入代码异味风险。"""

    threshold = (
        STAGE2_SYNTHESIS_ACCEPTANCE_SCORE
        if contains_stage2_input
        else SYNTHESIS_ACCEPTANCE_SCORE
    )
    return {
        "quality_score": round(quality_score, 4),
        "final_score": round(quality_score, 4),
        "acceptance_threshold": threshold,
    }


def decide_synthesis_status(
    *,
    contains_stage2_input: bool,
    merged_code_present: bool,
    syntax_valid: bool,
    unsupported_calls: Sequence[str],
    context_contract_valid: bool,
    review_is_idiom: bool,
    quality_score: float,
    improves_quality: bool,
    preserves_intents: bool,
    review_unsupported_additions: Sequence[str],
) -> tuple[str, str]:
    """只裁决合成质量；代码异味由独立门禁处理。"""

    if not merged_code_present:
        return "rejected", "组装未产生代码。"
    if not syntax_valid:
        return "rejected", "合成结果未通过 Tree-sitter 语法结构检查。"
    if unsupported_calls or review_unsupported_additions:
        return "rejected", "合成结果包含输入习语和允许上下文之外的新增操作。"
    if not context_contract_valid:
        return "rejected", "未能提供通过来源校验的同代表区域上下文。"
    if not review_is_idiom:
        return "rejected", "质量有效性 Agent 判断合成结果不属于代码习语。"
    if not preserves_intents:
        return "rejected", "合成结果未忠实保留来源习语意图。"
    if not improves_quality:
        return "rejected", "合成结果相较来源习语没有明确质量增益。"

    scorecard = build_synthesis_scorecard(
        contains_stage2_input=contains_stage2_input,
        quality_score=quality_score,
    )
    if scorecard["final_score"] >= scorecard["acceptance_threshold"]:
        return "accepted", (
            "阶段2合同输入满足严格质量阈值（正式流程不执行）。"
            if contains_stage2_input
            else "已判断习语合成后产生明确质量增益。"
        )
    return (
        "rejected",
        f"合成总分 {scorecard['final_score']:.2f} 未达到自动接受门槛。",
    )


class IdiomSynthesisPipeline:
    """阶段四的功能语义入口：只处理多个习语的合成。"""

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        model_client: Optional[OpenAIChatCompletionClient] = None,
        max_group_candidates: int = 12,
    ) -> None:
        self.model = model
        self.model_client = model_client
        self._owns_model_client = model_client is None
        if max_group_candidates < 2:
            raise ValueError("max_group_candidates 必须至少为 2")
        self.max_group_candidates = max_group_candidates
        self.runtime: Optional[SingleThreadedAgentRuntime] = None

    def run_contract(self) -> dict[str, object]:
        return {
            "artifact_semantics": "synthesis_delta",
            "region_grouping": "exact_representative_source_extent",
            "decision_policy": {
                "acceptance_score": SYNTHESIS_ACCEPTANCE_SCORE,
                "stage2_contract_score": (
                    STAGE2_SYNTHESIS_ACCEPTANCE_SCORE
                ),
                "calibration_status": (
                    "synthetic_smoke_only_pilot_required"
                ),
            },
            "max_group_candidates": self.max_group_candidates,
            "idiom_taxonomy": {
                "version": IDIOM_TAXONOMY_VERSION,
                "known_type_count": len(KNOWN_IDIOM_TYPES),
                "repository_specific_label": (
                    REPOSITORY_SPECIFIC_IDIOM_LABEL
                ),
            },
            "prompt_contracts": {
                "planning": {
                    "version": SYNTHESIS_PLANNING_PROMPT_VERSION,
                    "sha256": SYNTHESIS_PLANNING_PROMPT_SHA256,
                },
                "assembly": {
                    "version": IDIOM_ASSEMBLY_PROMPT_VERSION,
                    "sha256": IDIOM_ASSEMBLY_PROMPT_SHA256,
                },
                "quality_review": {
                    "version": SYNTHESIS_REVIEW_PROMPT_VERSION,
                    "sha256": SYNTHESIS_REVIEW_PROMPT_SHA256,
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
        if self.runtime is not None:
            return
        if self.model_client is None:
            self.model_client = create_model_client(self.model)
        runtime = SingleThreadedAgentRuntime()
        await register_agent(
            runtime,
            "synthesis_planning",
            lambda: SynthesisPlanningAgent(self.model_client),
        )
        await register_agent(
            runtime,
            "synthesis_assembly",
            lambda: IdiomAssemblyAgent(self.model_client),
        )
        await register_agent(
            runtime,
            "synthesis_review",
            lambda: SynthesisReviewAgent(self.model_client),
        )
        await register_agent(
            runtime,
            SMELL_REVIEW_AGENT_TYPE,
            lambda: SmellReviewAgent(self.model_client),
        )
        runtime.start()
        self.runtime = runtime

    @staticmethod
    def _candidate_payload(candidate: IdiomCandidate) -> dict:
        return {
            "candidate_id": candidate.candidate_id,
            "code": candidate.code,
            "support_count": candidate.support_count,
            "input_stage": candidate.input_stage,
            "intent": candidate.intent,
            "judgment_status": candidate.judgment_status,
            "judgment_reason": candidate.judgment_reason,
            "idiom_classification": candidate.idiom_classification,
            "agent_reasons": candidate.agent_reasons,
            "loc_label": candidate.loc_label,
        }

    async def synthesize(
        self,
        candidates: Sequence[IdiomCandidate],
        *,
        source_root: str | None = None,
    ) -> SynthesisResult:
        if len(candidates) < 2:
            raise ValueError("习语合成至少需要两个候选")
        project = candidates[0].project
        context_key = candidates[0].context_key
        if any(candidate.project != project for candidate in candidates):
            raise ValueError("禁止跨仓库合成习语")
        if any(candidate.context_key != context_key for candidate in candidates):
            raise ValueError("习语合成只能处理代表源码范围完全相同的候选")

        if len(candidates) > self.max_group_candidates:
            context_evidence = {
                "mode": SYNTHESIS_CONTEXT_MODE,
                "required": True,
                "available": False,
                "source_root_supplied": source_root is not None,
                "candidate_ids": [
                    candidate.candidate_id for candidate in candidates
                ],
                "candidate_count": len(candidates),
                "candidate_limit": self.max_group_candidates,
                "limit_exceeded": True,
            }
            return SynthesisResult(
                project=project,
                status="rejected",
                selected=list(candidates),
                context_evidence=context_evidence,
                agent_trace=_not_run_traces("candidate_limit_exceeded"),
                scorecard=build_synthesis_scorecard(
                    contains_stage2_input=any(
                        candidate.input_stage == 2
                        for candidate in candidates
                    ),
                    quality_score=0.0,
                ),
                deterministic_checks={
                    "candidate_limit_exceeded": True,
                    "candidate_count": len(candidates),
                    "candidate_limit": self.max_group_candidates,
                },
                decision_reason=(
                    "同区域候选数量超过本次显式上限；为避免静默遗漏，"
                    "未截断候选且未调用 Agent。请提高上限后重试该区域。"
                ),
            )

        group_candidates = list(candidates)
        (
            available_context,
            context_evidence,
        ) = load_group_context_with_evidence(group_candidates, source_root)
        contains_stage2_input = any(
            candidate.input_stage == 2 for candidate in group_candidates
        )
        context_evidence.update(
            {
                "source_root_supplied": source_root is not None,
                "candidate_count": len(group_candidates),
            }
        )
        if not available_context:
            return SynthesisResult(
                project=project,
                status="rejected",
                context_evidence=context_evidence,
                agent_trace=_not_run_traces("context_gate_rejected"),
                scorecard=build_synthesis_scorecard(
                    contains_stage2_input=contains_stage2_input,
                    quality_score=0.0,
                ),
                deterministic_checks={"context_contract_valid": False},
                decision_reason="未能自动加载并验证候选所在代表源码区域。",
            )

        await self.initialize()
        assert self.runtime is not None

        payload = [
            self._candidate_payload(candidate)
            for candidate in group_candidates
        ]
        plan_result = await dispatch_with_fallback(
            self.runtime.send_message(
                SynthesisPlanningRequest(
                    candidates=payload,
                    context_code=available_context,
                ),
                recipient=default_agent_id("synthesis_planning"),
            ),
            SynthesisPlanningResult(
                should_synthesize=False,
                selected_indices=[],
                synthesis_goal="",
                ordering_constraints=[],
                expected_improvement="",
                reason="规划 Agent Runtime 路由失败，跳过当前候选组。",
                call_status="failed",
                call_attempts=0,
                failure_kind="runtime_dispatch_error",
            ),
        )
        plan_data = asdict(plan_result)
        if not plan_result.should_synthesize:
            plan_failed = plan_result.call_status == "failed"
            return SynthesisResult(
                project=project,
                status="rejected",
                context_evidence=context_evidence,
                plan=plan_data,
                agent_trace={
                    "planning": agent_trace(
                        plan_result,
                        "skip_group",
                    ),
                    **{
                        stage: not_run_trace("planning_stopped")
                        for stage in _SYNTHESIS_AGENT_STAGES[1:]
                    },
                },
                scorecard=build_synthesis_scorecard(
                    contains_stage2_input=contains_stage2_input,
                    quality_score=0.0,
                ),
                deterministic_checks={"synthesis_planned": False},
                decision_reason=(
                    "规划 Agent 技术失败，跳过当前候选组。"
                    if plan_failed
                    else "规划 Agent 未发现至少两个能够产生明确增益的习语。"
                ),
            )

        selected = [
            group_candidates[index]
            for index in plan_result.selected_indices
        ]
        assembly_result = await dispatch_with_fallback(
            self.runtime.send_message(
                IdiomAssemblyRequest(
                    selected_codes=[
                        candidate.code for candidate in selected
                    ],
                    plan=plan_data,
                    context_code=available_context,
                ),
                recipient=default_agent_id("synthesis_assembly"),
            ),
            IdiomAssemblyResult(
                merged_code="",
                used_context=False,
                added_from_context=[],
                reason="组装 Agent Runtime 路由失败。",
                call_status="failed",
                call_attempts=0,
                failure_kind="runtime_dispatch_error",
            ),
        )
        assembly_data = asdict(assembly_result)
        merged = assembly_result.merged_code
        allowed_context = available_context
        unsupported_calls = unsupported_call_targets(
            merged,
            [candidate.code for candidate in selected],
            allowed_context,
        )
        syntax_valid = bool(merged) and syntax_structure_valid(merged)
        context_contract_valid = bool(allowed_context)
        deterministic = {
            "syntax_structure_valid": syntax_valid,
            "unsupported_call_targets": unsupported_calls,
            "context_contract_valid": context_contract_valid,
        }
        if not merged or not syntax_valid or unsupported_calls:
            if not merged:
                reason = (
                    "组装 Agent 技术失败，跳过复审并拒绝当前候选组。"
                    if assembly_result.call_status == "failed"
                    else "组装 Agent 未产生代码，跳过复审并拒绝当前候选组。"
                )
            elif not syntax_valid:
                reason = (
                    "合成结果未通过 Tree-sitter 语法结构检查，"
                    "跳过复审并拒绝当前候选组。"
                )
            else:
                reason = (
                    "合成结果包含来源习语和允许上下文之外的新增调用，"
                    "跳过复审并拒绝当前候选组。"
                )
            return SynthesisResult(
                project=project,
                status="rejected",
                selected=selected,
                merged_code=merged,
                context_evidence=context_evidence,
                plan=plan_data,
                assembly=assembly_data,
                agent_trace={
                    "planning": agent_trace(plan_result, "skip_group"),
                    "assembly": agent_trace(
                        assembly_result,
                        "skip_downstream_and_reject_group",
                    ),
                    "quality_review": not_run_trace(
                        "assembly_or_deterministic_gate_rejected"
                    ),
                    "smell_review": not_run_trace(
                        "assembly_or_deterministic_gate_rejected"
                    ),
                },
                scorecard=build_synthesis_scorecard(
                    contains_stage2_input=contains_stage2_input,
                    quality_score=0.0,
                ),
                deterministic_checks=deterministic,
                decision_reason=reason,
            )
        smell_request = SmellReviewRequest(
            project=project,
            candidate_id="synthesis:"
            + ",".join(candidate.candidate_id for candidate in selected),
            candidate_code=merged,
            related_examples=[
                available_context,
                *[candidate.code for candidate in selected],
            ][:5],
            deterministic_evidence={
                **deterministic,
                "source_judgments": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "judgment_reason": candidate.judgment_reason,
                        "idiom_classification": (
                            candidate.idiom_classification
                        ),
                        "agent_reasons": candidate.agent_reasons,
                    }
                    for candidate in selected
                ],
            },
        )

        review_result, smell_result = await asyncio.gather(
            dispatch_with_fallback(
                self.runtime.send_message(
                    SynthesisReviewRequest(
                        source_idioms=[
                            self._candidate_payload(candidate)
                            for candidate in selected
                        ],
                        plan=plan_data,
                        merged_code=merged,
                        context_code=allowed_context,
                        assembly_evidence=assembly_data,
                    ),
                    recipient=default_agent_id("synthesis_review"),
                ),
                SynthesisReviewResult(
                    is_idiom=False,
                    quality_score=0.0,
                    improves_quality=False,
                    preserves_intents=False,
                    unsupported_additions=[],
                    issues=["质量复审 Agent Runtime 路由失败"],
                    idiom_classification=empty_idiom_classification(
                        "Runtime 路由失败，未执行合成习语类型判断。"
                    ),
                    reason="不能自动确认合成质量，采用安全拒绝。",
                    call_status="failed",
                    call_attempts=0,
                    failure_kind="runtime_dispatch_error",
                ),
            ),
            dispatch_with_fallback(
                self.runtime.send_message(
                    smell_request,
                    recipient=default_agent_id(SMELL_REVIEW_AGENT_TYPE),
                ),
                SmellReviewResult(
                    analysis_status="failed",
                    risk_score=100.0,
                    max_severity="none",
                    categories=[],
                    findings=[],
                    reason="代码异味 Agent Runtime 路由失败，采用安全拒绝。",
                    call_status="failed",
                    call_attempts=0,
                    failure_kind="runtime_dispatch_error",
                ),
            ),
        )
        review_data = asdict(review_result)
        smell_data = asdict(smell_result)
        selected_contains_stage2 = any(
            candidate.input_stage == 2 for candidate in selected
        )
        status, reason = decide_synthesis_status(
            contains_stage2_input=selected_contains_stage2,
            merged_code_present=bool(merged),
            syntax_valid=syntax_valid,
            unsupported_calls=unsupported_calls,
            context_contract_valid=context_contract_valid,
            review_is_idiom=review_result.is_idiom,
            quality_score=review_result.quality_score,
            improves_quality=review_result.improves_quality,
            preserves_intents=review_result.preserves_intents,
            review_unsupported_additions=review_result.unsupported_additions,
        )
        scorecard = build_synthesis_scorecard(
            contains_stage2_input=selected_contains_stage2,
            quality_score=review_result.quality_score,
        )
        smell_gate = build_smell_gate(
            analysis_status=smell_result.analysis_status,
            risk_score=smell_result.risk_score,
            max_severity=smell_result.max_severity,
            categories=smell_result.categories,
            finding_count=len(smell_result.findings),
        )
        if smell_gate["rejected"]:
            status = "rejected"
            if smell_gate["trigger_kind"] == "analysis_failure":
                reason = "代码异味审查失败，独立门禁采用安全拒绝。"
            else:
                categories = "、".join(smell_result.categories) or "未分类"
                reason = (
                    f"代码异味风险分 {smell_result.risk_score:.2f} "
                    f"达到独立过滤阈值；类别：{categories}。"
                )
        reason = (
            f"{reason} 质量复审依据：{review_result.reason} "
            f"异味审查依据：{smell_result.reason}"
        ).strip()
        return SynthesisResult(
            project=project,
            status=status,
            selected=selected,
            merged_code=merged,
            context_evidence=context_evidence,
            plan=plan_data,
            assembly=assembly_data,
            review=review_data,
            smell=smell_data,
            smell_gate=smell_gate,
            smell_review_input=asdict(smell_request),
            agent_trace={
                "planning": agent_trace(plan_result, "skip_group"),
                "assembly": agent_trace(
                    assembly_result,
                    "skip_downstream_and_reject_group",
                ),
                "quality_review": agent_trace(
                    review_result,
                    "reject_group",
                ),
                "smell_review": agent_trace(
                    smell_result,
                    "reject_group",
                ),
            },
            scorecard=scorecard,
            deterministic_checks=deterministic,
            decision_reason=reason,
        )

    async def shutdown(self) -> None:
        try:
            if self.runtime is not None:
                await self.runtime.stop()
                await self.runtime.close()
        finally:
            self.runtime = None
            if self.model_client is not None and self._owns_model_client:
                await self.model_client.close()
                self.model_client = None
