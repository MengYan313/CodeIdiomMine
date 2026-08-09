"""把习语判断产物转换为合成候选。"""

from __future__ import annotations

import pickle
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from ..idiom_judgment.source_context import representative_source_identity
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


def load_idiom_candidates(
    path: str | Path,
) -> tuple[str, List[IdiomCandidate]]:
    """加载当前习语判断产物。"""

    with Path(path).open("rb") as stream:
        data = pickle.load(stream)
    if not isinstance(data, dict) or data.get("artifact_type") != "idiom_judgment":
        raise ValueError("合成输入必须是习语判断 artifact")
    project, candidates = _from_judgment_artifact(data)
    if not project:
        raise ValueError("无法从输入确定仓库身份")
    if any(candidate.project != project for candidate in candidates):
        raise ValueError("合成输入包含多个仓库")
    return project, candidates


def load_accepted_judgments(path: str | Path) -> List[Dict[str, Any]]:
    """读取阶段3基础习语库，供阶段4构造最终库。"""

    with Path(path).open("rb") as stream:
        data = pickle.load(stream)
    if not isinstance(data, dict) or data.get("artifact_type") != "idiom_judgment":
        raise ValueError("合成输入必须是习语判断 artifact")
    accepted = data.get("accepted")
    if not isinstance(accepted, list):
        raise TypeError("习语判断 artifact 的 accepted 必须是列表")
    return accepted


def group_related_idioms(
    candidates: Iterable[IdiomCandidate],
) -> List[List[IdiomCandidate]]:
    """
    使用完整簇成员位置发现同一函数/区域内的习语共现。

    每个阶段3习语在一个区域内最多形成一个区域绑定候选；相同候选集合跨区域
    只保留首个稳定代表，避免重复规划和相反裁决。没有同区域伙伴的习语仍由
    阶段3基础库保留。
    """

    candidates_by_id: Dict[str, IdiomCandidate] = {}
    regions: Dict[
        tuple[str, str, str],
        Dict[str, Dict[tuple[Any, ...], Any]],
    ] = {}
    for candidate in candidates:
        candidates_by_id[candidate.candidate_id] = candidate
        infos = candidate.source_infos or [candidate.representative_info]
        for info in infos:
            identity = representative_source_identity(
                candidate.project,
                info,
            )
            if identity is None:
                continue
            node = info[3]
            occurrence_key = (
                str(node.get("extent") or ""),
                node.get("start_byte"),
                node.get("end_byte"),
            )
            regions.setdefault(identity, {}).setdefault(
                candidate.candidate_id,
                {},
            ).setdefault(occurrence_key, info)

    groups: Dict[tuple[str, ...], List[IdiomCandidate]] = {}
    for _, region_candidates in sorted(regions.items()):
        if len(region_candidates) < 2:
            continue
        group = [
            replace(
                candidates_by_id[candidate_id],
                region_info=next(iter(occurrences.values())),
                matched_source_infos=list(occurrences.values()),
            )
            for candidate_id, occurrences in region_candidates.items()
        ]
        group = sorted(
            group,
            key=lambda candidate: (
                -candidate.support_count,
                candidate.candidate_id,
            ),
        )
        key = tuple(sorted(candidate.candidate_id for candidate in group))
        groups.setdefault(key, group)
    return list(groups.values())
