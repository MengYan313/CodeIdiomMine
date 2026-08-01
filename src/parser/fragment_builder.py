"""在 Parser 阶段把 AST 候选编译为满足模型长度合同的原始代码片段。"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import pandas as pd
from transformers import AutoTokenizer

from ..common.logging import get_logger
from ..common.node_kinds import BLOCK_KINDS, FUNCTION_KINDS, STATEMENT_KINDS
from .candidates import SelectedCandidate, select_candidates
from .cpp_adapter import CPP_ADAPTER
from .token_budget import TokenBudget, resolve_max_input_tokens


logger = get_logger(__name__)
MODEL_INPUT_CONFIGS = {
    "codellama": {
        "name": "codellama/CodeLlama-7b-hf",
        "max_length": 2048,
        "description": "CodeLLaMA 7B - 大型代码语言模型",
    },
    "unixcoder": {
        "name": "microsoft/unixcoder-base",
        "max_length": 512,
        "description": "UniXcoder - 轻量级代码预训练模型",
    },
    "codebert": {
        "name": "microsoft/codebert-base",
        "max_length": 512,
        "description": "CodeBERT - 基础代码预训练模型",
    },
}


def resolve_model_input(
    model: str,
    max_input_tokens: Optional[int] = None,
) -> Tuple[str, int]:
    if model in MODEL_INPUT_CONFIGS:
        config = MODEL_INPUT_CONFIGS[model]
        model_name = str(config["name"])
        configured_limit = int(config["max_length"])
    else:
        model_name = model
        configured_limit = 512
    return model_name, resolve_max_input_tokens(
        configured_limit,
        max_input_tokens,
    )


def load_token_budget(
    model: str = "unixcoder",
    *,
    max_input_tokens: Optional[int] = None,
    local_files_only: bool = False,
) -> TokenBudget:
    """只加载 tokenizer；Parser 阶段不加载或执行 embedding 模型。"""
    model_name, effective_limit = resolve_model_input(
        model,
        max_input_tokens,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=False,
        local_files_only=local_files_only,
    )
    return TokenBudget(tokenizer, model_name, effective_limit)


def _candidate_type(candidate: SelectedCandidate) -> str:
    if candidate.origin == "semantic_def_use":
        return "semantic_def_use"
    return candidate.level


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


def _iter_functions(
    data: pd.DataFrame,
) -> Iterable[
    Tuple[int, str, str, Sequence[Mapping[str, Any]]]
]:
    for row_index in range(len(data)):
        project = str(data.iloc[row_index]["project"])
        files = data.iloc[row_index]["cppFile"]
        asts = data.iloc[row_index]["func_ast"]
        for file_name, file_data in zip(files, asts):
            for function_ast in file_data:
                yield row_index, project, str(file_name), function_ast


def potential_candidate_snippets(data: pd.DataFrame) -> list[str]:
    """预收集候选过滤器会检查的节点，避免逐片段调用 tokenizer。"""
    snippets: set[str] = set()
    for _, _, _, function_ast in _iter_functions(data):
        for index, node in enumerate(function_ast):
            kind = str(node.get("kind") or "")
            if (
                index == 0
                or kind in CPP_ADAPTER.quality_region_kinds
                or kind in CPP_ADAPTER.quality_statement_kinds
                or CPP_ADAPTER.is_function_body(kind)
                or kind in FUNCTION_KINDS
                or kind in BLOCK_KINDS
                or kind in STATEMENT_KINDS
            ):
                code = str(node.get("code_snippet") or "")
                if code:
                    snippets.add(code)
        if function_ast:
            for semantic_slice in function_ast[0].get("semantic_slices") or []:
                if isinstance(semantic_slice, Mapping):
                    code = str(semantic_slice.get("code_snippet") or "")
                    if code:
                        snippets.add(code)
    return sorted(snippets)


def prepare_fragment_data(
    data: pd.DataFrame,
    token_budget: TokenBudget,
    *,
    min_nodes: int = 10,
    min_ast_num: int = 5,
    max_regions_per_function: int = 2,
    max_statements_per_function: int = 2,
) -> pd.DataFrame:
    """生成 model-ready 片段；所有长度决策均在 Parser 阶段完成。"""
    potential = potential_candidate_snippets(data)
    logger.info("Parser 批量统计 %s 个唯一候选文本", len(potential))
    count_by_text = dict(zip(potential, token_budget.counts(potential)))

    def token_count(node: Mapping[str, Any]) -> int:
        return count_by_text[str(node.get("code_snippet") or "")]

    def fits(node: Mapping[str, Any]) -> bool:
        code = str(node.get("code_snippet") or "")
        return bool(code) and count_by_text[code] <= token_budget.max_input_tokens

    projects = [str(value) for value in data["project"]]
    project_sources: list[list[str]] = [[] for _ in projects]
    project_infos: list[list[list[Any]]] = [[] for _ in projects]
    project_rejections: list[list[Dict[str, Any]]] = [[] for _ in projects]
    project_stats: list[Counter[str]] = [Counter() for _ in projects]
    project_seen: list[set[Tuple[str, str, str, str]]] = [
        set() for _ in projects
    ]
    raw_seen: list[set[Tuple[str, str, str, str]]] = [
        set() for _ in projects
    ]
    rejection_seen: list[set[Tuple[str, str, str, str]]] = [
        set() for _ in projects
    ]

    for row_index, project, file_name, function_ast in _iter_functions(data):
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
        stats = project_stats[row_index]
        root_code = (
            str(function_ast[0].get("code_snippet") or "")
            if function_ast
            else ""
        )
        root_over = bool(
            root_code
            and count_by_text[root_code] > token_budget.max_input_tokens
        )
        fallback_strategies = sorted(
            {
                _candidate_type(candidate)
                for candidate in ready_candidates
                if candidate.level != "function"
            }
        )
        if root_over:
            stats["over_budget_function_record_count"] += 1
            stats[
                "function_with_fallback_count"
                if fallback_strategies
                else "function_without_fallback_count"
            ] += 1
            for strategy in fallback_strategies:
                stats[f"functions_degraded_to_{strategy}_count"] += 1

        for candidate in raw_candidates:
            candidate_type = _candidate_type(candidate)
            key = _candidate_key(file_name, candidate)
            if key in raw_seen[row_index]:
                continue
            raw_seen[row_index].add(key)
            stats[f"raw_{candidate_type}_count"] += 1
            count = token_count(candidate.node_info)
            if count <= token_budget.max_input_tokens:
                continue
            stats[f"rejected_{candidate_type}_count"] += 1
            if key in rejection_seen[row_index]:
                continue
            rejection_seen[row_index].add(key)
            node = candidate.node_info
            project_rejections[row_index].append(
                {
                    "source_path": node.get("source_path") or file_name,
                    "source_file_id": node.get("source_file_id"),
                    "function_extent": candidate.function_extent,
                    "extent": node.get("extent"),
                    "candidate_type": candidate_type,
                    "candidate_origin": candidate.origin,
                    "token_count": count,
                    "token_budget": token_budget.max_input_tokens,
                    "reason": "over_token_budget",
                    "action": (
                        "degraded"
                        if candidate.level == "function"
                        and fallback_strategies
                        else "excluded"
                    ),
                    "fallback_strategies": (
                        fallback_strategies
                        if candidate.level == "function"
                        else []
                    ),
                }
            )

        for candidate in ready_candidates:
            key = _candidate_key(file_name, candidate)
            if key in project_seen[row_index]:
                continue
            project_seen[row_index].add(key)
            node_info = dict(candidate.node_info)
            code = str(node_info.get("code_snippet") or "")
            count = count_by_text[code]
            strategy = _candidate_type(candidate)
            node_info["length_control"] = token_budget.metadata(
                token_count=count,
                strategy=strategy,
                degraded_from=(
                    "function"
                    if root_over and candidate.level != "function"
                    else None
                ),
            )
            project_sources[row_index].append(code)
            project_infos[row_index].append(
                [
                    project,
                    file_name,
                    candidate.function_extent,
                    node_info,
                ]
            )
            stats[f"model_ready_{strategy}_count"] += 1

    return pd.DataFrame(
        {
            "project": projects,
            "model_name": [token_budget.model_name for _ in projects],
            "max_input_tokens": [
                token_budget.max_input_tokens for _ in projects
            ],
            "fragment_src": project_sources,
            "fragment_info": project_infos,
            "fragment_rejections": project_rejections,
            "fragment_stats": [
                dict(sorted(value.items())) for value in project_stats
            ],
        }
    )


def build_fragment_file(
    *,
    dataset_path: str,
    output_path: str,
    model: str = "unixcoder",
    max_input_tokens: Optional[int] = None,
    local_files_only: bool = False,
) -> pd.DataFrame:
    """从四列 AST 数据集生成 Parser 片段产物。"""
    source_path = Path(dataset_path)
    budget = load_token_budget(
        model,
        max_input_tokens=max_input_tokens,
        local_files_only=local_files_only,
    )
    fragments = prepare_fragment_data(pd.read_pickle(source_path), budget)
    fragments.attrs.update(
        {
            "source_dataset_path": source_path.as_posix(),
            "decision_stage": "parser",
        }
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fragments.to_pickle(target)
    logger.info(
        "Parser model-ready 片段已保存到 %s，共 %s 条",
        target,
        sum(len(value) for value in fragments["fragment_src"]),
    )
    return fragments


def main() -> None:
    parser = argparse.ArgumentParser(
        description="在 Parser 阶段生成满足 embedding 长度合同的代码片段"
    )
    parser.add_argument("--input", required=True, help="Parser dataset.pkl")
    parser.add_argument("--output", required=True, help="输出 fragments.pkl")
    parser.add_argument("--model", default="unixcoder")
    parser.add_argument("--max-input-tokens", type=int, default=None)
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="只使用本地 tokenizer 缓存，禁止下载",
    )
    args = parser.parse_args()
    build_fragment_file(
        dataset_path=args.input,
        output_path=args.output,
        model=args.model,
        max_input_tokens=args.max_input_tokens,
        local_files_only=args.local_files_only,
    )


if __name__ == "__main__":
    main()
