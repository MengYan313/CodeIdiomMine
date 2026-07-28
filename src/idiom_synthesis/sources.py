"""阶段3正式输入及阶段2合同兼容输入到合成候选的适配器。"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from .schema import IdiomCandidate


def _semantic_intent(record: Dict[str, Any]) -> str:
    semantic = record.get("semantic")
    if isinstance(semantic, dict):
        return str(semantic.get("intent") or "")
    return ""


def _from_judgment_artifact(
    artifact: Dict[str, Any],
) -> tuple[str, List[IdiomCandidate]]:
    project = str(artifact.get("project") or "")
    candidates: List[IdiomCandidate] = []
    for record in artifact.get("accepted") or []:
        approved_ids = {
            str(value)
            for value in (record.get("approved_abstraction_ids") or [])
        }
        approved_proposals = [
            proposal
            for proposal in (record.get("abstraction_proposals") or [])
            if isinstance(proposal, dict)
            and str(proposal.get("proposal_id")) in approved_ids
        ]
        raw_agent_reasons = record.get("agent_reasons")
        agent_reasons = {
            str(key): str(value)
            for key, value in (
                raw_agent_reasons.items()
                if isinstance(raw_agent_reasons, Mapping)
                else []
            )
        }
        raw_classification = record.get("idiom_classification")
        candidates.append(
            IdiomCandidate(
                candidate_id=f"judgment:{record.get('cluster_id')}",
                project=project or str(record.get("project") or ""),
                code=str(
                    record.get("template_code")
                    or record.get("center_point")
                    or ""
                ).strip(),
                loc_label=str(record.get("loc_label") or ""),
                source_infos=list(record.get("source_infos") or []),
                representative_info=record.get("info"),
                support_count=int(record.get("cnt") or 0),
                input_stage=3,
                intent=_semantic_intent(record),
                judgment_status=str(record.get("status") or ""),
                judgment_reason=str(record.get("decision_reason") or ""),
                idiom_classification=(
                    dict(raw_classification)
                    if isinstance(raw_classification, Mapping)
                    else {}
                ),
                agent_reasons=agent_reasons,
                placeholders=approved_proposals,
                judgment_evidence={
                    "rules": record.get("rules"),
                    "semantic": record.get("semantic"),
                    "smell": record.get("smell"),
                    "approved_abstraction_ids": record.get(
                        "approved_abstraction_ids"
                    ),
                    "abstraction_applied": record.get(
                        "abstraction_applied"
                    ),
                    "decision_reason": record.get("decision_reason"),
                    "idiom_classification": record.get(
                        "idiom_classification"
                    ),
                    "agent_reasons": record.get("agent_reasons"),
                },
            )
        )
    return project, [candidate for candidate in candidates if candidate.code]


def _from_stage2(items: List[Any]) -> tuple[str, List[IdiomCandidate]]:
    if len(items) != 1 or not isinstance(items[0], dict):
        raise ValueError("阶段2合同适配一次只接受一个仓库的 clusters.pkl")
    project = str(items[0].get("pros_name") or "")
    clusters = items[0].get("clusters")
    candidates: List[IdiomCandidate] = []
    for _, row in clusters.iterrows():
        infos = list(row.get("infos") or [])
        candidates.append(
            IdiomCandidate(
                candidate_id=f"cluster:{row.get('label')}",
                project=project,
                code=str(row.get("center_point") or "").strip(),
                loc_label=str(row.get("loc_label") or ""),
                source_infos=infos,
                representative_info=row.get("center_point_info"),
                support_count=int(row.get("cluster_size") or len(infos)),
                input_stage=2,
                judgment_status="not_run",
            )
        )
    return project, [candidate for candidate in candidates if candidate.code]


def load_idiom_candidates(
    path: str | Path,
    *,
    input_kind: str = "auto",
) -> tuple[str, List[IdiomCandidate], str]:
    """适配阶段3正式输入；阶段2分支只用于合同与后备逻辑验证。"""

    with Path(path).open("rb") as stream:
        data = pickle.load(stream)
    detected = input_kind
    if input_kind == "auto":
        if isinstance(data, dict) and data.get("artifact_type") == "idiom_judgment":
            detected = "judgment"
        elif (
            isinstance(data, list)
            and data
            and isinstance(data[0], dict)
            and "clusters" in data[0]
            and "pros_name" in data[0]
        ):
            detected = "stage2"
        else:
            raise ValueError("无法识别合成输入产物")

    if detected == "judgment":
        if not isinstance(data, dict):
            raise ValueError("judgment 输入必须是习语判断 artifact")
        project, candidates = _from_judgment_artifact(data)
    elif detected == "stage2":
        if not isinstance(data, list):
            raise ValueError("stage2 输入必须是 clusters.pkl")
        project, candidates = _from_stage2(data)
    else:
        raise ValueError(f"不支持的 input_kind: {input_kind}")
    if not project:
        raise ValueError("无法从输入确定仓库身份")
    if any(candidate.project != project for candidate in candidates):
        raise ValueError("合成输入包含多个仓库")
    return project, candidates, detected


def group_related_idioms(
    candidates: Iterable[IdiomCandidate],
) -> List[List[IdiomCandidate]]:
    """
    只以完全相同的代表函数/区域身份形成候选组。

    阶段4是同区域合成增量，不根据跨区域共现、语义相似度或其他成员位置扩大
    分组。没有同区域伙伴的阶段3习语继续保留在阶段3产物，不复制进阶段4。
    """

    groups: Dict[str, List[IdiomCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.context_key, []).append(candidate)
    return [
        sorted(
            group,
            key=lambda candidate: (
                -candidate.support_count,
                candidate.candidate_id,
            ),
        )
        for _, group in sorted(groups.items())
        if len(group) >= 2
    ]
