"""聚类标签到阶段2统一产物 Schema 的转换。"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import pairwise_distances_argmin_min


CLUSTER_COLUMNS = [
    "label",
    "center_point",
    "else_point",
    "cluster_size",
    "center_point_info",
    "infos",
    "loc_label",
]


def embeddings_to_numpy(
    embeddings: Sequence[torch.Tensor | np.ndarray],
) -> np.ndarray:
    """把对齐的 CPU tensor/数组转换为二维 float32 矩阵。"""

    data = np.stack(
        [
            item.detach().cpu().numpy()
            if isinstance(item, torch.Tensor)
            else np.asarray(item)
            for item in embeddings
        ]
    )
    data = np.squeeze(data)
    if data.ndim != 2:
        raise ValueError(f"embedding 必须形成二维矩阵，实际形状为 {data.shape}")
    if not np.isfinite(data).all():
        raise ValueError("embedding 包含非有限值")
    return data.astype(np.float32, copy=False)


def build_cluster_dataframe(
    *,
    labels: np.ndarray,
    representative_data: np.ndarray,
    sources: Sequence[str],
    infos: Sequence[Any],
) -> pd.DataFrame:
    """按统一七列 Schema 构造簇，并在原始空间选择代表代码。"""

    if len(labels) != len(representative_data):
        raise ValueError("聚类标签与 embedding 数量不一致")
    if len(labels) != len(sources) or len(labels) != len(infos):
        raise ValueError("聚类标签、源码和元数据数量不一致")

    records: list[dict[str, Any]] = []
    for raw_label in sorted(int(value) for value in set(labels) if value >= 0):
        cluster_indices = np.flatnonzero(labels == raw_label)
        if len(cluster_indices) < 2:
            continue
        points = representative_data[cluster_indices]
        centroid = np.mean(points, axis=0)
        closest_indices, _ = pairwise_distances_argmin_min(
            np.asarray([centroid]),
            points,
            metric="cosine",
        )
        closest_local_index = int(closest_indices[0])
        closest_global_index = int(cluster_indices[closest_local_index])
        closest_info = infos[closest_global_index]
        if not isinstance(closest_info, (list, tuple)) or len(closest_info) < 3:
            raise ValueError("代表代码元数据不符合 [项目, 文件, extent, ...] 合同")

        member_sources = [str(sources[index]) for index in cluster_indices]
        member_infos = [infos[index] for index in cluster_indices]
        records.append(
            {
                "label": raw_label,
                "center_point": str(sources[closest_global_index]),
                "else_point": [
                    source
                    for index, source in enumerate(member_sources)
                    if index != closest_local_index
                ],
                "cluster_size": int(len(cluster_indices)),
                "center_point_info": closest_info,
                "infos": member_infos,
                "loc_label": (
                    f"{closest_info[0]}-{closest_info[1]}-{closest_info[2]}"
                ),
            }
        )
    return pd.DataFrame.from_records(records, columns=CLUSTER_COLUMNS)
