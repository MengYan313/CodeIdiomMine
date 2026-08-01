"""习语合成正式 CLI：消费阶段3习语判断产物。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import pickle
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..common.logging import get_logger
from ..common.progress import progress
from ..common.run_checkpoint import RunCheckpoint
from ..llm.config import load_project_env, resolve_model
from .pipeline import IdiomSynthesisPipeline
from .planning_agent import DEFAULT_MAX_PLANS_PER_REGION
from .schema import (
    IDIOM_SYNTHESIS_SCHEMA_VERSION,
    SynthesisResult,
    build_synthesis_artifact,
)
from .sources import group_related_idioms, load_idiom_candidates


logger = get_logger(__name__)


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _orchestration_failure_result(
    project: str,
    group: list,
) -> SynthesisResult:
    """记录当前组失败并允许后续组继续，不把技术失败伪装成业务判断。"""

    return SynthesisResult(
        project=project,
        status="rejected",
        selected=list(group),
        merged_code="",
        context_evidence={
            "available": False,
            "candidate_ids": [
                candidate.candidate_id for candidate in group
            ],
        },
        agent_trace={
            "orchestration": {
                "status": "failed",
                "logical_attempts": 0,
                "failure_kind": "unexpected_region_orchestration_error",
                "failure_action": "skip_region",
            }
        },
        decision_reason="候选区域编排发生未预料异常，已跳过该区域并继续运行。",
    )


async def synthesize_idioms(
    input_path: str,
    output_path: str,
    *,
    input_kind: str = "judgment",
    report_path: Optional[str] = None,
    source_root: Optional[str] = None,
    model: Optional[str] = None,
    max_groups: int = -1,
    max_group_candidates: int = 12,
    max_plans_per_region: int = DEFAULT_MAX_PLANS_PER_REGION,
    delay_seconds: float = 0.0,
    checkpoint_path: Optional[str] = None,
    resume: bool = False,
) -> Dict[str, Any]:
    run_started = time.monotonic()
    load_project_env()
    if resume and not checkpoint_path:
        raise ValueError("--resume 必须与 --checkpoint 一起使用")
    project, candidates, detected = load_idiom_candidates(
        input_path,
        input_kind=input_kind,
    )
    groups = group_related_idioms(candidates)
    if max_groups > 0:
        groups = groups[:max_groups]
    grouped_candidate_count = len(
        {
            candidate.candidate_id
            for group in groups
            for candidate in group
        }
    )
    region_candidate_membership_count = sum(map(len, groups))

    contract_only = detected == "stage2"
    if not contract_only and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("习语合成需要 OPENAI_API_KEY")
    input_digest = _sha256(Path(input_path))
    resolved_model = (
        "none_contract_only" if contract_only else resolve_model(model)
    )
    checkpoint = (
        RunCheckpoint(
            checkpoint_path,
            metadata={
                "stage": "idiom_synthesis",
                "schema_version": IDIOM_SYNTHESIS_SCHEMA_VERSION,
                "input_sha256": input_digest,
                "project": project,
                "input_kind": detected,
                "group_count": len(groups),
                "model": resolved_model,
                "source_root": str(Path(source_root).resolve())
                if source_root
                else "",
                "max_group_candidates": int(max_group_candidates),
                "max_plans_per_region": int(max_plans_per_region),
            },
            resume=resume,
        )
        if checkpoint_path and not contract_only
        else None
    )
    results_by_position = (
        checkpoint.load_records() if checkpoint is not None else {}
    )
    if any(position < 0 or position >= len(groups) for position in results_by_position):
        if checkpoint is not None:
            checkpoint.close()
        raise ValueError("checkpoint 含超出当前候选组范围的记录位置")

    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    run_contract: Dict[str, Any] = {
        "artifact_semantics": "synthesis_delta",
        "region_grouping": "member_source_region_cooccurrence",
        "decision_policy": {
            "calibration_status": "synthetic_smoke_only_pilot_required"
        },
        "max_group_candidates": max_group_candidates,
        "max_plans_per_region": max_plans_per_region,
        "planning_mode": "single_region_call_batched_plans",
    }
    if not contract_only:
        pipeline = IdiomSynthesisPipeline(
            model=model,
            max_group_candidates=max_group_candidates,
            max_plans_per_region=max_plans_per_region,
        )
        run_contract = pipeline.run_contract()
        try:
            for position, group in enumerate(
                progress(groups, desc=f"合成 {project}", unit="组")
            ):
                if position in results_by_position:
                    continue
                try:
                    region_results = await pipeline.synthesize(
                        group,
                        source_root=source_root,
                    )
                except Exception as exc:
                    logger.error(
                        "候选组编排失败，已记录拒绝并继续；error_type=%s",
                        type(exc).__name__,
                    )
                    region_results = [
                        _orchestration_failure_result(project, group)
                    ]
                results_by_position[position] = region_results
                if checkpoint is not None:
                    checkpoint.save_record(position, region_results)
                if delay_seconds > 0 and position < len(groups) - 1:
                    await asyncio.sleep(delay_seconds)
        finally:
            usage = pipeline.usage_snapshot()
            await pipeline.shutdown()
            if checkpoint is not None:
                checkpoint.close()

    results = (
        []
        if contract_only
        else [
            result
            for position in range(len(groups))
            for result in results_by_position[position]
        ]
    )
    artifact = build_synthesis_artifact(
        project,
        results,
        input_kind=detected,
        input_candidate_count=len(candidates),
        related_group_count=len(groups),
        grouped_candidate_count=grouped_candidate_count,
        region_candidate_membership_count=(
            region_candidate_membership_count
        ),
    )
    artifact["execution_status"] = (
        "contract_only_not_executed"
        if contract_only
        else "completed"
    )
    artifact["input"] = {
        "path": str(Path(input_path)),
        "sha256": input_digest,
        "candidate_count": len(candidates),
        "related_group_count": len(groups),
    }
    artifact["run"] = {
        "model": resolved_model,
        "calibration_status": "synthetic_smoke_only_pilot_required",
        "checkpoint_enabled": checkpoint is not None,
        "resumed": bool(resume),
        "elapsed_seconds": round(time.monotonic() - run_started, 6),
        "usage": usage,
        **run_contract,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        pickle.dump(artifact, stream, protocol=pickle.HIGHEST_PROTOCOL)

    report = {
        "schema_version": 1,
        "artifact_type": "idiom_synthesis_report",
        "project": project,
        "input_kind": detected,
        "execution_status": artifact["execution_status"],
        "input": artifact["input"],
        "output_path": str(output),
        "summary": artifact["summary"],
        "run": artifact["run"],
    }
    if report_path:
        report_output = Path(report_path)
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    if contract_only:
        logger.info(
            "阶段2合同适配完成，未执行阶段4 Agent: %s",
            report["summary"],
        )
    else:
        logger.info("习语合成完成: %s", report["summary"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "从完整簇成员位置发现同区域共现并执行规划、组装、"
            "有效性与类型复审"
        )
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="习语判断 artifact；阶段2仅保留适配合同测试",
    )
    parser.add_argument("--output", "-o", required=True, help="习语合成 PKL")
    parser.add_argument(
        "--input-kind",
        choices=("judgment",),
        default="judgment",
    )
    parser.add_argument("--report", help="不含源码的汇总 JSON")
    parser.add_argument(
        "--source-root",
        required=True,
        help="源码根；自动读取并验证成员共同出现的函数/区域上下文",
    )
    parser.add_argument("--model", "-m", default=None, help="默认使用低档模型")
    parser.add_argument("--max-groups", type=int, default=-1)
    parser.add_argument("--max-group-candidates", type=int, default=12)
    parser.add_argument(
        "--max-plans-per-region",
        type=int,
        default=DEFAULT_MAX_PLANS_PER_REGION,
        help="每个成员共现区域一次规划最多返回的语义计划数",
    )
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument(
        "--checkpoint",
        help="可选 SQLite checkpoint；逐区域持久化，避免重复已完成区域",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从 --checkpoint 续跑；输入和运行配置必须完全一致",
    )
    args = parser.parse_args()
    asyncio.run(
        synthesize_idioms(
            args.input,
            args.output,
            input_kind=args.input_kind,
            report_path=args.report,
            source_root=args.source_root,
            model=args.model,
            max_groups=args.max_groups,
            max_group_candidates=args.max_group_candidates,
            max_plans_per_region=args.max_plans_per_region,
            delay_seconds=args.delay,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
        )
    )


if __name__ == "__main__":
    main()
