"""Baseline 产物的统一习语记录与指标合同。

各 baseline 都写出与现有判断阶段相同的 ``*_idiom.pkl`` 文件。这样评价器
只负责计算已经固定的九项指标，不需要按方法维护不同公式或数据分支。
"""

from __future__ import annotations

import json
import math
import pickle
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


FINAL_METRICS = (
    "IC_macro",
    "IC_micro",
    "IC",
    "ISP",
    "F1",
    "idiom_type_count",
    "avg_cluster_size",
    "avg_cross_file_support",
    "AvgAST",
)


def is_source_info(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 4
        and isinstance(value[3], dict)
    )


def unique_source_infos(values: Iterable[Sequence[Any]]) -> List[Sequence[Any]]:
    """按项目、文件和候选 extent 稳定去重来源证据。"""
    unique: Dict[tuple[str, str, str], Sequence[Any]] = {}
    for value in values:
        if not is_source_info(value):
            continue
        node_info = value[3]
        extent = str(node_info.get("extent") or value[2])
        key = (str(value[0]), str(value[1]), extent)
        unique.setdefault(key, value)
    return list(unique.values())


def average_node_value(infos: Sequence[Sequence[Any]], field: str) -> float:
    values = [
        float(info[3][field])
        for info in infos
        if is_source_info(info) and info[3].get(field) is not None
    ]
    return sum(values) / len(values) if values else 0.0


def make_idiom_record(
    *,
    center_point: str,
    source_infos: Iterable[Sequence[Any]],
    provenance: Mapping[str, Any],
    template: str | None = None,
    intent: str | None = None,
) -> Dict[str, Any]:
    """构造所有 baseline 共用的向后兼容判断阶段记录。"""
    infos = unique_source_infos(source_infos)
    if not center_point.strip():
        raise ValueError("center_point 不能为空")
    if not infos:
        raise ValueError("baseline 习语必须至少保留一条 source_info")

    representative = infos[0]
    node_info = representative[3]
    candidate_extent = str(node_info.get("extent") or representative[2])
    record: Dict[str, Any] = {
        "center_point": center_point,
        "info": representative,
        "source_infos": infos,
        "cnt": len(infos),
        "avg_ast_num": average_node_value(infos, "ast_num"),
        "avg_subtree_size": average_node_value(infos, "subtree_size"),
        "loc_label": (
            f"{representative[0]}-{representative[1]}-{candidate_extent}"
        ),
        "baseline_provenance": dict(provenance),
    }
    if template is not None:
        record["template"] = template
    if intent is not None:
        record["intent"] = intent
    return record


def write_project_idioms(
    output_dir: str | Path,
    project_name: str,
    idioms: Sequence[Mapping[str, Any]],
) -> Path:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{project_name}_idiom.pkl"
    with output_path.open("wb") as file:
        pickle.dump(list(idioms), file)
    return output_path


def write_run_manifest(output_dir: str | Path, manifest: Mapping[str, Any]) -> Path:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "baseline-manifest.json"
    output_path.write_text(
        json.dumps(dict(manifest), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path


def _validate_metric_group(group: Mapping[str, Any], location: str) -> None:
    missing = [metric for metric in FINAL_METRICS if metric not in group]
    if missing:
        raise ValueError(f"{location} 缺少指标: {', '.join(missing)}")
    for metric in FINAL_METRICS:
        value = group[metric]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{location}.{metric} 不是数值")
        if not math.isfinite(float(value)):
            raise ValueError(f"{location}.{metric} 不是有限数值")


def validate_metric_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """证明固定九项指标可在逐项目、仓库宏平均和全局层计算。"""
    projects = payload.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("评价结果没有逐项目指标")
    for index, project in enumerate(projects):
        if not isinstance(project, Mapping):
            raise ValueError(f"projects[{index}] 不是对象")
        _validate_metric_group(project, f"projects[{index}]")

    repository_macro = payload.get("repository_macro")
    global_metrics = payload.get("global")
    if not isinstance(repository_macro, Mapping):
        raise ValueError("评价结果缺少 repository_macro")
    if not isinstance(global_metrics, Mapping):
        raise ValueError("评价结果缺少 global")
    _validate_metric_group(repository_macro, "repository_macro")
    _validate_metric_group(global_metrics, "global")
    return {
        "metric_names": list(FINAL_METRICS),
        "project_count": len(projects),
        "validated_levels": ["project", "repository_macro", "global"],
    }
