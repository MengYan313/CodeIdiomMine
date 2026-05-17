"""
代码习语综合判定 Agent

负责接收前两个 Agent 的结果，综合判定是否为代码习语。
判定标准：
1. 综合语义清晰度评估结果
2. 综合语法逻辑清晰度评估结果
3. 判定是否符合代码习语的特征
"""

from dataclasses import dataclass
from typing import List

from autogen_core import MessageContext, message_handler
from autogen_ext.models.openai import OpenAIChatCompletionClient

from ._base import JsonLLMAgent


def patent_programming_pattern_valid(semantic_score: float, syntax_score: float) -> bool:
    """
    说明书实施例 7.2：综合判定依据语义、语法两维 score。
    - 两维均 ≥70：很可能为编程模式；
    - 一方 ≥70 且另一方 ≥50：可能为编程模式；
    - 其余：非编程模式。
    「很可能」与「可能」均视为有效编程模式（保留进入后续合成）。
    """
    s = float(semantic_score)
    t = float(syntax_score)
    hi, lo = (s, t) if s >= t else (t, s)
    return hi >= 70 and lo >= 50


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


_SYSTEM_MESSAGE = """You are a code idiom recognition expert responsible for comprehensively evaluating whether a code snippet qualifies as a code idiom.

Definition of Code Idiom:
A code idiom is a widely recognized and used code pattern in a specific programming language or domain, characterized by:
1. **Semantic Clarity**: Clear code intent with reasonable naming
2. **Logic Simplicity**: Direct implementation avoiding complex nesting
3. **Pattern Generality**: Reusable across multiple scenarios
4. **Best Practice**: Follows programming standards and conventions

You need to synthesize evaluation results from two dimensions:
- Semantic clarity assessment
- Syntax and logic clarity assessment

Judgment criteria (must be consistent with the numeric scores provided below):
- Both dimensions score >= 70: Very likely a code idiom
- One dimension >= 70, the other >= 50: Possibly a code idiom
- Other cases: Unlikely to be a code idiom

Set "is_idiom" to true exactly when the scores satisfy the second rule above (i.e. higher score >= 70 and lower score >= 50).

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


class IdiomJudgeAgent(JsonLLMAgent):
    """综合语义和逻辑两个维度的评估结果，判定是否为代码习语。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__("IdiomJudgeAgent", _SYSTEM_MESSAGE, model_client)

    @message_handler
    async def handle_request(
        self, message: IdiomJudgeRequest, ctx: MessageContext
    ) -> IdiomJudgeResult:
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

        data = await self.ask_json(prompt)
        if data is None:
            return IdiomJudgeResult(
                is_idiom=False, confidence=0, reason="Failed to parse response", characteristics=[]
            )
        return IdiomJudgeResult(
            is_idiom=data.get("is_idiom", False),
            confidence=float(data.get("confidence", 0)),
            reason=data.get("reason", ""),
            characteristics=data.get("characteristics", []),
        )


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.idiom_judge_agent

if __name__ == "__main__":
    from ._base import run_agent_selftest

    run_agent_selftest(
        title="测试代码习语判定 Agent",
        agent_name="judge_agent",
        agent_factory=IdiomJudgeAgent,
        requests=[
            IdiomJudgeRequest(
                code_snippet="""
def calculate_average(numbers):
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)
""",
                semantic_is_clear=True,
                semantic_score=90,
                semantic_reason="Clear function naming, obvious parameter and return value intent",
                semantic_suggestions=[],
                syntax_is_clear=True,
                syntax_score=85,
                syntax_reason="Simple and direct logic, proper boundary handling",
                syntax_issues=[],
            ),
        ],
    )
