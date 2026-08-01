"""Parser 阶段使用的 embedding token 预算、校验与追溯元数据。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence


def resolve_max_input_tokens(
    configured_limit: int,
    requested_limit: Optional[int],
) -> int:
    """只允许调用方收紧已验证的模型输入上限。"""
    if configured_limit < 1:
        raise ValueError("模型配置的 token 上限必须大于等于 1")
    if requested_limit is None:
        return configured_limit
    if requested_limit < 1:
        raise ValueError("max_input_tokens 必须大于等于 1")
    if requested_limit > configured_limit:
        raise ValueError(
            "max_input_tokens 只能收紧模型上限："
            f"请求 {requested_limit}，模型配置上限 {configured_limit}"
        )
    return requested_limit


def count_tokenized_inputs(
    tokenizer: Any,
    snippets: Sequence[str],
    *,
    batch_size: int = 256,
) -> List[int]:
    """按实际 tokenizer 统计包含特殊 token 的最终输入长度。"""
    if batch_size < 1:
        raise ValueError("batch_size 必须大于等于 1")
    counts: List[int] = []
    for start in range(0, len(snippets), batch_size):
        batch = list(snippets[start : start + batch_size])
        encoded = tokenizer(
            batch,
            add_special_tokens=True,
            truncation=False,
            padding=False,
        )
        input_ids = encoded["input_ids"]
        counts.extend(len(value) for value in input_ids)
    return counts


@dataclass(frozen=True)
class TokenBudget:
    """把模型名、有效上限和 tokenizer 绑定为 Parser 长度控制器。"""

    tokenizer: Any
    model_name: str
    max_input_tokens: int

    def count(self, snippet: str) -> int:
        return count_tokenized_inputs(self.tokenizer, [snippet], batch_size=1)[0]

    def counts(
        self,
        snippets: Sequence[str],
        *,
        batch_size: int = 256,
    ) -> List[int]:
        return count_tokenized_inputs(
            self.tokenizer,
            snippets,
            batch_size=batch_size,
        )

    def fits(self, snippet_or_node: str | Mapping[str, Any]) -> bool:
        if isinstance(snippet_or_node, str):
            snippet = snippet_or_node
        else:
            snippet = str(snippet_or_node.get("code_snippet") or "")
        return bool(snippet) and self.count(snippet) <= self.max_input_tokens

    def validate(self, snippets: Sequence[str]) -> List[int]:
        counts = self.counts(snippets)
        violations = [
            (index, count)
            for index, count in enumerate(counts)
            if count > self.max_input_tokens
        ]
        if violations:
            preview = ", ".join(
                f"#{index}={count}" for index, count in violations[:5]
            )
            raise ValueError(
                "检测到超出 embedding token 预算的输入，拒绝静默截断："
                f"上限={self.max_input_tokens}，超限={len(violations)}，"
                f"示例={preview}"
            )
        return counts

    def metadata(
        self,
        *,
        token_count: int,
        strategy: str,
        degraded_from: Optional[str] = None,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {
            "decision_stage": "parser",
            "model_name": self.model_name,
            "token_budget": self.max_input_tokens,
            "token_count": token_count,
            "within_budget": token_count <= self.max_input_tokens,
            "strategy": strategy,
        }
        if degraded_from is not None:
            value["degraded_from"] = degraded_from
        return value
