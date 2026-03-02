"""
代码习语合成流水线

读取习语判定结果 result/cpp/{repo}_idiom.pkl，按 loc_label 分组，
对同组内代码习语两两尝试合成，将合成成功的结果保存到 result/cpp/{repo}_idiom_syn.pkl。
"""

import asyncio
import glob
import os
import pickle
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Any, Optional

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from autogen_core import SingleThreadedAgentRuntime, AgentId
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .idiom_synthesis_agent import IdiomSynthesisAgent, IdiomSynthesisRequest
from ..logger import get_logger

logger = get_logger(__name__)


def find_idiom_files(input_dir: str) -> List[tuple]:
    """
    查找所有 {repo}_idiom.pkl 文件

    Args:
        input_dir: 输入目录

    Returns:
        [(repo_name, file_path), ...]
    """
    pattern = os.path.join(input_dir, "*_idiom.pkl")
    files = glob.glob(pattern)
    result = []
    for f in files:
        basename = os.path.basename(f)
        # envoy_idiom.pkl -> envoy
        repo = basename.replace("_idiom.pkl", "")
        result.append((repo, f))
    return sorted(result)


def load_idioms(file_path: str) -> List[Dict[str, Any]]:
    """
    加载习语判定结果

    Args:
        file_path: {repo}_idiom.pkl 路径

    Returns:
        [{"center_point": str, "infos": list, "loc_label": str}, ...]
    """
    with open(file_path, "rb") as f:
        return pickle.load(f)


def group_by_loc_label(idioms: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    按 loc_label 分组

    Args:
        idioms: 习语列表

    Returns:
        {loc_label: [idiom1, idiom2, ...], ...}
    """
    groups = defaultdict(list)
    for idiom in idioms:
        loc = idiom.get("loc_label", "")
        groups[loc].append(idiom)
    return dict(groups)


async def run_synthesis(
    input_dir: str = "result/cpp",
    output_dir: str = "result/cpp",
    model: str = "gpt-4o-mini",
    delay_seconds: float = 1.0,
    repos: Optional[List[str]] = None,
    quiet: bool = False,
) -> Dict[str, int]:
    """
    对习语判定结果进行两两合成

    Args:
        input_dir: 习语判定结果目录（{repo}_idiom.pkl）
        output_dir: 合成结果输出目录（{repo}_idiom_syn.pkl）
        model: 使用的 LLM 模型
        delay_seconds: 每次 API 调用间隔（秒）
        repos: 指定要处理的项目列表，None 表示处理所有找到的 _idiom.pkl
        quiet: 是否静默模式

    Returns:
        各项目合成成功的数量统计
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("未设置 OPENAI_API_KEY 环境变量，请先配置")

    idiom_files = find_idiom_files(input_dir)
    if not idiom_files:
        logger.warning(f"未找到 *_idiom.pkl 文件: {input_dir}")
        return {}

    if repos is not None:
        repos_set = set(repos)
        idiom_files = [(r, p) for r, p in idiom_files if r in repos_set]

    os.makedirs(output_dir, exist_ok=True)

    # 初始化运行时和 Agent
    runtime = SingleThreadedAgentRuntime()
    model_client = OpenAIChatCompletionClient(
        model=model,
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL")
    )
    await runtime.register_factory(
        "synthesis_agent",
        lambda: IdiomSynthesisAgent(model_client)
    )
    runtime.start()

    stats = {}

    try:
        for repo, file_path in idiom_files:
            logger.info(f"\n处理项目: {repo} ({file_path})")

            idioms = load_idioms(file_path)
            if not idioms:
                logger.info(f"  无习语，跳过")
                stats[repo] = 0
                continue

            groups = group_by_loc_label(idioms)
            total_pairs = sum(
                len(list(combinations(g, 2)))
                for g in groups.values()
                if len(g) >= 2
            )
            logger.info(f"  习语数: {len(idioms)}, 分组数: {len(groups)}, 待尝试合成对数: {total_pairs}")

            synthesized = []
            pair_idx = 0

            for loc_label, group in groups.items():
                if len(group) < 2:
                    continue

                for (a, b) in combinations(group, 2):
                    pair_idx += 1
                    code1 = a["center_point"]
                    code2 = b["center_point"]

                    if not quiet:
                        logger.info(f"  合成 [{pair_idx}/{total_pairs}] loc={loc_label}: ...")

                    try:
                        request = IdiomSynthesisRequest(
                            code_snippet_1=code1,
                            code_snippet_2=code2
                        )
                        result = await runtime.send_message(
                            request,
                            recipient=AgentId("synthesis_agent", key="default")
                        )

                        if result.is_related and result.synthesized_code:
                            synthesized.append({
                                "center_point": result.synthesized_code,
                                "infos_1": a["infos"],
                                "infos_2": b["infos"],
                                "loc_label": loc_label,
                            })
                            if not quiet:
                                logger.info(f"    ✓ 合成成功 ({result.relation_type})")
                        else:
                            if not quiet:
                                logger.info(f"    ✗ 不相关")

                    except Exception as e:
                        logger.warning(f"    合成失败，跳过: {e}")

                    if delay_seconds > 0:
                        await asyncio.sleep(delay_seconds)

            output_path = os.path.join(output_dir, f"{repo}_idiom_syn.pkl")
            with open(output_path, "wb") as f:
                pickle.dump(synthesized, f)
            logger.info(f"  已保存 {len(synthesized)} 个合成习语到 {output_path}")
            stats[repo] = len(synthesized)

    finally:
        await runtime.stop()

    return stats


def run_synthesis_sync(
    input_dir: str = "result/cpp",
    output_dir: str = "result/cpp",
    model: str = "gpt-4o-mini",
    delay_seconds: float = 1.0,
    repos: Optional[List[str]] = None,
    quiet: bool = False,
):
    """
    运行习语合成的同步入口
    """
    stats = asyncio.run(run_synthesis(
        input_dir=input_dir,
        output_dir=output_dir,
        model=model,
        delay_seconds=delay_seconds,
        repos=repos,
        quiet=quiet,
    ))
    logger.info("\n习语合成完成，统计:")
    for repo, count in stats.items():
        logger.info(f"  {repo}: {count} 个合成习语")


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="对习语判定结果进行两两合成")
    parser.add_argument(
        "--input-dir", "-i",
        default="result/cpp",
        help="习语判定结果目录（包含 *_idiom.pkl）",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="result/cpp",
        help="合成结果输出目录",
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
        help="每次 API 调用间隔（秒）",
    )
    parser.add_argument(
        "--repos",
        nargs="*",
        default=None,
        help="指定要处理的项目（不指定则处理所有）",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="静默模式",
    )

    args = parser.parse_args()

    run_synthesis_sync(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        model=args.model,
        delay_seconds=args.delay,
        repos=args.repos if args.repos else None,
        quiet=args.quiet,
    )


# 模块运行命令（从项目根目录运行）：
# python -m src.agent.idiom_synthesis --input-dir result/cpp --output-dir result/cpp
# python -m src.agent.idiom_synthesis --repos envoy TrafficMonitor  # 仅处理指定项目

if __name__ == "__main__":
    main()
