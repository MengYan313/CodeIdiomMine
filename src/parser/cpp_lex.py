"""基于 Tree-sitter C++ 叶节点的词法等价与保守结构签名。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

import tree_sitter

from .cpp_adapter import CPP_ADAPTER


_PARSER = CPP_ADAPTER.create_parser()
_COMMENT_KINDS = frozenset({"comment"})

LexicalToken = tuple[str, str]


@dataclass(frozen=True)
class CppLexicalAnalysis:
    tokens: tuple[LexicalToken, ...]
    ast_structure: tuple[str, ...]
    local_identifiers: frozenset[str]
    parse_valid: bool


def _iter_nodes(root: tree_sitter.Node) -> Iterable[tree_sitter.Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in _COMMENT_KINDS:
            continue
        yield node
        stack.extend(reversed(node.children))


def _tokens_for_node(
    node: tree_sitter.Node,
    source: bytes,
) -> tuple[LexicalToken, ...]:
    return tuple(
        (
            child.type,
            source[child.start_byte : child.end_byte].decode(
                "utf-8",
                errors="replace",
            ),
        )
        for child in _iter_nodes(node)
        if child.child_count == 0 and child.end_byte > child.start_byte
    )


def _declared_identifier(
    node: tree_sitter.Node | None,
    source: bytes,
) -> str:
    if node is None:
        return ""
    current = node
    while current.type != "identifier":
        current = current.child_by_field_name("declarator")
        if current is None:
            return ""
    return source[current.start_byte : current.end_byte].decode(
        "utf-8",
        errors="replace",
    )


@lru_cache(maxsize=8192)
def analyze_cpp_lexically(code: str) -> CppLexicalAnalysis:
    source = code.encode("utf-8")
    tree = _PARSER.parse(source)
    root = tree.root_node
    nodes = tuple(_iter_nodes(root))
    tokens = _tokens_for_node(root, source)
    local_identifiers = {
        name
        for node in nodes
        if node.type == "declaration"
        for name in (
            _declared_identifier(
                node.child_by_field_name("declarator"),
                source,
            ),
        )
        if name
    }
    return CppLexicalAnalysis(
        tokens=tokens,
        ast_structure=tuple(node.type for node in nodes),
        local_identifiers=frozenset(local_identifiers),
        parse_valid=not root.has_error,
    )


def lexical_tokens(code: str) -> tuple[LexicalToken, ...]:
    """忽略排版空白与注释，保留 C++ 词法 token 的类别和原文。"""

    return analyze_cpp_lexically(str(code)).tokens


def lexically_equivalent(left: str, right: str) -> bool:
    return lexical_tokens(left) == lexical_tokens(right)


def deduplicate_lexical_variants(
    codes: Iterable[str],
) -> list[str]:
    """按 C++ 词法 token 去重并保留首次出现的真实源码。"""

    variants: list[str] = []
    seen: set[tuple[LexicalToken, ...]] = set()
    for code in codes:
        value = str(code)
        key = lexical_tokens(value)
        if not key or key in seen:
            continue
        seen.add(key)
        variants.append(value)
    return variants
