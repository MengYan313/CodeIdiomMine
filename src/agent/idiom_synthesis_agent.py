"""
代码习语合成 Agent

负责判断两段代码是否具有相关性，若满足条件则合成为一段。
相关性判定标准：
1. 语义关联：两段代码在语义上有关联（如调用关系、逻辑延续）
2. 常见搭配：两段代码是常见的搭配模式（如 try-finally、init-cleanup）
3. 共同变量：两段代码共享变量或数据结构
"""

import json
from typing import List
from dataclasses import dataclass

from autogen_core import RoutedAgent, message_handler, MessageContext
from autogen_core.models import SystemMessage, UserMessage, LLMMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ..utils.response_parser import extract_tag_content
from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class IdiomSynthesisRequest:
    """习语合成请求"""
    code_snippet_1: str
    code_snippet_2: str


@dataclass
class IdiomSynthesisResult:
    """习语合成结果"""
    is_related: bool  # 两段代码是否具有相关性
    synthesized_code: str  # 合成后的代码（仅当 is_related=True 时有效）
    reason: str  # 判定理由
    relation_type: str  # 相关性类型：semantic / common_pair / shared_variable / multiple / none


class IdiomSynthesisAgent(RoutedAgent):
    """
    代码习语合成 Agent

    判断两段代码是否具有相关性，若满足任一条件则合成为一段并返回。
    """

    def __init__(
        self,
        model_client: OpenAIChatCompletionClient,
    ):
        """
        初始化习语合成 Agent

        Args:
            model_client: OpenAI 模型客户端
        """
        super().__init__("IdiomSynthesisAgent")
        self._model_client = model_client

        # 定义系统提示（英文）
        self._system_message = """You are a code idiom synthesis expert responsible for determining whether two code snippets are related and, if so, synthesizing them into a single coherent code snippet.

**Relation Criteria** (at least one must be satisfied for synthesis):
1. **Semantic Correlation**: The two snippets are semantically related (e.g., one calls the other, logical continuation, complementary functionality)
2. **Common Pairing**: The two snippets form a common idiom or pattern (e.g., try-finally, init-cleanup, open-close, lock-unlock)
3. **Shared Variables**: The two snippets share variables, data structures, or operate on the same context

**Synthesis Rules** (when is_related is true):
- Merge the two snippets into one coherent, syntactically correct code block
- Preserve the logical order and dependencies
- Remove redundant declarations (e.g., shared variables declared only once)
- Ensure the synthesized code is self-contained and executable where appropriate

**Output Guidelines**:
- relation_type: "semantic" | "common_pair" | "shared_variable" | "multiple" (when more than one applies) | "none" (when not related)
- When is_related is false, synthesized_code should be empty string ""

IMPORTANT RESPONSE FORMAT:
1. When referring to code snippets, wrap them with [Code Idiom] and [/Code Idiom] tags
2. Wrap your JSON response with [JSON] and [/JSON] tags

Example response format (when related):
[JSON]
{
    "is_related": true,
    "synthesized_code": "merged code here",
    "reason": "Reason for the judgment",
    "relation_type": "common_pair"
}
[/JSON]

Example response format (when not related):
[JSON]
{
    "is_related": false,
    "synthesized_code": "",
    "reason": "Reason why not related",
    "relation_type": "none"
}
[/JSON]"""

    @message_handler
    async def handle_request(
        self,
        message: IdiomSynthesisRequest,
        ctx: MessageContext
    ) -> IdiomSynthesisResult:
        """
        处理习语合成请求

        Args:
            message: 合成请求
            ctx: 消息上下文

        Returns:
            习语合成结果
        """
        # 构建提示（英文）
        prompt = f"""Please determine whether the following two code snippets are related, and if so, synthesize them into one.

**Code Snippet 1:**
[Code Idiom]
{message.code_snippet_1}
[/Code Idiom]

**Code Snippet 2:**
[Code Idiom]
{message.code_snippet_2}
[/Code Idiom]

Check for:
1. Semantic correlation (e.g., calling relationship, logical continuation)
2. Common pairing (e.g., try-finally, init-cleanup patterns)
3. Shared variables or data structures

If any condition is met, synthesize the two snippets into one coherent code block. Otherwise, set is_related to false and leave synthesized_code empty.

Please return the result in the specified format with [JSON] tags."""

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

            return IdiomSynthesisResult(
                is_related=result_json.get('is_related', False),
                synthesized_code=result_json.get('synthesized_code', ''),
                reason=result_json.get('reason', ''),
                relation_type=result_json.get('relation_type', 'none')
            )
        except Exception as e:
            # 解析失败，返回默认结果
            logger.error(f"解析响应失败: {str(e)}, 响应内容: {response_text[:500]}")
            return IdiomSynthesisResult(
                is_related=False,
                synthesized_code='',
                reason=f"Failed to parse response: {str(e)}",
                relation_type='none'
            )


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.idiom_synthesis_agent

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
        """测试习语合成 Agent"""
        print("=" * 60)
        print("测试习语合成 Agent")
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
            "synthesis_agent",
            lambda: IdiomSynthesisAgent(model_client)
        )

        # 启动运行时
        runtime.start()

        # 测试用例 1: 具有相关性的代码（try-finally 常见搭配）
        code1 = """
try:
    f = open('file.txt')
    data = f.read()
"""
        code2 = """
finally:
    f.close()
"""

        print("\n测试用例 1: try-finally 常见搭配")
        print(f"代码 1:\n{code1}")
        print(f"代码 2:\n{code2}")

        request1 = IdiomSynthesisRequest(
            code_snippet_1=code1.strip(),
            code_snippet_2=code2.strip()
        )

        result1 = await runtime.send_message(
            request1,
            recipient=AgentId("synthesis_agent", key="default")
        )

        print(f"\n结果:")
        print(f"  是否相关: {result1.is_related}")
        print(f"  相关性类型: {result1.relation_type}")
        print(f"  理由: {result1.reason}")
        if result1.synthesized_code:
            print(f"  合成代码:\n{result1.synthesized_code}")

        # 测试用例 2: 语义不相关的代码
        code3 = "x = 1 + 2"
        code4 = "print('hello')"

        print("\n" + "=" * 60)
        print("\n测试用例 2: 语义不相关的代码")
        print(f"代码 1: {code3}")
        print(f"代码 2: {code4}")

        request2 = IdiomSynthesisRequest(
            code_snippet_1=code3,
            code_snippet_2=code4
        )

        result2 = await runtime.send_message(
            request2,
            recipient=AgentId("synthesis_agent", key="default")
        )

        print(f"\n结果:")
        print(f"  是否相关: {result2.is_related}")
        print(f"  相关性类型: {result2.relation_type}")
        print(f"  理由: {result2.reason}")

        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)

        # 停止运行时
        await runtime.stop()

    asyncio.run(test())
