"""合成阶段的有界源码上下文读取与确定性验证。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Sequence

from ..parser.cpp_adapter import CPP_ADAPTER
from ..idiom_judgment.abstraction import sanitize_template_for_parser
from ..idiom_judgment.source_context import (
    load_verified_source_context,
    representative_source_identity,
    representative_source_sha256,
)
from .schema import IdiomCandidate


_CALL_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_:]*)\s*\(",
)
_CALL_KEYWORDS = {
    "alignas",
    "alignof",
    "catch",
    "decltype",
    "for",
    "if",
    "noexcept",
    "requires",
    "sizeof",
    "static_assert",
    "switch",
    "while",
}
SYNTHESIS_CONTEXT_MODE = "automatic_verified_member_cooccurrence_extent"


def load_group_context_with_evidence(
    candidates: Sequence[IdiomCandidate],
    source_root: str | Path | None,
    *,
    max_lines: int = 300,
    max_chars: int = 12000,
) -> tuple[str, dict[str, object]]:
    """读取成员共同出现的源码范围，并返回可审计的身份与哈希证据。"""

    evidence: dict[str, object] = {
        "mode": SYNTHESIS_CONTEXT_MODE,
        "required": True,
        "available": False,
        "verified": False,
        "failure_kind": "",
        "candidate_ids": [
            candidate.candidate_id for candidate in candidates
        ],
    }
    if not candidates:
        evidence["failure_kind"] = "candidate_group_empty"
        return "", evidence

    first = candidates[0]
    expected_identity = representative_source_identity(
        first.project,
        first.context_info,
    )
    if expected_identity is None:
        evidence["failure_kind"] = "invalid_representative_source_identity"
        return "", evidence
    expected_hash = representative_source_sha256(first.context_info)
    if not expected_hash:
        evidence["failure_kind"] = "source_hash_missing"
        return "", evidence

    matched_occurrences: list[dict[str, object]] = []
    for candidate in candidates:
        for info in candidate.region_source_infos:
            if (
                representative_source_identity(candidate.project, info)
                != expected_identity
            ):
                evidence["failure_kind"] = "member_region_mismatch"
                return "", evidence
            if representative_source_sha256(info) != expected_hash:
                evidence["failure_kind"] = "member_source_hash_mismatch"
                return "", evidence
            node = info[3]
            matched_occurrences.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "candidate_extent": str(node.get("extent") or ""),
                    "start_byte": node.get("start_byte"),
                    "end_byte": node.get("end_byte"),
                }
            )

    context, verified = load_verified_source_context(
        project=first.project,
        representative_info=first.context_info,
        source_root=source_root,
        max_lines=max_lines,
        max_chars=max_chars,
    )
    evidence.update(verified)
    evidence["mode"] = SYNTHESIS_CONTEXT_MODE
    evidence["required"] = True
    evidence["candidate_ids"] = [
        candidate.candidate_id for candidate in candidates
    ]
    evidence["matched_occurrences"] = matched_occurrences
    return context, evidence


def _parsed_fragment(source: str) -> tuple[bytes, object, int, int]:
    sanitized = sanitize_template_for_parser(source).encode("utf-8")
    parser = CPP_ADAPTER.create_parser()
    direct = parser.parse(sanitized)
    if not direct.root_node.has_error:
        return sanitized, direct.root_node, 0, len(sanitized)
    prefix = b"void __idiom_synthesis_fragment__() {\n"
    wrapped = prefix + sanitized + b"\n}"
    tree = parser.parse(wrapped)
    return wrapped, tree.root_node, len(prefix), len(prefix) + len(sanitized)


def _fragment_nodes(source: str, kind: str | None = None) -> list[object]:
    raw, root, start, end = _parsed_fragment(source)
    del raw
    nodes: list[object] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.end_byte <= start or node.start_byte >= end:
            continue
        if (
            node.start_byte >= start
            and node.end_byte <= end
            and (kind is None or node.type == kind)
        ):
            nodes.append(node)
        stack.extend(reversed(node.children))
    return sorted(nodes, key=lambda node: (node.start_byte, node.end_byte))


def _normalize_call_target(value: str) -> str:
    compact = re.sub(r"\s+", "", value)
    if "->" in compact:
        compact = compact.rsplit("->", 1)[-1]
    if "." in compact:
        compact = compact.rsplit(".", 1)[-1]
    return compact


def call_targets(source: str) -> set[str]:
    """使用 Tree-sitter 提取调用目标；解析异常时回退到保守正则。"""

    raw, _, _, _ = _parsed_fragment(source)
    calls: set[str] = set()
    for node in _fragment_nodes(source, "call_expression"):
        target = node.child_by_field_name("function")
        if target is None:
            continue
        value = raw[target.start_byte : target.end_byte].decode(
            "utf-8",
            errors="replace",
        )
        normalized = _normalize_call_target(value)
        if normalized and normalized not in _CALL_KEYWORDS:
            calls.add(normalized)
    if calls:
        return calls
    return {
        match.group(1)
        for match in _CALL_RE.finditer(source)
        if match.group(1) not in _CALL_KEYWORDS
    }


def unsupported_call_targets(
    merged_code: str,
    source_codes: Iterable[str],
    context_code: str,
) -> List[str]:
    allowed: set[str] = set()
    for source in source_codes:
        allowed.update(call_targets(source))
    allowed.update(call_targets(context_code))
    return sorted(call_targets(merged_code) - allowed)


def syntax_structure_valid(source: str) -> bool:
    sanitized = sanitize_template_for_parser(source)
    parser = CPP_ADAPTER.create_parser()
    raw = sanitized.encode("utf-8")
    direct = parser.parse(raw)
    if not direct.root_node.has_error:
        return True
    wrapped = (
        b"void __idiom_synthesis_fragment__() {\n"
        + raw
        + b"\n}"
    )
    return not parser.parse(wrapped).root_node.has_error
