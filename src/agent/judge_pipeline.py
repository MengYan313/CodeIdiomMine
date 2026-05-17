"""
多 Agent 代码习语判定系统测试

展示如何使用三个 Agent 协同工作来判定代码习语。
使用 SingleThreadedAgentRuntime 和 RoutedAgent 的 autogen 最佳实践。
"""

import asyncio
from typing import Dict, Any

from autogen_core import SingleThreadedAgentRuntime, AgentId

from ._base import create_model_client, load_project_env
from .semantic_clarity_agent import (
    SemanticClarityAgent,
    SemanticClarityRequest,
    SemanticClarityResult
)
from .syntax_logic_agent import (
    SyntaxLogicAgent,
    SyntaxLogicRequest,
    SyntaxLogicResult
)
from .idiom_judge_agent import (
    IdiomJudgeAgent,
    IdiomJudgeRequest,
    IdiomJudgeResult,
    patent_programming_pattern_valid,
)


class CodeIdiomPipeline:
    """
    代码习语判定流水线（说明书 7.2：语义与语法并行 + 综合判定）。

    - 语义清晰度 Agent 与语法逻辑 Agent 对同一代码段并行调用 LLM；
    - 综合判定 Agent 汇总两路结果生成说明性结论；
    - 是否有效编程模式由 ``patent_programming_pattern_valid`` 按 7.2 分数阈值唯一决定，
      避免综合 Agent 的 LLM 输出与专利规则不一致。
    """
    
    def __init__(self, model: str = "gpt-4o-mini", quiet: bool = False):
        """
        初始化判定流水线
        
        Args:
            model: 使用的模型名称
            quiet: 为 True 时不打印步骤日志（供合成流水线 7.4 再判定调用）
        """
        self.model = model
        self._quiet = quiet
        self.runtime = None
        self._initialized = False
    
    async def initialize(self):
        """初始化运行时和 Agent"""
        if self._initialized:
            return
        
        if not self._quiet:
            print("🚀 初始化代码习语判定流水线...")

        load_project_env()

        # 创建运行时
        self.runtime = SingleThreadedAgentRuntime()

        # 创建模型客户端（三个 Agent 共享）
        model_client = create_model_client(self.model)
        
        # 注册三个 Agent
        await self.runtime.register_factory(
            "semantic_agent",
            lambda: SemanticClarityAgent(model_client)
        )
        if not self._quiet:
            print("   ✓ 语义清晰度 Agent 已注册")
        
        await self.runtime.register_factory(
            "syntax_agent",
            lambda: SyntaxLogicAgent(model_client)
        )
        if not self._quiet:
            print("   ✓ 语法逻辑 Agent 已注册")
        
        await self.runtime.register_factory(
            "judge_agent",
            lambda: IdiomJudgeAgent(model_client)
        )
        if not self._quiet:
            print("   ✓ 综合判定 Agent 已注册")
        
        # 启动运行时
        self.runtime.start()
        if not self._quiet:
            print("   ✓ 运行时已启动\n")
        
        self._initialized = True
    
    async def evaluate(self, code_snippet: str) -> Dict[str, Any]:
        """
        完整的代码习语判定流程
        
        Args:
            code_snippet: 代码片段
            
        Returns:
            包含所有评估结果的字典
        """
        if not self._initialized:
            await self.initialize()
        
        if not self._quiet:
            print("=" * 70)
            print("开始代码习语判定流程")
            print("=" * 70)
        
        # 步骤 1–2: 语义清晰度与语法逻辑并行判定（说明书 7.2）
        if not self._quiet:
            print("\n[步骤 1–2/3] 语义清晰度与语法逻辑并行判定...")
        semantic_result, syntax_result = await asyncio.gather(
            self.runtime.send_message(
                SemanticClarityRequest(code_snippet=code_snippet),
                recipient=AgentId("semantic_agent", key="default"),
            ),
            self.runtime.send_message(
                SyntaxLogicRequest(code_snippet=code_snippet),
                recipient=AgentId("syntax_agent", key="default"),
            ),
        )
        if not self._quiet:
            print(
                f"✓ 语义 — 清晰度: {semantic_result.is_clear}, 评分: {semantic_result.score}"
            )
            print(
                f"✓ 语法 — 清晰度: {syntax_result.is_clear}, 评分: {syntax_result.score}"
            )
        
        # 步骤 3: 综合判定（LLM 生成理由/置信度/特征；是否习语由专利 7.2 规则锁定）
        if not self._quiet:
            print("\n[步骤 3/3] 综合判定代码习语...")
        judge_request = IdiomJudgeRequest(
            code_snippet=code_snippet,
            semantic_is_clear=semantic_result.is_clear,
            semantic_score=semantic_result.score,
            semantic_reason=semantic_result.reason,
            semantic_suggestions=semantic_result.suggestions,
            syntax_is_clear=syntax_result.is_clear,
            syntax_score=syntax_result.score,
            syntax_reason=syntax_result.reason,
            syntax_issues=syntax_result.issues
        )
        idiom_result: IdiomJudgeResult = await self.runtime.send_message(
            judge_request,
            recipient=AgentId("judge_agent", key="default")
        )
        is_idiom_rule = patent_programming_pattern_valid(
            semantic_result.score, syntax_result.score
        )
        llm_is_idiom = idiom_result.is_idiom
        # 专利 7.2：以两维 score 阈值为最终是否有效编程模式；与 LLM 不一致时调整置信度
        if is_idiom_rule != llm_is_idiom:
            confidence = (semantic_result.score + syntax_result.score) / 2.0
        else:
            confidence = idiom_result.confidence
        if not self._quiet:
            print(
                f"✓ 完成 - 是否有效编程模式(7.2 规则): {is_idiom_rule}, "
                f"综合 Agent 原始判断: {llm_is_idiom}, 置信度: {confidence}"
            )
        
        # 返回完整结果
        return {
            'code': code_snippet,
            'semantic': {
                'is_clear': semantic_result.is_clear,
                'score': semantic_result.score,
                'reason': semantic_result.reason,
                'suggestions': semantic_result.suggestions
            },
            'syntax': {
                'is_clear': syntax_result.is_clear,
                'score': syntax_result.score,
                'reason': syntax_result.reason,
                'issues': syntax_result.issues
            },
            'final_judgment': {
                'is_idiom': is_idiom_rule,
                'confidence': confidence,
                'reason': idiom_result.reason,
                'characteristics': idiom_result.characteristics,
                'llm_is_idiom': llm_is_idiom,
            }
        }
    
    def print_result(self, result: Dict[str, Any]):
        """打印完整的评估结果"""
        print("\n" + "=" * 70)
        print("评估结果汇总")
        print("=" * 70)
        
        print(f"\n📝 代码片段:")
        print(result['code'])
        
        print(f"\n🔍 语义清晰度评估:")
        semantic = result['semantic']
        print(f"   状态: {'✓ 清晰' if semantic['is_clear'] else '✗ 不清晰'}")
        print(f"   评分: {semantic['score']}/100")
        print(f"   理由: {semantic['reason']}")
        if semantic['suggestions']:
            print(f"   建议: {', '.join(semantic['suggestions'])}")
        
        print(f"\n🔍 语法逻辑评估:")
        syntax = result['syntax']
        print(f"   状态: {'✓ 清晰' if syntax['is_clear'] else '✗ 不清晰'}")
        print(f"   评分: {syntax['score']}/100")
        print(f"   理由: {syntax['reason']}")
        if syntax['issues']:
            print(f"   问题: {', '.join(syntax['issues'])}")
        
        print(f"\n🎯 综合判定（有效编程模式以说明书 7.2 分数规则为准）:")
        judgment = result['final_judgment']
        status_icon = "✅" if judgment['is_idiom'] else "❌"
        print(f"   {status_icon} 是否为代码习语: {judgment['is_idiom']}")
        if judgment.get('llm_is_idiom') is not None and judgment['llm_is_idiom'] != judgment['is_idiom']:
            print(f"   （综合 Agent LLM 原始判断: {judgment['llm_is_idiom']}，已由规则修正）")
        print(f"   置信度: {judgment['confidence']}/100")
        print(f"   理由: {judgment['reason']}")
        if judgment['characteristics']:
            print(f"   习语特征:")
            for char in judgment['characteristics']:
                print(f"      - {char}")
    
    async def shutdown(self):
        """关闭运行时"""
        if self.runtime and self._initialized:
            await self.runtime.stop()
            if not self._quiet:
                print("\n🛑 运行时已停止")
