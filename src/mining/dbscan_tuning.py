"""对任意单仓 embedding 执行同一套 DBSCAN 无监督自动调参。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from ..common.logging import get_logger
from .cluster_result import build_cluster_dataframe, embeddings_to_numpy


logger = get_logger(__name__)

DEFAULT_EPS_VALUES = (
    0.01,
    0.025,
    0.05,
    0.10,
    0.15,
    0.175,
    0.20,
    0.25,
    0.30,
    0.35,
    0.40,
)
DEFAULT_MIN_SAMPLES_VALUES = (2, 3, 4)
DENSE_EPS_EXTENSION = (0.0025, 0.005)
SPARSE_EPS_EXTENSION = (0.45, 0.50)

IMPROVED_BAYESIAN_OBJECTIVE = (
    "constraint-aware-warm-start-improved-bayesian-v1"
)
SCORE_WEIGHTS = {
    "cross_file_recurrence": 0.45,
    "top100_head_recurrence": 0.15,
    "density_balance": 0.40,
}
DENSITY_BALANCE_WEIGHTS = {
    "coverage_target": 0.50,
    "anti_collapse": 0.50,
}


def parse_number_list(raw: str, converter: type) -> tuple[Any, ...]:
    values = tuple(
        converter(item.strip()) for item in raw.split(",") if item.strip()
    )
    if not values:
        raise ValueError("参数候选列表不能为空")
    return values


def source_file(info: Any) -> str:
    if isinstance(info, (list, tuple)) and len(info) > 1:
        return str(info[1])
    return ""


def calculate_candidate_metrics(
    *,
    data: np.ndarray,
    normalized: np.ndarray,
    labels: np.ndarray,
    infos: Sequence[Any],
) -> dict[str, Any]:
    """计算选择参数所需的纯无监督簇内指标。"""

    total = int(len(labels))
    members = {
        int(label): np.flatnonzero(labels == label)
        for label in np.unique(labels)
        if int(label) >= 0
    }
    members = {
        label: indices for label, indices in members.items() if len(indices) >= 2
    }
    sizes = {label: int(len(indices)) for label, indices in members.items()}
    clustered = sum(sizes.values())
    cohesion: dict[int, float] = {}
    file_counts: dict[int, int] = {}
    for label, indices in members.items():
        centroid = np.mean(data[indices], axis=0)
        centroid_norm = float(np.linalg.norm(centroid))
        if centroid_norm:
            similarities = normalized[indices] @ (centroid / centroid_norm)
            cohesion[label] = float(np.mean(1.0 - similarities))
        else:
            cohesion[label] = 1.0
        file_counts[label] = len(
            {source_file(infos[index]) for index in indices}
        )

    ranked = sorted(members, key=lambda label: (-sizes[label], label))
    top100 = ranked[:100]
    size_values = list(sizes.values())
    return {
        "candidate_count": total,
        "valid_cluster_count": len(members),
        "clustered_candidate_count": clustered,
        "noise_count": total - clustered,
        "coverage": clustered / total if total else 0.0,
        "noise_ratio": (total - clustered) / total if total else 0.0,
        "mean_cluster_size": (
            float(np.mean(size_values)) if size_values else None
        ),
        "median_cluster_size": (
            float(np.median(size_values)) if size_values else None
        ),
        "max_cluster_size": max(size_values, default=0),
        "max_cluster_ratio_total": (
            max(size_values) / total if size_values and total else 0.0
        ),
        "cross_file_cluster_count": sum(
            count >= 2 for count in file_counts.values()
        ),
        "top100": {
            "cluster_count": len(top100),
            "candidate_count": sum(sizes[label] for label in top100),
            "cross_file_cluster_count": sum(
                file_counts[label] >= 2 for label in top100
            ),
        },
        "macro_mean_cosine_distance_to_centroid": (
            float(np.mean(list(cohesion.values()))) if cohesion else None
        ),
        "labels_sha256": hashlib.sha256(labels.tobytes()).hexdigest(),
    }


def eligible_pool(
    rows: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """按冻结门槛返回参数候选池。"""

    def ratio_limit(row: dict[str, Any], base: float) -> float:
        total = max(1, int(row["candidate_count"]))
        return max(base, min(0.50, 5.0 / total))

    strict = [
        row
        for row in rows
        if 0.50 <= float(row["coverage"]) <= 0.80
        and float(row["max_cluster_ratio_total"])
        <= ratio_limit(row, 0.15)
    ]
    if strict:
        return "strict", strict
    expanded = [
        row
        for row in rows
        if 0.40 <= float(row["coverage"]) <= 0.85
        and float(row["max_cluster_ratio_total"])
        <= ratio_limit(row, 0.20)
    ]
    if expanded:
        return "expanded", expanded
    anti_collapse = [
        row
        for row in rows
        if float(row["max_cluster_ratio_total"])
        <= ratio_limit(row, 0.25)
    ]
    if anti_collapse:
        return "anti-collapse-only", anti_collapse
    return "unconstrained-fallback", rows


def quality_score(
    row: dict[str, Any],
    *,
    max_cross_file: int,
    max_top100_cross_file: int,
) -> tuple[float, dict[str, float]]:
    """计算用于改进贝叶斯优化的三指标无监督目标。"""

    coverage_component = max(
        0.0,
        1.0 - abs(float(row["coverage"]) - 0.65) / 0.15,
    )
    anti_collapse_component = max(
        0.0,
        1.0 - float(row["max_cluster_ratio_total"]) / 0.15,
    )
    components = {
        "cross_file_recurrence": (
            float(row["cross_file_cluster_count"]) / max_cross_file
            if max_cross_file
            else 0.0
        ),
        "top100_head_recurrence": (
            float(row["top100"]["cross_file_cluster_count"])
            / max_top100_cross_file
            if max_top100_cross_file
            else 0.0
        ),
        "density_balance": (
            coverage_component
            * DENSITY_BALANCE_WEIGHTS["coverage_target"]
            + anti_collapse_component
            * DENSITY_BALANCE_WEIGHTS["anti_collapse"]
        ),
    }
    return (
        sum(
            components[name] * SCORE_WEIGHTS[name]
            for name in SCORE_WEIGHTS
        ),
        components,
    )


def select_candidate(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, float, dict[str, float]]:
    """从任意仓库的扫描结果中确定性选择参数。"""

    if not rows:
        raise ValueError("DBSCAN 参数扫描结果不能为空")
    gate, pool = eligible_pool(rows)
    max_cross_file = max(
        int(row["cross_file_cluster_count"]) for row in pool
    )
    max_top100_cross_file = max(
        int(row["top100"]["cross_file_cluster_count"]) for row in pool
    )
    scored = [
        (
            *quality_score(
                row,
                max_cross_file=max_cross_file,
                max_top100_cross_file=max_top100_cross_file,
            ),
            row,
        )
        for row in pool
    ]
    score, components, selected = max(
        scored,
        key=lambda item: (
            item[0],
            -float(item[2]["eps"]),
            -int(item[2]["min_samples"]),
        ),
    )
    return selected, gate, score, components


class DBSCANAutoTuner:
    """以相同候选空间和评分规则处理任意新仓库。"""

    @staticmethod
    def tune(
        *,
        project: str,
        sources: Sequence[str],
        embeddings: Sequence[Any],
        infos: Sequence[Any],
        eps_values: Sequence[float] = DEFAULT_EPS_VALUES,
        min_samples_values: Sequence[int] = DEFAULT_MIN_SAMPLES_VALUES,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        if not eps_values or any(float(value) <= 0 for value in eps_values):
            raise ValueError("eps 候选必须是非空正数序列")
        if not min_samples_values or any(
            int(value) < 2 for value in min_samples_values
        ):
            raise ValueError("min_samples 候选必须全部至少为 2")

        data = embeddings_to_numpy(embeddings)
        norms = np.linalg.norm(data, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("embedding 包含零向量，无法计算余弦距离")
        normalized = data / norms
        rows: list[dict[str, Any]] = []
        labels_by_parameter: dict[tuple[float, int], np.ndarray] = {}

        def scan(candidate_eps_values: Sequence[float]) -> None:
            for eps in candidate_eps_values:
                if any(
                    math.isclose(float(eps), float(row["eps"]))
                    for row in rows
                ):
                    continue
                for min_samples in min_samples_values:
                    started = time.perf_counter()
                    labels = DBSCAN(
                        eps=float(eps),
                        min_samples=int(min_samples),
                        metric="cosine",
                    ).fit_predict(data)
                    metrics = calculate_candidate_metrics(
                        data=data,
                        normalized=normalized,
                        labels=labels,
                        infos=infos,
                    )
                    row = {
                        "eps": float(eps),
                        "min_samples": int(min_samples),
                        "elapsed_seconds": time.perf_counter() - started,
                        **metrics,
                    }
                    rows.append(row)
                    labels_by_parameter[
                        (float(eps), int(min_samples))
                    ] = labels

        scan(eps_values)
        initial_gate, _ = eligible_pool(rows)
        adaptive_extensions: list[str] = []
        if initial_gate != "strict":
            minimum_eps = min(float(value) for value in eps_values)
            minimum_rows = [
                row
                for row in rows
                if math.isclose(float(row["eps"]), minimum_eps)
            ]
            if minimum_rows and all(
                float(row["coverage"]) > 0.80
                for row in minimum_rows
            ):
                scan(DENSE_EPS_EXTENSION)
                adaptive_extensions.append("dense")
            if max(float(row["coverage"]) for row in rows) < 0.50:
                scan(SPARSE_EPS_EXTENSION)
                adaptive_extensions.append("sparse")

        selected, gate, score, components = select_candidate(rows)
        selected_key = (
            float(selected["eps"]),
            int(selected["min_samples"]),
        )
        clusters = build_cluster_dataframe(
            labels=labels_by_parameter[selected_key],
            representative_data=data,
            sources=sources,
            infos=infos,
        )
        report = {
            "schema_version": 1,
            "algorithm": "DBSCAN",
            "metric": "cosine",
            "optimization_method": (
                "repository-agnostic-unsupervised-grid-v1"
            ),
            "bayesian_objective": {
                "name": IMPROVED_BAYESIAN_OBJECTIVE,
                "role": (
                    "可由贝叶斯代理模型最小化的固定无监督目标；"
                    "当前入口负责评估 warm-start 候选并选择 incumbent"
                ),
                "loss": "1 - quality_score",
                "score_weights": SCORE_WEIGHTS,
                "density_balance_weights": DENSITY_BALANCE_WEIGHTS,
                "eps_search_space": {
                    "type": "real",
                    "low": 0.0025,
                    "high": 0.50,
                    "prior": "log-uniform",
                },
                "min_samples_search_space": {
                    "type": "integer",
                    "low": 2,
                    "high": 4,
                },
            },
            "project": project,
            "parameter_space": {
                "eps": sorted({float(row["eps"]) for row in rows}),
                "min_samples": [
                    int(value) for value in min_samples_values
                ],
                "adaptive_extensions": adaptive_extensions,
            },
            "hard_constraints": {
                "strict_coverage_min": 0.50,
                "strict_coverage_max": 0.80,
                "strict_max_cluster_ratio_total": 0.15,
                "expanded_coverage_min": 0.40,
                "expanded_coverage_max": 0.85,
                "expanded_max_cluster_ratio_total": 0.20,
                "small_repository_ratio_floor": (
                    "min(0.50, 5 / candidate_count)"
                ),
            },
            "score_weights": SCORE_WEIGHTS,
            "selection_gate": gate,
            "selected": {
                "eps": selected_key[0],
                "min_samples": selected_key[1],
                "quality_score": score,
                "score_components": components,
                "metrics": selected,
            },
            "results": rows,
        }
        return clusters, report

    @staticmethod
    def run(
        *,
        embedding_file: str,
        cluster_result_path: str,
        report_path: str,
        eps_values: Sequence[float] = DEFAULT_EPS_VALUES,
        min_samples_values: Sequence[int] = DEFAULT_MIN_SAMPLES_VALUES,
    ) -> dict[str, Any]:
        with open(embedding_file, "rb") as stream:
            data = pickle.load(stream)
        if not isinstance(data, pd.DataFrame) or len(data) != 1:
            raise ValueError("自动调参入口每次必须且只能处理一个仓库")
        required = {"pros_name", "pros_src", "pros_emb", "pros_info"}
        if set(data.columns) != required:
            raise ValueError(f"embedding 列不符合合同: {list(data.columns)}")
        row = data.iloc[0]
        project = str(row["pros_name"])
        sources = list(row["pros_src"])
        if any("ToBeDetermined" in source for source in sources):
            raise ValueError(f"{project}: 包含无效代码片段")
        clusters, report = DBSCANAutoTuner.tune(
            project=project,
            sources=sources,
            embeddings=list(row["pros_emb"]),
            infos=list(row["pros_info"]),
            eps_values=eps_values,
            min_samples_values=min_samples_values,
        )
        selected = report["selected"]
        output = [
            {
                "pros_name": project,
                "clusters": clusters,
                "clustering_metadata": {
                    "algorithm": "DBSCAN",
                    "metric": "cosine",
                    "optimization_method": report["optimization_method"],
                    "eps": selected["eps"],
                    "min_samples": selected["min_samples"],
                    "selection_gate": report["selection_gate"],
                },
            }
        ]
        cluster_path = Path(cluster_result_path)
        cluster_path.parent.mkdir(parents=True, exist_ok=True)
        with cluster_path.open("wb") as stream:
            pickle.dump(output, stream)
        report_file = Path(report_path)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info(
            "DBSCAN 自动调参完成: project=%s, eps=%s, min_samples=%s",
            project,
            selected["eps"],
            selected["min_samples"],
        )
        return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="对单个仓库执行通用 DBSCAN 无监督自动调参",
    )
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--output", "-o", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--eps-values",
        default=",".join(map(str, DEFAULT_EPS_VALUES)),
    )
    parser.add_argument(
        "--min-samples-values",
        default=",".join(map(str, DEFAULT_MIN_SAMPLES_VALUES)),
    )
    args = parser.parse_args()
    DBSCANAutoTuner.run(
        embedding_file=args.input,
        cluster_result_path=args.output,
        report_path=args.report,
        eps_values=parse_number_list(args.eps_values, float),
        min_samples_values=parse_number_list(
            args.min_samples_values,
            int,
        ),
    )


if __name__ == "__main__":
    main()
