"""Tree-sitter 通用解析核心所依赖的 C++ 语法适配策略。"""

from __future__ import annotations

from typing import List, Tuple

import tree_sitter
from tree_sitter import Language, Parser


class CppAdapter:
    """集中保存只由 tree-sitter-cpp 决定的节点规则和恢复策略。

    Parser 的遍历、诊断、候选排序、映射和长度控制不依赖这些具体节点名；
    本类也不是公共语言选择器，项目运行时仍固定为 C++。
    """

    language_name = "cpp"
    grammar_package = "tree_sitter_cpp"

    function_definition_kind = "function_definition"
    function_declarator_kind = "function_declarator"
    function_body_kind = "compound_statement"
    error_kind = "ERROR"
    preprocessor_prefix = "preproc_"
    identifier_kind = "identifier"

    name_kinds = frozenset(
        {"identifier", "type_identifier", "field_identifier"}
    )
    direct_callee_kinds = frozenset(
        {"identifier", "qualified_identifier"}
    )
    quality_function_kinds = frozenset({"function_definition"})
    quality_region_kinds = frozenset(
        {
            "case_statement",
            "catch_clause",
            "do_statement",
            "for_range_loop",
            "for_statement",
            "if_statement",
            "lambda_expression",
            "switch_statement",
            "try_statement",
            "while_statement",
        }
    )
    quality_statement_kinds = frozenset(
        {
            "break_statement",
            "co_return_statement",
            "continue_statement",
            "declaration",
            "expression_statement",
            "goto_statement",
            "labeled_statement",
            "return_statement",
            "static_assert_declaration",
            "throw_statement",
        }
    )
    core_operation_kinds = frozenset(
        {
            "assignment_expression",
            "call_expression",
            "co_await_expression",
            "co_return_statement",
            "delete_expression",
            "new_expression",
            "return_statement",
            "throw_statement",
            "update_expression",
        }
    )
    ignored_statement_unit_kinds = frozenset({"comment"})

    def create_parser(self) -> Parser:
        """加载 tree-sitter-cpp grammar，并返回固定为 C++ 的 Parser。"""
        try:
            import tree_sitter_cpp
        except ImportError as exc:
            raise ImportError(
                "无法导入 C++ grammar。请安装: pip install tree-sitter-cpp"
            ) from exc
        return Parser(Language(tree_sitter_cpp.language()))

    def is_function_definition(self, node_or_kind: tree_sitter.Node | str) -> bool:
        return self._kind(node_or_kind) == self.function_definition_kind

    def is_function_declarator(self, node_or_kind: tree_sitter.Node | str) -> bool:
        return self._kind(node_or_kind) == self.function_declarator_kind

    def is_function_body(self, node_or_kind: tree_sitter.Node | str) -> bool:
        return self._kind(node_or_kind) == self.function_body_kind

    def is_preprocessor(self, node_or_kind: tree_sitter.Node | str) -> bool:
        return self._kind(node_or_kind).startswith(self.preprocessor_prefix)

    def is_identifier(self, node_or_kind: tree_sitter.Node | str) -> bool:
        return self._kind(node_or_kind) == self.identifier_kind

    def mask_preprocessor(
        self,
        source: bytes,
    ) -> Tuple[bytes, List[Tuple[int, int]]]:
        """等长遮蔽 C/C++ 预处理指令及续行，不改变换行和字节坐标。"""
        shadow = bytearray(source)
        masked_ranges: List[Tuple[int, int]] = []
        offset = 0
        continuation = False
        for line in source.splitlines(keepends=True):
            stripped = line.lstrip(b" \t")
            is_directive = continuation or stripped.startswith(b"#")
            content_length = len(line.rstrip(b"\r\n"))
            if is_directive and content_length:
                for index in range(content_length):
                    if shadow[offset + index] not in (10, 13):
                        shadow[offset + index] = 32
                masked_ranges.append((offset, offset + content_length))
            continuation = (
                is_directive
                and line.rstrip(b"\r\n").rstrip(b" \t").endswith(b"\\")
            )
            offset += len(line)
        return bytes(shadow), masked_ranges

    @staticmethod
    def _kind(node_or_kind: tree_sitter.Node | str) -> str:
        if isinstance(node_or_kind, str):
            return node_or_kind
        return node_or_kind.type


CPP_ADAPTER = CppAdapter()
