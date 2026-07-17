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
from ..llm.prompting import build_json_system_prompt

_SYSTEM_MESSAGE = build_json_system_prompt(
    role="你是熟悉 C++ 语法、控制流和工程实践的代码分析专家。",
    goal="仅根据输入代码，评估其语法与逻辑清晰度。",
    success_criteria=(
        "检查语法正确性、执行流程、逻辑正确性、控制流和输入中可见的边界处理。",
        "score 使用 0–100：90–100 非常清晰，70–89 总体清晰，50–69 一般，30–49 不清晰，0–29 存在严重问题。",
        "is_clear 与评分一致：score 不低于 70 时为 true，否则为 false。",
        "reason 概括主要依据；issues 只列出输入中能够定位的具体问题。",
    ),
    constraints=(
        "不要假设片段外存在未展示的校验、异常处理或状态初始化。",
        "不要把单纯的格式或命名偏好重复计入逻辑问题。",
    ),
    field_rules=("reason 和 issues 使用中文。",),
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_clear": {"type": "boolean", "description": "语法与逻辑是否清晰"},
        "score": {"type": "number", "description": "0 到 100 的评分"},
        "reason": {"type": "string", "description": "评分理由"},
        "issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "发现的问题",
        },
    },
    "required": ["is_clear", "score", "reason", "issues"],
    "additionalProperties": False,
}


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
        super().__init__(
            "SyntaxLogicAgent", _SYSTEM_MESSAGE, model_client, _RESPONSE_SCHEMA
        )

    @message_handler
    async def handle_request(
        self, message: SyntaxLogicRequest, ctx: MessageContext
    ) -> SyntaxLogicResult:
        prompt = f"""请评估以下代码片段的语法与逻辑清晰度：

```cpp
{message.code_snippet}
```"""

        data = await self.ask_json(prompt)
        if data is None:
            return SyntaxLogicResult(
                is_clear=False, score=0, reason="响应解析失败", issues=[]
            )
        return SyntaxLogicResult(
            is_clear=data.get("is_clear", False),
            score=float(data.get("score", 0)),
            reason=data.get("reason", ""),
            issues=data.get("issues", []),
        )


# 模块运行命令（从项目根目录运行）：
# 运行示例：python -m src.agents.syntax_logic_agent

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
