"""在冻结 DBSCAN 之后按仓库保守归并重复簇。"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.metrics import pairwise_distances_argmin_min

from ..common.logging import get_logger
from ..parser.cpp_lex import (
    CppLexicalAnalysis,
    analyze_cpp_lexically,
    deduplicate_lexical_variants,
)
from .cluster_result import CLUSTER_COLUMNS, embeddings_to_numpy


logger = get_logger(__name__)
MERGE_SCHEMA_VERSION = 1
DEFAULT_SIMILARITY_THRESHOLD = 0.92
DEFAULT_MIN_FUZZY_TOKENS = 20


@dataclass(frozen=True)
class _EmbeddingMember:
    source: str
    info: Any
    embedding: np.ndarray


@dataclass
class _ClusterUnit:
    rows: list[Mapping[str, Any]]
    source_labels: list[int]
    analysis: CppLexicalAnalysis
    merge_reasons: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _node_info(info: Any) -> Mapping[str, Any]:
    if isinstance(info, (list, tuple)) and len(info) >= 4:
        node = info[3]
        if isinstance(node, Mapping):
            return node
    return {}


def _info_key(info: Any) -> tuple[Any, ...]:
    node = _node_info(info)
    values = list(info[:3]) if isinstance(info, (list, tuple)) else ["", "", ""]
    return (
        *map(str, values),
        int(node.get("start_byte", -1)),
        int(node.get("end_byte", -1)),
        str(node.get("extent") or ""),
        str(node.get("kind") or ""),
        str(node.get("candidate_origin") or ""),
    )


def _source_file(info: Any) -> str:
    if isinstance(info, (list, tuple)) and len(info) >= 2:
        return str(info[1] or "")
    return str(_node_info(info).get("source_path") or "")


def _load_single_project(path: Path, field: str) -> tuple[str, Any, dict]:
    with path.open("rb") as stream:
        items = pickle.load(stream)
    if not isinstance(items, list) or len(items) != 1:
        raise ValueError(f"{path} 必须只包含一个仓库")
    item = items[0]
    if not isinstance(item, dict) or "pros_name" not in item or field not in item:
        raise ValueError(f"{path} 不符合单仓库 {field} 合同")
    return str(item["pros_name"]), item[field], item


def _embedding_members(
    embeddings: pd.DataFrame,
    project: str,
) -> dict[tuple[Any, ...], _EmbeddingMember]:
    rows = embeddings[embeddings["pros_name"].astype(str) == project]
    sources: list[str] = []
    infos: list[Any] = []
    tensors: list[Any] = []
    for _, row in rows.iterrows():
        sources.extend(map(str, row["pros_src"]))
        infos.extend(row["pros_info"])
        tensors.extend(row["pros_emb"])
    matrix = embeddings_to_numpy(tensors)
    return {
        _info_key(info): _EmbeddingMember(source, info, matrix[index])
        for index, (source, info) in enumerate(zip(sources, infos))
    }


def _initial_units(clusters: pd.DataFrame) -> list[_ClusterUnit]:
    exact_groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    analyses: dict[tuple[Any, ...], CppLexicalAnalysis] = {}
    for _, row in clusters.iterrows():
        record = row.to_dict()
        analysis = analyze_cpp_lexically(str(record["center_point"]))
        token_key = analysis.tokens or (
            ("invalid_cluster_label", str(record["label"])),
        )
        exact_groups.setdefault(token_key, []).append(record)
        analyses[token_key] = analysis
    units = []
    for token_key, rows in exact_groups.items():
        labels = sorted(int(row["label"]) for row in rows)
        units.append(
            _ClusterUnit(
                rows=rows,
                source_labels=labels,
                analysis=analyses[token_key],
                merge_reasons=(
                    ["lexical_center_equivalent"]
                    if len(rows) > 1
                    else []
                ),
            )
        )
    return sorted(units, key=lambda unit: unit.source_labels[0])


def _similar(left: _ClusterUnit, right: _ClusterUnit, threshold: float) -> bool:
    ratio = SequenceMatcher(
        None,
        left.analysis.tokens,
        right.analysis.tokens,
        autojunk=False,
    ).ratio()
    if ratio < threshold:
        return False
    left_to_right: dict[str, str] = {}
    right_to_left: dict[str, str] = {}
    for left_token, right_token in zip(
        left.analysis.tokens,
        right.analysis.tokens,
    ):
        if left_token == right_token:
            continue
        left_kind, left_text = left_token
        right_kind, right_text = right_token
        if (
            left_kind != "identifier"
            or right_kind != "identifier"
            or left_text not in left.analysis.local_identifiers
            or right_text not in right.analysis.local_identifiers
        ):
            return False
        if left_to_right.setdefault(left_text, right_text) != right_text:
            return False
        if right_to_left.setdefault(right_text, left_text) != left_text:
            return False
    return True


def _merge_units(
    units: list[_ClusterUnit],
    *,
    similarity_threshold: float,
    min_fuzzy_tokens: int,
) -> list[_ClusterUnit]:
    buckets: dict[tuple[Any, ...], list[_ClusterUnit]] = {}
    final_units: list[_ClusterUnit] = []
    for unit in units:
        analysis = unit.analysis
        if not analysis.parse_valid or len(analysis.tokens) < min_fuzzy_tokens:
            final_units.append(unit)
            continue
        key = (
            analysis.ast_structure,
            len(analysis.tokens),
        )
        buckets.setdefault(key, []).append(unit)

    for bucket in buckets.values():
        groups: list[list[_ClusterUnit]] = []
        for unit in bucket:
            group = next(
                (
                    value
                    for value in groups
                    if all(
                        _similar(unit, member, similarity_threshold)
                        for member in value
                    )
                ),
                None,
            )
            if group is None:
                groups.append([unit])
            else:
                group.append(unit)
        for group in groups:
            rows = [row for unit in group for row in unit.rows]
            labels = sorted(
                label for unit in group for label in unit.source_labels
            )
            reasons = sorted(
                {
                    reason
                    for unit in group
                    for reason in unit.merge_reasons
                }
            )
            if len(group) > 1:
                reasons.append("ast_shape_and_high_lexical_similarity")
            final_units.append(
                _ClusterUnit(
                    rows=rows,
                    source_labels=labels,
                    analysis=group[0].analysis,
                    merge_reasons=reasons,
                )
            )
    return sorted(final_units, key=lambda unit: unit.source_labels[0])


def _unit_members(
    unit: _ClusterUnit,
    member_index: Mapping[tuple[Any, ...], _EmbeddingMember],
) -> list[_EmbeddingMember]:
    members = [
        member_index[_info_key(info)]
        for row in unit.rows
        for info in list(row.get("infos") or [])
    ]
    if len({_info_key(member.info) for member in members}) != len(members):
        raise ValueError("来源簇包含重复源码位置，无法无损归并")
    return members


def _merged_record(
    unit: _ClusterUnit,
    member_index: Mapping[tuple[Any, ...], _EmbeddingMember],
) -> tuple[dict[str, Any], dict[str, Any]]:
    members = _unit_members(unit, member_index)
    points = np.stack([member.embedding for member in members])
    centroid = np.mean(points, axis=0)
    closest, _ = pairwise_distances_argmin_min(
        np.asarray([centroid]),
        points,
        metric="cosine",
    )
    representative_index = int(closest[0])
    representative = members[representative_index]
    label = min(unit.source_labels)
    record = {
        "label": label,
        "center_point": representative.source,
        "else_point": [
            member.source
            for index, member in enumerate(members)
            if index != representative_index
        ],
        "cluster_size": len(members),
        "center_point_info": representative.info,
        "infos": [member.info for member in members],
        "loc_label": (
            f"{representative.info[0]}-"
            f"{representative.info[1]}-"
            f"{representative.info[2]}"
        ),
    }
    provenance = {
        "label": label,
        "source_labels": unit.source_labels,
        "source_cluster_count": len(unit.source_labels),
        "merge_reasons": unit.merge_reasons or ["not_merged"],
    }
    return record, provenance


def cluster_quality_summary(clusters: pd.DataFrame) -> dict[str, Any]:
    exact_duplicates = 0
    strong_proxies = 0
    member_count = 0
    for _, row in clusters.iterrows():
        codes = [str(row["center_point"]), *map(str, row["else_point"])]
        variants = deduplicate_lexical_variants(codes)
        infos = list(row["infos"])
        member_count += int(row["cluster_size"])
        exact_duplicates += int(len(variants) == 1)
        node = _node_info(row["center_point_info"])
        representative = analyze_cpp_lexically(str(row["center_point"]))
        nontrivial = (
            float(node.get("subtree_size", 0) or 0) >= 10
            and sum(len(text) for _, text in representative.tokens) >= 20
        )
        strong_proxies += int(
            nontrivial
            and len(variants) >= 2
            and len({_source_file(info) for info in infos}) >= 2
        )
    cluster_count = len(clusters)
    return {
        "cluster_count": cluster_count,
        "member_count": member_count,
        "exact_duplicate_count": exact_duplicates,
        "exact_duplicate_rate": (
            exact_duplicates / cluster_count if cluster_count else 0.0
        ),
        "strong_structure_proxy_count": strong_proxies,
        "strong_structure_proxy_rate": (
            strong_proxies / cluster_count if cluster_count else 0.0
        ),
    }


def merge_repository_clusters(
    *,
    project: str,
    clusters: pd.DataFrame,
    embeddings: pd.DataFrame,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    min_fuzzy_tokens: int = DEFAULT_MIN_FUZZY_TOKENS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """归并单仓库簇，保留七列 Schema 并返回逐簇来源元数据。"""

    if clusters.columns.tolist() != CLUSTER_COLUMNS:
        raise ValueError("输入 clusters.pkl 不符合阶段2七列 Schema")
    units = _merge_units(
        _initial_units(clusters),
        similarity_threshold=similarity_threshold,
        min_fuzzy_tokens=min_fuzzy_tokens,
    )
    member_index = _embedding_members(embeddings, project)
    records: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for unit in units:
        record, source = _merged_record(unit, member_index)
        records.append(record)
        provenance.append(source)
    merged = pd.DataFrame.from_records(records, columns=CLUSTER_COLUMNS)
    before = cluster_quality_summary(clusters)
    after = cluster_quality_summary(merged)
    metadata = {
        "schema_version": MERGE_SCHEMA_VERSION,
        "method": "repository_local_conservative_cluster_merge",
        "similarity_threshold": similarity_threshold,
        "min_fuzzy_tokens": min_fuzzy_tokens,
        "source_cluster_count": len(clusters),
        "merged_cluster_count": len(merged),
        "merged_group_count": sum(
            item["source_cluster_count"] > 1 for item in provenance
        ),
        "before": before,
        "after": after,
        "clusters": provenance,
    }
    return merged, metadata


def merge_cluster_artifacts(
    *,
    clusters_path: Path,
    embeddings_path: Path,
    output_path: Path,
    report_path: Path | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    min_fuzzy_tokens: int = DEFAULT_MIN_FUZZY_TOKENS,
) -> dict[str, Any]:
    project, clusters, source_item = _load_single_project(
        clusters_path,
        "clusters",
    )
    embeddings = pd.read_pickle(embeddings_path)
    embedding_projects = set(embeddings["pros_name"].astype(str))
    if len(embedding_projects) != 1:
        raise ValueError("embeddings.pkl 必须只包含一个仓库")
    embedding_project = next(iter(embedding_projects))
    if embedding_project != project:
        raise ValueError("clusters.pkl 与 embeddings.pkl 仓库不一致")
    merged, metadata = merge_repository_clusters(
        project=project,
        clusters=clusters,
        embeddings=embeddings,
        similarity_threshold=similarity_threshold,
        min_fuzzy_tokens=min_fuzzy_tokens,
    )
    input_metadata = {
        "clusters_path": str(clusters_path),
        "clusters_sha256": _sha256(clusters_path),
        "embeddings_path": str(embeddings_path),
        "embeddings_sha256": _sha256(embeddings_path),
    }
    output = [
        {
            "pros_name": project,
            "clusters": merged,
            "clustering_metadata": {
                "postprocessing": metadata,
                "source_clustering_metadata": source_item.get(
                    "clustering_metadata"
                ),
                "input": input_metadata,
            },
        }
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as stream:
        pickle.dump(output, stream, protocol=pickle.HIGHEST_PROTOCOL)
    report = {
        "schema_version": MERGE_SCHEMA_VERSION,
        "artifact_type": "cluster_merge_report",
        "project": project,
        "output_path": str(output_path),
        "input": input_metadata,
        **metadata,
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    logger.info(
        "簇归并完成: project=%s, before=%s, after=%s",
        project,
        len(clusters),
        len(merged),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="在冻结 DBSCAN 与阶段3之间执行单仓库保守簇归并"
    )
    parser.add_argument("--clusters", required=True, type=Path)
    parser.add_argument("--embeddings", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
    )
    parser.add_argument(
        "--min-fuzzy-tokens",
        type=int,
        default=DEFAULT_MIN_FUZZY_TOKENS,
    )
    args = parser.parse_args()
    report = merge_cluster_artifacts(
        clusters_path=args.clusters,
        embeddings_path=args.embeddings,
        output_path=args.output,
        report_path=args.report,
        similarity_threshold=args.similarity_threshold,
        min_fuzzy_tokens=args.min_fuzzy_tokens,
    )
    print(
        json.dumps(
            {
                "project": report["project"],
                "before": report["before"]["cluster_count"],
                "after": report["after"]["cluster_count"],
                "output": report["output_path"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
