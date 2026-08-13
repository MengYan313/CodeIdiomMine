"""IdioMine-CPP 的内部候选发现实现。

该 baseline 只保留 IdioMine 中与语言迁移关系最直接的三步：

1. 使用 Parser 已生成的局部 Def-Use 语义片段近似 DCC 子习语；
2. 复用给定 ``embeddings.pkl`` 中的预训练代码嵌入；
3. 在每个仓库内部独立执行 DBSCAN，并把全部非噪声簇作为习语种类。

它不声称复现原论文的 Java DvCFG/DCC，也不是独立 baseline。候选簇只在
``idiomine_cpp`` 内部供后续 ChatGPT 判断与合成使用；适配差异会汇入最终
IdioMine-CPP manifest 和每条记录的 provenance。
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.metrics import pairwise_distances_argmin_min

from ..common.logging import get_logger
from .baseline_common import (
    is_source_info,
    make_idiom_record,
    write_project_idioms,
    write_run_manifest,
)


logger = get_logger(__name__)

IDIOMINE_DOI = "10.1145/3597503.3639135"
IDIOMINE_REFERENCE_REPOSITORY = "https://github.com/Yanming-Yang/idioMine"
CANDIDATE_ORIGIN = "semantic_def_use"


def _as_vector(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    vector = np.asarray(value, dtype=float).reshape(-1)
    if vector.size == 0 or not np.isfinite(vector).all():
        raise ValueError("嵌入必须是非空有限向量")
    if float(np.linalg.norm(vector)) == 0.0:
        raise ValueError("余弦 DBSCAN 不接受零向量")
    return vector


def _is_dcc_lite_candidate(info: Any) -> bool:
    if not is_source_info(info):
        return False
    node_info = info[3]
    return (
        node_info.get("candidate_origin") == CANDIDATE_ORIGIN
        and bool(str(node_info.get("code_snippet") or "").strip())
    )


def _iter_project_embeddings(
    embedding_paths: Iterable[str | Path],
) -> Iterable[
    Tuple[str, Path, Sequence[str], Sequence[Any], Sequence[Any]]
]:
    seen_projects: set[str] = set()
    found_project = False
    for path in sorted(Path(raw_path) for raw_path in embedding_paths):
        with path.open("rb") as file:
            data = pickle.load(file)
        if not isinstance(data, pd.DataFrame):
            raise ValueError(f"{path} 不是 embeddings DataFrame")
        required = {"pros_name", "pros_src", "pros_emb", "pros_info"}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"{path} 缺少列: {sorted(missing)}")

        for _, row in data.sort_values("pros_name", kind="stable").iterrows():
            project = str(row["pros_name"])
            if project in seen_projects:
                raise ValueError(f"项目 {project} 出现在多个 embedding 输入中")
            seen_projects.add(project)
            sources = row["pros_src"]
            embeddings = row["pros_emb"]
            infos = row["pros_info"]
            if not all(
                isinstance(values, (list, tuple))
                for values in (sources, embeddings, infos)
            ):
                raise ValueError(f"{path} 的项目 {project} 列表字段格式错误")
            if not (len(sources) == len(embeddings) == len(infos)):
                raise ValueError(f"{path} 的项目 {project} 嵌入字段未对齐")
            found_project = True
            yield project, path, sources, embeddings, infos
    if not found_project:
        raise ValueError("没有可处理的 embedding 项目")


def _cluster_project(
    *,
    sources: Sequence[str],
    embeddings: Sequence[Any],
    infos: Sequence[Any],
    embedding_model: str,
    source_embeddings: str,
    eps: float,
    min_samples: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    selected_sources: List[str] = []
    selected_vectors: List[np.ndarray] = []
    selected_infos: List[Sequence[Any]] = []
    invalid_embedding_count = 0

    for source, embedding, info in zip(sources, embeddings, infos):
        if not _is_dcc_lite_candidate(info):
            continue
        try:
            vector = _as_vector(embedding)
        except ValueError:
            invalid_embedding_count += 1
            continue
        selected_sources.append(str(source))
        selected_vectors.append(vector)
        selected_infos.append(info)

    if not selected_vectors:
        return [], {
            "input_candidate_count": len(sources),
            "dcc_lite_candidate_count": 0,
            "invalid_embedding_count": invalid_embedding_count,
            "cluster_count": 0,
            "noise_candidate_count": 0,
        }

    dimensions = {vector.shape for vector in selected_vectors}
    if len(dimensions) != 1:
        raise ValueError(f"embedding 维度不一致: {sorted(dimensions)}")

    matrix = np.stack(selected_vectors)
    labels = DBSCAN(
        eps=eps,
        min_samples=min_samples,
        metric="cosine",
    ).fit_predict(matrix)
    idioms: List[Dict[str, Any]] = []
    cluster_labels = sorted(int(label) for label in set(labels) if label != -1)
    for label in cluster_labels:
        indices = np.where(labels == label)[0]
        points = matrix[indices]
        centroid = np.mean(points, axis=0)
        representative_offset, _ = pairwise_distances_argmin_min(
            np.array([centroid]),
            points,
            metric="cosine",
        )
        representative_index = int(indices[int(representative_offset[0])])
        representative_info = selected_infos[representative_index]
        source_infos = [representative_info]
        source_infos.extend(
            selected_infos[int(index)]
            for index in indices
            if int(index) != representative_index
        )
        idioms.append(
            make_idiom_record(
                center_point=selected_sources[representative_index],
                source_infos=source_infos,
                provenance={
                    "method": "idiomine_cpp",
                    "output_kind": "cluster_candidate",
                    "source_method": "IdioMine",
                    "source_doi": IDIOMINE_DOI,
                    "reference_repository": IDIOMINE_REFERENCE_REPOSITORY,
                    "embedding_model": embedding_model,
                    "source_embeddings": source_embeddings,
                    "cluster_label": label,
                    "raw_cluster_size": int(len(indices)),
                    "candidate_representation": (
                        "semantic_def_use_as_dcc_lite"
                    ),
                    "clustering": {
                        "algorithm": "DBSCAN",
                        "metric": "cosine",
                        "eps": eps,
                        "min_samples": min_samples,
                    },
                    "omitted_operations": [
                        "java_dvcfg",
                        "exact_dcc",
                        "heuristic_sub_idiom_association",
                    ],
                },
            )
        )

    return idioms, {
        "input_candidate_count": len(sources),
        "dcc_lite_candidate_count": len(selected_vectors),
        "invalid_embedding_count": invalid_embedding_count,
        "cluster_count": len(cluster_labels),
        "noise_candidate_count": int(np.sum(labels == -1)),
    }


def build_idiomine_cpp_candidate_artifacts(
    embedding_paths: Iterable[str | Path],
    output_dir: str | Path,
    *,
    embedding_model: str,
    eps: float = 0.5,
    min_samples: int = 2,
) -> Dict[str, int]:
    """为单一 IdioMine-CPP baseline 构造内部候选簇产物。"""
    if not 0 < eps <= 1:
        raise ValueError("eps 必须位于 (0, 1]")
    if min_samples < 2:
        raise ValueError("min_samples 必须大于等于 2")
    if not embedding_model.strip():
        raise ValueError("embedding_model 不能为空")

    counts: Dict[str, int] = {}
    project_manifest: List[Dict[str, Any]] = []
    source_paths: List[str] = []

    for project, path, sources, embeddings, infos in _iter_project_embeddings(
        embedding_paths
    ):
        source_paths.append(str(path))
        idioms, statistics = _cluster_project(
            sources=sources,
            embeddings=embeddings,
            infos=infos,
            embedding_model=embedding_model,
            source_embeddings=str(path),
            eps=eps,
            min_samples=min_samples,
        )
        output_path = write_project_idioms(output_dir, project, idioms)
        counts[project] = len(idioms)
        project_manifest.append(
            {
                "project": project,
                "source_embeddings": str(path),
                **statistics,
                "selected_idiom_count": len(idioms),
            }
        )
        logger.info(
            "IdioMine-CPP 候选 %s: DCC-lite=%d, clusters=%d, noise=%d -> %s",
            project,
            statistics["dcc_lite_candidate_count"],
            len(idioms),
            statistics["noise_candidate_count"],
            output_path,
        )

    write_run_manifest(
        output_dir,
        {
            "method": "idiomine_cpp",
            "artifact_kind": "candidate_clusters",
            "is_mock": False,
            "description": (
                "使用 C++ Parser 的 semantic_def_use 片段近似 IdioMine DCC，"
                "复用预先生成的代码嵌入，并按仓库独立执行 DBSCAN；"
                "该产物仅是 IdioMine-CPP 内部候选，不构成独立 baseline。"
            ),
            "source_method": {
                "name": "IdioMine",
                "doi": IDIOMINE_DOI,
                "reference_repository": IDIOMINE_REFERENCE_REPOSITORY,
            },
            "source_embeddings": sorted(set(source_paths)),
            "parameters": {
                "candidate_origin": CANDIDATE_ORIGIN,
                "embedding_model": embedding_model,
                "eps": eps,
                "min_samples": min_samples,
                "metric": "cosine",
            },
            "output_selection": {
                "policy": "all_non_noise_dbscan_clusters",
                "final_idiom_count_cap": None,
            },
            "adaptation": {
                "kept_operations": [
                    "dependency_chain_candidate_extraction",
                    "pretrained_code_embedding",
                    "repository_isolated_dbscan",
                ],
                "omitted_operations": [
                    "java_dvcfg",
                    "exact_dcc",
                    "heuristic_sub_idiom_association",
                ],
                "claim": "simplified_cpp_migration_not_full_reproduction",
            },
            "projects": project_manifest,
        },
    )
    return counts
