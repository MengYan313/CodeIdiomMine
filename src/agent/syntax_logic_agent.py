"""
语法和逻辑清晰度判定 Agent

负责判定输入的代码片段是否语法和逻辑清晰。
判定标准：
1. 语法是否正确
2. 逻辑流程是否合理
3. 是否存在明显的逻辑错误或反模式
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
class SyntaxLogicRequest:
    """语法和逻辑清晰度判定请求"""
    code_snippet: str


@dataclass
class SyntaxLogicResult:
    """语法和逻辑清晰度判定结果"""
    is_clear: bool  # 语法和逻辑是否清晰
    score: float  # 清晰度评分 (0-100)
    reason: str  # 判定理由
    issues: List[str]  # 发现的问题


class SyntaxLogicAgent(RoutedAgent):
    """
    语法和逻辑清晰度判定 Agent
    
    使用 LLM 评估代码片段的语法和逻辑清晰度。
    """
    
    def __init__(
        self,
        model_client: OpenAIChatCompletionClient,
    ):
        """
        初始化语法和逻辑清晰度判定 Agent
        
        Args:
            model_client: OpenAI 模型客户端
        """
        super().__init__("SyntaxLogicAgent")
        self._model_client = model_client
        
        # 定义系统提示（英文）
        self._system_message = """You are a professional code analysis expert specializing in evaluating code syntax and logic clarity.

Your task is to determine whether a code snippet has clear syntax and logic. Evaluation criteria include:
1. **Syntax Correctness**: Whether the syntax follows language standards (check for obvious syntax errors)
2. **Logic Clarity**: Whether the logical flow is reasonable and easy to follow
3. **Logic Correctness**: Whether there are obvious logical errors or anti-patterns
4. **Control Flow**: Whether conditional statements and loops are used reasonably
5. **Error Handling**: Whether edge cases and error scenarios are properly handled

Scoring criteria:
- 90-100: Syntax and logic are very clear, no obvious issues
- 70-89: Syntax and logic are relatively clear, with minor issues
- 50-69: Syntax and logic are average, with some issues
- 30-49: Syntax or logic is unclear, with multiple issues
- 0-29: Syntax or logic is confusing, with serious issues

IMPORTANT RESPONSE FORMAT:
1. When referring to the code snippet, wrap it with [Code Idiom] and [/Code Idiom] tags
2. Wrap your JSON response with [JSON] and [/JSON] tags

Example response format:
[JSON]
{
    "is_clear": true,
    "score": 85,
    "reason": "Reason for the score",
    "issues": ["issue 1", "issue 2"]
}
[/JSON]"""
    
    @message_handler
    async def handle_request(
        self,
        message: SyntaxLogicRequest,
        ctx: MessageContext
    ) -> SyntaxLogicResult:
        """
        处理语法和逻辑清晰度评估请求
        
        Args:
            message: 评估请求
            ctx: 消息上下文
            
        Returns:
            语法和逻辑清晰度判定结果
        """
        # 构建提示（英文）
        prompt = f"""Please evaluate the syntax and logic clarity of the following code snippet:

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
            
            return SyntaxLogicResult(
                is_clear=result_json.get('is_clear', False),
                score=float(result_json.get('score', 0)),
                reason=result_json.get('reason', ''),
                issues=result_json.get('issues', [])
            )
        except Exception as e:
            # 解析失败，返回默认结果
            logger.error(f"解析响应失败: {str(e)}, 响应内容: {response_text[:500]}")
            return SyntaxLogicResult(
                is_clear=False,
                score=0,
                reason=f"Failed to parse response: {str(e)}",
                issues=[]
            )


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.syntax_logic_agent

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
        """测试语法和逻辑清晰度判定 Agent"""
        print("=" * 60)
        print("测试语法和逻辑清晰度判定 Agent")
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
            "syntax_logic_agent",
            lambda: SyntaxLogicAgent(model_client)
        )
        
        # 启动运行时
        runtime.start()
        
        # 测试用例 1: 语法和逻辑清晰的代码
        code1 = """
def find_max(numbers):
    if not numbers:
        return None
    max_value = numbers[0]
    for num in numbers[1:]:
        if num > max_value:
            max_value = num
    return max_value
"""
        
        print("\n测试用例 1: 语法和逻辑清晰的代码")
        print(f"代码:\n{code1}")
        
        result1 = await runtime.send_message(
            SyntaxLogicRequest(code_snippet=code1),
            recipient=AgentId("syntax_logic_agent", key="default")
        )
        
        print(f"\n结果:")
        print(f"  语法和逻辑清晰: {result1.is_clear}")
        print(f"  评分: {result1.score}")
        print(f"  理由: {result1.reason}")
        print(f"  问题: {result1.issues}")
        
        # 测试用例 2: 有逻辑问题的代码
        code2 = """
def divide(a, b):
    result = a / b
    return result
"""
        
        print("\n" + "=" * 60)
        print("\n测试用例 2: 有逻辑问题的代码")
        print(f"代码:\n{code2}")
        
        result2 = await runtime.send_message(
            SyntaxLogicRequest(code_snippet=code2),
            recipient=AgentId("syntax_logic_agent", key="default")
        )
        
        print(f"\n结果:")
        print(f"  语法和逻辑清晰: {result2.is_clear}")
        print(f"  评分: {result2.score}")
        print(f"  理由: {result2.reason}")
        print(f"  问题: {result2.issues}")
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        
        # 停止运行时
        await runtime.stop()
    
    asyncio.run(test())
