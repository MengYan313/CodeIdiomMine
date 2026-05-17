"""
语法和逻辑清晰度判定 Agent

负责判定输入的代码片段是否语法和逻辑清晰。
判定标准：
1. 语法是否正确
2. 逻辑流程是否合理
3. 是否存在明显的逻辑错误或反模式
"""

from dataclasses import dataclass
from typing import List

from autogen_core import MessageContext, message_handler
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ._base import JsonLLMAgent

_SYSTEM_MESSAGE = """You are a professional code analysis expert specializing in evaluating code syntax and logic clarity.

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


class SyntaxLogicAgent(JsonLLMAgent):
    """使用 LLM 评估代码片段的语法和逻辑清晰度。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__("SyntaxLogicAgent", _SYSTEM_MESSAGE, model_client)

    @message_handler
    async def handle_request(
        self, message: SyntaxLogicRequest, ctx: MessageContext
    ) -> SyntaxLogicResult:
        prompt = f"""Please evaluate the syntax and logic clarity of the following code snippet:

[Code Idiom]
{message.code_snippet}
[/Code Idiom]

Please return the evaluation result in the specified format with [JSON] tags."""

        data = await self.ask_json(prompt)
        if data is None:
            return SyntaxLogicResult(
                is_clear=False, score=0, reason="Failed to parse response", issues=[]
            )
        return SyntaxLogicResult(
            is_clear=data.get("is_clear", False),
            score=float(data.get("score", 0)),
            reason=data.get("reason", ""),
            issues=data.get("issues", []),
        )


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.syntax_logic_agent

if __name__ == "__main__":
    from ._base import run_agent_selftest

    run_agent_selftest(
        title="测试语法和逻辑清晰度判定 Agent",
        agent_name="syntax_logic_agent",
        agent_factory=SyntaxLogicAgent,
        requests=[
            SyntaxLogicRequest(code_snippet="""
def find_max(numbers):
    if not numbers:
        return None
    max_value = numbers[0]
    for num in numbers[1:]:
        if num > max_value:
            max_value = num
    return max_value
"""),
            SyntaxLogicRequest(code_snippet="""
def divide(a, b):
    result = a / b
    return result
"""),
        ],
    )
