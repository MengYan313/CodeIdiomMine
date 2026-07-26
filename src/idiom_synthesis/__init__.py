"""习语合成：多习语关系分析、上下文补充、规划组装与复审。"""

from .pipeline import (
    IdiomSynthesisPipeline,
    build_synthesis_scorecard,
    decide_synthesis_status,
)
from .schema import SynthesisResult, IdiomCandidate
from .sources import group_related_idioms, load_idiom_candidates

__all__ = [
    "SynthesisResult",
    "IdiomCandidate",
    "IdiomSynthesisPipeline",
    "build_synthesis_scorecard",
    "decide_synthesis_status",
    "group_related_idioms",
    "load_idiom_candidates",
]
