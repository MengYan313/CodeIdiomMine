"""
定义不同编程语言的 AST 节点类型
用于识别函数级别、块级别和语句级别的节点
适配 tree-sitter 节点类型
"""

# C++ 节点类型（tree-sitter-cpp）
CPP_FUNC_KINDS = {
    "function_definition",
    "function_declarator",
    "method_definition",
    "class_specifier",
    "template_declaration",
    "template_function",
}

CPP_BLOCK_KINDS = {
    "if_statement",
    "for_statement",
    "for_range_loop",
    "while_statement",
    "do_statement",
    "switch_statement",
    "try_statement",
    "catch_clause",
}

CPP_STMT_KINDS = {
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

# Python 节点类型（tree-sitter-python）
PYTHON_FUNC_KINDS = {
    "function_definition",
    "class_definition",
}

PYTHON_BLOCK_KINDS = {
    "if_statement",
    "for_statement",
    "while_statement",
    "try_statement",
    "except_clause",
    "with_statement",
}

PYTHON_STMT_KINDS = {
    "expression_statement",
    "return_statement",
    "assignment",
    "augmented_assignment",
    "call",
    "lambda",
    "assert_statement",
    "raise_statement",
    "pass_statement",
    "break_statement",
    "continue_statement",
}

# Java 节点类型（tree-sitter-java）
JAVA_FUNC_KINDS = {
    "method_declaration",
    "class_declaration",
    "interface_declaration",
    "constructor_declaration",
}

JAVA_BLOCK_KINDS = {
    "if_statement",
    "for_statement",
    "enhanced_for_statement",
    "while_statement",
    "do_statement",
    "switch_statement",
    "try_statement",
    "catch_clause",
}

JAVA_STMT_KINDS = {
    "local_variable_declaration",
    "return_statement",
    "binary_expression",
    "throw_statement",
    "field_declaration",
    "method_invocation",
    "lambda_expression",
    "labeled_statement",
    "assert_statement",
}

# JavaScript 节点类型（tree-sitter-javascript）
JS_FUNC_KINDS = {
    "function_declaration",
    "function",
    "method_definition",
    "class_declaration",
    "arrow_function",
}

JS_BLOCK_KINDS = {
    "if_statement",
    "for_statement",
    "for_in_statement",
    "for_of_statement",
    "while_statement",
    "do_statement",
    "switch_statement",
    "try_statement",
    "catch_clause",
}

JS_STMT_KINDS = {
    "variable_declaration",
    "return_statement",
    "binary_expression",
    "throw_statement",
    "call_expression",
    "arrow_function",
    "labeled_statement",
    "expression_statement",
}

# 语言到节点类型的映射
LANGUAGE_NODE_KINDS = {
    "cpp": {
        "func": CPP_FUNC_KINDS,
        "block": CPP_BLOCK_KINDS,
        "stmt": CPP_STMT_KINDS,
    },
    "python": {
        "func": PYTHON_FUNC_KINDS,
        "block": PYTHON_BLOCK_KINDS,
        "stmt": PYTHON_STMT_KINDS,
    },
    "java": {
        "func": JAVA_FUNC_KINDS,
        "block": JAVA_BLOCK_KINDS,
        "stmt": JAVA_STMT_KINDS,
    },
    "javascript": {
        "func": JS_FUNC_KINDS,
        "block": JS_BLOCK_KINDS,
        "stmt": JS_STMT_KINDS,
    },
}

def get_node_kinds(language: str):
    """获取指定语言的节点类型定义"""
    return LANGUAGE_NODE_KINDS.get(language.lower(), LANGUAGE_NODE_KINDS["cpp"])

def get_func_kinds(language: str = "cpp"):
    """获取函数级别的节点类型"""
    return get_node_kinds(language)["func"]

def get_block_kinds(language: str = "cpp"):
    """获取块级别的节点类型"""
    return get_node_kinds(language)["block"]

def get_stmt_kinds(language: str = "cpp"):
    """获取语句级别的节点类型"""
    return get_node_kinds(language)["stmt"]

# 为了向后兼容，提供全局变量（默认 C++）
func_kind = get_func_kinds("cpp")
block_kind = get_block_kinds("cpp")
stmt_kind = get_stmt_kinds("cpp")

