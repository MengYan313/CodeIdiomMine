"""C++ AST 节点类型定义（tree-sitter-cpp）。"""

FUNCTION_KINDS = {
    "function_definition",
    "function_declarator",
    "method_definition",
    "class_specifier",
    "template_declaration",
    "template_function",
}

BLOCK_KINDS = {
    "if_statement",
    "for_statement",
    "for_range_loop",
    "while_statement",
    "do_statement",
    "switch_statement",
    "try_statement",
    "catch_clause",
}

STATEMENT_KINDS = {
    "declaration",
    "return_statement",
    "binary_expression",
    "throw_statement",
    "field_declaration",
    "call_expression",
    "lambda_expression",
    "labeled_statement",
    "goto_statement",
    "expression_statement",
    "compound_statement",
}
