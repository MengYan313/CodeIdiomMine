"""习语判断内部对象与阶段间兼容投影。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from .smell_taxonomy import SmellFinding


IDIOM_JUDGMENT_SCHEMA_VERSION = 6


def _node_info(info: Any) -> Mapping[str, Any]:
    if isinstance(info, (list, tuple)) and len(info) >= 4:
        node = info[3]
        if isinstance(node, Mapping):
            return node
    if isinstance(info, Mapping):
        return info
    return {}


def _member_code(info: Any) -> str:
    return str(_node_info(info).get("code_snippet") or "").strip()


def _source_file(info: Any) -> str:
    if isinstance(info, (list, tuple)) and len(info) >= 2:
        return str(info[1] or "")
    node = _node_info(info)
    return str(node.get("source_path") or "")


@dataclass(frozen=True)
class ClusterCandidate:
    """阶段2单簇在阶段3中的稳定表示。"""

    project: str
    cluster_id: str
    representative_code: str
    member_codes: List[str]
    representative_info: Any
    source_infos: List[Any]
    loc_label: str
    declared_cluster_size: int
    input_stage: int = 2

    @classmethod
    def from_cluster_row(
        cls,
        project: str,
        row: Mapping[str, Any],
    ) -> "ClusterCandidate":
        infos = list(row.get("infos") or [])
        representative = str(row.get("center_point") or "").strip()
        # `center_point + else_point` 是阶段2簇成员源码的直接合同，优先使用它
        # 以保证语义/抽象 Agent 看见完整簇；`infos[*].code_snippet` 仅作旧产物
        # 缺失该字段时的兼容回退。
        codes = [representative] if representative else []
        codes.extend(
            str(code).strip()
            for code in (row.get("else_point") or [])
            if str(code).strip()
        )
        if not codes:
            codes = [
                code
                for code in (_member_code(info) for info in infos)
                if code
            ]
        return cls(
            project=str(project),
            cluster_id=str(row.get("label")),
            representative_code=representative,
            member_codes=codes,
            representative_info=row.get("center_point_info"),
            source_infos=infos,
            loc_label=str(row.get("loc_label") or ""),
            declared_cluster_size=int(row.get("cluster_size") or len(infos)),
        )

    @property
    def source_files(self) -> List[str]:
        return [_source_file(info) for info in self.source_infos if _source_file(info)]

    @property
    def node_infos(self) -> List[Mapping[str, Any]]:
        return [_node_info(info) for info in self.source_infos]


@dataclass(frozen=True)
class RuleAssessment:
    """确定性规则的证据与门禁。"""

    eligible_for_llm: bool
    score: float
    support_count: int
    unique_source_count: int
    unique_file_count: int
    exact_duplicate: bool
    cross_file: bool
    hard_failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AbstractionProposal:
    """一个由规则发现、仍需语义/抽象 Agent 决策的保守抽象提案。"""

    proposal_id: str
    placeholder: str
    category: str
    token_positions: List[int]
    anchor_ranges: List[List[int]]
    values: List[str]
    support_count: int
    distinct_count: int
    support_ratio: float
    reason: str


@dataclass(frozen=True)
class SemanticAssessment:
    semantic_score: float
    reuse_score: float
    intent: str
    preconditions: List[str]
    abstraction_decision: str
    approved_abstraction_ids: List[str]
    abstraction_reason: str
    reason: str


@dataclass(frozen=True)
class SmellAssessment:
    analysis_status: str
    risk_score: float
    max_severity: str
    categories: List[str]
    findings: List[SmellFinding]
    reason: str


@dataclass
class IdiomJudgmentResult:
    """单簇阶段3结果；所有状态均保留完整证据。"""

    candidate: ClusterCandidate
    rules: RuleAssessment
    proposals: List[AbstractionProposal]
    status: str
    template_code: str
    approved_abstraction_ids: List[str] = field(default_factory=list)
    abstraction_applied: bool = False
    semantic: SemanticAssessment | None = None
    semantic_review_input: Dict[str, Any] = field(default_factory=dict)
    context_evidence: Dict[str, Any] = field(default_factory=dict)
    smell: SmellAssessment | None = None
    smell_gate: Dict[str, Any] = field(default_factory=dict)
    smell_review_input: Dict[str, Any] = field(default_factory=dict)
    agent_trace: Dict[str, Any] = field(default_factory=dict)
    scorecard: Dict[str, Any] = field(default_factory=dict)
    decision_reason: str = ""

    def to_record(self) -> Dict[str, Any]:
        node_infos = self.candidate.node_infos
        ast_nums = [
            float(info.get("ast_num", 0) or 0)
            for info in node_infos
            if isinstance(info, Mapping)
        ]
        subtree_sizes = [
            float(info.get("subtree_size", 0) or 0)
            for info in node_infos
            if isinstance(info, Mapping)
            and info.get("subtree_size") is not None
        ]
        record = {
            "idiom_judgment_schema_version": IDIOM_JUDGMENT_SCHEMA_VERSION,
            "project": self.candidate.project,
            "cluster_id": self.candidate.cluster_id,
            "status": self.status,
            "template_code": self.template_code,
            # 兼容既有阶段4/评价字段，但明确它是阶段3候选模板视图。
            "center_point": self.template_code,
            "representative_code": self.candidate.representative_code,
            "info": self.candidate.representative_info,
            "source_infos": list(self.candidate.source_infos),
            "cnt": self.rules.support_count,
            "avg_ast_num": (
                sum(ast_nums) / len(ast_nums) if ast_nums else 0.0
            ),
            "avg_subtree_size": (
                sum(subtree_sizes) / len(subtree_sizes)
                if subtree_sizes
                else 0.0
            ),
            "loc_label": self.candidate.loc_label,
            "input_stage": self.candidate.input_stage,
            "rules": asdict(self.rules),
            "abstraction_proposals": [
                asdict(proposal) for proposal in self.proposals
            ],
            "approved_abstraction_ids": list(
                self.approved_abstraction_ids
            ),
            "abstraction_applied": bool(self.abstraction_applied),
            "semantic": asdict(self.semantic) if self.semantic else None,
            "semantic_review_input": dict(self.semantic_review_input),
            "context_evidence": dict(self.context_evidence),
            "smell": asdict(self.smell) if self.smell else None,
            "smell_gate": dict(self.smell_gate),
            "smell_review_input": dict(self.smell_review_input),
            "agent_trace": dict(self.agent_trace),
            "scorecard": dict(self.scorecard),
            "decision_reason": self.decision_reason,
        }
        return record


def build_judgment_artifact(
    project: str,
    results: Sequence[IdiomJudgmentResult],
    *,
    rule_only: bool,
) -> Dict[str, Any]:
    records = [result.to_record() for result in results]
    by_status: Dict[str, List[Dict[str, Any]]] = {
        "accepted": [],
        "rejected": [],
        "pending_llm": [],
    }
    for record in records:
        status = record["status"]
        if status not in by_status:
            raise ValueError(f"阶段3不支持状态: {status}")
        if status == "pending_llm" and not rule_only:
            raise ValueError("完整阶段3运行不得输出 pending_llm")
        by_status[status].append(record)
    return {
        "artifact_type": "idiom_judgment",
        "stage": 3,
        "idiom_judgment_schema_version": IDIOM_JUDGMENT_SCHEMA_VERSION,
        "project": project,
        "rule_only": bool(rule_only),
        "accepted": by_status["accepted"],
        "rejected": by_status["rejected"],
        "pending_llm": by_status["pending_llm"],
        "summary": {
            "input_cluster_count": len(records),
            "accepted_count": len(by_status["accepted"]),
            "rejected_count": len(by_status["rejected"]),
            "pending_llm_count": len(by_status["pending_llm"]),
            "context_verified_count": sum(
                (record.get("context_evidence") or {}).get("verified")
                is True
                for record in records
            ),
            "context_unavailable_count": sum(
                (record.get("context_evidence") or {}).get("available")
                is False
                for record in records
            ),
            "context_required_rejection_count": sum(
                "context_required" in (
                    (record.get("rules") or {}).get("hard_failures") or []
                )
                for record in by_status["rejected"]
            ),
            "accepted_abstracted_count": sum(
                bool(record.get("abstraction_applied"))
                for record in by_status["accepted"]
            ),
            "accepted_unchanged_count": sum(
                not bool(record.get("abstraction_applied"))
                for record in by_status["accepted"]
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
