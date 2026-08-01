"""多习语自动上下文、规划、组装、质量与共享异味审查流水线。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Optional, Sequence

from autogen_core import SingleThreadedAgentRuntime
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..agents.base import (
    agent_trace,
    dispatch_with_fallback,
    not_run_trace,
)
from ..agents.base import default_agent_id, register_agent
from ..common.logging import get_logger
from ..llm.client import create_model_client
from ..idiom_judgment.smell_review_agent import (
    SMELL_REVIEW_AGENT_TYPE,
    SmellReviewAgent,
    SmellReviewRequest,
    SmellReviewResult,
)
from ..idiom_judgment.smell_taxonomy import build_smell_gate
from ..idiom_judgment.idiom_taxonomy import (
    KNOWN_IDIOM_TYPES,
    REPOSITORY_SPECIFIC_IDIOM_LABEL,
    empty_idiom_classification,
)
from .assembly_agent import (
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
    DEFAULT_MAX_PLANS_PER_REGION,
    SynthesisPlan,
    SynthesisPlanningAgent,
    SynthesisPlanningRequest,
    SynthesisPlanningResult,
)
from .review_agent import (
    SynthesisReviewAgent,
    SynthesisReviewRequest,
    SynthesisReviewResult,
)
from .schema import SynthesisResult, IdiomCandidate


SYNTHESIS_ACCEPTANCE_SCORE = 70.0
_SYNTHESIS_AGENT_STAGES = (
    "planning",
    "assembly",
    "quality_review",
    "smell_review",
)
logger = get_logger(__name__)


def _not_run_traces(reason: str) -> dict[str, dict[str, object]]:
    return {
        stage: not_run_trace(reason)
        for stage in _SYNTHESIS_AGENT_STAGES
    }


def _combination_key(candidate_ids: Sequence[str]) -> str:
    return "combination:" + "+".join(sorted(candidate_ids))


def _region_key(context_key: tuple[str, str, str]) -> str:
    return "region:" + "|".join(context_key)


def normalize_synthesis_plans(
    plans: Sequence[SynthesisPlan],
    candidates: Sequence[IdiomCandidate],
    *,
    max_plans_per_region: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """规范化计划索引，以候选集合生成稳定键并拒绝非法或重复计划。"""

    rejected: list[dict[str, object]] = []
    if len(plans) > max_plans_per_region:
        return [], {
            "raw_plan_count": len(plans),
            "valid_unique_plan_count": 0,
            "rejected_plan_count": len(plans),
            "limit_exceeded": True,
            "rejected_plans": [
                {
                    "position": -1,
                    "reason": "规划响应超过显式计划上限，未截断也未执行。",
                }
            ],
        }

    seen: set[tuple[int, ...]] = set()
    normalized: list[dict[str, object]] = []
    for position, plan in enumerate(plans):
        indices = sorted(set(plan.selected_indices))
        reason = ""
        if any(index < 0 or index >= len(candidates) for index in indices):
            reason = "selected_indices 含越界索引。"
        elif len(indices) < 2:
            reason = "计划必须包含至少两个不同候选。"
        elif not all(
            (
                plan.relation_kind.strip(),
                plan.synthesis_goal.strip(),
                plan.expected_improvement.strip(),
                plan.reason.strip(),
            )
        ):
            reason = "计划的关系、目标、预期增益或理由为空。"
        constraints = [
            value.strip()
            for value in plan.ordering_constraints
            if value.strip()
        ]
        if not reason and not constraints:
            reason = "计划的 ordering_constraints 为空。"
        key = tuple(indices)
        if not reason and key in seen:
            reason = "候选集合与先前计划重复。"
        if reason:
            rejected.append(
                {
                    "position": position,
                    "selected_indices": indices,
                    "reason": reason,
                }
            )
            continue

        seen.add(key)
        candidate_ids = [candidates[index].candidate_id for index in indices]
        normalized.append(
            {
                "selected_indices": indices,
                "selected_candidate_ids": candidate_ids,
                "relation_kind": plan.relation_kind.strip(),
                "synthesis_goal": plan.synthesis_goal.strip(),
                "ordering_constraints": constraints,
                "expected_improvement": (
                    plan.expected_improvement.strip()
                ),
                "reason": plan.reason.strip(),
                "combination_key": _combination_key(candidate_ids),
            }
        )
    return normalized, {
        "raw_plan_count": len(plans),
        "valid_unique_plan_count": len(normalized),
        "rejected_plan_count": len(rejected),
        "limit_exceeded": False,
        "rejected_plans": rejected,
    }


def build_synthesis_scorecard(
    *,
    quality_score: float,
) -> dict[str, float]:
    """只记录合成质量门槛，不混入代码异味风险。"""

    return {
        "quality_score": round(quality_score, 4),
        "final_score": round(quality_score, 4),
        "acceptance_threshold": SYNTHESIS_ACCEPTANCE_SCORE,
    }


def decide_synthesis_status(
    *,
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
        return "rejected", "未能提供通过来源校验的成员共现区域上下文。"
    if not review_is_idiom:
        return "rejected", "质量有效性 Agent 判断合成结果不属于代码习语。"
    if not preserves_intents:
        return "rejected", "合成结果未忠实保留来源习语意图。"
    if not improves_quality:
        return "rejected", "合成结果相较来源习语没有明确质量增益。"

    scorecard = build_synthesis_scorecard(
        quality_score=quality_score,
    )
    if scorecard["final_score"] >= scorecard["acceptance_threshold"]:
        return "accepted", "已判断习语合成后产生明确质量增益。"
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
        max_plans_per_region: int = DEFAULT_MAX_PLANS_PER_REGION,
    ) -> None:
        self.model = model
        self.model_client = model_client
        self._owns_model_client = model_client is None
        if max_group_candidates < 2:
            raise ValueError("max_group_candidates 必须至少为 2")
        if max_plans_per_region < 1:
            raise ValueError("max_plans_per_region 必须至少为 1")
        self.max_group_candidates = max_group_candidates
        self.max_plans_per_region = max_plans_per_region
        self.runtime: Optional[SingleThreadedAgentRuntime] = None

    def run_contract(self) -> dict[str, object]:
        return {
            "artifact_semantics": "synthesis_delta",
            "region_grouping": "member_source_region_cooccurrence",
            "decision_policy": {
                "acceptance_score": SYNTHESIS_ACCEPTANCE_SCORE,
                "calibration_status": (
                    "synthetic_smoke_only_pilot_required"
                ),
            },
            "max_group_candidates": self.max_group_candidates,
            "max_plans_per_region": self.max_plans_per_region,
            "planning_mode": "single_region_call_batched_plans",
            "idiom_taxonomy": {
                "known_type_count": len(KNOWN_IDIOM_TYPES),
                "repository_specific_label": (
                    REPOSITORY_SPECIFIC_IDIOM_LABEL
                ),
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
            lambda: SynthesisPlanningAgent(
                self.model_client,
                self.max_plans_per_region,
            ),
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
            "matched_occurrences": candidate.occurrence_records(),
            "source_order_byte": candidate.first_source_byte,
            "support_count": candidate.support_count,
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
    ) -> list[SynthesisResult]:
        """对一个成员共现区域规划一次，并执行其中全部合法唯一计划。"""

        if len(candidates) < 2:
            raise ValueError("习语合成至少需要两个候选")
        project = candidates[0].project
        context_key = candidates[0].context_key
        if any(candidate.project != project for candidate in candidates):
            raise ValueError("禁止跨仓库合成习语")
        if any(candidate.context_key != context_key for candidate in candidates):
            raise ValueError("习语合成只能处理成员共同出现于同一源码范围的候选")

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
            return [
                SynthesisResult(
                    project=project,
                    status="rejected",
                    selected=list(candidates),
                    context_evidence=context_evidence,
                    region_planning={
                        "region_key": _region_key(context_key),
                        "candidate_ids": [
                            candidate.candidate_id
                            for candidate in candidates
                        ],
                        "max_plans_per_region": (
                            self.max_plans_per_region
                        ),
                        "planning_called": False,
                    },
                    agent_trace=_not_run_traces(
                        "candidate_limit_exceeded"
                    ),
                    scorecard=build_synthesis_scorecard(
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
            ]

        group_candidates = list(candidates)
        (
            available_context,
            context_evidence,
        ) = load_group_context_with_evidence(group_candidates, source_root)
        context_evidence.update(
            {
                "source_root_supplied": source_root is not None,
                "candidate_count": len(group_candidates),
            }
        )
        if not available_context:
            return [
                SynthesisResult(
                    project=project,
                    status="rejected",
                    context_evidence=context_evidence,
                    region_planning={
                        "region_key": _region_key(context_key),
                        "candidate_ids": [
                            candidate.candidate_id
                            for candidate in group_candidates
                        ],
                        "max_plans_per_region": (
                            self.max_plans_per_region
                        ),
                        "planning_called": False,
                    },
                    agent_trace=_not_run_traces("context_gate_rejected"),
                    scorecard=build_synthesis_scorecard(
                        quality_score=0.0,
                    ),
                    deterministic_checks={
                        "context_contract_valid": False
                    },
                    decision_reason=(
                        "未能自动加载并验证候选成员共同出现的源码区域。"
                    ),
                )
            ]

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
                    max_plans_per_region=self.max_plans_per_region,
                ),
                recipient=default_agent_id("synthesis_planning"),
            ),
            SynthesisPlanningResult(
                plans=[],
                reason="规划 Agent Runtime 路由失败，跳过当前候选组。",
                call_status="failed",
                call_attempts=0,
                failure_kind="runtime_dispatch_error",
            ),
        )
        plans, validation = normalize_synthesis_plans(
            plan_result.plans,
            group_candidates,
            max_plans_per_region=self.max_plans_per_region,
        )
        region_planning = {
            "region_key": _region_key(context_key),
            "candidate_ids": [
                candidate.candidate_id for candidate in group_candidates
            ],
            "max_plans_per_region": self.max_plans_per_region,
            "planning_called": True,
            "overall_reason": plan_result.reason,
            "plans": [asdict(plan) for plan in plan_result.plans],
            "call_status": plan_result.call_status,
            "call_attempts": plan_result.call_attempts,
            "failure_kind": plan_result.failure_kind,
            "validation": validation,
        }
        if not plans:
            plan_failed = plan_result.call_status == "failed"
            if plan_failed:
                reason = "规划 Agent 技术失败，跳过当前候选区域。"
            elif validation["raw_plan_count"]:
                reason = "规划 Agent 返回的计划均未通过确定性校验。"
            else:
                reason = plan_result.reason
            return [
                SynthesisResult(
                    project=project,
                    status="rejected",
                    context_evidence=context_evidence,
                    region_planning=region_planning,
                    agent_trace={
                        "planning": agent_trace(
                            plan_result,
                            "skip_region",
                        ),
                        **{
                            stage: not_run_trace("planning_stopped")
                            for stage in _SYNTHESIS_AGENT_STAGES[1:]
                        },
                    },
                    scorecard=build_synthesis_scorecard(
                        quality_score=0.0,
                    ),
                    deterministic_checks={
                        "synthesis_planned": False,
                        "planning_validation": validation,
                    },
                    decision_reason=reason,
                )
            ]

        results: list[SynthesisResult] = []
        planning_trace = agent_trace(plan_result, "skip_region")
        for plan in plans:
            selected = [
                group_candidates[index]
                for index in plan["selected_indices"]
            ]
            try:
                result = await self._execute_plan(
                    project=project,
                    selected=selected,
                    plan=plan,
                    available_context=available_context,
                    context_evidence=context_evidence,
                    region_planning=region_planning,
                    planning_trace=planning_trace,
                )
            except Exception as exc:
                logger.error(
                    "单个合成计划编排失败，已跳过并继续；error_type=%s",
                    type(exc).__name__,
                )
                result = SynthesisResult(
                    project=project,
                    status="rejected",
                    selected=selected,
                    context_evidence=context_evidence,
                    region_planning=region_planning,
                    plan=plan,
                    agent_trace={
                        "planning": planning_trace,
                        "plan_orchestration": {
                            "status": "failed",
                            "logical_attempts": 0,
                            "failure_kind": (
                                "unexpected_plan_orchestration_error"
                            ),
                            "failure_action": "skip_plan",
                        },
                    },
                    scorecard=build_synthesis_scorecard(
                        quality_score=0.0,
                    ),
                    deterministic_checks={
                        "plan_orchestration_completed": False
                    },
                    decision_reason=(
                        "当前计划发生未预料编排异常，已跳过并继续同区域其他计划。"
                    ),
                )
            results.append(result)
        return results

    async def _execute_plan(
        self,
        *,
        project: str,
        selected: Sequence[IdiomCandidate],
        plan: dict[str, object],
        available_context: str,
        context_evidence: dict[str, object],
        region_planning: dict[str, object],
        planning_trace: dict[str, object],
    ) -> SynthesisResult:
        assert self.runtime is not None
        assembly_result = await dispatch_with_fallback(
            self.runtime.send_message(
                IdiomAssemblyRequest(
                    selected_idioms=[
                        self._candidate_payload(candidate)
                        for candidate in selected
                    ],
                    plan=plan,
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
        unsupported_calls = unsupported_call_targets(
            merged,
            [candidate.code for candidate in selected],
            available_context,
        )
        syntax_valid = bool(merged) and syntax_structure_valid(merged)
        context_contract_valid = bool(available_context)
        deterministic = {
            "syntax_structure_valid": syntax_valid,
            "unsupported_call_targets": unsupported_calls,
            "context_contract_valid": context_contract_valid,
        }
        if not merged or not syntax_valid or unsupported_calls:
            if not merged:
                reason = (
                    "组装 Agent 技术失败，跳过复审并拒绝当前计划。"
                    if assembly_result.call_status == "failed"
                    else "组装 Agent 未产生代码，跳过复审并拒绝当前计划。"
                )
            elif not syntax_valid:
                reason = (
                    "合成结果未通过 Tree-sitter 语法结构检查，"
                    "跳过复审并拒绝当前计划。"
                )
            else:
                reason = (
                    "合成结果包含来源习语和允许上下文之外的新增调用，"
                    "跳过复审并拒绝当前计划。"
                )
            return SynthesisResult(
                project=project,
                status="rejected",
                selected=list(selected),
                merged_code=merged,
                context_evidence=context_evidence,
                region_planning=region_planning,
                plan=plan,
                assembly=assembly_data,
                agent_trace={
                    "planning": planning_trace,
                    "assembly": agent_trace(
                        assembly_result,
                        "skip_downstream_and_reject_plan",
                    ),
                    "quality_review": not_run_trace(
                        "assembly_or_deterministic_gate_rejected"
                    ),
                    "smell_review": not_run_trace(
                        "assembly_or_deterministic_gate_rejected"
                    ),
                },
                scorecard=build_synthesis_scorecard(
                    quality_score=0.0,
                ),
                deterministic_checks=deterministic,
                decision_reason=reason,
            )
        smell_request = SmellReviewRequest(
            project=project,
            candidate_id=str(plan["combination_key"]),
            candidate_code=merged,
            related_examples=[
                available_context,
                *[
                    str(occurrence["local_code"])
                    for candidate in selected
                    for occurrence in candidate.occurrence_records()
                    if occurrence["local_code"]
                ],
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
                        plan=plan,
                        merged_code=merged,
                        context_code=available_context,
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
        status, reason = decide_synthesis_status(
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
            selected=list(selected),
            merged_code=merged,
            context_evidence=context_evidence,
            region_planning=region_planning,
            plan=plan,
            assembly=assembly_data,
            review=review_data,
            smell=smell_data,
            smell_gate=smell_gate,
            smell_review_input=asdict(smell_request),
            agent_trace={
                "planning": planning_trace,
                "assembly": agent_trace(
                    assembly_result,
                    "skip_downstream_and_reject_plan",
                ),
                "quality_review": agent_trace(
                    review_result,
                    "reject_plan",
                ),
                "smell_review": agent_trace(
                    smell_result,
                    "reject_plan",
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
