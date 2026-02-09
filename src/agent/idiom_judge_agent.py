"""
代码习语综合判定 Agent

负责接收前两个 Agent 的结果，综合判定是否为代码习语。
判定标准：
1. 综合语义清晰度评估结果
2. 综合语法逻辑清晰度评估结果
3. 判定是否符合代码习语的特征
"""

import json
from typing import Any, Dict, List
from dataclasses import dataclass

from autogen_core import RoutedAgent, message_handler, MessageContext
from autogen_core.models import SystemMessage, UserMessage, LLMMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..utils.response_parser import extract_tag_content
from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class IdiomJudgeRequest:
    """代码习语判定请求"""
    code_snippet: str
    semantic_is_clear: bool
    semantic_score: float
    semantic_reason: str
    semantic_suggestions: List[str]
    syntax_is_clear: bool
    syntax_score: float
    syntax_reason: str
    syntax_issues: List[str]


@dataclass
class IdiomJudgeResult:
    """代码习语判定结果"""
    is_idiom: bool  # 是否为代码习语
    confidence: float  # 置信度 (0-100)
    reason: str  # 判定理由
    characteristics: List[str]  # 识别出的习语特征


class IdiomJudgeAgent(RoutedAgent):
    """
    代码习语综合判定 Agent
    
    综合语义和逻辑两个维度的评估结果，判定是否为代码习语。
    """
    
    def __init__(
        self,
        model_client: OpenAIChatCompletionClient,
    ):
        """
        初始化代码习语判定 Agent
        
        Args:
            model_client: OpenAI 模型客户端
        """
        super().__init__("IdiomJudgeAgent")
        self._model_client = model_client
        
        # 定义系统提示（英文）
        self._system_message = """You are a code idiom recognition expert responsible for comprehensively evaluating whether a code snippet qualifies as a code idiom.

Definition of Code Idiom:
A code idiom is a widely recognized and used code pattern in a specific programming language or domain, characterized by:
1. **Semantic Clarity**: Clear code intent with reasonable naming
2. **Logic Simplicity**: Direct implementation avoiding complex nesting
3. **Pattern Generality**: Reusable across multiple scenarios
4. **Best Practice**: Follows programming standards and conventions

You need to synthesize evaluation results from two dimensions:
- Semantic clarity assessment
- Syntax and logic clarity assessment

Judgment criteria:
- Both dimensions score >= 70: Very likely a code idiom
- One dimension >= 70, the other >= 50: Possibly a code idiom
- Other cases: Unlikely to be a code idiom

IMPORTANT RESPONSE FORMAT:
1. When referring to the code snippet, wrap it with [Code Idiom] and [/Code Idiom] tags
2. Wrap your JSON response with [JSON] and [/JSON] tags

Example response format:
[JSON]
{
    "is_idiom": true,
    "confidence": 85,
    "reason": "Reason for the judgment",
    "characteristics": ["characteristic 1", "characteristic 2"]
}
[/JSON]"""
    
    @message_handler
    async def handle_request(
        self,
        message: IdiomJudgeRequest,
        ctx: MessageContext
    ) -> IdiomJudgeResult:
        """
        处理代码习语判定请求
        
        Args:
            message: 判定请求
            ctx: 消息上下文
            
        Returns:
            代码习语判定结果
        """
        # 构建提示（英文）
        prompt = f"""Please synthesize the following assessment results to determine whether the code snippet qualifies as a code idiom:

[Code Idiom]
{message.code_snippet}
[/Code Idiom]

**Semantic Clarity Assessment:**
- Is Clear: {message.semantic_is_clear}
- Score: {message.semantic_score}
- Reason: {message.semantic_reason}
- Suggestions: {message.semantic_suggestions}

**Syntax and Logic Clarity Assessment:**
- Is Clear: {message.syntax_is_clear}
- Score: {message.syntax_score}
- Reason: {message.syntax_reason}
- Issues: {message.syntax_issues}

Please return the comprehensive judgment result in the specified format with [JSON] tags."""
        
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
            
            return IdiomJudgeResult(
                is_idiom=result_json.get('is_idiom', False),
                confidence=float(result_json.get('confidence', 0)),
                reason=result_json.get('reason', ''),
                characteristics=result_json.get('characteristics', [])
            )
        except Exception as e:
            # 解析失败，返回默认结果
            logger.error(f"解析响应失败: {str(e)}, 响应内容: {response_text[:500]}")
            return IdiomJudgeResult(
                is_idiom=False,
                confidence=0,
                reason=f"Failed to parse response: {str(e)}",
                characteristics=[]
            )


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.idiom_judge_agent

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
        """测试代码习语判定 Agent"""
        print("=" * 60)
        print("测试代码习语判定 Agent")
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
            "judge_agent",
            lambda: IdiomJudgeAgent(model_client)
        )
        
        # 启动运行时
        runtime.start()
        
        # 模拟前两个 Agent 的评估结果
        code = """
def calculate_average(numbers):
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)
"""
        
        print(f"\n代码片段:\n{code}")
        print(f"\n模拟评估结果:")
        print(f"  语义: 清晰=True, 评分=90")
        print(f"  逻辑: 清晰=True, 评分=85")
        
        request = IdiomJudgeRequest(
            code_snippet=code,
            semantic_is_clear=True,
            semantic_score=90,
            semantic_reason="Clear function naming, obvious parameter and return value intent",
            semantic_suggestions=[],
            syntax_is_clear=True,
            syntax_score=85,
            syntax_reason="Simple and direct logic, proper boundary handling",
            syntax_issues=[]
        )
        
        result = await runtime.send_message(
            request,
            recipient=AgentId("judge_agent", key="default")
        )
        
        print(f"\n综合判定结果:")
        print(f"  是否为代码习语: {result.is_idiom}")
        print(f"  置信度: {result.confidence}")
        print(f"  理由: {result.reason}")
        print(f"  特征: {result.characteristics}")
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        
        # 停止运行时
        await runtime.stop()
    
    asyncio.run(test())
