"""从冻结的聚类标签集合构造不经过 LLM 的模拟习语产物。

该模块只用于离线验证评价器的公式、匹配器和数据契约。生成文件包含
``mock_provenance``，不得作为模型质量或论文实验结果。
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from ..common.logging import get_logger
from .baseline_common import write_project_idioms

logger = get_logger(__name__)


def _average_node_value(infos: List[Any], field: str) -> float:
    values: List[float] = []
    for info in infos:
        if not isinstance(info, (list, tuple)) or len(info) < 4:
            continue
        node_info = info[3]
        if not isinstance(node_info, dict) or node_info.get(field) is None:
            continue
        values.append(float(node_info[field]))
    return sum(values) / len(values) if values else 0.0


def _valid_info(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 4
        and isinstance(value[3], dict)
    )


def build_mock_idioms(
    clusters_path: str | Path,
    output_dir: str | Path,
    selection_manifest: str | Path | None = None,
) -> Dict[str, int]:
    """构造无排序模拟习语；可用已有清单冻结纳入的簇标签集合。"""
    clusters_path = Path(clusters_path)
    output_dir = Path(output_dir)
    with clusters_path.open("rb") as file:
        cluster_results = pickle.load(file)

    selected_labels: Dict[str, set[int]] = {}
    manifest_path = Path(selection_manifest) if selection_manifest else None
    if manifest_path is not None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest:
            selected_labels.setdefault(str(item["project"]), set()).add(
                int(item["label"])
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    counts: Dict[str, int] = {}
    for project_result in cluster_results:
        project_name = str(project_result["pros_name"])
        clusters = project_result["clusters"]
        if not isinstance(clusters, pd.DataFrame) or clusters.empty:
            counts[project_name] = 0
            continue
        if manifest_path is None:
            selected = clusters
        else:
            labels = selected_labels.get(project_name, set())
            selected = clusters[clusters["label"].isin(labels)]
            if len(selected) != len(labels):
                raise ValueError(
                    f"{project_name} 清单含 {len(labels)} 个簇，但只找到 {len(selected)} 个"
                )

        idioms: List[Dict[str, Any]] = []
        for _, row in selected.iterrows():
            center = str(row.get("center_point") or "").strip()
            infos = row.get("infos")
            source_infos = list(infos) if isinstance(infos, list) else []
            representative = row.get("center_point_info")
            if not _valid_info(representative):
                representative = source_infos[0] if source_infos else None
            if not center or representative is None:
                continue

            node_info = representative[3]
            candidate_extent = str(node_info.get("extent") or representative[2])
            loc_label = f"{representative[0]}-{representative[1]}-{candidate_extent}"
            idioms.append(
                {
                    "center_point": center,
                    "info": representative,
                    "source_infos": source_infos,
                    "cnt": len(source_infos),
                    "avg_ast_num": _average_node_value(source_infos, "ast_num"),
                    "avg_subtree_size": _average_node_value(
                        source_infos, "subtree_size"
                    ),
                    "loc_label": loc_label,
                    "mock_provenance": {
                        "kind": "frozen_cluster_selection_without_llm",
                        "source": str(clusters_path),
                        "selection_manifest": str(manifest_path) if manifest_path else None,
                        "cluster_label": int(row["label"]),
                    },
                }
            )

        output_path = write_project_idioms(output_dir, project_name, idioms)
        counts[project_name] = len(idioms)
        logger.info("模拟习语 %s: %d -> %s", project_name, len(idioms), output_path)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="从冻结的聚类集合构造无排序离线模拟习语")
    parser.add_argument(
        "--clusters", default="outputs/library/cli11/stage2/clusters.pkl", help="聚类 PKL"
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/library/cli11/mock",
        help="模拟习语输出目录",
    )
    parser.add_argument(
        "--selection-manifest",
        default="outputs/library/cli11/readables/clusters.top100.json",
        help="已有簇选择清单；只读取 project/label，不使用其中 rank",
    )
    args = parser.parse_args()
    build_mock_idioms(args.clusters, args.output_dir, args.selection_manifest)


if __name__ == "__main__":
    main()
