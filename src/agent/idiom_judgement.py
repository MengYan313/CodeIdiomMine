"""
代码习语判定流水线

读取 mining 模块的聚类结果，对每个 center_point 进行代码习语判定，
将判定为习语的结果按项目保存到 result/cpp/{repo}_idiom.pkl。
"""

import asyncio
import contextlib
import os
import pickle
from io import StringIO
from pathlib import Path
from typing import List, Dict, Any

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from .test_multi_agent import CodeIdiomPipeline
from ..logger import get_logger

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
            "infos": row.get("infos", []),
            "loc_label": row.get("loc_label", ""),
        })
    return records


async def judge_idioms(
    clusters_path: str,
    output_dir: str = "result/cpp",
    model: str = "gpt-4o-mini",
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
        for i, item in enumerate(cluster_results):
            pros_name = item["pros_name"]
            clusters = item["clusters"]

            records = extract_center_points(clusters)
            if limit_per_project > 0:
                records = records[:limit_per_project]

            logger.info(f"\n处理项目 [{i+1}/{len(cluster_results)}]: {pros_name}，共 {len(records)} 个 center_point")

            idioms = []
            for j, rec in enumerate(records):
                center_point = rec["center_point"]
                logger.info(f"  判定 [{j+1}/{len(records)}]: {center_point[:80]}..." if len(center_point) > 80 else f"  判定 [{j+1}/{len(records)}]: {center_point}")

                try:
                    if quiet:
                        with contextlib.redirect_stdout(StringIO()):
                            result = await pipeline.evaluate(center_point)
                    else:
                        result = await pipeline.evaluate(center_point)
                    if result["final_judgment"]["is_idiom"]:
                        idioms.append({
                            "center_point": center_point,
                            "infos": rec["infos"],
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
    clusters_path: str = "output/cpp/clusters.pkl",
    output_dir: str = "result/cpp",
    model: str = "gpt-4o-mini",
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
        default="output/cpp/clusters.pkl",
        help="聚类结果文件路径",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="result/cpp",
        help="习语结果输出目录",
    )
    parser.add_argument(
        "--model", "-m",
        default="gpt-4o-mini",
        help="使用的 LLM 模型",
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


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.idiom_judgement --input output/cpp/clusters.pkl --output-dir result/cpp
# python -m src.agent.idiom_judgement --input output/cpp/clusters.pkl --limit 5  # 测试：每项目仅判定 5 个

if __name__ == "__main__":
    main()
