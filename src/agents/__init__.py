"""
CodeIdiomMine Agent Module
多 Agent 代码习语判定系统

基于 autogen_core 和 autogen_ext 实现。
"""

from importlib import import_module

__all__ = [
    "BaseRoutedAgent",
    "default_agent_id",
    "register_agent",
    "SemanticClarityAgent",
    "SemanticClarityRequest",
    "SemanticClarityResult",
    "SyntaxLogicAgent",
    "SyntaxLogicRequest",
    "SyntaxLogicResult",
    "IdiomJudgeAgent",
    "IdiomJudgeRequest",
    "IdiomJudgeResult",
    "patent_programming_pattern_valid",
    "PlanningSynthesisAgent",
    "PlanningSynthesisRequest",
    "PlanningSynthesisResult",
    "CodeAssemblyAgent",
    "CodeAssemblyRequest",
    "CodeAssemblyResult",
    "MAX_SYNTHESIS_ITERATIONS",
]

_EXPORTS = {
    "BaseRoutedAgent": (".base", "BaseRoutedAgent"),
    "default_agent_id": (".base", "default_agent_id"),
    "register_agent": (".base", "register_agent"),
    "SemanticClarityAgent": (".semantic_clarity_agent", "SemanticClarityAgent"),
    "SemanticClarityRequest": (".semantic_clarity_agent", "SemanticClarityRequest"),
    "SemanticClarityResult": (".semantic_clarity_agent", "SemanticClarityResult"),
    "SyntaxLogicAgent": (".syntax_logic_agent", "SyntaxLogicAgent"),
    "SyntaxLogicRequest": (".syntax_logic_agent", "SyntaxLogicRequest"),
    "SyntaxLogicResult": (".syntax_logic_agent", "SyntaxLogicResult"),
    "IdiomJudgeAgent": (".idiom_judge_agent", "IdiomJudgeAgent"),
    "IdiomJudgeRequest": (".idiom_judge_agent", "IdiomJudgeRequest"),
    "IdiomJudgeResult": (".idiom_judge_agent", "IdiomJudgeResult"),
    "patent_programming_pattern_valid": (".idiom_judge_agent", "patent_programming_pattern_valid"),
    "PlanningSynthesisAgent": (".planning_synthesis_agent", "PlanningSynthesisAgent"),
    "PlanningSynthesisRequest": (".planning_synthesis_agent", "PlanningSynthesisRequest"),
    "PlanningSynthesisResult": (".planning_synthesis_agent", "PlanningSynthesisResult"),
    "CodeAssemblyAgent": (".code_assembly_agent", "CodeAssemblyAgent"),
    "CodeAssemblyRequest": (".code_assembly_agent", "CodeAssemblyRequest"),
    "CodeAssemblyResult": (".code_assembly_agent", "CodeAssemblyResult"),
    "MAX_SYNTHESIS_ITERATIONS": (".idiom_synthesis", "MAX_SYNTHESIS_ITERATIONS"),
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
