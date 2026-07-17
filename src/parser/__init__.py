"""CodeIdiomMine 的 C++ Tree-sitter 解析模块。"""

from importlib import import_module

__all__ = ['ASTParser', 'FileScanner', 'parse_repository', 'read_data']

_EXPORTS = {
    "ASTParser": (".ast_parser", "ASTParser"),
    "FileScanner": (".file_scanner", "FileScanner"),
    "parse_repository": (".repo2data", "parse_repository"),
    "read_data": (".repo2data", "read_data"),
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
