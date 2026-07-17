"""
CodeIdiomMine Utils Module
实用工具模块
"""

from importlib import import_module

__all__ = [
    'Pkl2CsvConverter',
]

_EXPORTS = {
    "Pkl2CsvConverter": (".pkl2csv", "Pkl2CsvConverter"),
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
