"""只抽象高频、结构对齐且低语义的信息元素。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from tree_sitter import Node

from ..parser.cpp_adapter import CPP_ADAPTER
from .schema import AbstractionProposal, ClusterCandidate


_IDENTIFIER_KINDS = {
    "identifier",
    "field_identifier",
}
_LITERAL_KINDS = {
    "number_literal",
    "string_literal",
    "char_literal",
    "raw_string_literal",
}
_TYPE_ANCESTORS = {
    "type_descriptor",
    "type_identifier",
    "primitive_type",
    "sized_type_specifier",
    "template_type",
    "qualified_identifier",
    "namespace_identifier",
}
_SEMANTIC_LITERAL_ANCESTORS = {
    "binary_expression",
    "case_statement",
    "conditional_expression",
    "if_statement",
    "return_statement",
    "subscript_expression",
    "switch_statement",
    "while_statement",
}
_SENTINEL_LITERALS = {
    "-1",
    "0",
    "1",
    "false",
    "nullptr",
    "null",
    "true",
}
_PLACEHOLDER_RE = re.compile(r"<(?:VAR|LIT)_\d+>")


@dataclass(frozen=True)
class AbstractionPolicy:
    """习语判断默认采用的保守抽象阈值。"""

    min_instances: int = 3
    min_distinct_values: int = 3
    min_support_ratio: float = 0.60


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    start_byte: int
    end_byte: int
    category: str
    low_semantic: bool
    alignment_category: str = ""

    @property
    def shape(self) -> str:
        if self.category == "VAR":
            return "<VAR>"
        if self.category == "LIT" and self.low_semantic:
            return "<LIT>"
        if self.alignment_category:
            return f"<{self.alignment_category}>"
        return f"{self.kind}:{self.text}"


def _ancestors(node: Node) -> List[Node]:
    values: List[Node] = []
    current = node.parent
    while current is not None:
        values.append(current)
        current = current.parent
    return values


def _inside_call_target(node: Node, ancestors: Sequence[Node]) -> bool:
    for ancestor in ancestors:
        if ancestor.type != "call_expression":
            continue
        target = ancestor.child_by_field_name("function")
        if (
            target is not None
            and target.start_byte <= node.start_byte
            and node.end_byte <= target.end_byte
        ):
            return True
    return False


def _inside_range(node: Node, container: Node | None) -> bool:
    return bool(
        container is not None
        and container.start_byte <= node.start_byte
        and node.end_byte <= container.end_byte
    )


def _is_declaration_identifier(node: Node) -> bool:
    if node.type not in _IDENTIFIER_KINDS:
        return False
    for ancestor in _ancestors(node):
        if ancestor.type not in {
            "declaration",
            "field_declaration",
            "for_range_loop",
            "init_declarator",
            "optional_parameter_declaration",
            "parameter_declaration",
        }:
            continue
        for field in ("declarator", "left"):
            container = ancestor.child_by_field_name(field)
            if container is not None and container.type == "init_declarator":
                container = container.child_by_field_name("declarator")
            if _inside_range(node, container):
                return True
    return False


def _classify_leaf(
    node: Node,
    source: bytes,
    local_declarations: set[str],
) -> tuple[str, bool, str]:
    text = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
    ancestors = _ancestors(node)
    ancestor_kinds = {ancestor.type for ancestor in ancestors}
    if node.type in _IDENTIFIER_KINDS:
        if _inside_call_target(node, ancestors):
            return "KEEP", False, ""
        if ancestor_kinds & _TYPE_ANCESTORS:
            return "KEEP", False, ""
        if text not in local_declarations:
            return "KEEP", False, "ID"
        return "VAR", True, ""
    if node.type in _LITERAL_KINDS:
        low_semantic = (
            text.strip().lower() not in _SENTINEL_LITERALS
            and not ancestor_kinds & _SEMANTIC_LITERAL_ANCESTORS
            and "%" not in text
            and "{" not in text
        )
        return "LIT", low_semantic, ""
    return "KEEP", False, ""


def _leaf_tokens(source_text: str) -> List[_Token]:
    """解析片段；语句/区域使用固定函数包装，失败时安全地不提出抽象。"""

    code = source_text.encode("utf-8")
    wrappers = (
        (b"", b""),
        (b"void __idiom_judgment_fragment__() {\n", b"\n}"),
    )
    for prefix, suffix in wrappers:
        parser = CPP_ADAPTER.create_parser()
        wrapped = prefix + code + suffix
        tree = parser.parse(wrapped)
        start = len(prefix)
        end = start + len(code)
        leaves: List[Node] = []
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.child_count:
                stack.extend(reversed(node.children))
                continue
            if node.end_byte <= start or node.start_byte >= end:
                continue
            if node.start_byte < start or node.end_byte > end:
                continue
            leaves.append(node)
        local_declarations = {
            wrapped[node.start_byte : node.end_byte].decode(
                "utf-8", errors="replace"
            )
            for node in leaves
            if _is_declaration_identifier(node)
        }
        tokens: List[_Token] = []
        for node in leaves:
            category, low_semantic, alignment_category = _classify_leaf(
                node,
                wrapped,
                local_declarations,
            )
            text = wrapped[node.start_byte : node.end_byte].decode(
                "utf-8", errors="replace"
            )
            tokens.append(
                _Token(
                    kind=node.type,
                    text=text,
                    start_byte=node.start_byte - start,
                    end_byte=node.end_byte - start,
                    category=category,
                    low_semantic=low_semantic,
                    alignment_category=alignment_category,
                )
            )
        tokens.sort(key=lambda token: (token.start_byte, token.end_byte))
        if tokens and (not tree.root_node.has_error or prefix):
            return tokens
    return []


def propose_abstractions(
    candidate: ClusterCandidate,
    policy: AbstractionPolicy | None = None,
) -> List[AbstractionProposal]:
    """
    只在多数实例具有完全相同的词法/语法形状时提出抽象。

    调用目标、类型、控制条件、返回值、哨兵值和格式字符串始终保留。提案不是最终
    修改；只有语义/抽象 Agent 返回 abstract 且明确批准的 proposal_id 才会应用。
    """

    policy = policy or AbstractionPolicy()
    representative_tokens = _leaf_tokens(candidate.representative_code)
    if not representative_tokens:
        return []
    tokenized = [_leaf_tokens(code) for code in candidate.member_codes]
    tokenized = [tokens for tokens in tokenized if tokens]
    if len(tokenized) < policy.min_instances:
        return []

    groups: dict[tuple[str, ...], List[List[_Token]]] = {}
    for tokens in tokenized:
        key = tuple(token.shape for token in tokens)
        groups.setdefault(key, []).append(tokens)
    representative_key = tuple(
        token.shape for token in representative_tokens
    )
    aligned = groups.get(representative_key, [])
    if not aligned:
        return []
    largest_group_size = max(len(items) for items in groups.values())
    if len(aligned) < largest_group_size:
        # 代表实例不属于最大结构组时不切换锚点，避免把另一实例的字节范围应用到
        # center_point；该簇仍可接受，只是不执行自动抽象。
        return []
    support_ratio = len(aligned) / max(1, len(candidate.member_codes))
    if (
        len(aligned) < policy.min_instances
        or support_ratio < policy.min_support_ratio
    ):
        return []

    anchor = representative_tokens
    proposals: List[AbstractionProposal] = []
    positions_by_signature: dict[tuple[str, tuple[str, ...]], List[int]] = {}
    for position, token in enumerate(anchor):
        if token.category not in {"VAR", "LIT"} or not token.low_semantic:
            continue
        values = tuple(tokens[position].text for tokens in aligned)
        distinct = set(values)
        if len(distinct) < policy.min_distinct_values:
            continue
        positions_by_signature.setdefault((token.category, values), []).append(
            position
        )

    counters = {"VAR": 0, "LIT": 0}
    for (category, values), positions in sorted(
        positions_by_signature.items(),
        key=lambda item: (item[1][0], item[0][0]),
    ):
        counters[category] += 1
        proposal_id = f"{category.lower()}-{counters[category]}"
        placeholder = f"<{category}_{counters[category]}>"
        proposals.append(
            AbstractionProposal(
                proposal_id=proposal_id,
                placeholder=placeholder,
                category=category,
                token_positions=list(positions),
                anchor_ranges=[
                    [anchor[position].start_byte, anchor[position].end_byte]
                    for position in positions
                ],
                values=sorted(set(values)),
                support_count=len(aligned),
                distinct_count=len(set(values)),
                support_ratio=round(support_ratio, 6),
                reason=(
                    "局部变量在相同结构角色中高频换名"
                    if category == "VAR"
                    else "低语义字面量在相同结构角色中高频变化"
                ),
            )
        )
    return proposals


def apply_approved_abstractions(
    source: str,
    proposals: Iterable[AbstractionProposal],
    approved_ids: Iterable[str],
) -> str:
    """只把规则提案与 LLM 批准集合的交集应用到代表源码。"""

    allowed = set(approved_ids)
    replacements: List[tuple[int, int, str]] = []
    for proposal in proposals:
        if proposal.proposal_id not in allowed:
            continue
        for start, end in proposal.anchor_ranges:
            replacements.append((int(start), int(end), proposal.placeholder))
    result = source
    for start, end, placeholder in sorted(replacements, reverse=True):
        if start < 0 or end < start or end > len(result.encode("utf-8")):
            continue
        encoded = result.encode("utf-8")
        encoded = encoded[:start] + placeholder.encode("utf-8") + encoded[end:]
        result = encoded.decode("utf-8", errors="replace")
    return result


def sanitize_template_for_parser(source: str) -> str:
    """把阶段3占位符替换为可解析的保守哑元，仅用于语法结构检查。"""

    return _PLACEHOLDER_RE.sub("__idiom_placeholder", source)
