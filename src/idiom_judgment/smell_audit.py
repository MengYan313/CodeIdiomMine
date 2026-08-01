"""阶段3/4代码异味过滤的确定性事后审计。"""

from __future__ import annotations

import argparse
import json
import math
import pickle
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from ..common.logging import get_logger
from .smell_taxonomy import (
    SMELL_CATEGORIES,
    SMELL_CATEGORY_BY_ID,
    SMELL_REJECTION_THRESHOLD,
    SMELL_TAXONOMY_SOURCES,
)


logger = get_logger(__name__)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value if math.isfinite(float(value)) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _candidate_id(stage: int, record: Mapping[str, Any]) -> str:
    if stage == 3:
        return f"cluster:{record.get('cluster_id')}"
    selected = record.get("selected_candidate_ids") or []
    return "synthesis:" + ",".join(str(value) for value in selected)


def _audit_id(
    *,
    stage: int,
    project: str,
    candidate_id: str,
    review_input: Mapping[str, Any],
) -> str:
    del review_input
    return f"{stage}:{project}:{candidate_id}"


def extract_smell_audit_samples(
    artifact_paths: Iterable[str | Path],
) -> list[Dict[str, Any]]:
    """从阶段3/4当前 artifact 提取异味审查的完整输入、输出与门禁。"""

    samples: list[Dict[str, Any]] = []
    seen_ids = set()
    expected_types = {
        "idiom_judgment": 3,
        "idiom_synthesis": 4,
    }
    for raw_path in artifact_paths:
        path = Path(raw_path)
        with path.open("rb") as stream:
            artifact = pickle.load(stream)
        if not isinstance(artifact, Mapping):
            raise TypeError(f"{path} 必须是当前阶段3/4 artifact")
        artifact_type = str(artifact.get("artifact_type") or "")
        if artifact_type not in expected_types:
            raise ValueError(f"{path} 不属于阶段3/4语义 artifact")
        stage = expected_types[artifact_type]
        project = str(artifact.get("project") or "")
        for partition in ("accepted", "rejected"):
            records = artifact.get(partition) or []
            if not isinstance(records, list):
                raise TypeError(f"{path} 的 {partition} 必须为 list")
            for record in records:
                if not isinstance(record, Mapping):
                    continue
                smell = record.get("smell")
                gate = record.get("smell_gate")
                review_input = record.get("smell_review_input")
                if not all(
                    isinstance(value, Mapping)
                    for value in (smell, gate, review_input)
                ):
                    continue
                candidate_id = _candidate_id(stage, record)
                code = str(
                    review_input.get("candidate_code")
                    or record.get("center_point")
                    or ""
                )
                audit_id = _audit_id(
                    stage=stage,
                    project=project,
                    candidate_id=candidate_id,
                    review_input=review_input,
                )
                if audit_id in seen_ids:
                    continue
                seen_ids.add(audit_id)
                samples.append(
                    {
                        "audit_id": audit_id,
                        "stage": stage,
                        "project": project,
                        "candidate_id": candidate_id,
                        "result_status": str(record.get("status") or partition),
                        "candidate_code": code,
                        "related_examples": _json_safe(
                            review_input.get("related_examples") or []
                        ),
                        "deterministic_evidence": _json_safe(
                            review_input.get("deterministic_evidence") or {}
                        ),
                        "predicted": {
                            "analysis_status": str(
                                smell.get("analysis_status") or ""
                            ),
                            "risk_score": float(
                                smell.get("risk_score") or 0.0
                            ),
                            "categories": sorted(
                                {
                                    str(value)
                                    for value in (
                                        smell.get("categories") or []
                                    )
                                }
                            ),
                            "findings": _json_safe(
                                smell.get("findings") or []
                            ),
                            "filtered_by_smell": (
                                gate.get("trigger_kind") == "risk_threshold"
                            ),
                            "gate": _json_safe(gate),
                        },
                        "source_artifact": str(path),
                    }
                )
    return sorted(samples, key=lambda item: item["audit_id"])


def _sample_order(sample: Mapping[str, Any], seed: str) -> str:
    return f"{seed}:{sample['audit_id']}"


def _category_diverse_samples(
    samples: Sequence[Dict[str, Any]],
    *,
    budget: int,
) -> list[Dict[str, Any]]:
    """在稳定顺序内优先覆盖更多预测类别，再填满预算。"""

    if budget <= 0:
        return []
    selected: list[Dict[str, Any]] = []
    selected_ids = set()
    for category in SMELL_CATEGORY_BY_ID:
        for sample in samples:
            if (
                category
                in set(sample["predicted"].get("categories") or [])
                and sample["audit_id"] not in selected_ids
            ):
                selected.append(sample)
                selected_ids.add(sample["audit_id"])
                break
        if len(selected) >= budget:
            return selected
    for sample in samples:
        if sample["audit_id"] not in selected_ids:
            selected.append(sample)
            selected_ids.add(sample["audit_id"])
        if len(selected) >= budget:
            break
    return selected


def select_stratified_audit_samples(
    samples: Sequence[Dict[str, Any]],
    *,
    limit: int,
    seed: str,
) -> list[Dict[str, Any]]:
    """确定性平衡抽取被异味过滤、未过滤和审查失败样本。"""

    ordered = sorted(samples, key=lambda item: _sample_order(item, seed))
    if limit <= 0 or len(ordered) <= limit:
        return ordered
    filtered = [
        item
        for item in ordered
        if item["predicted"]["gate"].get("trigger_kind")
        == "risk_threshold"
    ]
    failures = [
        item
        for item in ordered
        if item["predicted"]["gate"].get("trigger_kind")
        == "analysis_failure"
    ]
    not_filtered = [
        item
        for item in ordered
        if item["predicted"]["gate"].get("trigger_kind") == "none"
    ]

    failure_budget = min(len(failures), limit // 10)
    remaining_budget = limit - failure_budget
    filtered_budget = min(len(filtered), (remaining_budget + 1) // 2)
    not_filtered_budget = min(
        len(not_filtered),
        remaining_budget - filtered_budget,
    )
    selected = (
        _category_diverse_samples(filtered, budget=filtered_budget)
        + _category_diverse_samples(
            not_filtered,
            budget=not_filtered_budget,
        )
        + failures[:failure_budget]
    )
    selected_ids = {item["audit_id"] for item in selected}

    for bucket in (not_filtered, filtered, failures[failure_budget:]):
        for item in bucket:
            if len(selected) >= limit:
                break
            if item["audit_id"] not in selected_ids:
                selected.append(item)
                selected_ids.add(item["audit_id"])
    return sorted(selected, key=lambda item: item["audit_id"])


def build_smell_audit_payload(
    artifact_paths: Iterable[str | Path],
    *,
    limit: int = 200,
    seed: str = "smell-audit",
) -> Dict[str, Any]:
    """生成可盲审的分层样本与人工标签模板。"""

    all_samples = extract_smell_audit_samples(artifact_paths)
    samples = select_stratified_audit_samples(
        all_samples,
        limit=limit,
        seed=seed,
    )
    trigger_counts = {
        trigger: sum(
            sample["predicted"]["gate"].get("trigger_kind") == trigger
            for sample in samples
        )
        for trigger in ("risk_threshold", "none", "analysis_failure")
    }
    category_counts = {
        category: sum(
            category in set(sample["predicted"].get("categories") or [])
            for sample in samples
        )
        for category in SMELL_CATEGORY_BY_ID
    }
    return {
        "smell_threshold": SMELL_REJECTION_THRESHOLD,
        "sampling": {
            "seed": seed,
            "limit": limit,
            "population_count": len(all_samples),
            "sample_count": len(samples),
            "trigger_counts": trigger_counts,
            "category_counts": category_counts,
        },
        "taxonomy": [
            _json_safe(category.__dict__) for category in SMELL_CATEGORIES
        ],
        "taxonomy_sources": list(SMELL_TAXONOMY_SOURCES),
        "samples": samples,
        "review_items": [
            {
                key: sample[key]
                for key in (
                    "audit_id",
                    "stage",
                    "project",
                    "candidate_id",
                    "candidate_code",
                    "related_examples",
                    "deterministic_evidence",
                )
            }
            for sample in samples
        ],
        "label_template": [
            {
                "audit_id": sample["audit_id"],
                "blocking_smell": None,
                "categories": [],
                "notes": "",
            }
            for sample in samples
        ],
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _classification_metrics(
    pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> Dict[str, Any]:
    tp = fp = tn = fn = 0
    for sample, label in pairs:
        predicted = bool(sample["predicted"]["filtered_by_smell"])
        actual = bool(label["blocking_smell"])
        if predicted and actual:
            tp += 1
        elif predicted:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return {
        "labeled_count": len(pairs),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "filter_precision": precision,
        "filter_recall": recall,
        "filter_f1": (
            round(2 * precision * recall / (precision + recall), 6)
            if precision + recall
            else 0.0
        ),
        "accuracy": _ratio(tp + tn, len(pairs)),
        "false_filter_rate": _ratio(fp, tp + fp),
        "miss_rate": _ratio(fn, tp + fn),
    }


def _category_metrics(
    pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    f1_values = []
    for category in SMELL_CATEGORY_BY_ID:
        tp = fp = fn = 0
        for sample, label in pairs:
            predicted = category in set(
                sample["predicted"].get("categories") or []
            )
            actual = category in set(label.get("categories") or [])
            if predicted and actual:
                tp += 1
            elif predicted:
                fp += 1
            elif actual:
                fn += 1
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        f1 = (
            round(2 * precision * recall / (precision + recall), 6)
            if precision + recall
            else 0.0
        )
        support = tp + fn
        definition = SMELL_CATEGORY_BY_ID[category]
        metrics[category] = {
            "family": definition.family,
            "name": definition.name,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "support": support,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        if support or tp + fp:
            f1_values.append(f1)
    metrics["_macro"] = {
        "evaluated_category_count": len(f1_values),
        "f1": (
            round(sum(f1_values) / len(f1_values), 6)
            if f1_values
            else 0.0
        ),
    }
    return metrics


def evaluate_smell_audit(
    samples_payload: Mapping[str, Any],
    labels_payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """计算过滤准确性、误过滤/漏报和逐类别 P/R/F1。"""

    samples = samples_payload.get("samples")
    labels = labels_payload.get("labels")
    if not isinstance(samples, list) or not isinstance(labels, list):
        raise TypeError("审计样本必须含 samples，人工标签必须含 labels")
    sample_by_id = {
        str(sample["audit_id"]): sample
        for sample in samples
        if isinstance(sample, Mapping) and sample.get("audit_id")
    }
    label_by_id: Dict[str, Mapping[str, Any]] = {}
    for label in labels:
        if not isinstance(label, Mapping) or not label.get("audit_id"):
            raise ValueError("每条人工标签都必须包含 audit_id")
        audit_id = str(label["audit_id"])
        if audit_id in label_by_id:
            raise ValueError(f"重复人工标签: {audit_id}")
        if not isinstance(label.get("blocking_smell"), bool):
            raise ValueError(f"{audit_id} 的 blocking_smell 必须为 boolean")
        categories = label.get("categories") or []
        if not isinstance(categories, list):
            raise ValueError(f"{audit_id} 的 categories 必须为 list")
        unknown = sorted(
            {str(value) for value in categories}
            - set(SMELL_CATEGORY_BY_ID)
        )
        if unknown:
            raise ValueError(f"{audit_id} 含未知异味类别: {unknown}")
        label_by_id[audit_id] = label

    unknown_label_ids = sorted(set(label_by_id) - set(sample_by_id))
    if unknown_label_ids:
        raise ValueError(f"人工标签引用未知 audit_id: {unknown_label_ids}")
    pairs = [
        (sample_by_id[audit_id], label)
        for audit_id, label in label_by_id.items()
        if sample_by_id[audit_id]["predicted"]["gate"].get("trigger_kind")
        != "analysis_failure"
    ]
    overall = _classification_metrics(pairs)
    by_stage = {}
    for stage in (3, 4):
        stage_pairs = [
            pair for pair in pairs if int(pair[0].get("stage") or 0) == stage
        ]
        by_stage[str(stage)] = {
            **_classification_metrics(stage_pairs),
            "categories": _category_metrics(stage_pairs),
        }
    return {
        "smell_threshold": samples_payload.get("smell_threshold"),
        "sample_count": len(samples),
        "provided_label_count": len(label_by_id),
        "evaluated_label_count": len(pairs),
        "missing_label_count": len(samples) - len(label_by_id),
        "analysis_failure_sample_count": sum(
            sample["predicted"]["gate"].get("trigger_kind")
            == "analysis_failure"
            for sample in samples
        ),
        "labeled_analysis_failure_excluded_count": sum(
            sample["predicted"]["gate"].get("trigger_kind")
            == "analysis_failure"
            and sample["audit_id"] in label_by_id
            for sample in samples
        ),
        "overall": {
            **overall,
            "categories": _category_metrics(pairs),
        },
        "by_stage": by_stage,
    }


def _read_json(path: str | Path) -> Mapping[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise TypeError(f"{path} 顶层必须为 JSON object")
    return data


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="准备或评价阶段3/4代码异味过滤人工审计"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="生成分层审计样本和标签模板")
    prepare.add_argument(
        "--artifact",
        action="append",
        required=True,
        help="阶段3或阶段4 artifact；可重复传入",
    )
    prepare.add_argument("--output", required=True, help="审计样本 JSON")
    prepare.add_argument("--limit", type=int, default=200)
    prepare.add_argument("--seed", default="smell-audit")

    evaluate = subparsers.add_parser("evaluate", help="评价人工标签")
    evaluate.add_argument("--samples", required=True, help="prepare 生成的 JSON")
    evaluate.add_argument(
        "--labels",
        required=True,
        help="含 labels 数组的人工标签 JSON",
    )
    evaluate.add_argument("--output", required=True, help="准确性报告 JSON")

    args = parser.parse_args()
    if args.command == "prepare":
        payload = build_smell_audit_payload(
            args.artifact,
            limit=args.limit,
            seed=args.seed,
        )
        _write_json(args.output, payload)
        logger.info("代码异味审计样本已写入: %s", args.output)
    else:
        report = evaluate_smell_audit(
            _read_json(args.samples),
            _read_json(args.labels),
        )
        _write_json(args.output, report)
        logger.info("代码异味审计报告已写入: %s", args.output)


if __name__ == "__main__":
    main()
