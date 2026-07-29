"""习语合成输入、轨迹与输出对象。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from ..idiom_judgment.idiom_taxonomy import (
    CATALOGED_IDIOM_KIND,
    NOT_APPLICABLE_IDIOM_KIND,
    REPOSITORY_SPECIFIC_IDIOM_KIND,
    empty_idiom_classification,
)

IDIOM_SYNTHESIS_SCHEMA_VERSION = 7
SYNTHESIS_ARTIFACT_SEMANTICS = "synthesis_delta"


def _node_info(info: Any) -> Mapping[str, Any]:
    if isinstance(info, (list, tuple)) and len(info) >= 4:
        node = info[3]
        return node if isinstance(node, Mapping) else {}
    return info if isinstance(info, Mapping) else {}


@dataclass(frozen=True)
class IdiomCandidate:
    candidate_id: str
    project: str
    code: str
    loc_label: str
    source_infos: List[Any]
    representative_info: Any
    support_count: int
    input_stage: int
    intent: str = ""
    judgment_status: str = ""
    judgment_reason: str = ""
    idiom_classification: Dict[str, Any] = field(default_factory=dict)
    agent_reasons: Dict[str, str] = field(default_factory=dict)
    placeholders: List[Dict[str, Any]] = field(default_factory=list)
    judgment_evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def context_key(self) -> str:
        info = self.representative_info
        if isinstance(info, (list, tuple)) and len(info) >= 3:
            source_path = str(info[1] or "").strip()
            source_extent = str(info[2] or "").strip()
            if source_path and source_extent:
                return f"{self.project}:{source_path}:{source_extent}"
        # loc_label 是历史显示字段，不能证明两个候选来自同一源码区域。缺少
        # 代表文件或范围时为每个候选生成独立键，使其无法误入阶段4合成组。
        return f"{self.project}:unlocated:{self.candidate_id}"


@dataclass
class SynthesisResult:
    project: str
    status: str
    selected: List[IdiomCandidate] = field(default_factory=list)
    merged_code: str = ""
    context_evidence: Dict[str, Any] = field(default_factory=dict)
    plan: Dict[str, Any] = field(default_factory=dict)
    assembly: Dict[str, Any] = field(default_factory=dict)
    review: Dict[str, Any] = field(default_factory=dict)
    smell: Dict[str, Any] = field(default_factory=dict)
    smell_gate: Dict[str, Any] = field(default_factory=dict)
    smell_review_input: Dict[str, Any] = field(default_factory=dict)
    agent_trace: Dict[str, Any] = field(default_factory=dict)
    scorecard: Dict[str, Any] = field(default_factory=dict)
    deterministic_checks: Dict[str, Any] = field(default_factory=dict)
    decision_reason: str = ""

    def to_record(self) -> Dict[str, Any]:
        infos: List[Any] = []
        cnt = 0
        ast_total = 0.0
        ast_weight = 0
        subtree_total = 0.0
        subtree_weight = 0
        for candidate in self.selected:
            if candidate.source_infos:
                infos.extend(candidate.source_infos)
            elif candidate.representative_info is not None:
                infos.append(candidate.representative_info)
            weight = max(1, int(candidate.support_count or 0))
            cnt += weight
            node = _node_info(candidate.representative_info)
            ast = float(node.get("ast_num", 0) or 0)
            subtree = float(node.get("subtree_size", 0) or 0)
            if ast:
                ast_total += ast * weight
                ast_weight += weight
            if subtree:
                subtree_total += subtree * weight
                subtree_weight += weight
        loc_labels = sorted(
            {candidate.loc_label for candidate in self.selected if candidate.loc_label}
        )
        classification = self.review.get("idiom_classification")
        if not isinstance(classification, Mapping):
            classification = asdict(
                empty_idiom_classification(
                    "尚未执行或未通过合成结果习语类型复审。"
                )
            )
        agent_reasons = {
            "planning": str(self.plan.get("reason") or ""),
            "assembly": str(self.assembly.get("reason") or ""),
            "quality_review": str(self.review.get("reason") or ""),
            "idiom_classification": str(
                classification.get("reason") or ""
            ),
            "smell_review": str(self.smell.get("reason") or ""),
        }
        source_judgments = [
            {
                "candidate_id": candidate.candidate_id,
                "judgment_status": candidate.judgment_status,
                "intent": candidate.intent,
                "judgment_reason": candidate.judgment_reason,
                "idiom_classification": dict(
                    candidate.idiom_classification
                ),
                "agent_reasons": dict(candidate.agent_reasons),
            }
            for candidate in self.selected
        ]
        return {
            "idiom_synthesis_schema_version": IDIOM_SYNTHESIS_SCHEMA_VERSION,
            "project": self.project,
            "status": self.status,
            "center_point": self.merged_code,
            "synthesized_code": self.merged_code,
            "selected_candidate_ids": [
                candidate.candidate_id for candidate in self.selected
            ],
            "source_judgments": source_judgments,
            "input_stages": sorted(
                {candidate.input_stage for candidate in self.selected}
            ),
            "loc_label": loc_labels[0] if len(loc_labels) == 1 else "",
            "source_loc_labels": loc_labels,
            "info": infos[0] if infos else None,
            "source_infos": infos,
            "cnt": cnt,
            "avg_ast_num": ast_total / ast_weight if ast_weight else 0.0,
            "avg_subtree_size": (
                subtree_total / subtree_weight if subtree_weight else 0.0
            ),
            "context_evidence": self.context_evidence,
            "synthesis_plan": self.plan,
            "assembly": self.assembly,
            "review": self.review,
            "idiom_classification": dict(classification),
            "smell": self.smell,
            "smell_gate": self.smell_gate,
            "smell_review_input": self.smell_review_input,
            "agent_trace": self.agent_trace,
            "scorecard": self.scorecard,
            "deterministic_checks": self.deterministic_checks,
            "decision_reason": self.decision_reason,
            "agent_reasons": agent_reasons,
            "merge_rounds": 1,
            "synthesis_trace": [
                {
                    "selected_candidate_ids": [
                        candidate.candidate_id for candidate in self.selected
                    ],
                    "status": self.status,
                    "reason": self.decision_reason,
                }
            ],
        }


def build_synthesis_artifact(
    project: str,
    results: Sequence[SynthesisResult],
    *,
    input_kind: str,
    input_candidate_count: int | None = None,
    related_group_count: int | None = None,
    grouped_candidate_count: int | None = None,
) -> Dict[str, Any]:
    records = [result.to_record() for result in results]
    unsupported_statuses = sorted(
        {
            str(record["status"])
            for record in records
            if record["status"] not in {"accepted", "rejected"}
        }
    )
    if unsupported_statuses:
        raise ValueError(
            "阶段4只支持 accepted/rejected，收到: "
            + ", ".join(unsupported_statuses)
        )
    accepted = [record for record in records if record["status"] == "accepted"]
    rejected = [record for record in records if record["status"] == "rejected"]
    classification_kind_counts = {
        CATALOGED_IDIOM_KIND: 0,
        REPOSITORY_SPECIFIC_IDIOM_KIND: 0,
        NOT_APPLICABLE_IDIOM_KIND: 0,
    }
    catalog_type_counts: Dict[str, int] = {}
    for record in accepted:
        classification = record.get("idiom_classification") or {}
        kind = str(classification.get("kind") or NOT_APPLICABLE_IDIOM_KIND)
        classification_kind_counts[kind] = (
            classification_kind_counts.get(kind, 0) + 1
        )
        for type_id in classification.get("catalog_ids") or []:
            catalog_type_counts[str(type_id)] = (
                catalog_type_counts.get(str(type_id), 0) + 1
            )
    return {
        "artifact_type": "idiom_synthesis",
        "stage": 4,
        "idiom_synthesis_schema_version": IDIOM_SYNTHESIS_SCHEMA_VERSION,
        "project": project,
        "input_kind": input_kind,
        "artifact_semantics": SYNTHESIS_ARTIFACT_SEMANTICS,
        "passthrough_included": False,
        "accepted": accepted,
        "rejected": rejected,
        "summary": {
            "attempt_count": len(records),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "input_candidate_count": (
                int(input_candidate_count)
                if input_candidate_count is not None
                else None
            ),
            "related_group_count": (
                int(related_group_count)
                if related_group_count is not None
                else None
            ),
            "grouped_candidate_count": (
                int(grouped_candidate_count)
                if grouped_candidate_count is not None
                else None
            ),
            "passthrough_candidate_count": 0,
            "accepted_classification_kind_counts": (
                classification_kind_counts
            ),
            "accepted_catalog_type_counts": dict(
                sorted(catalog_type_counts.items())
            ),
            "technical_failure_count": sum(
                any(
                    isinstance(trace, Mapping)
                    and trace.get("status") == "failed"
                    for trace in (record.get("agent_trace") or {}).values()
                )
                for record in records
            ),
        },
    }
