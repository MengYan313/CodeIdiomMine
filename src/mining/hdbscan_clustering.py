"""基于 HDBSCAN 的逐仓代码片段聚类。"""

from __future__ import annotations

import argparse
import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from hdbscan import HDBSCAN
from sklearn.decomposition import PCA

from ..common.logging import get_logger
from ..common.progress import progress
from .cluster_result import build_cluster_dataframe, embeddings_to_numpy


logger = get_logger(__name__)


class HDBSCANClusteringProcessor:
    """执行余弦一致的降维 HDBSCAN，并保持既有聚类产物 Schema。"""

    @staticmethod
    def load_pkl(file_path: str) -> pd.DataFrame:
        logger.info("加载数据文件: %s", file_path)
        with open(file_path, "rb") as stream:
            data = pickle.load(stream)
        if not isinstance(data, pd.DataFrame):
            raise TypeError(f"embedding 产物必须是 DataFrame，实际为 {type(data)}")
        required = {"pros_name", "pros_src", "pros_emb", "pros_info"}
        if set(data.columns) != required:
            raise ValueError(f"embedding 列不符合合同: {list(data.columns)}")
        logger.info("embedding 数据形状: %s", data.shape)
        return data

    @staticmethod
    def prepare_clustering_space(
        data: np.ndarray,
        *,
        normalize: bool = True,
        pca_components: int = 32,
        pca_random_state: int = 0,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """生成 HDBSCAN 空间，并返回可复现实验元数据。"""

        prepared = data.astype(np.float32, copy=True)
        if normalize:
            norms = np.linalg.norm(prepared, axis=1, keepdims=True)
            if np.any(norms == 0):
                raise ValueError("embedding 包含零向量，无法执行 L2 归一化")
            prepared /= norms

        effective_components = 0
        explained_variance_ratio = None
        if pca_components:
            effective_components = min(
                int(pca_components),
                prepared.shape[0] - 1,
                prepared.shape[1],
            )
            if effective_components < 2:
                raise ValueError("PCA 有效维数必须至少为 2")
            reducer = PCA(
                n_components=effective_components,
                svd_solver="randomized",
                random_state=pca_random_state,
            )
            prepared = reducer.fit_transform(prepared)
            explained_variance_ratio = float(
                reducer.explained_variance_ratio_.sum()
            )

        metadata = {
            "input_dimensions": int(data.shape[1]),
            "normalize": normalize,
            "pca_components_requested": int(pca_components),
            "pca_components_effective": effective_components,
            "pca_random_state": pca_random_state,
            "pca_explained_variance_ratio": explained_variance_ratio,
            "output_dimensions": int(prepared.shape[1]),
        }
        return np.ascontiguousarray(prepared), metadata

    @staticmethod
    def perform_hdbscan_clustering(
        pro_name: str,
        pro_src: list[str],
        pro_emb: list[Any],
        pro_info: list[Any],
        *,
        min_cluster_size: int = 2,
        min_samples: int = 1,
        cluster_selection_method: str = "leaf",
        cluster_selection_epsilon: float = 0.0,
        normalize: bool = True,
        pca_components: int = 32,
        pca_random_state: int = 0,
        algorithm: str = "boruvka_kdtree",
        leaf_size: int = 40,
        core_dist_n_jobs: int = 1,
        approx_min_span_tree: bool = True,
    ) -> tuple[np.ndarray, pd.DataFrame, dict[str, Any]]:
        if min_cluster_size < 2:
            raise ValueError("min_cluster_size 必须至少为 2")
        if min_samples < 1:
            raise ValueError("min_samples 必须至少为 1")
        if cluster_selection_method not in {"eom", "leaf"}:
            raise ValueError("cluster_selection_method 必须是 eom 或 leaf")
        if cluster_selection_epsilon < 0:
            raise ValueError("cluster_selection_epsilon 不能为负数")

        representative_data = embeddings_to_numpy(pro_emb)
        clustering_data, space_metadata = (
            HDBSCANClusteringProcessor.prepare_clustering_space(
                representative_data,
                normalize=normalize,
                pca_components=pca_components,
                pca_random_state=pca_random_state,
            )
        )
        logger.info(
            "执行 HDBSCAN: project=%s, min_cluster_size=%s, min_samples=%s, "
            "method=%s, epsilon=%s, dimensions=%s",
            pro_name,
            min_cluster_size,
            min_samples,
            cluster_selection_method,
            cluster_selection_epsilon,
            clustering_data.shape[1],
        )
        model = HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric="euclidean",
            alpha=1.0,
            algorithm=algorithm,
            leaf_size=leaf_size,
            core_dist_n_jobs=core_dist_n_jobs,
            cluster_selection_method=cluster_selection_method,
            cluster_selection_epsilon=cluster_selection_epsilon,
            allow_single_cluster=False,
            approx_min_span_tree=approx_min_span_tree,
            gen_min_span_tree=False,
            prediction_data=False,
        )
        labels = model.fit_predict(clustering_data)
        cluster_data = build_cluster_dataframe(
            labels=labels,
            representative_data=representative_data,
            sources=pro_src,
            infos=pro_info,
        )
        noise_count = int(np.count_nonzero(labels < 0))
        logger.info(
            "HDBSCAN 结果: %s 个有效簇, %s 个噪声点",
            len(cluster_data),
            noise_count,
        )
        metadata = {
            **space_metadata,
            "min_cluster_size": min_cluster_size,
            "min_samples": min_samples,
            "metric": "euclidean",
            "cluster_selection_method": cluster_selection_method,
            "cluster_selection_epsilon": cluster_selection_epsilon,
            "algorithm": algorithm,
            "leaf_size": leaf_size,
            "core_dist_n_jobs": core_dist_n_jobs,
            "approx_min_span_tree": approx_min_span_tree,
            "noise_count": noise_count,
            "valid_cluster_count": len(cluster_data),
        }
        return labels, cluster_data, metadata

    @staticmethod
    def process_projects(
        data: pd.DataFrame,
        **parameters: Any,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        rows = data.to_dict(orient="records")
        for row in progress(rows, desc="HDBSCAN 聚类项目", unit="项目"):
            project = str(row["pros_name"])
            sources = list(row["pros_src"])
            if any("ToBeDetermined" in source for source in sources):
                logger.warning("跳过项目 %s（包含无效代码片段）", project)
                continue
            labels, clusters, metadata = (
                HDBSCANClusteringProcessor.perform_hdbscan_clustering(
                    project,
                    sources,
                    list(row["pros_emb"]),
                    list(row["pros_info"]),
                    **parameters,
                )
            )
            del labels
            results.append(
                {
                    "pros_name": project,
                    "clusters": clusters,
                    "clustering_metadata": metadata,
                }
            )
        return results

    @staticmethod
    def save_cluster_results(
        cluster_results: list[dict[str, Any]],
        output_path: str,
    ) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as stream:
            pickle.dump(cluster_results, stream)
        logger.info("HDBSCAN 聚类结果已保存到: %s", output_path)

    @staticmethod
    def run_clustering(
        embedding_file: str,
        cluster_result_path: str,
        **parameters: Any,
    ) -> None:
        logger.info("=" * 60)
        logger.info("HDBSCAN 代码习语聚类")
        logger.info("=" * 60)
        data = HDBSCANClusteringProcessor.load_pkl(embedding_file)
        results = HDBSCANClusteringProcessor.process_projects(
            data,
            **parameters,
        )
        HDBSCANClusteringProcessor.save_cluster_results(
            results,
            cluster_result_path,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="HDBSCAN 代码习语聚类")
    parser.add_argument(
        "--input",
        "-i",
        default="outputs/library/cli11/stage2/embeddings.pkl",
        help="输入 embedding pickle",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="outputs/library/cli11/stage2/clusters-hdbscan.pkl",
        help="输出聚类 pickle",
    )
    parser.add_argument("--min-cluster-size", type=int, default=2)
    parser.add_argument("--min-samples", type=int, default=1)
    parser.add_argument(
        "--cluster-selection-method",
        choices=("eom", "leaf"),
        default="leaf",
    )
    parser.add_argument("--cluster-selection-epsilon", type=float, default=0.0)
    parser.add_argument("--pca-components", type=int, default=32)
    parser.add_argument("--pca-random-state", type=int, default=0)
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="关闭聚类前的 L2 归一化",
    )
    parser.add_argument(
        "--algorithm",
        choices=(
            "best",
            "generic",
            "prims_kdtree",
            "prims_balltree",
            "boruvka_kdtree",
            "boruvka_balltree",
        ),
        default="boruvka_kdtree",
    )
    parser.add_argument("--leaf-size", type=int, default=40)
    parser.add_argument("--core-dist-n-jobs", type=int, default=1)
    parser.add_argument(
        "--exact-min-span-tree",
        action="store_true",
        help="关闭近似最小生成树",
    )
    args = parser.parse_args()

    os.environ.setdefault("OMP_NUM_THREADS", "1")
    HDBSCANClusteringProcessor.run_clustering(
        embedding_file=args.input,
        cluster_result_path=args.output,
        min_cluster_size=args.min_cluster_size,
        min_samples=args.min_samples,
        cluster_selection_method=args.cluster_selection_method,
        cluster_selection_epsilon=args.cluster_selection_epsilon,
        normalize=not args.no_normalize,
        pca_components=args.pca_components,
        pca_random_state=args.pca_random_state,
        algorithm=args.algorithm,
        leaf_size=args.leaf_size,
        core_dist_n_jobs=args.core_dist_n_jobs,
        approx_min_span_tree=not args.exact_min_span_tree,
    )


if __name__ == "__main__":
    main()
