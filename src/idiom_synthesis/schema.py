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

SYNTHESIS_ARTIFACT_SEMANTICS = "synthesis_delta"


def _node_info(info: Any) -> Mapping[str, Any]:
    if isinstance(info, (list, tuple)) and len(info) >= 4:
        node = info[3]
        return node if isinstance(node, Mapping) else {}
    return info if isinstance(info, Mapping) else {}


def _source_identity(info: Any) -> tuple[str, str, str] | None:
    if not isinstance(info, (list, tuple)) or len(info) < 4:
        return None
    project, source_path, source_extent, _ = info[:4]
    if not project or not source_path or not source_extent:
        return None
    return str(project), str(source_path), str(source_extent)


def _occurrence_sort_key(info: Any) -> tuple[int, int, str]:
    node = _node_info(info)
    return (
        int(node.get("start_byte", 0) or 0),
        int(node.get("end_byte", 0) or 0),
        str(node.get("extent") or ""),
    )


@dataclass(frozen=True)
class IdiomCandidate:
    candidate_id: str
    project: str
    code: str
    loc_label: str
    source_infos: List[Any]
    representative_info: Any
    support_count: int
    region_info: Any = None
    matched_source_infos: List[Any] = field(default_factory=list)
    intent: str = ""
    judgment_status: str = ""
    judgment_reason: str = ""
    idiom_classification: Dict[str, Any] = field(default_factory=dict)
    agent_reasons: Dict[str, str] = field(default_factory=dict)
    placeholders: List[Dict[str, Any]] = field(default_factory=list)
    judgment_evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def context_info(self) -> Any:
        return self.region_info or self.representative_info

    @property
    def context_key(self) -> tuple[str, str, str]:
        identity = _source_identity(self.context_info)
        if identity is not None and identity[0] == self.project:
            return identity
        # loc_label 是历史显示字段，不能证明两个候选来自同一源码区域。缺少
        # 区域成员或代表范围时为每个候选生成独立键，使其无法误入阶段4合成组。
        return self.project, "", f"unlocated:{self.candidate_id}"

    @property
    def region_source_infos(self) -> List[Any]:
        if self.matched_source_infos:
            return sorted(self.matched_source_infos, key=_occurrence_sort_key)
        matching = [
            info
            for info in self.source_infos
            if _source_identity(info) == self.context_key
        ]
        if matching:
            return sorted(matching, key=_occurrence_sort_key)
        return [self.context_info] if self.context_info is not None else []

    @property
    def first_source_byte(self) -> int:
        infos = self.region_source_infos
        if not infos:
            return 0
        return _occurrence_sort_key(infos[0])[0]

    def occurrence_records(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for info in self.region_source_infos:
            identity = _source_identity(info)
            if identity is None:
                continue
            node = _node_info(info)
            records.append(
                {
                    "candidate_id": self.candidate_id,
                    "project": identity[0],
                    "source_path": identity[1],
                    "function_extent": identity[2],
                    "candidate_extent": str(node.get("extent") or ""),
                    "start_byte": node.get("start_byte"),
                    "end_byte": node.get("end_byte"),
                    "local_code": str(node.get("code_snippet") or ""),
                }
            )
        return records


@dataclass
class SynthesisResult:
    project: str
    status: str
    selected: List[IdiomCandidate] = field(default_factory=list)
    merged_code: str = ""
    context_evidence: Dict[str, Any] = field(default_factory=dict)
    region_planning: Dict[str, Any] = field(default_factory=dict)
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
        matched_infos: List[Any] = []
        cnt = 0
        ast_total = 0.0
        ast_weight = 0
        subtree_total = 0.0
        subtree_weight = 0
        for candidate in self.selected:
            matched_infos.extend(candidate.region_source_infos)
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
            "planning": str(
                self.plan.get("reason")
                or self.region_planning.get("overall_reason")
                or ""
            ),
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
        matched_occurrences = [
            occurrence
            for candidate in self.selected
            for occurrence in candidate.occurrence_records()
        ]
        source_order_candidate_ids = [
            candidate.candidate_id
            for candidate in sorted(
                self.selected,
                key=lambda candidate: (
                    candidate.first_source_byte,
                    candidate.candidate_id,
                ),
            )
        ]
        region_identity = dict(
            self.context_evidence.get("source_identity") or {}
        )
        return {
            "project": self.project,
            "status": self.status,
            "center_point": self.merged_code,
            "synthesized_code": self.merged_code,
            "selected_candidate_ids": [
                candidate.candidate_id for candidate in self.selected
            ],
            "source_judgments": source_judgments,
            "loc_label": loc_labels[0] if len(loc_labels) == 1 else "",
            "source_loc_labels": loc_labels,
            "info": matched_infos[0] if matched_infos else (
                infos[0] if infos else None
            ),
            "source_infos": infos,
            "matched_source_infos": matched_infos,
            "matched_occurrences": matched_occurrences,
            "region_identity": region_identity,
            "source_order_candidate_ids": source_order_candidate_ids,
            "cooccurrence_evidence": {
                "grouping": "member_source_region_cooccurrence",
                "selected_candidate_count": len(self.selected),
                "matched_occurrence_count": len(matched_occurrences),
            },
            "cnt": cnt,
            "avg_ast_num": ast_total / ast_weight if ast_weight else 0.0,
            "avg_subtree_size": (
                subtree_total / subtree_weight if subtree_weight else 0.0
            ),
            "context_evidence": self.context_evidence,
            "region_planning": self.region_planning,
            "combination_key": str(
                self.plan.get("combination_key") or ""
            ),
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
                    "combination_key": str(
                        self.plan.get("combination_key") or ""
                    ),
                    "selected_candidate_ids": [
                        candidate.candidate_id for candidate in self.selected
                    ],
                    "relation_kind": str(
                        self.plan.get("relation_kind") or ""
                    ),
                    "status": self.status,
                    "reason": self.decision_reason,
                }
            ],
        }


def build_synthesis_artifact(
    project: str,
    results: Sequence[SynthesisResult],
    *,
    input_candidate_count: int | None = None,
    related_group_count: int | None = None,
    grouped_candidate_count: int | None = None,
    region_candidate_membership_count: int | None = None,
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
    regions = {
        str(planning["region_key"]): planning
        for record in records
        if (planning := record.get("region_planning"))
        and planning.get("region_key")
    }
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
        "project": project,
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
            "region_candidate_membership_count": (
                int(region_candidate_membership_count)
                if region_candidate_membership_count is not None
                else None
            ),
            "planning_call_count": sum(
                bool(planning.get("planning_called"))
                for planning in regions.values()
            ),
            "valid_unique_plan_count": sum(
                int(
                    (
                        planning.get("validation") or {}
                    ).get("valid_unique_plan_count", 0)
                )
                for planning in regions.values()
            ),
            "rejected_planning_plan_count": sum(
                int(
                    (
                        planning.get("validation") or {}
                    ).get("rejected_plan_count", 0)
                )
                for planning in regions.values()
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
