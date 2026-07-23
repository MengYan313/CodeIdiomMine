"""基于局部 Def-Use 关系为长函数和长区域提取语义核心片段。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import tree_sitter

from .cpp_adapter import CPP_ADAPTER

SEMANTIC_SLICE_KIND = "semantic_slice"
SEMANTIC_ANALYSIS_VERSION = "def-use-v1"


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _walk(node: tree_sitter.Node) -> Iterable[tree_sitter.Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _identifiers(node: Optional[tree_sitter.Node], source: bytes) -> Set[str]:
    if node is None:
        return set()
    return {
        _decode(current.text or source[current.start_byte : current.end_byte])
        for current in _walk(node)
        if CPP_ADAPTER.is_identifier(current)
    }


def _definition_nodes(node: tree_sitter.Node) -> List[tree_sitter.Node]:
    definitions: List[tree_sitter.Node] = []
    for current in _walk(node):
        if current.type == "init_declarator":
            declarator = current.child_by_field_name("declarator")
            if declarator is not None:
                definitions.append(declarator)
        elif current.type == "declaration":
            for child in current.named_children:
                if child.type.endswith("declarator") and child.type != "init_declarator":
                    definitions.append(child)
        elif current.type == "assignment_expression":
            left = current.child_by_field_name("left")
            if left is not None:
                definitions.append(left)
        elif current.type == "update_expression":
            argument = current.child_by_field_name("argument")
            if argument is None and current.named_children:
                argument = current.named_children[0]
            if argument is not None:
                definitions.append(argument)
        elif current.type == "for_range_loop":
            declarator = current.child_by_field_name("declarator")
            if declarator is not None:
                definitions.append(declarator)
    return definitions


def _direct_callee_identifiers(node: tree_sitter.Node, source: bytes) -> Set[str]:
    ignored: Set[str] = set()
    for current in _walk(node):
        if current.type != "call_expression":
            continue
        function = current.child_by_field_name("function")
        if function is None:
            continue
        if function.type in CPP_ADAPTER.direct_callee_kinds:
            ignored.update(_identifiers(function, source))
    return ignored


def _compound_assignment_uses(
    node: tree_sitter.Node,
    source: bytes,
) -> Set[str]:
    uses: Set[str] = set()
    for current in _walk(node):
        if current.type not in {"assignment_expression", "update_expression"}:
            continue
        if current.type == "update_expression":
            argument = current.child_by_field_name("argument")
            if argument is None and current.named_children:
                argument = current.named_children[0]
            uses.update(_identifiers(argument, source))
            continue
        left = current.child_by_field_name("left")
        right = current.child_by_field_name("right")
        if left is None or right is None:
            continue
        operator_text = _decode(source[left.end_byte : right.start_byte])
        if "=" in operator_text and operator_text.strip() != "=":
            uses.update(_identifiers(left, source))
    return uses


@dataclass(frozen=True)
class StatementFacts:
    node: tree_sitter.Node
    definitions: frozenset[str]
    uses: frozenset[str]
    core_kinds: frozenset[str]


def _statement_facts(node: tree_sitter.Node, source: bytes) -> StatementFacts:
    definition_nodes = _definition_nodes(node)
    definitions: Set[str] = set()
    definition_ranges: List[Tuple[int, int]] = []
    for definition_node in definition_nodes:
        definitions.update(_identifiers(definition_node, source))
        definition_ranges.append(
            (definition_node.start_byte, definition_node.end_byte)
        )

    uses: Set[str] = set()
    core_kinds: Set[str] = set()
    ignored_callees = _direct_callee_identifiers(node, source)
    for current in _walk(node):
        if current.type in CPP_ADAPTER.core_operation_kinds:
            core_kinds.add(current.type)
        if not CPP_ADAPTER.is_identifier(current):
            continue
        if any(
            start <= current.start_byte and current.end_byte <= end
            for start, end in definition_ranges
        ):
            continue
        value = _decode(current.text or source[current.start_byte : current.end_byte])
        if value not in ignored_callees:
            uses.add(value)
    uses.update(_compound_assignment_uses(node, source))
    return StatementFacts(
        node=node,
        definitions=frozenset(definitions),
        uses=frozenset(uses),
        core_kinds=frozenset(core_kinds),
    )


def _line_span(node: tree_sitter.Node) -> int:
    return node.end_point[0] - node.start_point[0] + 1


def _container_is_long(
    container: tree_sitter.Node,
    *,
    is_function_body: bool,
    min_function_lines: int,
    min_function_bytes: int,
    min_region_lines: int,
    min_region_bytes: int,
) -> bool:
    byte_length = container.end_byte - container.start_byte
    line_length = _line_span(container)
    if is_function_body:
        return line_length >= min_function_lines or byte_length >= min_function_bytes
    return line_length >= min_region_lines or byte_length >= min_region_bytes


def _statement_units(container: tree_sitter.Node) -> List[tree_sitter.Node]:
    return [
        child
        for child in container.named_children
        if child.type not in CPP_ADAPTER.ignored_statement_unit_kinds
        and not CPP_ADAPTER.is_preprocessor(child)
        and not child.is_extra
        and child.end_byte > child.start_byte
    ]


def _dependency_edges(
    facts: Sequence[StatementFacts],
) -> List[Tuple[int, int, str]]:
    latest_definition: Dict[str, int] = {}
    edges: List[Tuple[int, int, str]] = []
    for index, item in enumerate(facts):
        for name in sorted(item.uses):
            source_index = latest_definition.get(name)
            if source_index is not None and source_index != index:
                edges.append((source_index, index, name))
        for name in sorted(item.definitions):
            latest_definition[name] = index
    return edges


def _dependency_closure(
    anchor: int,
    edges: Sequence[Tuple[int, int, str]],
    *,
    backward_hops: int = 2,
    forward_hops: int = 1,
) -> Set[int]:
    incoming: Dict[int, Set[int]] = {}
    outgoing: Dict[int, Set[int]] = {}
    for source, target, _ in edges:
        incoming.setdefault(target, set()).add(source)
        outgoing.setdefault(source, set()).add(target)

    selected = {anchor}
    frontier = {anchor}
    for _ in range(backward_hops):
        next_frontier = {
            source
            for target in frontier
            for source in incoming.get(target, set())
            if source not in selected
        }
        selected.update(next_frontier)
        frontier = next_frontier

    frontier = {anchor}
    for _ in range(forward_hops):
        next_frontier = {
            target
            for source in frontier
            for target in outgoing.get(source, set())
            if target not in selected
        }
        selected.update(next_frontier)
        frontier = next_frontier
    return selected


def _slice_for_anchor(
    *,
    anchor: int,
    facts: Sequence[StatementFacts],
    edges: Sequence[Tuple[int, int, str]],
    parent_extent: str,
    source: bytes,
    source_path: str,
    source_file_id: str,
    source_sha256: str,
    parse_origin: str,
    max_span_statements: int,
    max_slice_bytes: int,
    max_slice_lines: int,
) -> Optional[Dict[str, Any]]:
    selected = _dependency_closure(anchor, edges)
    selected = {
        index
        for index in selected
        if abs(index - anchor) < max_span_statements
    }
    selected.add(anchor)
    related_edges = [
        edge for edge in edges if edge[0] in selected and edge[1] in selected
    ]
    if len(selected) < 2 or not related_edges:
        return None

    first = min(selected)
    last = max(selected)
    span_count = last - first + 1
    if span_count > max_span_statements:
        return None
    cohesion = len(selected) / span_count
    if cohesion < 0.5:
        return None
    if facts[anchor].core_kinds <= {
        "assignment_expression",
        "update_expression",
    } and cohesion < 1.0:
        return None

    start_node = facts[first].node
    end_node = facts[last].node
    start_byte = start_node.start_byte
    end_byte = end_node.end_byte
    byte_length = end_byte - start_byte
    line_length = end_node.end_point[0] - start_node.start_point[0] + 1
    if byte_length <= 0 or byte_length > max_slice_bytes:
        return None
    if line_length <= 1 or line_length > max_slice_lines:
        return None
    if any(item.node.has_error or item.node.is_missing for item in facts[first : last + 1]):
        return None

    shared_symbols = sorted({name for _, _, name in related_edges})
    anchor_kinds = sorted(facts[anchor].core_kinds)
    included_core_kinds = sorted(
        {
            kind
            for item in facts[first : last + 1]
            for kind in item.core_kinds
        }
    )
    extent = (
        f"{start_node.start_point[0] + 1}-{start_node.start_point[1]}-"
        f"{end_node.end_point[0] + 1}-{end_node.end_point[1]}"
    )
    code = _decode(source[start_byte:end_byte])
    included_facts = facts[first : last + 1]
    return {
        "depth": 1,
        "extent": extent,
        "kind": SEMANTIC_SLICE_KIND,
        "type_kind": None,
        "type_spelling": None,
        "spelling": None,
        "displayname": None,
        "code_snippet": code,
        "ast_num": span_count,
        "subtree_size": sum(item.node.descendant_count for item in included_facts),
        "candidate_level": "region",
        "candidate_origin": "semantic_def_use",
        "analysis_version": SEMANTIC_ANALYSIS_VERSION,
        "parent_extent": parent_extent,
        "source_path": source_path,
        "source_file_id": source_file_id,
        "source_sha256": source_sha256,
        "start_byte": start_byte,
        "end_byte": end_byte,
        "mapping_version": 2,
        "mapping_exact": True,
        "parse_origin": parse_origin,
        "has_error": False,
        "is_missing": False,
        "dependency_summary": {
            "anchor_statement_index": anchor,
            "anchor_kinds": anchor_kinds,
            "included_core_kinds": included_core_kinds,
            "selected_statement_indices": sorted(selected),
            "span_statement_count": span_count,
            "selected_statement_count": len(selected),
            "cohesion": cohesion,
            "shared_symbols": shared_symbols,
            "edges": [
                {"source": source_index, "target": target_index, "symbol": name}
                for source_index, target_index, name in related_edges
            ],
        },
    }


def extract_semantic_slices(
    function_node: tree_sitter.Node,
    source: bytes,
    *,
    source_path: str,
    source_file_id: str,
    source_sha256: str,
    parse_origin: str = "raw",
    min_function_lines: int = 30,
    min_function_bytes: int = 1200,
    min_region_lines: int = 20,
    min_region_bytes: int = 800,
    max_span_statements: int = 12,
    max_slice_bytes: int = 4000,
    max_slice_lines: int = 80,
    max_slices: int = 6,
) -> List[Dict[str, Any]]:
    """在长函数/区域内以局部 Def-Use 闭包生成连续、可回映射的核心片段。"""
    body = function_node.child_by_field_name("body")
    if body is None or not CPP_ADAPTER.is_function_body(body):
        return []

    containers = [
        node
        for node in _walk(body)
        if CPP_ADAPTER.is_function_body(node)
    ]
    candidates: Dict[Tuple[int, int], Dict[str, Any]] = {}
    function_extent = (
        f"{function_node.start_point[0] + 1}-{function_node.start_point[1]}-"
        f"{function_node.end_point[0] + 1}-{function_node.end_point[1]}"
    )

    for container in containers:
        if container.has_error or container.is_missing:
            continue
        is_function_body = container.id == body.id
        if not _container_is_long(
            container,
            is_function_body=is_function_body,
            min_function_lines=min_function_lines,
            min_function_bytes=min_function_bytes,
            min_region_lines=min_region_lines,
            min_region_bytes=min_region_bytes,
        ):
            continue
        units = _statement_units(container)
        if len(units) < 2:
            continue
        facts = [_statement_facts(unit, source) for unit in units]
        edges = _dependency_edges(facts)
        if not edges:
            continue
        for anchor, item in enumerate(facts):
            if not item.core_kinds:
                continue
            candidate = _slice_for_anchor(
                anchor=anchor,
                facts=facts,
                edges=edges,
                parent_extent=function_extent,
                source=source,
                source_path=source_path,
                source_file_id=source_file_id,
                source_sha256=source_sha256,
                parse_origin=parse_origin,
                max_span_statements=max_span_statements,
                max_slice_bytes=max_slice_bytes,
                max_slice_lines=max_slice_lines,
            )
            if candidate is None:
                continue
            key = (int(candidate["start_byte"]), int(candidate["end_byte"]))
            previous = candidates.get(key)
            if previous is None:
                candidates[key] = candidate
                continue
            current_summary = candidate["dependency_summary"]
            previous_summary = previous["dependency_summary"]
            current_score = (
                float(current_summary["cohesion"]),
                len(current_summary["edges"]),
                -int(candidate["end_byte"]) + int(candidate["start_byte"]),
            )
            previous_score = (
                float(previous_summary["cohesion"]),
                len(previous_summary["edges"]),
                -int(previous["end_byte"]) + int(previous["start_byte"]),
            )
            if current_score > previous_score:
                candidates[key] = candidate

    ranked = sorted(
        candidates.values(),
        key=lambda value: (
            -int("call_expression" in value["dependency_summary"]["anchor_kinds"]),
            -int(
                any(
                    kind
                    in {
                        "return_statement",
                        "throw_statement",
                        "new_expression",
                        "delete_expression",
                        "co_return_statement",
                    }
                    for kind in value["dependency_summary"]["anchor_kinds"]
                )
            ),
            -len(value["dependency_summary"]["anchor_kinds"]),
            -int("call_expression" in value["dependency_summary"]["included_core_kinds"]),
            -len(value["dependency_summary"]["included_core_kinds"]),
            -float(value["dependency_summary"]["cohesion"]),
            -len(value["dependency_summary"]["edges"]),
            int(value["end_byte"]) - int(value["start_byte"]),
            int(value["start_byte"]),
        ),
    )
    selected: List[Dict[str, Any]] = []
    low_diversity_signatures: Set[Tuple[Tuple[str, ...], Tuple[str, ...]]] = set()
    for candidate in ranked:
        summary = candidate["dependency_summary"]
        included_core_kinds = tuple(summary["included_core_kinds"])
        signature = (
            tuple(summary["shared_symbols"]),
            included_core_kinds,
        )
        if set(included_core_kinds) <= {
            "assignment_expression",
            "update_expression",
        }:
            if signature in low_diversity_signatures:
                continue
            low_diversity_signatures.add(signature)
        start = int(candidate["start_byte"])
        end = int(candidate["end_byte"])
        overlaps_too_much = False
        for previous in selected:
            previous_start = int(previous["start_byte"])
            previous_end = int(previous["end_byte"])
            overlap = max(0, min(end, previous_end) - max(start, previous_start))
            shorter = min(end - start, previous_end - previous_start)
            if shorter and overlap / shorter >= 0.6:
                overlaps_too_much = True
                break
        if overlaps_too_much:
            continue
        selected.append(candidate)
        if len(selected) >= max_slices:
            break
    return sorted(
        selected,
        key=lambda value: (int(value["start_byte"]), int(value["end_byte"])),
    )
