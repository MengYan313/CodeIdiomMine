"""
代码习语聚类模块
使用 DBSCAN 算法进行基于密度的聚类
"""

import os
import pickle
from typing import List, Dict, Optional, Tuple

import torch
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.metrics import silhouette_score, pairwise_distances_argmin_min
from skopt import gp_minimize
from skopt.space import Real, Integer

from ..common.logging import get_logger
from ..common.progress import progress

# 创建日志记录器
logger = get_logger(__name__)


class ClusteringProcessor:
    """聚类处理器类"""
    
    @staticmethod
    def load_pkl(file_path: str, limit: int = -1) -> pd.DataFrame:
        """
        加载 pickle 文件
        
        Args:
            file_path: 文件路径
            limit: 限制加载的行数，-1 表示加载全部
            
        Returns:
            DataFrame
        """
        logger.info(f"加载数据文件: {file_path}")
        with open(file_path, "rb") as f:
            data = pickle.load(f)
        
        logger.info(f"数据类型: {type(data)}")
        logger.info(f"数据形状: {data.shape}")
        
        if isinstance(data, pd.DataFrame):
            logger.debug(f"数据前5行:\n{data.head()}")
            if limit != -1:
                data = data.iloc[:limit]
                logger.info(f"限制加载前 {limit} 行，当前形状: {data.shape}")
        
        return data
    
    @staticmethod
    def dense_clustering(embeddings: List[torch.Tensor]) -> Tuple[float, int]:
        """
        使用 DBSCAN 进行聚类，并通过贝叶斯优化选择最佳参数
        
        Args:
            embeddings: 嵌入向量列表
            
        Returns:
            (best_eps, best_min_samples) 最佳参数元组
        """
        # 将嵌入向量转换为 numpy 数组
        data = np.stack([tensor.numpy() if isinstance(tensor, torch.Tensor) else tensor 
                         for tensor in embeddings])
        data = np.squeeze(data)  # 移除大小为 1 的维度
        logger.info(f"嵌入数据形状: {data.shape}")
        
        def objective(params):
            """
            目标函数：最大化轮廓系数（返回负值因为优化器是最小化）
            """
            eps, min_samples = params
            dbscan = DBSCAN(eps=eps, min_samples=int(min_samples), metric='cosine')
            labels = dbscan.fit_predict(data)
            
            # 如果只有一个簇或全是噪声点，返回较大的惩罚值
            unique_labels = set(labels)
            if len(unique_labels) <= 1 or (len(unique_labels) == 2 and -1 in unique_labels):
                return 1.0  # 返回较大的惩罚值
            
            score = silhouette_score(data, labels)
            return -score  # 返回负值以实现最大化
        
        # 定义参数空间
        space = [
            Real(0.01, 0.5, name='eps'),  # eps 参数范围
            Integer(2, 10, name='min_samples')  # min_samples 参数范围
        ]
        
        # 使用贝叶斯优化
        logger.info("开始贝叶斯优化...")
        result = gp_minimize(objective, space, n_calls=50, random_state=0)
        
        best_eps, best_min_samples = result.x
        best_score = -result.fun
        
        logger.info(f"优化结果:")
        logger.info(f"  最佳 eps: {best_eps:.4f}")
        logger.info(f"  最佳 min_samples: {best_min_samples}")
        logger.info(f"  最佳轮廓系数: {best_score:.4f}")
        
        return best_eps, best_min_samples
    
    @staticmethod
    def perform_dbscan_clustering(
        pro_name: str,
        pro_src: List[str],
        pro_emb: List[torch.Tensor],
        pro_info: List[List],
        eps: float = 0.5,
        min_samples: int = 2,
        optimize_params: bool = False
    ) -> Tuple[np.ndarray, pd.DataFrame]:
        """
        执行 DBSCAN 聚类并分析结果
        
        Args:
            pro_name: 项目名称
            pro_src: 代码片段列表
            pro_emb: 嵌入向量列表
            pro_info: 信息列表
            eps: DBSCAN 的 eps 参数
            min_samples: DBSCAN 的 min_samples 参数
            optimize_params: 是否优化参数
            
        Returns:
            (cluster_labels, cluster_data) 聚类标签和聚类数据
        """
        # 转换嵌入向量为 numpy 数组
        data = np.stack([tensor.numpy() if isinstance(tensor, torch.Tensor) else tensor 
                         for tensor in pro_emb])
        data = np.squeeze(data)
        
        # 如果需要优化参数
        if optimize_params:
            logger.info(f"优化项目 {pro_name} 的聚类参数...")
            eps, min_samples = ClusteringProcessor.dense_clustering(pro_emb)
        
        # 执行 DBSCAN 聚类
        logger.info(f"执行 DBSCAN 聚类 (eps={eps:.4f}, min_samples={min_samples})...")
        dbscan = DBSCAN(eps=eps, min_samples=min_samples, metric='cosine')
        cluster_labels = dbscan.fit_predict(data)
        
        unique_labels = set(cluster_labels)
        num_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
        num_noise = list(cluster_labels).count(-1)
        
        logger.info(f"聚类结果: {num_clusters} 个簇, {num_noise} 个噪声点")
        
        # 构建聚类数据
        cluster_data = pd.DataFrame(columns=[
            'label', 'center_point', 'else_point', 'cluster_size',
            'center_point_info', 'infos', 'loc_label'
        ])
        
        for label in unique_labels:
            if label == -1:  # 跳过噪声点
                continue
            
            # 获取当前簇的所有点
            cluster_indices = np.where(cluster_labels == label)[0]
            points_in_cluster = data[cluster_indices]
            srcs = [pro_src[i] for i in cluster_indices]
            infos = [pro_info[i] for i in cluster_indices]
            
            # 计算簇中心
            centroid = np.mean(points_in_cluster, axis=0)
            
            # 找到最接近中心的点（频繁习语）
            # 查询方向必须是“一个质心 -> 全部簇成员”。反向调用会为每个
            # 簇成员都返回唯一目标（质心）的索引 0，最终总是误选第一个成员。
            closest_point_idx, _ = pairwise_distances_argmin_min(
                np.array([centroid]), points_in_cluster, metric='cosine'
            )
            
            if len(closest_point_idx) > 0 and infos:
                closest_point_info = infos[closest_point_idx[0]]
                closest_point_str = srcs[closest_point_idx[0]]
                
                # 构建位置标签
                loc1 = closest_point_info[0]  # 项目名
                loc2 = closest_point_info[1]  # 文件名
                loc3 = closest_point_info[2]  # 代码段位置
                loc_label = f"{loc1}-{loc2}-{loc3}"
                
                # 获取其他代码片段
                else_point = [src for i, src in enumerate(srcs) 
                             if i != closest_point_idx[0]]
            else:
                closest_point_str = None
                closest_point_info = None
                else_point = []
                loc_label = ""
            
            # 添加到聚类数据
            cluster_data.loc[len(cluster_data.index)] = [
                label,
                closest_point_str,
                else_point,
                len(points_in_cluster),
                closest_point_info,
                infos,
                loc_label
            ]
            
            if closest_point_str:
                logger.info(f"  簇 {label} (大小: {len(points_in_cluster)}):")
                logger.info(f"{closest_point_str}")
        
        return cluster_labels, cluster_data
    
    @staticmethod
    def clustering(
        pro_name: str,
        pro_src: List[str],
        pro_emb: List[torch.Tensor],
        pro_info: List[List],
        eps: float = 0.5,
        min_samples: int = 2,
        optimize_params: bool = False
    ) -> pd.DataFrame:
        """
        对单个项目进行聚类
        
        Args:
            pro_name: 项目名称
            pro_src: 代码片段列表
            pro_emb: 嵌入向量列表
            pro_info: 信息列表
            eps: DBSCAN eps 参数
            min_samples: DBSCAN min_samples 参数
            optimize_params: 是否优化参数
            
        Returns:
            聚类结果 DataFrame
        """
        cluster_labels, cluster_data = ClusteringProcessor.perform_dbscan_clustering(
            pro_name, pro_src, pro_emb, pro_info, eps, min_samples, optimize_params
        )
        return cluster_data
    
    @staticmethod
    def process_projects(
        data: pd.DataFrame,
        eps: float = 0.5,
        min_samples: int = 2,
        optimize_params: bool = False
    ) -> List[Dict]:
        """
        处理所有项目的聚类
        
        Args:
            data: 包含嵌入数据的 DataFrame
            eps: DBSCAN eps 参数
            min_samples: DBSCAN min_samples 参数
            optimize_params: 是否优化参数
            
        Returns:
            聚类结果列表
        """
        pros_name = data['pros_name']
        pros_src = data['pros_src']
        pros_emb = data['pros_emb']
        pros_info = data['pros_info']
        
        cluster_results = []
        
        for i, pro_name in enumerate(
            progress(pros_name, desc="聚类项目", unit="项目")
        ):
            logger.info(f"\n{'='*60}")
            logger.info(f"处理项目 [{i+1}/{len(pros_name)}]: {pro_name}")
            logger.info(f"{'='*60}")
            
            pro_src = pros_src[i]
            pro_emb = pros_emb[i]
            pro_info = pros_info[i]
            
            # 过滤无效代码片段
            if any("ToBeDetermined" in src for src in pro_src):
                logger.warning(f"跳过项目 {pro_name}（包含无效代码片段）")
                continue
            
            # 执行聚类
            cluster_data = ClusteringProcessor.clustering(
                pro_name, pro_src, pro_emb, pro_info, eps, min_samples, optimize_params
            )
            
            # 统计信息
            num_clusters = len(cluster_data['label'].unique())
            avg_cluster_size = cluster_data['cluster_size'].mean() if len(cluster_data) > 0 else 0
            top100_clusters = cluster_data.nlargest(100, 'cluster_size')
            
            logger.info(f"\n项目 {pro_name} 聚类统计:")
            logger.info(f"  簇数量: {num_clusters}")
            logger.info(f"  平均簇大小: {avg_cluster_size:.2f}")
            logger.info(f"  前 100 个习语:")
            for idx, row in top100_clusters.iterrows():
                snippet = row['center_point'] if row['center_point'] else "None"
                logger.info(f"    簇 {row['label']} (大小: {row['cluster_size']}):")
                logger.info(f"{snippet}")
            
            # 保存结果
            cluster_results.append({
                "pros_name": pro_name,
                "clusters": cluster_data
            })
        
        return cluster_results
    
    @staticmethod
    def save_cluster_results(cluster_results: List[Dict], output_path: str):
        """
        保存聚类结果
        
        Args:
            cluster_results: 聚类结果列表
            output_path: 输出文件路径
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, "wb") as f:
            pickle.dump(cluster_results, f)
        
        logger.info(f"聚类结果已保存到: {output_path}")
        logger.info(f"共 {len(cluster_results)} 个项目的聚类结果")
    
    @staticmethod
    def run_clustering(
        embedding_file: str,
        cluster_result_path: str,
        eps: float = 0.5,
        min_samples: int = 2,
        optimize_params: bool = False
    ):
        """
        运行聚类的完整流程
        
        Args:
            embedding_file: 嵌入数据文件路径
            cluster_result_path: 聚类结果输出路径
            eps: DBSCAN eps 参数
            min_samples: DBSCAN min_samples 参数
            optimize_params: 是否优化参数
        """
        logger.info("=" * 60)
        logger.info("代码习语聚类")
        logger.info("=" * 60)
        
        logger.info(f"加载嵌入数据: {embedding_file}")
        data = ClusteringProcessor.load_pkl(embedding_file)
        
        logger.info("开始聚类...")
        cluster_results = ClusteringProcessor.process_projects(data, eps, min_samples, optimize_params)
        
        ClusteringProcessor.save_cluster_results(cluster_results, cluster_result_path)
        logger.info("聚类完成！")


def main():
    """测试聚类功能"""
    import argparse
    
    parser = argparse.ArgumentParser(description='代码习语聚类')
    parser.add_argument(
        '--input', '-i',
        default='outputs/cli11/stage2/embeddings.pkl',
        help='输入的嵌入数据文件路径'
    )
    parser.add_argument(
        '--output', '-o',
        default='outputs/cli11/stage2/clusters-raw.pkl',
        help='输出的聚类结果文件路径'
    )
    parser.add_argument(
        '--eps', '-e',
        type=float,
        default=0.5,
        help='DBSCAN eps 参数'
    )
    parser.add_argument(
        '--min-samples', '-m',
        type=int,
        default=2,
        help='DBSCAN min_samples 参数'
    )
    parser.add_argument(
        '--optimize',
        action='store_true',
        help='是否优化聚类参数（使用贝叶斯优化）'
    )
    
    args = parser.parse_args()
    
    ClusteringProcessor.run_clustering(
        embedding_file=args.input,
        cluster_result_path=args.output,
        eps=args.eps,
        min_samples=args.min_samples,
        optimize_params=args.optimize
    )


if __name__ == "__main__":
    main()
