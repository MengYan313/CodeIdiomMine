"""
语义清晰度判定 Agent

负责判定输入的代码片段是否语义清晰。
判定标准：
1. 变量和函数命名是否有意义
2. 代码意图是否明确
3. 是否容易理解其功能
"""

from dataclasses import dataclass
from typing import List

from autogen_core import MessageContext, message_handler
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ._base import JsonLLMAgent

_SYSTEM_MESSAGE = """You are a professional code review expert specializing in evaluating code semantic clarity.

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


class SemanticClarityAgent(JsonLLMAgent):
    """使用 LLM 评估代码片段的语义清晰度。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__("SemanticClarityAgent", _SYSTEM_MESSAGE, model_client)

    @message_handler
    async def handle_request(
        self, message: SemanticClarityRequest, ctx: MessageContext
    ) -> SemanticClarityResult:
        prompt = f"""Please evaluate the semantic clarity of the following code snippet:

[Code Idiom]
{message.code_snippet}
[/Code Idiom]

Please return the evaluation result in the specified format with [JSON] tags."""

        data = await self.ask_json(prompt)
        if data is None:
            return SemanticClarityResult(
                is_clear=False, score=0, reason="Failed to parse response", suggestions=[]
            )
        return SemanticClarityResult(
            is_clear=data.get("is_clear", False),
            score=float(data.get("score", 0)),
            reason=data.get("reason", ""),
            suggestions=data.get("suggestions", []),
        )


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.semantic_clarity_agent

if __name__ == "__main__":
    from ._base import run_agent_selftest

    run_agent_selftest(
        title="测试语义清晰度判定 Agent",
        agent_name="semantic_agent",
        agent_factory=SemanticClarityAgent,
        requests=[
            SemanticClarityRequest(code_snippet="""
def calculate_average(numbers):
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)
"""),
            SemanticClarityRequest(code_snippet="""
def f(x):
    a = []
    for i in x:
        if i % 2 == 0:
            a.append(i)
    return a
"""),
        ],
    )
