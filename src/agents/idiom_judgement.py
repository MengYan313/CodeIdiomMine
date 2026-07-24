"""
代码习语判定流水线

读取 mining 模块的聚类结果，对每个 center_point 进行代码习语判定，
将判定为习语的结果按项目保存到 results/cpp/{repo}_idiom.pkl。
"""

import asyncio
import contextlib
import os
import pickle
from io import StringIO
from typing import Any, Dict, List, Optional

from ._base import load_project_env
from .judge_pipeline import CodeIdiomPipeline
from ..common.logging import get_logger
from ..common.progress import progress

load_project_env()

logger = get_logger(__name__)


def load_clusters(clusters_path: str) -> List[Dict]:
    """
    加载聚类结果

    Args:
        clusters_path: clusters.pkl 文件路径

    Returns:
        聚类结果列表 [{"pros_name": str, "clusters": DataFrame}, ...]
    """
    logger.info(f"加载聚类数据: {clusters_path}")
    with open(clusters_path, "rb") as f:
        cluster_results = pickle.load(f)
    logger.info(f"共 {len(cluster_results)} 个项目")
    return cluster_results


def extract_center_points(cluster_data) -> List[Dict[str, Any]]:
    """
    从聚类 DataFrame 中提取所有 center_point 及其关联信息

    Args:
        cluster_data: 单个项目的聚类 DataFrame

    Returns:
        [{"center_point": str, "infos": list, "loc_label": str}, ...]
    """
    records = []
    for _, row in cluster_data.iterrows():
        center_point = row.get("center_point")
        if center_point is None or (isinstance(center_point, str) and not center_point.strip()):
            continue
        records.append({
            "center_point": center_point,
            "center_point_info": row.get("center_point_info"),
            "infos": row.get("infos", []),
            "loc_label": row.get("loc_label", ""),
        })
    return records


def simplify_infos(
    infos: List,
    representative_info: Optional[List] = None,
) -> Dict[str, Any]:
    """
    将嵌套的 infos 列表简化为紧凑的存储格式。

    infos 为聚类簇中所有代码片段的信息列表，每个元素形如 [pro_name, file_name, extent_root, node_info]，
    其中 node_info 为 dict，包含 ast_num 等字段。

    Args:
        infos: 原始 infos 嵌套列表

    Returns:
        {
            "info": 与 center_point 对应的代表性信息,
            "source_infos": 簇中全部来源信息,
            "cnt": 列表长度（习语出现次数）,
            "avg_ast_num": 各元素 node_info.ast_num 的平均值,
            "avg_subtree_size": 各元素完整子树节点数的平均值（若可用）
        }
    """
    if not infos:
        return {
            "info": representative_info,
            "source_infos": [],
            "cnt": 0,
            "avg_ast_num": 0.0,
            "avg_subtree_size": 0.0,
        }

    info = representative_info if representative_info is not None else infos[0]
    cnt = len(infos)

    ast_nums = []
    subtree_sizes = []
    for item in infos:
        if isinstance(item, (list, tuple)) and len(item) >= 4:
            node_info = item[3]
            if isinstance(node_info, dict):
                ast_nums.append(node_info.get("ast_num", 0))
                if node_info.get("subtree_size") is not None:
                    subtree_sizes.append(node_info["subtree_size"])
        elif isinstance(item, dict):
            ast_nums.append(item.get("ast_num", 0))
            if item.get("subtree_size") is not None:
                subtree_sizes.append(item["subtree_size"])

    avg_ast_num = sum(ast_nums) / len(ast_nums) if ast_nums else 0.0
    avg_subtree_size = (
        sum(subtree_sizes) / len(subtree_sizes) if subtree_sizes else 0.0
    )

    return {
        "info": info,
        "source_infos": list(infos),
        "cnt": cnt,
        "avg_ast_num": avg_ast_num,
        "avg_subtree_size": avg_subtree_size,
    }


async def judge_idioms(
    clusters_path: str,
    output_dir: str = "results/cpp",
    model: Optional[str] = None,
    delay_seconds: float = 1.0,
    limit_per_project: int = -1,
    quiet: bool = False,
) -> Dict[str, int]:
    """
    对聚类结果中的 center_point 进行习语判定并保存

    Args:
        clusters_path: clusters.pkl 路径
        output_dir: 输出目录，习语结果保存为 {output_dir}/{repo}_idiom.pkl
        model: 使用的 LLM 模型
        delay_seconds: 每次 API 调用间隔（秒），避免频率限制
        limit_per_project: 每个项目最多判定数量，-1 表示不限制
        quiet: 是否静默模式（抑制 pipeline 的详细输出）

    Returns:
        各项目判定为习语的数量统计
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("未设置 OPENAI_API_KEY 环境变量，请先配置")

    cluster_results = load_clusters(clusters_path)
    os.makedirs(output_dir, exist_ok=True)

    pipeline = CodeIdiomPipeline(model=model)
    await pipeline.initialize()

    stats = {}

    try:
        for i, item in enumerate(
            progress(cluster_results, desc="判断项目", unit="项目")
        ):
            pros_name = item["pros_name"]
            clusters = item["clusters"]

            records = extract_center_points(clusters)
            if limit_per_project > 0:
                records = records[:limit_per_project]

            logger.info(f"\n处理项目 [{i+1}/{len(cluster_results)}]: {pros_name}，共 {len(records)} 个 center_point")

            idioms = []
            for j, rec in enumerate(
                progress(
                    records,
                    desc=f"判断 {pros_name}",
                    unit="候选",
                    leave=False,
                )
            ):
                center_point = rec["center_point"]
                preview = center_point[:80] + "..." if len(center_point) > 80 else center_point
                logger.info(f"  判定 [{j+1}/{len(records)}]: {preview}")

                try:
                    if quiet:
                        with contextlib.redirect_stdout(StringIO()):
                            result = await pipeline.evaluate(center_point)
                    else:
                        result = await pipeline.evaluate(center_point)
                    if result["final_judgment"]["is_idiom"]:
                        simplified = simplify_infos(
                            rec["infos"],
                            representative_info=rec.get("center_point_info"),
                        )
                        idioms.append({
                            "center_point": center_point,
                            "info": simplified["info"],
                            "source_infos": simplified["source_infos"],
                            "cnt": simplified["cnt"],
                            "avg_ast_num": simplified["avg_ast_num"],
                            "avg_subtree_size": simplified["avg_subtree_size"],
                            "loc_label": rec["loc_label"],
                        })
                        logger.info(f"    ✓ 判定为习语 (置信度: {result['final_judgment']['confidence']})")
                    else:
                        logger.info(f"    ✗ 非习语")
                except Exception as e:
                    logger.warning(f"    判定失败，跳过: {e}")

                if delay_seconds > 0 and j < len(records) - 1:
                    await asyncio.sleep(delay_seconds)

            output_path = os.path.join(output_dir, f"{pros_name}_idiom.pkl")
            with open(output_path, "wb") as f:
                pickle.dump(idioms, f)
            logger.info(f"  已保存 {len(idioms)} 个习语到 {output_path}")
            stats[pros_name] = len(idioms)

    finally:
        await pipeline.shutdown()

    return stats


def run_judgement(
    clusters_path: str = "outputs/cpp/clusters.pkl",
    output_dir: str = "results/cpp",
    model: Optional[str] = None,
    delay_seconds: float = 1.0,
    limit_per_project: int = -1,
    quiet: bool = False,
):
    """
    运行习语判定的同步入口

    Args:
        clusters_path: clusters.pkl 路径
        output_dir: 输出目录
        model: LLM 模型
        delay_seconds: API 调用间隔
        limit_per_project: 每项目判定数量上限，-1 表示不限制
        quiet: 是否静默模式
    """
    stats = asyncio.run(judge_idioms(
        clusters_path=clusters_path,
        output_dir=output_dir,
        model=model,
        delay_seconds=delay_seconds,
        limit_per_project=limit_per_project,
        quiet=quiet,
    ))
    logger.info("\n习语判定完成，统计:")
    for repo, count in stats.items():
        logger.info(f"  {repo}: {count} 个习语")


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="对聚类结果进行代码习语判定")
    parser.add_argument(
        "--input", "-i",
        default="outputs/cpp/clusters.pkl",
        help="聚类结果文件路径",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="results/cpp",
        help="习语结果输出目录",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="使用的 LLM 模型（默认读取 OPENAI_MODEL_LOW）",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="每次 API 调用间隔（秒），避免频率限制",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=-1,
        help="每个项目最多判定数量，-1 表示不限制（用于测试可设小值如 5）",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="静默模式，减少 pipeline 的详细输出",
    )

    args = parser.parse_args()

    run_judgement(
        clusters_path=args.input,
        output_dir=args.output_dir,
        model=args.model,
        delay_seconds=args.delay,
        limit_per_project=args.limit,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
