"""
语义清晰度判定 Agent

负责判定输入的代码片段是否语义清晰。
判定标准：
1. 变量和函数命名是否有意义
2. 代码意图是否明确
3. 是否容易理解其功能
"""

import json
from typing import Any, List, Sequence
from dataclasses import dataclass

from autogen_core import RoutedAgent, message_handler, MessageContext
from autogen_core.models import SystemMessage, UserMessage, LLMMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..utils.response_parser import extract_tag_content
from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class SemanticClarityRequest:
    """语义清晰度判定请求"""
    code_snippet: str


@dataclass
class SemanticClarityResult:
    """语义清晰度判定结果"""
    is_clear: bool  # 是否语义清晰
    score: float  # 清晰度评分 (0-100)
    reason: str  # 判定理由
    suggestions: List[str]  # 改进建议


class SemanticClarityAgent(RoutedAgent):
    """
    语义清晰度判定 Agent
    
    使用 LLM 评估代码片段的语义清晰度。
    """
    
    def __init__(
        self,
        model_client: OpenAIChatCompletionClient,
    ):
        """
        初始化语义清晰度判定 Agent
        
        Args:
            model_client: OpenAI 模型客户端
        """
        super().__init__("SemanticClarityAgent")
        self._model_client = model_client
        
        # 定义系统提示（英文）
        self._system_message = """You are a professional code review expert specializing in evaluating code semantic clarity.

Your task is to determine whether a code snippet has clear semantics. Evaluation criteria include:
1. **Naming Quality**: Whether variable, function, and class names are meaningful and follow conventions
2. **Intent Clarity**: Whether the code's functionality and purpose are immediately apparent
3. **Understandability**: Whether the code can be understood without deep analysis

Scoring criteria:
- 90-100: Very clear semantics, excellent naming, obvious intent
- 70-89: Relatively clear semantics, with minor room for improvement
- 50-69: Average semantics, needs some improvement
- 30-49: Unclear semantics, has multiple issues
- 0-29: Confusing semantics, difficult to understand

IMPORTANT RESPONSE FORMAT:
1. When referring to the code snippet, wrap it with [Code Idiom] and [/Code Idiom] tags
2. Wrap your JSON response with [JSON] and [/JSON] tags

Example response format:
[JSON]
{
    "is_clear": true,
    "score": 85,
    "reason": "Reason for the score",
    "suggestions": ["suggestion 1", "suggestion 2"]
}
[/JSON]"""
    
    @message_handler
    async def handle_request(
        self,
        message: SemanticClarityRequest,
        ctx: MessageContext
    ) -> SemanticClarityResult:
        """
        处理语义清晰度评估请求
        
        Args:
            message: 评估请求
            ctx: 消息上下文
            
        Returns:
            语义清晰度判定结果
        """
        # 构建提示（英文）
        prompt = f"""Please evaluate the semantic clarity of the following code snippet:

[Code Idiom]
{message.code_snippet}
[/Code Idiom]

Please return the evaluation result in the specified format with [JSON] tags."""
        
        # 构建消息列表
        messages: List[LLMMessage] = [
            SystemMessage(content=self._system_message),
            UserMessage(content=prompt, source="user")
        ]
        
        # 调用 LLM
        response = await self._model_client.create(
            messages=messages,
            extra_create_args={"temperature": 0.0}
        )
        
        # 解析响应
        response_text = response.content
        
        try:
            # 使用 extract_tag_content 提取 JSON 标签内容
            json_content = extract_tag_content(
                response_text, 
                "JSON", 
                default="",
                logger_instance=logger
            )
            
            # 如果提取失败，尝试直接解析整个响应
            if not json_content:
                json_content = response_text
            
            # 解析 JSON
            result_json = json.loads(json_content)
            
            return SemanticClarityResult(
                is_clear=result_json.get('is_clear', False),
                score=float(result_json.get('score', 0)),
                reason=result_json.get('reason', ''),
                suggestions=result_json.get('suggestions', [])
            )
        except Exception as e:
            # 解析失败，返回默认结果
            logger.error(f"解析响应失败: {str(e)}, 响应内容: {response_text[:500]}")
            return SemanticClarityResult(
                is_clear=False,
                score=0,
                reason=f"Failed to parse response: {str(e)}",
                suggestions=[]
            )


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.semantic_clarity_agent

if __name__ == "__main__":
    import asyncio
    import os
    from pathlib import Path
    from autogen_core import SingleThreadedAgentRuntime, AgentId
    
    # 尝试加载 .env 文件
    try:
        from dotenv import load_dotenv
        project_root = Path(__file__).parent.parent.parent
        env_path = project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass
    
    async def test():
        """测试语义清晰度判定 Agent"""
        print("=" * 60)
        print("测试语义清晰度判定 Agent")
        print("=" * 60)
        
        # 检查环境变量
        if not os.getenv("OPENAI_API_KEY"):
            print("\n❌ 错误: 未设置 OPENAI_API_KEY 环境变量")
            print("\n请设置环境变量后重试:")
            print("  export OPENAI_API_KEY='your-api-key'")
            print("  export OPENAI_BASE_URL='your-base-url'  # 可选")
            return
        
        # 创建运行时
        runtime = SingleThreadedAgentRuntime()
        
        # 创建模型客户端
        model_client = OpenAIChatCompletionClient(
            model="gpt-4o-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL")
        )
        
        # 注册 Agent
        await runtime.register_factory(
            "semantic_agent",
            lambda: SemanticClarityAgent(model_client)
        )
        
        # 启动运行时
        runtime.start()
        
        # 测试用例 1: 语义清晰的代码
        code1 = """
def calculate_average(numbers):
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)
"""
        
        print("\n测试用例 1: 语义清晰的代码")
        print(f"代码:\n{code1}")
        
        result1 = await runtime.send_message(
            SemanticClarityRequest(code_snippet=code1),
            recipient=AgentId("semantic_agent", key="default")
        )
        
        print(f"\n结果:")
        print(f"  语义清晰: {result1.is_clear}")
        print(f"  评分: {result1.score}")
        print(f"  理由: {result1.reason}")
        print(f"  建议: {result1.suggestions}")
        
        # 测试用例 2: 语义不清晰的代码
        code2 = """
def f(x):
    a = []
    for i in x:
        if i % 2 == 0:
            a.append(i)
    return a
"""
        
        print("\n" + "=" * 60)
        print("\n测试用例 2: 语义不清晰的代码")
        print(f"代码:\n{code2}")
        
        result2 = await runtime.send_message(
            SemanticClarityRequest(code_snippet=code2),
            recipient=AgentId("semantic_agent", key="default")
        )
        
        print(f"\n结果:")
        print(f"  语义清晰: {result2.is_clear}")
        print(f"  评分: {result2.score}")
        print(f"  理由: {result2.reason}")
        print(f"  建议: {result2.suggestions}")
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        
        # 停止运行时
        await runtime.stop()
    
    asyncio.run(test())
