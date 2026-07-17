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
from ..llm.prompting import build_json_system_prompt


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


_SYSTEM_MESSAGE = build_json_system_prompt(
    role="你是代码习语识别专家，负责综合已有评估作出一致判定。",
    goal="判断输入代码是否构成可识别、可复用并符合常见实践的代码习语。",
    success_criteria=(
        "综合语义清晰度、语法与逻辑清晰度，以及输入代码体现的通用模式。",
        "严格按分数判定：较高分不低于 70 且较低分不低于 50 时 is_idiom 为 true，否则为 false。",
        "confidence 反映证据强度和两项评分的一致程度，范围为 0–100。",
        "characteristics 只列出能够由代码或上游评估直接支持的习语特征。",
    ),
    constraints=(
        "不得仅因代码简短、可运行或风格整洁就认定为代码习语。",
        "不得声称某模式被广泛使用，除非输入本身足以支持该结论。",
    ),
    field_rules=("reason 和 characteristics 使用中文。",),
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_idiom": {"type": "boolean", "description": "是否为代码习语"},
        "confidence": {"type": "number", "description": "0 到 100 的置信度"},
        "reason": {"type": "string", "description": "综合判定理由"},
        "characteristics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "识别出的习语特征",
        },
    },
    "required": ["is_idiom", "confidence", "reason", "characteristics"],
    "additionalProperties": False,
}


class IdiomJudgeAgent(JsonLLMAgent):
    """综合语义和逻辑两个维度的评估结果，判定是否为代码习语。"""

    def __init__(self, model_client: OpenAIChatCompletionClient):
        super().__init__(
            "IdiomJudgeAgent", _SYSTEM_MESSAGE, model_client, _RESPONSE_SCHEMA
        )

    @message_handler
    async def handle_request(
        self, message: IdiomJudgeRequest, ctx: MessageContext
    ) -> IdiomJudgeResult:
        prompt = f"""请综合以下评估结果，判断代码片段是否构成代码习语。

## 代码片段
```cpp
{message.code_snippet}
```

## 语义清晰度评估
- 是否清晰：{message.semantic_is_clear}
- 评分：{message.semantic_score}
- 理由：{message.semantic_reason}
- 建议：{message.semantic_suggestions}

## 语法与逻辑清晰度评估
- 是否清晰：{message.syntax_is_clear}
- 评分：{message.syntax_score}
- 理由：{message.syntax_reason}
- 问题：{message.syntax_issues}"""

        data = await self.ask_json(prompt)
        if data is None:
            return IdiomJudgeResult(
                is_idiom=False, confidence=0, reason="响应解析失败", characteristics=[]
            )
        return IdiomJudgeResult(
            is_idiom=data.get("is_idiom", False),
            confidence=float(data.get("confidence", 0)),
            reason=data.get("reason", ""),
            characteristics=data.get("characteristics", []),
        )


# 模块运行命令（从项目根目录运行）：
# 运行示例：python -m src.agents.idiom_judge_agent

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
                semantic_reason="函数命名清楚，参数和返回值意图明确",
                semantic_suggestions=[],
                syntax_is_clear=True,
                syntax_score=85,
                syntax_reason="逻辑直接，并正确处理边界情况",
                syntax_issues=[],
            ),
        ],
    )
