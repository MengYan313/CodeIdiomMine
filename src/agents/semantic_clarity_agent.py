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
from ..llm.prompting import build_json_system_prompt

_SYSTEM_MESSAGE = build_json_system_prompt(
    role="你是熟悉 C++ 与常见工程惯例的代码审查专家。",
    goal="仅根据输入代码，评估其语义清晰度。",
    success_criteria=(
        "分别评估命名质量、意图清晰度和无需额外上下文时的可理解性。",
        "score 使用 0–100：90–100 非常清晰，70–89 总体清晰，50–69 一般，30–49 不清晰，0–29 难以理解。",
        "is_clear 与评分一致：score 不低于 70 时为 true，否则为 false。",
        "reason 指向输入中的具体证据；suggestions 只包含能够提升清晰度的可执行建议。",
    ),
    constraints=(
        "不要根据片段外的实现、调用方或业务背景作无依据推断。",
        "不要把个人风格偏好当作语义缺陷。",
    ),
    field_rules=("reason 和 suggestions 使用中文。",),
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_clear": {"type": "boolean", "description": "语义是否清晰"},
        "score": {"type": "number", "description": "0 到 100 的评分"},
        "reason": {"type": "string", "description": "评分理由"},
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "改进建议",
        },
    },
    "required": ["is_clear", "score", "reason", "suggestions"],
    "additionalProperties": False,
}


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
        super().__init__(
            "SemanticClarityAgent", _SYSTEM_MESSAGE, model_client, _RESPONSE_SCHEMA
        )

    @message_handler
    async def handle_request(
        self, message: SemanticClarityRequest, ctx: MessageContext
    ) -> SemanticClarityResult:
        prompt = f"""请评估以下代码片段的语义清晰度：

```cpp
{message.code_snippet}
```"""

        data = await self.ask_json(prompt)
        if data is None:
            return SemanticClarityResult(
                is_clear=False, score=0, reason="响应解析失败", suggestions=[]
            )
        return SemanticClarityResult(
            is_clear=data.get("is_clear", False),
            score=float(data.get("score", 0)),
            reason=data.get("reason", ""),
            suggestions=data.get("suggestions", []),
        )


# 模块运行命令（从项目根目录运行）：
# 运行示例：python -m src.agents.semantic_clarity_agent

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
