"""复用既有 Agent 响应，按当前确定性策略重放阶段3裁决。"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ..common.logging import get_logger
from .pipeline import (
    IdiomJudgmentPipeline,
    build_judgment_scorecard,
    decide_judgment_status,
)
from .schema import build_judgment_artifact_from_records
from .smell_taxonomy import build_smell_gate


logger = get_logger(__name__)


def replay_judgment_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """保持 Agent 证据不变，只重算当前确定性裁决。"""

    replayed = dict(record)
    rules = dict(replayed["rules"])
    rules["warnings"] = [
        warning
        for warning in rules.get("warnings", [])
        if warning != "small_semantic_unit"
    ]
    evidence = dict(rules.get("evidence") or {})
    evidence.pop("semantic_action_count", None)
    rules["evidence"] = evidence
    replayed["rules"] = rules

    semantic = replayed.get("semantic")
    smell = replayed.get("smell")
    if semantic is None or smell is None:
        replayed["status"] = "rejected"
        replayed["decision_reason"] = (
            "缺少可复用的语义或异味审查结果，确定性重放保持拒绝。"
        )
        return replayed

    scorecard = build_judgment_scorecard(
        rule_score=float(rules["score"]),
        semantic_score=float(semantic["semantic_score"]),
        reuse_score=float(semantic["reuse_score"]),
    )
    status, reason = decide_judgment_status(
        rule_eligible=bool(rules["eligible_for_llm"]),
        rule_score=float(rules["score"]),
        semantic_is_idiom=bool(semantic["is_idiom"]),
        semantic_score=float(semantic["semantic_score"]),
        reuse_score=float(semantic["reuse_score"]),
    )
    smell_gate = build_smell_gate(
        analysis_status=str(smell["analysis_status"]),
        risk_score=float(smell["risk_score"]),
        max_severity=str(smell["max_severity"]),
        categories=list(smell["categories"]),
        finding_count=len(smell["findings"]),
    )
    if smell_gate["rejected"]:
        status = "rejected"
        if smell_gate["trigger_kind"] == "analysis_failure":
            reason = "代码异味审查失败，独立门禁采用安全拒绝。"
        else:
            categories = "、".join(smell["categories"]) or "未分类"
            reason = (
                f"代码异味风险分 {float(smell['risk_score']):.2f} "
                f"达到独立过滤阈值；类别：{categories}。"
            )
    replayed.update(
        {
            "status": status,
            "scorecard": scorecard,
            "smell_gate": smell_gate,
            "decision_reason": (
                f"{reason} 语义判断依据：{semantic['reason']} "
                f"异味审查依据：{smell['reason']}"
            ).strip(),
        }
    )
    return replayed


def replay_judgment_artifact(
    input_path: str,
    output_path: str,
    *,
    report_path: Optional[str] = None,
) -> Dict[str, Any]:
    """读取完整阶段3产物并写出零 LLM 调用的策略重放结果。"""

    source = Path(input_path)
    with source.open("rb") as stream:
        previous = pickle.load(stream)
    if previous.get("artifact_type") != "idiom_judgment":
        raise ValueError("输入必须是阶段3 idiom_judgment artifact")
    if previous.get("rule_only"):
        raise ValueError("确定性重放需要已经完成 Agent 审查的阶段3产物")

    records = [
        *previous.get("accepted", []),
        *previous.get("rejected", []),
        *previous.get("pending_llm", []),
    ]
    replayed_records = [replay_judgment_record(record) for record in records]
    project = str(previous["project"])
    artifact = build_judgment_artifact_from_records(
        project,
        replayed_records,
        rule_only=False,
    )
    contract = IdiomJudgmentPipeline().run_contract()
    artifact["input"] = {"replayed_from": str(source)}
    artifact["run"] = {
        "execution_mode": "deterministic_policy_replay",
        "llm_call_count": 0,
        "reused_semantic_review_count": sum(
            record.get("semantic") is not None for record in replayed_records
        ),
        "source_model": (previous.get("run") or {}).get("model", ""),
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        **contract,
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        pickle.dump(artifact, stream, protocol=pickle.HIGHEST_PROTOCOL)

    report = {
        "artifact_type": "idiom_judgment_replay_report",
        "project": project,
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
    logger.info("阶段3确定性重放完成: %s", artifact["summary"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="复用既有 Agent 响应，按当前确定性策略重放阶段3",
    )
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--output", "-o", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()
    replay_judgment_artifact(
        args.input,
        args.output,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()
