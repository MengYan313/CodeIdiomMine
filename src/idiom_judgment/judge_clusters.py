"""习语判断 CLI：阶段2单簇产物到过滤后的候选习语。"""

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
from .pipeline import IdiomJudgmentPipeline
from .schema import (
    IDIOM_JUDGMENT_SCHEMA_VERSION,
    ClusterCandidate,
    IdiomJudgmentResult,
    RuleAssessment,
    build_judgment_artifact,
)


logger = get_logger(__name__)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _orchestration_failure_result(
    candidate: ClusterCandidate,
) -> IdiomJudgmentResult:
    """把未预料的单簇编排异常转成可审计拒绝，使后续簇可以继续。"""

    support_count = len(candidate.source_infos) or len(
        candidate.member_codes
    )
    rules = RuleAssessment(
        eligible_for_llm=False,
        score=0.0,
        support_count=support_count,
        unique_source_count=len(set(candidate.member_codes)),
        unique_file_count=len(set(candidate.source_files)),
        exact_duplicate=False,
        cross_file=False,
        hard_failures=["orchestration_failure"],
        evidence={"failure_scope": "single_cluster"},
    )
    return IdiomJudgmentResult(
        candidate=candidate,
        rules=rules,
        proposals=[],
        status="rejected",
        template_code=candidate.representative_code,
        agent_trace={
            "orchestration": {
                "status": "failed",
                "logical_attempts": 0,
                "failure_kind": "unexpected_orchestration_error",
                "failure_action": "skip_cluster",
            }
        },
        decision_reason="单簇编排发生未预料异常，已跳过该簇并继续运行。",
    )


def load_single_repository_clusters(path: str | Path) -> tuple[str, Any]:
    input_path = Path(path)
    with input_path.open("rb") as stream:
        items = pickle.load(stream)
    if not isinstance(items, list) or len(items) != 1:
        raise ValueError("习语判断一次只接受一个仓库的 clusters.pkl")
    item = items[0]
    if not isinstance(item, dict) or "pros_name" not in item or "clusters" not in item:
        raise ValueError("clusters.pkl 不符合 [{pros_name, clusters}] 合同")
    return str(item["pros_name"]), item["clusters"]


async def judge_clusters(
    input_path: str,
    output_path: str,
    *,
    report_path: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = -1,
    delay_seconds: float = 0.0,
    rule_only: bool = False,
    source_root: Optional[str] = None,
    require_context: bool = False,
    checkpoint_path: Optional[str] = None,
    resume: bool = False,
) -> Dict[str, Any]:
    run_started = time.monotonic()
    load_project_env()
    if resume and not checkpoint_path:
        raise ValueError("--resume 必须与 --checkpoint 一起使用")
    if not rule_only and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("未设置 OPENAI_API_KEY；可先用 --rule-only 执行离线预检")

    project, clusters = load_single_repository_clusters(input_path)
    input_digest = _sha256(Path(input_path))
    rows = list(clusters.iterrows())
    if limit > 0:
        rows = rows[:limit]

    resolved_model = "none_rule_only" if rule_only else resolve_model(model)
    checkpoint = (
        RunCheckpoint(
            checkpoint_path,
            metadata={
                "stage": "idiom_judgment",
                "schema_version": IDIOM_JUDGMENT_SCHEMA_VERSION,
                "input_sha256": input_digest,
                "project": project,
                "row_count": len(rows),
                "rule_only": bool(rule_only),
                "model": resolved_model,
                "source_root": str(Path(source_root).resolve())
                if source_root
                else "",
                "require_context": bool(require_context),
            },
            resume=resume,
        )
        if checkpoint_path
        else None
    )
    results_by_position = (
        checkpoint.load_records() if checkpoint is not None else {}
    )
    resumed_record_count = len(results_by_position)
    if any(position < 0 or position >= len(rows) for position in results_by_position):
        if checkpoint is not None:
            checkpoint.close()
        raise ValueError("checkpoint 含超出当前输入范围的记录位置")

    pipeline = IdiomJudgmentPipeline(
        model=model,
        source_root=source_root,
        require_context=require_context,
    )
    run_contract = pipeline.run_contract()
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    try:
        for position, (_, row) in enumerate(
            progress(rows, desc=f"判断 {project}", unit="簇")
        ):
            if position in results_by_position:
                continue
            candidate = ClusterCandidate.from_cluster_row(project, row)
            try:
                result = await pipeline.evaluate(
                    candidate,
                    rule_only=rule_only,
                )
            except Exception as exc:
                logger.error(
                    "簇 %s 编排失败，已记录拒绝并继续；error_type=%s",
                    candidate.cluster_id,
                    type(exc).__name__,
                )
                result = _orchestration_failure_result(candidate)
            results_by_position[position] = result
            if checkpoint is not None:
                checkpoint.save_record(position, result)
            if (
                delay_seconds > 0
                and position < len(rows) - 1
                and not rule_only
            ):
                await asyncio.sleep(delay_seconds)
    finally:
        usage = pipeline.usage_snapshot()
        await pipeline.shutdown()
        if checkpoint is not None:
            checkpoint.close()

    results = [results_by_position[position] for position in range(len(rows))]
    artifact = build_judgment_artifact(project, results, rule_only=rule_only)
    artifact["artifact_type"] = "idiom_judgment"
    artifact["input"] = {
        "clusters_path": str(Path(input_path)),
        "clusters_sha256": input_digest,
    }
    artifact["run"] = {
        "model": resolved_model,
        "calibration_status": "synthetic_smoke_only_pilot_required",
        "checkpoint_enabled": checkpoint_path is not None,
        "resumed": bool(resume),
        "resumed_record_count": resumed_record_count,
        "require_context": bool(require_context),
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
        "artifact_type": "idiom_judgment_report",
        "project": project,
        "rule_only": rule_only,
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
    logger.info("习语判断完成: %s", report["summary"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "对单仓库聚类簇执行规则、保守抽象、语义、习语类型和异味审查"
        )
    )
    parser.add_argument("--input", "-i", required=True, help="阶段2 clusters.pkl")
    parser.add_argument("--output", "-o", required=True, help="习语判断 PKL")
    parser.add_argument("--report", help="不含源码的汇总 JSON")
    parser.add_argument("--model", "-m", default=None, help="默认使用低档模型")
    parser.add_argument("--limit", type=int, default=-1, help="最多处理的簇数")
    parser.add_argument("--delay", type=float, default=0.0, help="簇间延迟秒数")
    parser.add_argument(
        "--source-root",
        help="源码根；完整运行时自动加载并校验代表函数/区域上下文",
    )
    parser.add_argument(
        "--require-context",
        action="store_true",
        help="上下文缺失或哈希不匹配时零 LLM 调用并拒绝当前簇",
    )
    parser.add_argument(
        "--checkpoint",
        help="可选 SQLite checkpoint；逐簇持久化，避免中断后重复付费调用",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从 --checkpoint 续跑；输入和运行配置必须完全一致",
    )
    parser.add_argument(
        "--rule-only",
        action="store_true",
        help="只执行离线规则和抽象提案，结果标记为 pending_llm",
    )
    args = parser.parse_args()
    asyncio.run(
        judge_clusters(
            args.input,
            args.output,
            report_path=args.report,
            model=args.model,
            limit=args.limit,
            delay_seconds=args.delay,
            rule_only=args.rule_only,
            source_root=args.source_root,
            require_context=args.require_context,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
        )
    )


if __name__ == "__main__":
    main()
