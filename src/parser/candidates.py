"""从函数 AST 中选择三种基础粒度和 Def-Use 增强候选。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..common.node_kinds import BLOCK_KINDS, FUNCTION_KINDS, STATEMENT_KINDS
from .cpp_adapter import CPP_ADAPTER
from .semantic_slicer import SEMANTIC_SLICE_KIND


LEGACY_PROFILE = "legacy"
QUALITY_PROFILE = "quality-v2"
SUPPORTED_PROFILES = (LEGACY_PROFILE, QUALITY_PROFILE)

CandidateFilter = Callable[[Mapping[str, Any]], bool]
MAX_QUALITY_STATEMENT_BYTES = 4000
MAX_QUALITY_STATEMENT_LINES = 80


@dataclass(frozen=True)
class SelectedCandidate:
    level: str
    function_extent: str
    node_info: Mapping[str, Any]
    origin: str


def _parse_extent(extent: str) -> Optional[Tuple[int, int, int, int]]:
    parts = extent.split("-")
    if len(parts) != 4:
        return None
    try:
        return tuple(map(int, parts))  # type: ignore[return-value]
    except ValueError:
        return None


def _within_extent(outer: str, inner: str) -> bool:
    outer_value = _parse_extent(outer)
    inner_value = _parse_extent(inner)
    if outer_value is None or inner_value is None:
        return False
    osl, osc, oel, oec = outer_value
    isl, isc, iel, iec = inner_value
    return (osl, osc) <= (isl, isc) and (iel, iec) <= (oel, oec)


def _subtree_end(
    function_ast: Sequence[Mapping[str, Any]],
    root_index: int,
) -> int:
    root_depth = int(function_ast[root_index].get("depth", 0) or 0)
    end = root_index + 1
    while end < len(function_ast):
        if int(function_ast[end].get("depth", 0) or 0) <= root_depth:
            break
        end += 1
    return end


def _legacy_candidates(
    function_ast: Sequence[Mapping[str, Any]],
    *,
    min_nodes: int,
    min_ast_num: int,
    candidate_filter: Optional[CandidateFilter],
) -> List[SelectedCandidate]:
    if len(function_ast) < min_nodes:
        return []
    extent_valid = "0-0-0-0"
    function_extent = str(function_ast[0].get("extent") or "")
    candidates: List[SelectedCandidate] = []
    for node_info in function_ast:
        code = str(node_info.get("code_snippet") or "")
        kind = str(node_info.get("kind") or "")
        extent = str(node_info.get("extent") or "")
        ast_num = int(node_info.get("ast_num", 0) or 0)
        if not code or ast_num < min_ast_num:
            continue
        if candidate_filter is not None and not candidate_filter(node_info):
            continue
        if kind in FUNCTION_KINDS:
            candidates.append(
                SelectedCandidate("function", function_extent, node_info, "base")
            )
        elif kind in BLOCK_KINDS:
            candidates.append(
                SelectedCandidate("region", function_extent, node_info, "base")
            )
        elif kind in STATEMENT_KINDS and not _within_extent(extent_valid, extent):
            extent_valid = extent
            candidates.append(
                SelectedCandidate("statement", function_extent, node_info, "base")
            )
    return candidates


def _node_contexts(
    function_ast: Sequence[Mapping[str, Any]],
) -> List[Tuple[Optional[int], Optional[int]]]:
    """返回每个节点的父节点下标和最近函数定义下标。"""
    contexts: List[Tuple[Optional[int], Optional[int]]] = []
    stack: List[int] = []
    for index, node in enumerate(function_ast):
        depth = int(node.get("depth", 0) or 0)
        while stack and int(function_ast[stack[-1]].get("depth", 0) or 0) >= depth:
            stack.pop()
        parent_index = stack[-1] if stack else None
        function_index = next(
            (
                ancestor
                for ancestor in reversed(stack)
                if str(function_ast[ancestor].get("kind") or "")
                == CPP_ADAPTER.function_definition_kind
            ),
            None,
        )
        if CPP_ADAPTER.is_function_definition(
            str(node.get("kind") or "")
        ):
            function_index = index
        contexts.append((parent_index, function_index))
        stack.append(index)
    return contexts


def _subtree_kinds(
    function_ast: Sequence[Mapping[str, Any]],
    root_index: int,
) -> set[str]:
    return {
        str(function_ast[index].get("kind") or "")
        for index in range(root_index, _subtree_end(function_ast, root_index))
    }


def _candidate_complete(node_info: Mapping[str, Any]) -> bool:
    parse_flags = int(node_info.get("parse_flags", 0) or 0)
    return not bool(
        parse_flags & 0b111
        or
        node_info.get("has_error")
        or node_info.get("is_error")
        or node_info.get("is_missing")
    )


def _materialize_mapping(
    node_info: Mapping[str, Any],
    function_node: Mapping[str, Any],
) -> Mapping[str, Any]:
    """只在候选输出上继承函数级文件身份，避免给数百万 AST 节点重复存储。"""
    required = (
        "source_path",
        "source_file_id",
        "source_sha256",
        "mapping_version",
        "mapping_exact",
        "parse_origin",
    )
    if all(node_info.get(key) is not None for key in required):
        return node_info
    materialized = dict(node_info)
    for key in required:
        if materialized.get(key) is None and function_node.get(key) is not None:
            materialized[key] = function_node[key]
    materialized.setdefault("mapping_version", 2)
    materialized.setdefault("mapping_exact", True)
    return materialized


def _region_score(
    function_ast: Sequence[Mapping[str, Any]],
    index: int,
) -> Tuple[int, int, int, int]:
    node = function_ast[index]
    kinds = _subtree_kinds(function_ast, index)
    core_count = len(kinds & CPP_ADAPTER.core_operation_kinds)
    subtree_size = int(node.get("subtree_size", 0) or 0)
    start_byte = int(node.get("start_byte", index) or index)
    return core_count, min(subtree_size, 500), -subtree_size, -start_byte


def _statement_score(
    function_ast: Sequence[Mapping[str, Any]],
    index: int,
) -> Tuple[int, int, int, int]:
    node = function_ast[index]
    kind = str(node.get("kind") or "")
    kinds = _subtree_kinds(function_ast, index)
    core_count = len(kinds & CPP_ADAPTER.core_operation_kinds)
    priority = {
        "throw_statement": 5,
        "co_return_statement": 5,
        "return_statement": 4,
        "expression_statement": 3,
        "declaration": 2,
    }.get(kind, 1)
    subtree_size = int(node.get("subtree_size", 0) or 0)
    start_byte = int(node.get("start_byte", index) or index)
    return core_count, priority, min(subtree_size, 120), -start_byte


def _take_diverse(
    indices: Sequence[int],
    function_ast: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    score,
    candidate_filter: Optional[CandidateFilter],
) -> List[int]:
    ordered = sorted(
        indices,
        key=lambda index: (score(function_ast, index), -index),
        reverse=True,
    )
    selected: List[int] = []
    selected_kinds: set[str] = set()
    for index in ordered:
        if (
            candidate_filter is not None
            and not candidate_filter(function_ast[index])
        ):
            continue
        kind = str(function_ast[index].get("kind") or "")
        if kind in selected_kinds:
            continue
        selected.append(index)
        selected_kinds.add(kind)
        if len(selected) >= limit:
            return sorted(selected)
    for index in ordered:
        if (
            index not in selected
            and (
                candidate_filter is None
                or candidate_filter(function_ast[index])
            )
        ):
            selected.append(index)
        if len(selected) >= limit:
            break
    return sorted(selected)


def _quality_candidates(
    function_ast: Sequence[Mapping[str, Any]],
    *,
    min_nodes: int,
    min_ast_num: int,
    max_regions_per_function: int,
    max_statements_per_function: int,
    candidate_filter: Optional[CandidateFilter],
) -> List[SelectedCandidate]:
    if not function_ast:
        return []
    contexts = _node_contexts(function_ast)
    # 每个 function_ast 已由 Parser 以函数为根保存。树中更深处偶尔还会
    # 出现局部类方法或容错解析产生的嵌套 function_definition；它们不是
    # 当前记录的独立函数，不能再次作为函数级候选。
    function_indices = (
        [0]
        if str(function_ast[0].get("kind") or "")
        in CPP_ADAPTER.quality_function_kinds
        else []
    )
    candidates: List[SelectedCandidate] = []

    for function_index in function_indices:
        function_node = function_ast[function_index]
        function_extent = str(function_node.get("extent") or "")
        function_end = _subtree_end(function_ast, function_index)
        function_size = int(
            function_node.get("subtree_size", function_end - function_index)
            or (function_end - function_index)
        )
        if (
            function_size < min_nodes
            or not str(function_node.get("code_snippet") or "")
            or not _candidate_complete(function_node)
        ):
            continue
        if (
            candidate_filter is None
            or candidate_filter(function_node)
        ):
            candidates.append(
                SelectedCandidate(
                    "function",
                    function_extent,
                    function_node,
                    "base",
                )
            )

        region_indices: List[int] = []
        statement_indices: List[int] = []
        for index in range(function_index + 1, function_end):
            node = function_ast[index]
            parent_index, nearest_function_index = contexts[index]
            if nearest_function_index != function_index:
                continue
            kind = str(node.get("kind") or "")
            code = str(node.get("code_snippet") or "")
            if not code or not _candidate_complete(node):
                continue
            subtree_size = int(node.get("subtree_size", 0) or 0)
            ast_num = int(node.get("ast_num", 0) or 0)
            parent_kind = (
                str(function_ast[parent_index].get("kind") or "")
                if parent_index is not None
                else ""
            )

            is_standalone_scope = (
                CPP_ADAPTER.is_function_body(kind)
                and CPP_ADAPTER.is_function_body(parent_kind)
            )
            if (
                kind in CPP_ADAPTER.quality_region_kinds
                or is_standalone_scope
            ) and subtree_size >= max(min_nodes, min_ast_num + 1):
                if kind == "lambda_expression" or ast_num >= 3:
                    region_indices.append(index)
                continue

            if kind in CPP_ADAPTER.quality_statement_kinds:
                encoded_size = len(code.encode("utf-8"))
                line_count = code.count("\n") + 1
                if (
                    encoded_size > MAX_QUALITY_STATEMENT_BYTES
                    or line_count > MAX_QUALITY_STATEMENT_LINES
                ):
                    continue
                minimum_size = 3 if kind in {
                    "break_statement",
                    "continue_statement",
                    "co_return_statement",
                    "return_statement",
                    "throw_statement",
                } else min_ast_num
                if subtree_size >= minimum_size:
                    statement_indices.append(index)

        for index in _take_diverse(
            region_indices,
            function_ast,
            limit=max_regions_per_function,
            score=_region_score,
            candidate_filter=candidate_filter,
        ):
            candidates.append(
                SelectedCandidate(
                    "region",
                    function_extent,
                    _materialize_mapping(function_ast[index], function_node),
                    "base",
                )
            )
        for index in _take_diverse(
            statement_indices,
            function_ast,
            limit=max_statements_per_function,
            score=_statement_score,
            candidate_filter=candidate_filter,
        ):
            candidates.append(
                SelectedCandidate(
                    "statement",
                    function_extent,
                    _materialize_mapping(function_ast[index], function_node),
                    "base",
                )
            )

        semantic_slices = function_node.get("semantic_slices") or []
        for semantic_slice in semantic_slices:
            if (
                isinstance(semantic_slice, Mapping)
                and str(semantic_slice.get("kind") or "") == SEMANTIC_SLICE_KIND
                and str(semantic_slice.get("code_snippet") or "")
                and _candidate_complete(semantic_slice)
                and (
                    candidate_filter is None
                    or candidate_filter(semantic_slice)
                )
            ):
                candidates.append(
                    SelectedCandidate(
                        "region",
                        function_extent,
                        semantic_slice,
                        "semantic_def_use",
                    )
                )

    deduplicated: Dict[Tuple[str, str, str], SelectedCandidate] = {}
    for candidate in candidates:
        node = candidate.node_info
        key = (
            candidate.level,
            str(node.get("extent") or ""),
            candidate.origin,
        )
        deduplicated.setdefault(key, candidate)
    level_order = {"function": 0, "region": 1, "statement": 2}
    return sorted(
        deduplicated.values(),
        key=lambda candidate: (
            int(candidate.node_info.get("start_byte", 0) or 0),
            int(candidate.node_info.get("end_byte", 0) or 0),
            level_order[candidate.level],
            candidate.origin,
        ),
    )


def select_candidates(
    function_ast: Sequence[Mapping[str, Any]],
    *,
    profile: str = QUALITY_PROFILE,
    min_nodes: int = 10,
    min_ast_num: int = 5,
    max_regions_per_function: int = 2,
    max_statements_per_function: int = 2,
    candidate_filter: Optional[CandidateFilter] = None,
) -> List[SelectedCandidate]:
    """按显式 profile 选择候选；过滤函数根时仍允许降级选择其子候选。"""
    if profile == LEGACY_PROFILE:
        return _legacy_candidates(
            function_ast,
            min_nodes=min_nodes,
            min_ast_num=min_ast_num,
            candidate_filter=candidate_filter,
        )
    if profile == QUALITY_PROFILE:
        return _quality_candidates(
            function_ast,
            min_nodes=min_nodes,
            min_ast_num=min_ast_num,
            max_regions_per_function=max_regions_per_function,
            max_statements_per_function=max_statements_per_function,
            candidate_filter=candidate_filter,
        )
    raise ValueError(
        f"未知候选 profile: {profile}；可选值为 {', '.join(SUPPORTED_PROFILES)}"
    )
