"""Stage 2 高频聚类消融。

该消融把 Stage 2 DBSCAN 簇直接视为习语种类，不调用 LLM，也不执行 Stage 3
判断或 Stage 4 合成。它与 IC 机会域共享聚类来源，因此自动覆盖指标只用于诊断
Stage 2 频率上界；Stage 3/4 的质量增益必须通过盲化人工标注比较。
"""

from __future__ import annotations

import argparse
import math
import pickle
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from ..common.logging import get_logger
from .baseline_common import make_idiom_record, write_project_idioms, write_run_manifest


logger = get_logger(__name__)


def _select_clusters(
    clusters: pd.DataFrame,
    *,
    min_cluster_size: int,
    selection_ratio: float,
    max_types: int,
) -> pd.DataFrame:
    if min_cluster_size < 1:
        raise ValueError("min_cluster_size 必须大于等于 1")
    if not 0 < selection_ratio < 1:
        raise ValueError("selection_ratio 必须位于 (0, 1)，以实际执行比例截断")
    if max_types < 1:
        raise ValueError("max_types 必须为正数")
    if not isinstance(clusters, pd.DataFrame) or clusters.empty:
        return pd.DataFrame(columns=getattr(clusters, "columns", []))

    eligible = clusters[
        pd.to_numeric(clusters["cluster_size"], errors="coerce")
        >= min_cluster_size
    ].copy()
    if eligible.empty:
        return eligible

    eligible["_stable_label"] = eligible["label"].map(str)
    eligible = eligible.sort_values(
        ["cluster_size", "_stable_label"],
        ascending=[False, True],
        kind="mergesort",
    )
    ratio_limit = max(1, math.ceil(len(eligible) * selection_ratio))
    limit = min(ratio_limit, max_types)
    return eligible.head(limit).drop(columns=["_stable_label"])


def build_stage2_frequency_ablation(
    clusters_path: str | Path,
    output_dir: str | Path,
    *,
    selection_ratio: float,
    min_cluster_size: int = 3,
    max_types: int = 100,
) -> Dict[str, int]:
    """从冻结的 Stage 2 聚类生成频率消融习语文件。"""
    clusters_path = Path(clusters_path)
    with clusters_path.open("rb") as file:
        project_results = pickle.load(file)

    counts: Dict[str, int] = {}
    project_manifest: List[Dict[str, Any]] = []
    for project_result in project_results:
        project_name = str(project_result["pros_name"])
        clusters = project_result["clusters"]
        selected = _select_clusters(
            clusters,
            min_cluster_size=min_cluster_size,
            selection_ratio=selection_ratio,
            max_types=max_types,
        )
        cluster_sizes = pd.to_numeric(clusters["cluster_size"], errors="coerce")
        eligible_cluster_count = int((cluster_sizes >= min_cluster_size).sum())
        ratio_selected_count = (
            max(1, math.ceil(eligible_cluster_count * selection_ratio))
            if eligible_cluster_count
            else 0
        )

        idioms: List[Dict[str, Any]] = []
        for _, row in selected.iterrows():
            center_point = str(row.get("center_point") or "").strip()
            infos = row.get("infos")
            source_infos = list(infos) if isinstance(infos, list) else []
            if not center_point or not source_infos:
                continue
            record = make_idiom_record(
                center_point=center_point,
                source_infos=source_infos,
                provenance={
                    "method": "stage2_frequency_ablation",
                    "comparison_role": "quality_ablation",
                    "cluster_label": int(row["label"]),
                    "selection_score": int(row["cluster_size"]),
                    "selection_rule": {
                        "min_cluster_size": min_cluster_size,
                        "selection_ratio": selection_ratio,
                        "max_types": max_types,
                    },
                    "source_clusters": str(clusters_path),
                },
            )
            record["ablation_provenance"] = record.pop("baseline_provenance")
            idioms.append(record)

        output_path = write_project_idioms(output_dir, project_name, idioms)
        counts[project_name] = len(idioms)
        project_manifest.append(
            {
                "project": project_name,
                "input_cluster_count": int(len(clusters)),
                "minimum_size_eligible_count": eligible_cluster_count,
                "ratio_selected_count_before_cap": ratio_selected_count,
                "selected_cluster_count": int(len(selected)),
                "selected_idiom_count": len(idioms),
            }
        )
        logger.info(
            "Stage 2 高频聚类消融 %s: %d/%d -> %s",
            project_name,
            len(idioms),
            len(clusters),
            output_path,
        )

    write_run_manifest(
        output_dir,
        {
            "method": "stage2_frequency_ablation",
            "comparison_role": "quality_ablation",
            "automatic_metrics_role": "stage2_coverage_upper_bound_diagnostic",
            "primary_comparison": "blinded_manual_idiom_quality_annotation",
            "is_mock": False,
            "description": (
                "Tree-sitter 规则候选、预训练代码嵌入和 DBSCAN 聚类；"
                "簇依次经最小簇大小、保留比例和种类数量上限截断后直接作为人工质量对照。"
            ),
            "source_clusters": str(clusters_path),
            "selection_rule": {
                "min_cluster_size": min_cluster_size,
                "selection_ratio": selection_ratio,
                "max_types": max_types,
                "order": [
                    "filter_min_cluster_size",
                    "rank_by_cluster_size_then_label",
                    "apply_selection_ratio",
                    "apply_max_types_cap",
                ],
            },
            "projects": project_manifest,
        },
        filename="ablation-manifest.json",
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="构造 Stage 2 高频聚类消融的 C++ 习语样本"
    )
    parser.add_argument("--clusters", default="outputs/library/cli11/stage2/clusters.pkl")
    parser.add_argument(
        "--output-dir",
        default="results/ablations/stage2-frequency/cli11",
    )
    parser.add_argument("--min-cluster-size", type=int, default=3)
    parser.add_argument(
        "--selection-ratio",
        type=float,
        required=True,
        help="在合格簇中按大小保留的比例，必须显式设置且位于 (0, 1)",
    )
    parser.add_argument(
        "--max-types",
        type=int,
        default=100,
        help="比例截断后每项目最多输出的习语种类数（默认 100）",
    )
    args = parser.parse_args()
    build_stage2_frequency_ablation(
        args.clusters,
        args.output_dir,
        selection_ratio=args.selection_ratio,
        min_cluster_size=args.min_cluster_size,
        max_types=args.max_types,
    )


if __name__ == "__main__":
    main()
