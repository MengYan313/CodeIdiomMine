"""仅规则分析、代码嵌入与聚类的 baseline。

该方法把 DBSCAN 簇直接视为习语种类，不调用 LLM，也不执行主方法的判断、
合成或回流。产物依次经过最小簇大小、保留比例和种类数量上限三项规则；
数量上限不是评价指标，也不适用于其他方法。
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


def build_rules_embedding_baseline(
    clusters_path: str | Path,
    output_dir: str | Path,
    *,
    selection_ratio: float,
    min_cluster_size: int = 3,
    max_types: int = 100,
) -> Dict[str, int]:
    """从规范聚类产物生成正式 baseline 习语文件。"""
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
            idioms.append(
                make_idiom_record(
                    center_point=center_point,
                    source_infos=source_infos,
                    provenance={
                        "method": "rules_embedding_clustering",
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
            )

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
            "规则+嵌入聚类 baseline %s: %d/%d -> %s",
            project_name,
            len(idioms),
            len(clusters),
            output_path,
        )

    write_run_manifest(
        output_dir,
        {
            "method": "rules_embedding_clustering",
            "is_mock": False,
            "description": (
                "Tree-sitter 规则候选、预训练代码嵌入和 DBSCAN 聚类；"
                "簇依次经最小簇大小、保留比例和种类数量上限截断后直接作为习语。"
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
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="构造仅规则分析、嵌入和聚类的 C++ 习语 baseline"
    )
    parser.add_argument("--clusters", default="outputs/cpp/clusters.pkl")
    parser.add_argument(
        "--output-dir",
        default="results/baselines/rules-embedding-clustering/cpp",
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
    build_rules_embedding_baseline(
        args.clusters,
        args.output_dir,
        selection_ratio=args.selection_ratio,
        min_cluster_size=args.min_cluster_size,
        max_types=args.max_types,
    )


if __name__ == "__main__":
    main()
