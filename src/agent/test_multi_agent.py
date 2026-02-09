"""
多 Agent 代码习语判定系统测试

展示如何使用三个 Agent 协同工作来判定代码习语。
使用 SingleThreadedAgentRuntime 和 RoutedAgent 的 autogen 最佳实践。
"""

import asyncio
import os
from pathlib import Path
from typing import Dict, Any

from autogen_core import SingleThreadedAgentRuntime, AgentId
from autogen_ext.models.openai import OpenAIChatCompletionClient

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    # 获取项目根目录
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✓ 已加载环境变量从: {env_path}")
except ImportError:
    print("⚠ 未安装 python-dotenv，跳过 .env 文件加载")
    print("  可以通过以下命令安装: pip install python-dotenv")

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
    IdiomJudgeResult
)


class CodeIdiomPipeline:
    """代码习语判定流水线"""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        """
        初始化判定流水线
        
        Args:
            model: 使用的模型名称
        """
        self.model = model
        self.runtime = None
        self._initialized = False
    
    async def initialize(self):
        """初始化运行时和 Agent"""
        if self._initialized:
            return
        
        print("🚀 初始化代码习语判定流水线...")
        
        # 创建运行时
        self.runtime = SingleThreadedAgentRuntime()
        
        # 创建模型客户端（三个 Agent 共享）
        model_client = OpenAIChatCompletionClient(
            model=self.model,
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL")
        )
        
        # 注册三个 Agent
        await self.runtime.register_factory(
            "semantic_agent",
            lambda: SemanticClarityAgent(model_client)
        )
        print("   ✓ 语义清晰度 Agent 已注册")
        
        await self.runtime.register_factory(
            "syntax_agent",
            lambda: SyntaxLogicAgent(model_client)
        )
        print("   ✓ 语法逻辑 Agent 已注册")
        
        await self.runtime.register_factory(
            "judge_agent",
            lambda: IdiomJudgeAgent(model_client)
        )
        print("   ✓ 综合判定 Agent 已注册")
        
        # 启动运行时
        self.runtime.start()
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
        
        print("=" * 70)
        print("开始代码习语判定流程")
        print("=" * 70)
        
        # 步骤 1: 语义清晰度判定
        print("\n[步骤 1/3] 语义清晰度判定...")
        semantic_result: SemanticClarityResult = await self.runtime.send_message(
            SemanticClarityRequest(code_snippet=code_snippet),
            recipient=AgentId("semantic_agent", key="default")
        )
        print(f"✓ 完成 - 清晰度: {semantic_result.is_clear}, 评分: {semantic_result.score}")
        
        # 步骤 2: 语法逻辑判定
        print("\n[步骤 2/3] 语法逻辑清晰度判定...")
        syntax_result: SyntaxLogicResult = await self.runtime.send_message(
            SyntaxLogicRequest(code_snippet=code_snippet),
            recipient=AgentId("syntax_agent", key="default")
        )
        print(f"✓ 完成 - 清晰度: {syntax_result.is_clear}, 评分: {syntax_result.score}")
        
        # 步骤 3: 综合判定
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
        print(f"✓ 完成 - 是否为习语: {idiom_result.is_idiom}, 置信度: {idiom_result.confidence}")
        
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
                'is_idiom': idiom_result.is_idiom,
                'confidence': idiom_result.confidence,
                'reason': idiom_result.reason,
                'characteristics': idiom_result.characteristics
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
        
        print(f"\n🎯 综合判定:")
        judgment = result['final_judgment']
        status_icon = "✅" if judgment['is_idiom'] else "❌"
        print(f"   {status_icon} 是否为代码习语: {judgment['is_idiom']}")
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
            print("\n🛑 运行时已停止")


async def main():
    """测试多 Agent 协同工作"""
    print("=" * 70)
    print("多 Agent 代码习语判定系统测试")
    print("=" * 70)
    print()
    
    # 检查环境变量
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ 错误: 未设置 OPENAI_API_KEY 环境变量")
        print("\n请设置环境变量后重试:")
        print("  export OPENAI_API_KEY='your-api-key'")
        print("  export OPENAI_BASE_URL='your-base-url'  # 可选")
        return
    
    # 创建判定流水线
    pipeline = CodeIdiomPipeline(model="gpt-4o-mini")
    
    # 测试用例
    test_cases = [
        {
            'name': '测试用例 1: 经典列表推导式（Python 习语）',
            'code': '''# 从列表中筛选偶数
numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
even_numbers = [x for x in numbers if x % 2 == 0]'''
        },
        {
            'name': '测试用例 2: 安全字典访问（Python 习语）',
            'code': '''def get_user_name(user_dict):
    return user_dict.get('name', 'Anonymous')'''
        },
        {
            'name': '测试用例 3: 过度复杂的逻辑（非习语）',
            'code': '''def f(x):
    a = []
    for i in x:
        if i:
            if type(i) == int:
                if i > 0:
                    if i % 2 == 0:
                        a.append(i)
    return a'''
        }
    ]
    
    try:
        # 依次测试每个用例
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n{'=' * 70}")
            print(f"{test_case['name']}")
            print(f"{'=' * 70}")
            
            result = await pipeline.evaluate(test_case['code'])
            pipeline.print_result(result)
            
            if i < len(test_cases):
                print(f"\n{'─' * 70}")
                await asyncio.sleep(1)  # 避免 API 频率限制
        
        print(f"\n{'=' * 70}")
        print("✨ 测试完成")
        print(f"{'=' * 70}")
    
    finally:
        # 确保关闭运行时
        await pipeline.shutdown()


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.test_multi_agent

if __name__ == "__main__":
    asyncio.run(main())
