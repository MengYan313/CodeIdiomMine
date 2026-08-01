"""审计 Parser 候选在 embedding tokenizer 下的长度与降级结果。"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import pandas as pd
from transformers import AutoTokenizer

from ..common.logging import get_logger
from .candidates import SelectedCandidate, select_candidates
from .fragment_builder import (
    potential_candidate_snippets,
    resolve_model_input,
)
from .token_budget import TokenBudget


logger = get_logger(__name__)
def _percentile(sorted_values: Sequence[int], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    return (
        sorted_values[lower] * (upper - position)
        + sorted_values[upper] * (position - lower)
    )


def summarize_token_lengths(
    values: Sequence[int],
    *,
    token_budget: int,
) -> Dict[str, Any]:
    """生成稳定的 token 长度分布，供脚本和离线测试共同使用。"""
    ordered = sorted(values)
    over_limit = sum(value > token_budget for value in ordered)
    return {
        "count": len(ordered),
        "min": ordered[0] if ordered else 0,
        "p50": _percentile(ordered, 0.50),
        "p75": _percentile(ordered, 0.75),
        "p90": _percentile(ordered, 0.90),
        "p95": _percentile(ordered, 0.95),
        "p99": _percentile(ordered, 0.99),
        "max": ordered[-1] if ordered else 0,
        "over_budget_count": over_limit,
        "over_budget_rate": over_limit / len(ordered) if ordered else 0.0,
    }


def _candidate_type(candidate: SelectedCandidate) -> str:
    if candidate.origin == "semantic_def_use":
        return "semantic_def_use"
    return candidate.level


def _iter_functions(
    data: pd.DataFrame,
) -> Iterable[Tuple[str, str, Sequence[Mapping[str, Any]]]]:
    for row_index in range(len(data)):
        project = str(data.iloc[row_index]["project"])
        files = data.iloc[row_index]["cppFile"]
        asts = data.iloc[row_index]["func_ast"]
        for file_name, file_data in zip(files, asts):
            for function_ast in file_data:
                yield project, str(file_name), function_ast


def _candidate_key(
    file_name: str,
    candidate: SelectedCandidate,
) -> Tuple[str, str, str, str]:
    node = candidate.node_info
    return (
        str(node.get("source_file_id") or file_name),
        str(node.get("extent") or ""),
        candidate.level,
        candidate.origin,
    )


def build_token_length_report(
    *,
    data: pd.DataFrame,
    dataset_path: Path,
    token_budget: TokenBudget,
    min_nodes: int = 10,
    min_ast_num: int = 5,
    max_regions_per_function: int = 2,
    max_statements_per_function: int = 2,
) -> Dict[str, Any]:
    """比较原始候选和执行 token 降级后的 model-ready 候选。"""
    potential = potential_candidate_snippets(data)
    logger.info("批量统计 %s 个唯一候选文本的 token 长度", len(potential))
    counts = token_budget.counts(potential)
    count_by_text = dict(zip(potential, counts))

    def token_count(node: Mapping[str, Any]) -> int:
        return count_by_text[str(node.get("code_snippet") or "")]

    def fits(node: Mapping[str, Any]) -> bool:
        code = str(node.get("code_snippet") or "")
        return bool(code) and count_by_text[code] <= token_budget.max_input_tokens

    raw_lengths: Dict[str, list[int]] = {
        "function": [],
        "region": [],
        "statement": [],
        "semantic_def_use": [],
    }
    ready_lengths: Dict[str, list[int]] = {
        key: [] for key in raw_lengths
    }
    raw_seen: Dict[str, set[Tuple[str, str, str, str]]] = {}
    ready_seen: Dict[str, set[Tuple[str, str, str, str]]] = {}
    degradation: Counter[str] = Counter()

    for project, file_name, function_ast in _iter_functions(data):
        raw_candidates = select_candidates(
            function_ast,
            min_nodes=min_nodes,
            min_ast_num=min_ast_num,
            max_regions_per_function=max_regions_per_function,
            max_statements_per_function=max_statements_per_function,
        )
        ready_candidates = select_candidates(
            function_ast,
            min_nodes=min_nodes,
            min_ast_num=min_ast_num,
            max_regions_per_function=max_regions_per_function,
            max_statements_per_function=max_statements_per_function,
            candidate_filter=fits,
        )
        project_raw_seen = raw_seen.setdefault(project, set())
        project_ready_seen = ready_seen.setdefault(project, set())
        for candidate in raw_candidates:
            key = _candidate_key(file_name, candidate)
            if key not in project_raw_seen:
                project_raw_seen.add(key)
                raw_lengths[_candidate_type(candidate)].append(
                    token_count(candidate.node_info)
                )
        for candidate in ready_candidates:
            key = _candidate_key(file_name, candidate)
            if key not in project_ready_seen:
                project_ready_seen.add(key)
                ready_lengths[_candidate_type(candidate)].append(
                    token_count(candidate.node_info)
                )

        root_code = (
            str(function_ast[0].get("code_snippet") or "")
            if function_ast
            else ""
        )
        root_over = bool(
            root_code
            and count_by_text[root_code] > token_budget.max_input_tokens
        )
        if not root_over:
            continue
        degradation["over_budget_function_count"] += 1
        fallbacks = [
            candidate
            for candidate in ready_candidates
            if candidate.level != "function"
        ]
        if fallbacks:
            degradation["function_with_fallback_count"] += 1
        else:
            degradation["function_without_fallback_count"] += 1
        for candidate in fallbacks:
            degradation[
                f"fallback_{_candidate_type(candidate)}_count"
            ] += 1

    raw_summary = {
        key: summarize_token_lengths(
            values,
            token_budget=token_budget.max_input_tokens,
        )
        for key, values in raw_lengths.items()
    }
    ready_summary = {
        key: summarize_token_lengths(
            values,
            token_budget=token_budget.max_input_tokens,
        )
        for key, values in ready_lengths.items()
    }
    raw_total = [value for values in raw_lengths.values() for value in values]
    ready_total = [
        value for values in ready_lengths.values() for value in values
    ]
    raw_summary["total"] = summarize_token_lengths(
        raw_total,
        token_budget=token_budget.max_input_tokens,
    )
    ready_summary["total"] = summarize_token_lengths(
        ready_total,
        token_budget=token_budget.max_input_tokens,
    )
    return {
        "dataset": {
            "path": dataset_path.as_posix(),
        },
        "model": {
            "name": token_budget.model_name,
            "max_input_tokens": token_budget.max_input_tokens,
            "length_includes_special_tokens": True,
            "silent_truncation_allowed": False,
        },
        "raw_candidates": raw_summary,
        "model_ready_candidates": ready_summary,
        "degradation": dict(sorted(degradation.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="审计 Parser 候选的 embedding token 长度与降级结果"
    )
    parser.add_argument("--dataset", required=True, help="Parser dataset.pkl")
    parser.add_argument("--output", required=True, help="输出 JSON 报告")
    parser.add_argument(
        "--model",
        default="unixcoder",
        help="模型简称或 Hugging Face 模型名（默认: unixcoder）",
    )
    parser.add_argument(
        "--max-input-tokens",
        type=int,
        default=None,
        help="可选的更严格总 token 上限",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="只使用本地模型缓存，禁止下载",
    )
    args = parser.parse_args()

    model_name, effective_limit = resolve_model_input(
        args.model,
        args.max_input_tokens,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=False,
        local_files_only=args.local_files_only,
    )
    budget = TokenBudget(tokenizer, model_name, effective_limit)
    dataset_path = Path(args.dataset)
    report = build_token_length_report(
        data=pd.read_pickle(dataset_path),
        dataset_path=dataset_path,
        token_budget=budget,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("token 长度审计已写入: %s", output_path)


if __name__ == "__main__":
    main()
