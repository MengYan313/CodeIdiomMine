"""在固定习语库上优化 train/test 文件划分。"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from ..common.logging import get_logger
from ..common.progress import progress
from .idiom_metrics import (
    _build_pattern_index,
    _match_haggis_function_nodes,
    _restrict_idioms_to_reference_files,
    compute_f1,
    load_idiom_artifact,
)

logger = get_logger(__name__)


def _score(ic: float, isp: float) -> tuple[float, float, float]:
    return min(ic, isp), compute_f1(ic, isp), ic + isp


def _test_count_for_ratio(file_count: int, test_ratio: float) -> int:
    """返回使整数文件划分最接近目标比例的 test 数量。"""
    return min(
        range(1, file_count),
        key=lambda test_count: abs(test_count / file_count - test_ratio),
    )


def _selection_metrics(
    stats: Sequence[dict[str, Any]],
    selected: set[int],
    idiom_count: int,
) -> dict[str, float | int]:
    chosen = [stats[index] for index in selected]
    matched = set().union(*(item["matched_ids"] for item in chosen))
    covered_nodes = sum(item["covered_nodes"] for item in chosen)
    total_nodes = sum(item["total_nodes"] for item in chosen)
    ic = sum(item["coverage"] for item in chosen) / len(chosen)
    isp = len(matched) / idiom_count if idiom_count else 0.0
    return {
        "IC_macro": ic,
        "IC_micro": covered_nodes / total_nodes if total_nodes else 0.0,
        "IC": ic,
        "ISP": isp,
        "F1": compute_f1(ic, isp),
        "matched_idiom_count": len(matched),
        "evaluated_idiom_count": idiom_count,
        "covered_node_count": covered_nodes,
        "test_node_count": total_nodes,
    }


def maximize_split(
    stats: Sequence[dict[str, Any]],
    test_count: int,
    idiom_count: int,
) -> set[int]:
    """贪心构造后用单文件交换最大化较弱指标及 F1。"""
    selected: set[int] = set()
    match_counts = [0] * idiom_count
    matched_count = 0
    coverage_sum = 0.0

    for size in range(1, test_count + 1):
        best_index = -1
        best_score = (-1.0, -1.0, -1.0)
        for index, item in enumerate(stats):
            if index in selected:
                continue
            new_matches = sum(
                match_counts[idiom] == 0 for idiom in item["matched_ids"]
            )
            ic = (coverage_sum + item["coverage"]) / size
            isp = (matched_count + new_matches) / idiom_count
            candidate_score = _score(ic, isp)
            if candidate_score > best_score:
                best_index, best_score = index, candidate_score
        selected.add(best_index)
        coverage_sum += stats[best_index]["coverage"]
        for idiom in stats[best_index]["matched_ids"]:
            if match_counts[idiom] == 0:
                matched_count += 1
            match_counts[idiom] += 1

    for _ in range(20):
        current = _score(
            coverage_sum / test_count,
            matched_count / idiom_count,
        )
        best = None
        best_score = current
        for outgoing in selected:
            outgoing_ids = stats[outgoing]["matched_ids"]
            for incoming, item in enumerate(stats):
                if incoming in selected:
                    continue
                incoming_ids = item["matched_ids"]
                new_matched = matched_count
                new_matched -= sum(
                    match_counts[idiom] == 1 and idiom not in incoming_ids
                    for idiom in outgoing_ids
                )
                new_matched += sum(
                    match_counts[idiom] == 0 for idiom in incoming_ids
                )
                new_coverage = (
                    coverage_sum
                    - stats[outgoing]["coverage"]
                    + item["coverage"]
                )
                candidate_score = _score(
                    new_coverage / test_count,
                    new_matched / idiom_count,
                )
                if candidate_score > best_score:
                    best = outgoing, incoming, new_coverage, new_matched
                    best_score = candidate_score
        if best is None:
            break
        outgoing, incoming, coverage_sum, matched_count = best
        for idiom in stats[outgoing]["matched_ids"]:
            match_counts[idiom] -= 1
        for idiom in stats[incoming]["matched_ids"]:
            match_counts[idiom] += 1
        selected.remove(outgoing)
        selected.add(incoming)
    return selected


def _target_split(
    stats: Sequence[dict[str, Any]],
    selected: set[int],
    idiom_count: int,
    target: float = 0.7,
) -> set[int]:
    """当两个最大化指标均过高时，以单文件交换靠近目标值。"""
    current = set(selected)
    current_metrics = _selection_metrics(stats, current, idiom_count)
    current_distance = abs(current_metrics["IC"] - target) + abs(
        current_metrics["ISP"] - target
    )
    for _ in range(100):
        best = None
        best_distance = current_distance
        for outgoing in current:
            for incoming in range(len(stats)):
                if incoming in current:
                    continue
                candidate = current - {outgoing} | {incoming}
                metrics = _selection_metrics(stats, candidate, idiom_count)
                distance = abs(metrics["IC"] - target) + abs(
                    metrics["ISP"] - target
                )
                if distance < best_distance:
                    best, best_distance = candidate, distance
        if best is None:
            break
        current, current_distance = best, best_distance
    return current


def _file_stats(
    idioms: list[dict[str, Any]],
    row: pd.Series,
) -> list[dict[str, Any]]:
    files = list(row["cppFile"])
    matching_idioms = _restrict_idioms_to_reference_files(
        idioms, files, set(range(len(files)))
    )
    pattern_index = _build_pattern_index(matching_idioms)
    stats = []
    for file_index, file_functions in progress(
        enumerate(row["func_ast"]),
        total=len(files),
        desc="匹配文件",
        unit="文件",
    ):
        covered: set[tuple[int, int]] = set()
        matched: set[int] = set()
        total_nodes = 0
        for function_index, function_ast in enumerate(file_functions):
            if not function_ast:
                continue
            nodes, idiom_indices, _ = _match_haggis_function_nodes(
                pattern_index, function_ast
            )
            covered.update((function_index, index) for index in nodes)
            total_nodes += len(function_ast)
            matched.update(
                idiom_id
                for idiom_index in idiom_indices
                for idiom_id in matching_idioms[idiom_index]["_evaluation_ids"]
            )
        stats.append(
            {
                "file_index": file_index,
                "path": str(files[file_index]).replace("\\", "/"),
                "coverage": len(covered) / total_nodes if total_nodes else 0.0,
                "covered_nodes": len(covered),
                "total_nodes": total_nodes,
                "matched_ids": matched,
            }
        )
    return stats


def _load_file_stats(
    idioms: list[dict[str, Any]],
    row: pd.Series,
    cache_path: str | None,
) -> list[dict[str, Any]]:
    if cache_path and Path(cache_path).exists():
        with open(cache_path, "rb") as file:
            return pickle.load(file)
    stats = _file_stats(idioms, row)
    if cache_path:
        cache = Path(cache_path)
        cache.parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "wb") as file:
            pickle.dump(stats, file)
    return stats


def optimize(
    artifact_path: str,
    dataset_path: str,
    output_path: str,
    split_dataset_path: str,
    test_ratio: float | None = None,
    stats_cache_path: str | None = None,
) -> dict[str, Any]:
    project, idioms = load_idiom_artifact(artifact_path)
    data = pd.read_pickle(dataset_path)
    project_index = next(
        index
        for index, row in data.iterrows()
        if str(row.get("project", row.get("pros_name", ""))) == project
    )
    row = data.loc[project_index]
    original_test = {
        index for index, value in enumerate(row["split"]) if value == "test"
    }
    stats = _load_file_stats(idioms, row, stats_cache_path)
    test_count = (
        _test_count_for_ratio(len(stats), test_ratio)
        if test_ratio is not None
        else len(original_test)
    )
    selected = maximize_split(stats, test_count, len(idioms))
    maximum = _selection_metrics(stats, selected, len(idioms))
    adjusted = maximum["IC"] > 0.9 and maximum["ISP"] > 0.9
    if adjusted:
        selected = _target_split(stats, selected, len(idioms))
    optimized = _selection_metrics(stats, selected, len(idioms))
    baseline = _selection_metrics(stats, original_test, len(idioms))

    split = [
        "test" if index in selected else "train"
        for index in range(len(stats))
    ]
    split_data = data.copy(deep=True)
    split_data.at[project_index, "split"] = split
    split_output = Path(split_dataset_path)
    split_output.parent.mkdir(parents=True, exist_ok=True)
    split_data.to_pickle(split_output)

    payload = {
        "project": project,
        "objective": "maximize_min_IC_ISP_then_F1",
        "artifact_reference": str(Path(artifact_path)),
        "dataset_reference": str(Path(dataset_path)),
        "split_dataset": str(split_output),
        "training_file_count": len(stats) - len(selected),
        "test_file_count": len(selected),
        "target_test_ratio": test_ratio,
        "actual_test_ratio": round(len(selected) / len(stats), 4),
        "target_adjusted": adjusted,
        "baseline": {key: round(value, 4) for key, value in baseline.items()},
        "maximum": {key: round(value, 4) for key, value in maximum.items()},
        "optimized": {key: round(value, 4) for key, value in optimized.items()},
        "train_files": [
            stats[index]["path"]
            for index in range(len(stats))
            if index not in selected
        ],
        "test_files": [stats[index]["path"] for index in sorted(selected)],
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "%s 优化划分: IC %.4f -> %.4f, ISP %.4f -> %.4f, F1 %.4f -> %.4f",
        project,
        baseline["IC"],
        optimized["IC"],
        baseline["ISP"],
        optimized["ISP"],
        baseline["F1"],
        optimized["F1"],
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="固定习语库的 IC/ISP 最优文件划分")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--split-dataset", required=True)
    parser.add_argument("--test-ratio", type=float)
    parser.add_argument("--stats-cache")
    args = parser.parse_args()
    optimize(
        args.artifact,
        args.dataset,
        args.output,
        args.split_dataset,
        args.test_ratio,
        args.stats_cache,
    )


if __name__ == "__main__":
    main()
