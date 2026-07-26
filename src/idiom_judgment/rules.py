"""习语判断的单簇确定性过滤规则。"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

from .schema import ClusterCandidate, RuleAssessment


_TRIVIAL_CODE = re.compile(
    r"^(?:;|\{\s*\}|break\s*;|continue\s*;|return\s*;)$"
)
_MEANINGFUL_TEXT = re.compile(
    r"(?:\w+\s*\(|=|\b(?:if|for|while|switch|try|catch|throw|co_await)\b)"
)


def _normalize_source(source: str) -> str:
    return re.sub(r"\s+", " ", source).strip()


def _bounded_score(candidate: ClusterCandidate) -> float:
    support = max(0, len(candidate.member_codes))
    unique_sources = len({_normalize_source(code) for code in candidate.member_codes})
    unique_files = len(set(candidate.source_files))
    subtree_sizes = [
        float(info.get("subtree_size", 0) or 0)
        for info in candidate.node_infos
        if isinstance(info, Mapping)
    ]
    median_size = 0.0
    if subtree_sizes:
        values = sorted(subtree_sizes)
        median_size = values[len(values) // 2]
    score = min(25.0, 10.0 * math.log2(max(1, support)))
    score += min(20.0, 8.0 * math.log2(max(1, unique_sources)))
    score += 20.0 if unique_files >= 2 else 5.0
    score += min(20.0, median_size / 2.0)
    score += 15.0 if any(
        _MEANINGFUL_TEXT.search(code) for code in candidate.member_codes
    ) else 0.0
    return round(min(100.0, score), 4)


def evaluate_cluster_rules(candidate: ClusterCandidate) -> RuleAssessment:
    """只拒绝合同无效或确定性低价值的簇；模糊质量交给 LLM。"""

    hard_failures: list[str] = []
    warnings: list[str] = []
    support_count = len(candidate.source_infos) or len(candidate.member_codes)
    normalized = [
        _normalize_source(code)
        for code in candidate.member_codes
        if _normalize_source(code)
    ]
    unique_source_count = len(set(normalized))
    unique_file_count = len(set(candidate.source_files))

    if candidate.declared_cluster_size < 2 or support_count < 2:
        hard_failures.append("cluster_support_below_two")
    if not candidate.representative_code:
        hard_failures.append("empty_representative")
    if not normalized:
        hard_failures.append("empty_members")
    if (
        candidate.source_infos
        and candidate.declared_cluster_size != len(candidate.source_infos)
    ):
        hard_failures.append("cluster_size_mismatch")

    projects = {
        str(info[0])
        for info in candidate.source_infos
        if isinstance(info, (list, tuple)) and info
    }
    if projects and projects != {candidate.project}:
        hard_failures.append("mixed_repository_evidence")

    if normalized and all(_TRIVIAL_CODE.fullmatch(code) for code in normalized):
        hard_failures.append("trivial_control_only")

    exact_duplicate = unique_source_count == 1 and bool(normalized)
    cross_file = unique_file_count >= 2
    if exact_duplicate:
        warnings.append("exact_source_duplicate")
    if not cross_file:
        warnings.append("single_file_only")
    if unique_source_count < 2:
        warnings.append("no_source_variation")
    if support_count != candidate.declared_cluster_size:
        warnings.append("support_derived_from_available_evidence")

    parse_flagged = sum(
        bool(int(info.get("parse_flags", 0) or 0) & 0b111)
        for info in candidate.node_infos
    )
    if parse_flagged:
        warnings.append("parser_diagnostics_present")

    return RuleAssessment(
        eligible_for_llm=not hard_failures,
        score=_bounded_score(candidate),
        support_count=support_count,
        unique_source_count=unique_source_count,
        unique_file_count=unique_file_count,
        exact_duplicate=exact_duplicate,
        cross_file=cross_file,
        hard_failures=hard_failures,
        warnings=warnings,
        evidence={
            "declared_cluster_size": candidate.declared_cluster_size,
            "available_member_code_count": len(candidate.member_codes),
            "available_source_info_count": len(candidate.source_infos),
            "parse_flagged_member_count": parse_flagged,
        },
    )
