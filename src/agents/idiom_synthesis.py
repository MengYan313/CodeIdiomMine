"""
代码模板合成流水线（说明书 7.3 + 7.4）

读取 results/cpp/{repo}_idiom.pkl，按 loc_label 分组；每组内以首条习语为锚，
由规划合成 Agent 决策是否继续及本轮并入的候选，由代码组装 Agent 执行合并；
合并结果经 7.2 三 Agent 流水线再判定；合法则进入下一轮，最多合成 3 次（3 轮合并）。
"""

from __future__ import annotations

import asyncio
import glob
import os
import pickle
from collections import defaultdict
from typing import Any, Dict, List, Optional

from autogen_core import SingleThreadedAgentRuntime, AgentId

from ._base import create_model_client, load_project_env
from .base import register_agent
from .code_assembly_agent import (
    CodeAssemblyAgent,
    CodeAssemblyRequest,
)
from .judge_pipeline import CodeIdiomPipeline
from .planning_synthesis_agent import (
    PlanningSynthesisAgent,
    PlanningSynthesisRequest,
)
from ..common.logging import get_logger
from ..common.progress import progress

logger = get_logger(__name__)

load_project_env()

# 说明书 7.4：多轮合并迭代上限
MAX_SYNTHESIS_ITERATIONS = 3


def find_idiom_files(input_dir: str) -> List[tuple]:
    """查找所有 {repo}_idiom.pkl，返回 [(repo_name, path), ...]。"""
    pattern = os.path.join(input_dir, "*_idiom.pkl")
    files = glob.glob(pattern)
    result = []
    for f in files:
        basename = os.path.basename(f)
        repo = basename.replace("_idiom.pkl", "")
        result.append((repo, f))
    return sorted(result)


def load_idioms(file_path: str) -> List[Dict[str, Any]]:
    with open(file_path, "rb") as f:
        return pickle.load(f)


def group_by_loc_label(idioms: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for idiom in idioms:
        loc = idiom.get("loc_label", "")
        groups[loc].append(idiom)
    return dict(groups)


def _aggregate_sources(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """合并来源证据，并按出现次数计算节点规模的加权平均。"""
    infos = []
    cnt = 0
    ast_weighted_sum = 0.0
    ast_weight = 0
    subtree_weighted_sum = 0.0
    subtree_weight = 0
    for s in sources:
        source_infos = s.get("source_infos")
        if isinstance(source_infos, list) and source_infos:
            infos.extend(source_infos)
        else:
            info = s.get("info")
            if info is not None:
                infos.append(info)
        source_count = int(s.get("cnt", 0) or 0)
        cnt += source_count
        avg_ast_num = float(s.get("avg_ast_num", 0.0) or 0.0)
        if source_count > 0:
            ast_weighted_sum += avg_ast_num * source_count
            ast_weight += source_count
        avg_subtree_size = float(s.get("avg_subtree_size", 0.0) or 0.0)
        if avg_subtree_size > 0 and source_count > 0:
            subtree_weighted_sum += avg_subtree_size * source_count
            subtree_weight += source_count
    return {
        "source_infos": infos,
        "cnt": cnt,
        "avg_ast_num": ast_weighted_sum / ast_weight if ast_weight else 0.0,
        "avg_subtree_size": (
            subtree_weighted_sum / subtree_weight if subtree_weight else 0.0
        ),
    }


async def synthesize_group(
    loc_label: str,
    group: List[Dict[str, Any]],
    runtime: SingleThreadedAgentRuntime,
    judge: CodeIdiomPipeline,
    delay_seconds: float,
    quiet: bool,
) -> Optional[Dict[str, Any]]:
    """
    对同一 loc_label 下的一组已通过判定的习语做至多 MAX_SYNTHESIS_ITERATIONS 轮规划-组装-再判定。
    若从未出现合法合并，返回 None。
    """
    if len(group) < 2:
        return None

    pool: List[Dict[str, Any]] = list(group[1:])
    current = str(group[0].get("center_point") or "").strip()
    if not current:
        return None
    incorporated: List[Dict[str, Any]] = [group[0]]
    trace: List[Dict[str, Any]] = []
    successful_rounds = 0

    for iteration in range(MAX_SYNTHESIS_ITERATIONS):
        candidates = [
            str(r.get("center_point") or "").strip()
            for r in pool
        ]
        # 去掉空串条目，保持与 pool 下标一致：重建对齐列表
        paired = [(r, t) for r, t in zip(pool, candidates) if t]
        if not paired:
            break
        pool = [p[0] for p in paired]
        candidates = [p[1] for p in paired]

        plan = await runtime.send_message(
            PlanningSynthesisRequest(
                current_code=current,
                candidate_snippets=candidates,
                iteration_index=iteration,
                max_iterations=MAX_SYNTHESIS_ITERATIONS,
                loc_label=loc_label,
            ),
            recipient=AgentId("planning_synthesis_agent", key="default"),
        )
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        if plan.should_stop or not plan.selected_indices:
            trace.append(
                {
                    "iteration": iteration,
                    "stopped": True,
                    "reason": plan.reason,
                    "selected_indices": plan.selected_indices,
                }
            )
            break

        idx_set = {i for i in plan.selected_indices if 0 <= i < len(pool)}
        if not idx_set:
            trace.append(
                {
                    "iteration": iteration,
                    "stopped": True,
                    "reason": "invalid_indices",
                    "selected_indices": plan.selected_indices,
                }
            )
            break

        ordered_idx = sorted(idx_set)
        segments = [pool[i].get("center_point", "") for i in ordered_idx]
        asm = await runtime.send_message(
            CodeAssemblyRequest(base_code=current, segments_to_merge=segments),
            recipient=AgentId("code_assembly_agent", key="default"),
        )
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        merged = (asm.merged_code or "").strip()
        if not merged:
            trace.append(
                {
                    "iteration": iteration,
                    "assemble_failed": True,
                    "reason": asm.reason,
                }
            )
            break

        verdict = await judge.evaluate(merged)
        valid = bool(verdict["final_judgment"]["is_idiom"])
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        trace.append(
            {
                "iteration": iteration,
                "selected_indices": ordered_idx,
                "plan_reason": plan.reason,
                "assemble_reason": asm.reason,
                "post_merge_valid": valid,
            }
        )

        if not valid:
            break

        successful_rounds += 1
        current = merged
        for i in sorted(idx_set, reverse=True):
            incorporated.append(pool.pop(i))

    if successful_rounds == 0:
        return None

    meta = _aggregate_sources(incorporated)
    return {
        "center_point": current,
        "loc_label": loc_label,
        "info": meta["source_infos"][0] if meta["source_infos"] else None,
        "source_infos": meta["source_infos"],
        "cnt": meta["cnt"],
        "avg_ast_num": meta["avg_ast_num"],
        "avg_subtree_size": meta["avg_subtree_size"],
        "merge_rounds": successful_rounds,
        "synthesis_trace": trace,
    }


async def run_synthesis(
    input_dir: str = "results/cpp",
    output_dir: str = "results/cpp",
    model: Optional[str] = None,
    delay_seconds: float = 1.0,
    repos: Optional[List[str]] = None,
    quiet: bool = False,
) -> Dict[str, int]:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("未设置 OPENAI_API_KEY 环境变量，请先配置")

    idiom_files = find_idiom_files(input_dir)
    if not idiom_files:
        logger.warning("未找到 *_idiom.pkl 文件: %s", input_dir)
        return {}

    if repos is not None:
        want = set(repos)
        idiom_files = [(r, p) for r, p in idiom_files if r in want]

    os.makedirs(output_dir, exist_ok=True)

    runtime = SingleThreadedAgentRuntime()
    model_client = create_model_client(model)
    await register_agent(
        runtime,
        "planning_synthesis_agent",
        lambda: PlanningSynthesisAgent(model_client),
    )
    await register_agent(
        runtime,
        "code_assembly_agent",
        lambda: CodeAssemblyAgent(model_client),
    )
    runtime.start()

    judge = CodeIdiomPipeline(model=model, quiet=True)
    await judge.initialize()

    stats: Dict[str, int] = {}

    try:
        for repo, file_path in progress(
            idiom_files, desc="合成项目", unit="项目"
        ):
            logger.info("\n处理项目: %s (%s)", repo, file_path)
            idioms = load_idioms(file_path)
            if not idioms:
                logger.info("  无习语，跳过")
                stats[repo] = 0
                continue

            groups = group_by_loc_label(idioms)
            multi_groups = sum(1 for g in groups.values() if len(g) >= 2)
            logger.info(
                "  习语数: %d, 分组数: %d, 其中可合成组(>=2条): %d",
                len(idioms),
                len(groups),
                multi_groups,
            )

            synthesized: List[Dict[str, Any]] = []
            for loc_label, group in progress(
                groups.items(),
                total=len(groups),
                desc=f"合成 {repo}",
                unit="分组",
                leave=False,
            ):
                if len(group) < 2:
                    continue
                try:
                    rec = await synthesize_group(
                        loc_label,
                        group,
                        runtime,
                        judge,
                        delay_seconds,
                        quiet,
                    )
                    if rec:
                        synthesized.append(rec)
                        if not quiet:
                            logger.info(
                                "  ✓ loc 合成成功: %s (合并轮次=%s)",
                                loc_label[:80] + ("..." if len(loc_label) > 80 else ""),
                                rec.get("merge_rounds"),
                            )
                    elif not quiet:
                        logger.info(
                            "  — loc 未产生有效合成: %s",
                            loc_label[:80] + ("..." if len(loc_label) > 80 else ""),
                        )
                except Exception as e:
                    logger.warning("  组合成失败 loc=%s: %s", loc_label, e)

            out_path = os.path.join(output_dir, f"{repo}_idiom_syn.pkl")
            with open(out_path, "wb") as f:
                pickle.dump(synthesized, f)
            logger.info("  已保存 %d 条合成模板到 %s", len(synthesized), out_path)
            stats[repo] = len(synthesized)

    finally:
        await judge.shutdown()
        await runtime.stop()
        await runtime.close()
        await model_client.close()

    return stats


def run_synthesis_sync(
    input_dir: str = "results/cpp",
    output_dir: str = "results/cpp",
    model: Optional[str] = None,
    delay_seconds: float = 1.0,
    repos: Optional[List[str]] = None,
    quiet: bool = False,
):
    stats = asyncio.run(
        run_synthesis(
            input_dir=input_dir,
            output_dir=output_dir,
            model=model,
            delay_seconds=delay_seconds,
            repos=repos,
            quiet=quiet,
        )
    )
    logger.info("\n模板合成完成，统计:")
    for repo, count in stats.items():
        logger.info("  %s: %d 条", repo, count)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="7.3/7.4：规划合成 + 代码组装 + 再判定迭代（每区域最多 3 轮合并）"
    )
    parser.add_argument(
        "--input-dir",
        "-i",
        default="results/cpp",
        help="习语判定结果目录（*_idiom.pkl）",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default="results/cpp",
        help="合成输出目录（*_idiom_syn.pkl）",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="LLM 模型名（默认读取 OPENAI_MODEL_LOW）",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="各 Agent 调用之间的间隔（秒）",
    )
    parser.add_argument(
        "--repos",
        nargs="*",
        default=None,
        help="仅处理指定项目名",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="减少日志",
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


if __name__ == "__main__":
    main()
