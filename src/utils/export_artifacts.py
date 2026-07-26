"""将流水线 PKL 产物导出为适合人工分析的限量 JSON 视图。"""

from __future__ import annotations

import argparse
import gc
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

import pandas as pd
import torch


DATASET_COLUMNS = ["project", "cppFile", "func_ast", "func_src"]
EMBEDDING_COLUMNS = ["pros_name", "pros_src", "pros_emb", "pros_info"]
CLUSTER_COLUMNS = [
    "label",
    "center_point",
    "else_point",
    "cluster_size",
    "center_point_info",
    "infos",
    "loc_label",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _truncate_text(value: Any, limit: int) -> tuple[str, bool]:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_columns(data: pd.DataFrame, expected: Sequence[str], stage: str) -> None:
    actual = data.columns.tolist()
    if actual != list(expected):
        raise ValueError(f"{stage} 列不符合契约: expected={list(expected)}, actual={actual}")


def _path_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "resolved_path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).astimezone().isoformat(timespec="seconds"),
    }


def _safe_node_info(info: Any) -> dict[str, Any]:
    if not isinstance(info, (list, tuple)) or len(info) < 4:
        return {}
    node = info[3] if isinstance(info[3], dict) else {}
    return {
        "project": info[0],
        "file": info[1],
        "function_extent": info[2],
        "node_extent": node.get("extent"),
        "kind": node.get("kind"),
        "ast_num": node.get("ast_num"),
        "depth": node.get("depth"),
        "spelling": node.get("spelling"),
    }


def export_dataset(
    input_path: Path,
    output_dir: Path,
    limit: int,
    text_limit: int,
) -> dict[str, Any]:
    data = pd.read_pickle(input_path)
    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"dataset 必须是 DataFrame，实际为 {type(data)!r}")
    _validate_columns(data, DATASET_COLUMNS, "dataset")

    preview: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    totals = Counter()
    root_kinds = Counter()

    for _, row in data.iterrows():
        project_counts = Counter()
        project_root_kinds = Counter()
        source_lengths: list[int] = []

        for file_path, file_asts, file_sources in zip(
            row["cppFile"], row["func_ast"], row["func_src"]
        ):
            project_counts["files"] += 1
            for function_index, (function_ast, source) in enumerate(
                zip(file_asts, file_sources)
            ):
                root = function_ast[0] if function_ast else {}
                kind = root.get("kind") or "<unknown>"
                error_nodes = sum(
                    1 for node in function_ast if node.get("kind") == "ERROR"
                )
                project_counts["functions"] += 1
                project_counts["ast_nodes"] += len(function_ast)
                project_counts["error_nodes"] += error_nodes
                project_root_kinds[kind] += 1
                source_lengths.append(len(source))

                if len(preview) < limit:
                    source_preview, truncated = _truncate_text(source, text_limit)
                    preview.append(
                        {
                            "index": len(preview),
                            "project": row["project"],
                            "file": file_path,
                            "function_index_in_file": function_index,
                            "root_kind": kind,
                            "extent": root.get("extent"),
                            "node_count": len(function_ast),
                            "error_node_count": error_nodes,
                            "source_char_count": len(source),
                            "source_line_count": source.count("\n") + 1 if source else 0,
                            "source": source_preview,
                            "source_truncated": truncated,
                        }
                    )

        totals.update(project_counts)
        root_kinds.update(project_root_kinds)
        projects.append(
            {
                "project": row["project"],
                **project_counts,
                "error_node_rate": (
                    project_counts["error_nodes"] / project_counts["ast_nodes"]
                    if project_counts["ast_nodes"]
                    else 0.0
                ),
                "source_chars": {
                    "min": min(source_lengths) if source_lengths else 0,
                    "median": median(source_lengths) if source_lengths else 0,
                    "max": max(source_lengths) if source_lengths else 0,
                },
                "root_kind_counts": dict(project_root_kinds.most_common()),
            }
        )

    summary = {
        "stage": "dataset",
        "generated_at": _now_iso(),
        "input": _path_metadata(input_path),
        "schema": DATASET_COLUMNS,
        "totals": {
            **totals,
            "error_node_rate": (
                totals["error_nodes"] / totals["ast_nodes"]
                if totals["ast_nodes"]
                else 0.0
            ),
        },
        "root_kind_counts": dict(root_kinds.most_common()),
        "projects": projects,
        "preview": {
            "path": "dataset.preview.json",
            "limit": limit,
            "records": len(preview),
            "text_limit": text_limit,
        },
    }
    _write_json(output_dir / "dataset.summary.json", summary)
    _write_json(output_dir / "dataset.preview.json", preview)
    del data
    gc.collect()
    return summary


def _tensor_details(tensor: Any, vector_head: int) -> dict[str, Any]:
    value = tensor.detach().cpu() if isinstance(tensor, torch.Tensor) else torch.as_tensor(tensor)
    flattened = value.reshape(-1).to(dtype=torch.float64)
    return {
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "device": value.device.type,
        "l2_norm": float(torch.linalg.vector_norm(flattened).item()),
        "head": [float(item) for item in flattened[:vector_head].tolist()],
    }


def export_embeddings(
    input_path: Path,
    output_dir: Path,
    limit: int,
    text_limit: int,
    vector_head: int,
) -> dict[str, Any]:
    data = pd.read_pickle(input_path)
    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"embeddings 必须是 DataFrame，实际为 {type(data)!r}")
    _validate_columns(data, EMBEDDING_COLUMNS, "embeddings")

    preview: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    total_snippets = 0
    all_kinds = Counter()
    shapes = Counter()
    dtypes = Counter()
    devices = Counter()

    for _, row in data.iterrows():
        sources = row["pros_src"]
        embeddings = row["pros_emb"]
        infos = row["pros_info"]
        if not (len(sources) == len(embeddings) == len(infos)):
            raise ValueError(f"项目 {row['pros_name']} 的嵌入数据未对齐")

        project_kinds = Counter()
        source_lengths: list[int] = []
        finite_count = 0
        norms: list[float] = []

        for source, embedding, info in zip(sources, embeddings, infos):
            details = _tensor_details(embedding, vector_head)
            safe_info = _safe_node_info(info)
            kind = safe_info.get("kind") or "<unknown>"
            project_kinds[kind] += 1
            all_kinds[kind] += 1
            source_lengths.append(len(source))
            norms.append(details["l2_norm"])
            shapes[str(details["shape"])] += 1
            dtypes[details["dtype"]] += 1
            devices[details["device"]] += 1

            tensor = embedding if isinstance(embedding, torch.Tensor) else torch.as_tensor(embedding)
            finite_count += int(bool(torch.isfinite(tensor).all()))

            if len(preview) < limit:
                source_preview, truncated = _truncate_text(source, text_limit)
                preview.append(
                    {
                        "index": len(preview),
                        **safe_info,
                        "source_char_count": len(source),
                        "source_line_count": source.count("\n") + 1 if source else 0,
                        "source": source_preview,
                        "source_truncated": truncated,
                        "embedding": details,
                    }
                )

        total_snippets += len(sources)
        projects.append(
            {
                "project": row["pros_name"],
                "snippets": len(sources),
                "finite_embeddings": finite_count,
                "source_chars": {
                    "min": min(source_lengths) if source_lengths else 0,
                    "median": median(source_lengths) if source_lengths else 0,
                    "max": max(source_lengths) if source_lengths else 0,
                },
                "embedding_l2_norm": {
                    "min": min(norms) if norms else 0.0,
                    "median": median(norms) if norms else 0.0,
                    "max": max(norms) if norms else 0.0,
                },
                "kind_counts": dict(project_kinds.most_common()),
            }
        )

    summary = {
        "stage": "embeddings",
        "generated_at": _now_iso(),
        "input": _path_metadata(input_path),
        "schema": EMBEDDING_COLUMNS,
        "totals": {
            "projects": len(data),
            "snippets": total_snippets,
            "shape_counts": dict(shapes),
            "dtype_counts": dict(dtypes),
            "device_counts": dict(devices),
            "kind_counts": dict(all_kinds.most_common()),
        },
        "projects": projects,
        "preview": {
            "path": "embeddings.preview.json",
            "limit": limit,
            "records": len(preview),
            "text_limit": text_limit,
            "vector_head": vector_head,
        },
    }
    _write_json(output_dir / "embeddings.summary.json", summary)
    _write_json(output_dir / "embeddings.preview.json", preview)
    del data
    gc.collect()
    return summary


def _member_location_sample(infos: Iterable[Any], limit: int = 5) -> list[dict[str, Any]]:
    return [_safe_node_info(info) for info in list(infos)[:limit]]


def export_clusters(
    input_path: Path,
    output_dir: Path,
    top: int,
    text_limit: int,
    embedding_counts: dict[str, int] | None,
    eps: float | None,
    min_samples: int | None,
) -> dict[str, Any]:
    data = pd.read_pickle(input_path)
    if not isinstance(data, list):
        raise TypeError(f"clusters 必须是 list，实际为 {type(data)!r}")

    preview: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    total_clusters = 0
    total_members = 0

    for project_result in data:
        project = project_result.get("pros_name")
        clusters = project_result.get("clusters")
        if not isinstance(clusters, pd.DataFrame):
            raise TypeError(f"项目 {project} 的 clusters 必须是 DataFrame")
        _validate_columns(clusters, CLUSTER_COLUMNS, f"clusters/{project}")

        ordered = clusters.sort_values(
            ["cluster_size", "label"], ascending=[False, True], kind="stable"
        )
        sizes = [int(size) for size in clusters["cluster_size"].tolist()]
        members = sum(sizes)
        input_snippets = embedding_counts.get(project) if embedding_counts else None
        representative_kinds = Counter()
        unique_files: set[str] = set()

        for rank, (_, row) in enumerate(ordered.head(top).iterrows(), start=1):
            center_info = _safe_node_info(row["center_point_info"])
            center_preview, truncated = _truncate_text(row["center_point"], text_limit)
            representative_kinds[center_info.get("kind") or "<unknown>"] += 1
            if center_info.get("file"):
                unique_files.add(center_info["file"])
            preview.append(
                {
                    "project": project,
                    "rank": rank,
                    "label": int(row["label"]),
                    "cluster_size": int(row["cluster_size"]),
                    "loc_label": row["loc_label"],
                    "center": center_info,
                    "center_source_char_count": len(row["center_point"] or ""),
                    "center_source": center_preview,
                    "center_source_truncated": truncated,
                    "member_locations_sample": _member_location_sample(row["infos"]),
                }
            )

        # 汇总的代表节点类型和文件覆盖应基于所有簇，而非 TopN。
        representative_kinds = Counter()
        unique_files = set()
        for info in clusters["center_point_info"]:
            safe_info = _safe_node_info(info)
            representative_kinds[safe_info.get("kind") or "<unknown>"] += 1
            if safe_info.get("file"):
                unique_files.add(safe_info["file"])

        project_summary: dict[str, Any] = {
            "project": project,
            "clusters": len(clusters),
            "clusters_size_ge_3": sum(size >= 3 for size in sizes),
            "clustered_members": members,
            "cluster_size": {
                "min": min(sizes) if sizes else 0,
                "median": median(sizes) if sizes else 0,
                "mean": members / len(sizes) if sizes else 0.0,
                "max": max(sizes) if sizes else 0,
                "top20": sorted(sizes, reverse=True)[:20],
            },
            "unique_center_files": len(unique_files),
            "representative_kind_counts": dict(representative_kinds.most_common()),
            "top_records": min(top, len(clusters)),
        }
        if input_snippets is not None:
            noise = input_snippets - members
            project_summary.update(
                {
                    "input_snippets": input_snippets,
                    "noise_inferred": noise,
                    "coverage_rate": members / input_snippets if input_snippets else 0.0,
                }
            )
        projects.append(project_summary)
        total_clusters += len(clusters)
        total_members += members

    summary = {
        "stage": "clusters",
        "generated_at": _now_iso(),
        "input": _path_metadata(input_path),
        "schema": CLUSTER_COLUMNS,
        "parameters": {"eps": eps, "min_samples": min_samples},
        "totals": {
            "projects": len(data),
            "clusters": total_clusters,
            "clustered_members": total_members,
        },
        "projects": projects,
        "preview": {
            "path": "clusters.top100.json" if top == 100 else "clusters.top.json",
            "top_per_project": top,
            "records": len(preview),
            "text_limit": text_limit,
        },
    }
    preview_name = "clusters.top100.json" if top == 100 else "clusters.top.json"
    _write_json(output_dir / "clusters.summary.json", summary)
    _write_json(output_dir / preview_name, preview)
    del data
    gc.collect()
    return summary


def _result_paths(
    result_dir: Path,
    stage: str,
    *,
    legacy_result_dir: Path | None = None,
) -> list[Path]:
    if stage == "judgment":
        paths = list(result_dir.glob("**/idiom-judgment.pkl"))
        legacy_root = legacy_result_dir or result_dir
        paths.extend(
            path for path in legacy_root.glob("*_idiom.pkl")
            if not path.name.endswith("_idiom_syn.pkl")
        )
    elif stage == "synthesis":
        paths = list(result_dir.glob("**/idiom-synthesis.pkl"))
        paths.extend(result_dir.glob("*_idiom_syn.pkl"))
    else:
        raise ValueError(f"未知 Agent 产物阶段: {stage}")
    paths = sorted(set(paths))
    if not paths:
        raise FileNotFoundError(f"{result_dir} 中没有 {stage} PKL 产物")
    return paths


def _load_result_records(
    path: Path,
    stage: str,
) -> tuple[list[dict[str, Any]], dict[str, int] | None]:
    payload = pd.read_pickle(path)
    if isinstance(payload, list):
        return payload, None

    expected_type = {
        "judgment": "idiom_judgment",
        "synthesis": "idiom_synthesis",
    }[stage]
    if not isinstance(payload, dict) or payload.get("artifact_type") != expected_type:
        raise TypeError(f"{path} 必须包含 {expected_type} artifact")
    records = payload.get("accepted")
    if not isinstance(records, list):
        raise TypeError(f"{path} 的 accepted 必须是 list")
    status_counts = {
        key: len(payload.get(key) or [])
        for key in ("accepted", "rejected", "pending_llm")
        if key in payload
    }
    return records, status_counts


def _finite_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(float(value)) else None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    number = _finite_number(value)
    if number is not None:
        return number
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def export_agent_results(
    result_dir: Path,
    output_dir: Path,
    stage: str,
    limit: int,
    text_limit: int,
    *,
    legacy_result_dir: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    paths = _result_paths(
        result_dir,
        stage,
        legacy_result_dir=legacy_result_dir,
    )
    required = {
        "judgment": {"center_point", "info", "cnt", "avg_ast_num", "loc_label"},
        "synthesis": {
            "center_point",
            "info",
            "source_infos",
            "cnt",
            "avg_ast_num",
            "loc_label",
            "merge_rounds",
            "synthesis_trace",
        },
    }[stage]
    current_required = {
        "judgment": {
            "source_infos",
            "rules",
            "abstraction_proposals",
            "approved_abstraction_ids",
            "abstraction_applied",
            "semantic",
            "semantic_review_input",
            "smell",
            "smell_gate",
            "smell_review_input",
            "agent_trace",
            "scorecard",
        },
        "synthesis": {
            "context_evidence",
            "synthesis_plan",
            "review",
            "smell",
            "smell_gate",
            "smell_review_input",
            "agent_trace",
            "scorecard",
        },
    }[stage]
    synthesis_stage = stage == "synthesis"
    preview: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    all_counts: list[int] = []
    all_ast_averages: list[float] = []
    all_merge_rounds: list[int] = []
    representative_kinds = Counter()

    for path in paths:
        records, status_counts = _load_result_records(path, stage)
        file_counts: list[int] = []
        file_ast_averages: list[float] = []
        file_merge_rounds: list[int] = []

        for record_index, record in enumerate(records):
            if not isinstance(record, dict):
                raise TypeError(f"{path} 的第 {record_index} 条记录不是 dict")
            record_required = (
                required | current_required
                if status_counts is not None
                else required
            )
            missing = record_required - record.keys()
            if missing:
                raise ValueError(f"{path} 的第 {record_index} 条缺少字段: {sorted(missing)}")

            info = _safe_node_info(record["info"])
            representative_kinds[info.get("kind") or "<unknown>"] += 1
            count = int(record["cnt"])
            ast_average = float(record["avg_ast_num"])
            file_counts.append(count)
            file_ast_averages.append(ast_average)
            all_counts.append(count)
            all_ast_averages.append(ast_average)
            if synthesis_stage:
                rounds = int(record["merge_rounds"])
                file_merge_rounds.append(rounds)
                all_merge_rounds.append(rounds)

            if len(preview) < limit:
                source, truncated = _truncate_text(record["center_point"], text_limit)
                item = {
                    "index": len(preview),
                    "artifact_file": path.name,
                    "record_index": record_index,
                    "center": info,
                    "loc_label": record["loc_label"],
                    "cnt": count,
                    "avg_ast_num": ast_average,
                    "source_char_count": len(record["center_point"] or ""),
                    "center_source": source,
                    "center_source_truncated": truncated,
                }
                if synthesis_stage:
                    item.update(
                        {
                            "merge_rounds": int(record["merge_rounds"]),
                            "source_info_count": len(record["source_infos"]),
                            "source_infos_sample": [
                                _safe_node_info(source_info)
                                for source_info in record["source_infos"][:5]
                            ],
                            "synthesis_trace": _json_safe(record["synthesis_trace"]),
                        }
                    )
                preview.append(item)

        artifact_summary: dict[str, Any] = {
            "file": _path_metadata(path),
            "records": len(records),
            "total_cnt": sum(file_counts),
            "avg_ast_num": {
                "min": min(file_ast_averages) if file_ast_averages else 0.0,
                "median": median(file_ast_averages) if file_ast_averages else 0.0,
                "max": max(file_ast_averages) if file_ast_averages else 0.0,
            },
        }
        if status_counts is not None:
            artifact_summary["status_counts"] = status_counts
        if synthesis_stage:
            artifact_summary["merge_rounds"] = {
                "min": min(file_merge_rounds) if file_merge_rounds else 0,
                "median": median(file_merge_rounds) if file_merge_rounds else 0,
                "max": max(file_merge_rounds) if file_merge_rounds else 0,
            }
        artifacts.append(artifact_summary)
        del records

    summary: dict[str, Any] = {
        "stage": stage,
        "generated_at": _now_iso(),
        "result_dir": str(result_dir),
        "required_fields": sorted(required),
        "totals": {
            "files": len(paths),
            "records": len(all_counts),
            "total_cnt": sum(all_counts),
            "avg_ast_num": {
                "min": min(all_ast_averages) if all_ast_averages else 0.0,
                "median": median(all_ast_averages) if all_ast_averages else 0.0,
                "max": max(all_ast_averages) if all_ast_averages else 0.0,
            },
            "representative_kind_counts": dict(representative_kinds.most_common()),
        },
        "artifacts": artifacts,
        "preview": {
            "path": f"{stage}.preview.json",
            "limit": limit,
            "records": len(preview),
            "text_limit": text_limit,
        },
    }
    if synthesis_stage:
        summary["totals"]["merge_rounds"] = {
            "min": min(all_merge_rounds) if all_merge_rounds else 0,
            "median": median(all_merge_rounds) if all_merge_rounds else 0,
            "max": max(all_merge_rounds) if all_merge_rounds else 0,
        }
    _write_json(output_dir / f"{stage}.summary.json", summary)
    _write_json(output_dir / f"{stage}.preview.json", preview)
    gc.collect()
    return summary, [_path_metadata(path) for path in paths]


def _write_readme(
    output_dir: Path,
    input_dir: Path,
    result_dir: Path,
    stages: Sequence[str],
    limit: int,
    cluster_top: int,
    text_limit: int,
    vector_head: int,
    cluster_eps: float | None,
    cluster_min_samples: int | None,
) -> None:
    files = {
        "dataset": "`dataset.summary.json` 与 `dataset.preview.json`",
        "embeddings": "`embeddings.summary.json` 与 `embeddings.preview.json`",
        "clusters": (
            "`clusters.summary.json` 与 "
            + ("`clusters.top100.json`" if cluster_top == 100 else "`clusters.top.json`")
        ),
        "judgment": "`judgment.summary.json` 与 `judgment.preview.json`",
        "synthesis": "`synthesis.summary.json` 与 `synthesis.preview.json`",
    }
    lines = [
        "# CodeIdiomMine 可读产物\n",
        "PKL 仍是流水线的唯一机器接口；本目录是可重新生成的人工分析视图。",
        "不要把这些限量预览当作下一阶段输入。\n",
        f"- 输入目录：`{input_dir}`",
        f"- Agent 结果目录：`{result_dir}`",
        f"- 解析/嵌入预览上限：{limit} 条",
        f"- 聚类预览上限：每项目 Top{cluster_top}",
        f"- 单段源码上限：{text_limit} 字符；截断记录带 `*_truncated=true`",
        "- 嵌入仅展示形状、dtype、设备、L2 范数和向量头部，完整 tensor 保留在 PKL",
        "",
        "## 文件",
        "",
    ]
    for stage in stages:
        lines.append(f"- {stage}: {files[stage]}")
    lines.extend(
        [
            "- `manifest.json`：输入文件、导出参数和生成文件索引",
            "",
            "## 重新生成",
            "",
            "```bash",
            ".venv/bin/python -m src.utils.export_artifacts \\",
            f"  --input-dir {input_dir} --output-dir {output_dir} \\",
            f"  --result-dir {result_dir} \\",
            f"  --stages {' '.join(stages)} \\",
            f"  --limit {limit} --cluster-top {cluster_top} \\",
            f"  --text-limit {text_limit} --vector-head {vector_head}"
            + (" \\" if cluster_eps is not None or cluster_min_samples is not None else ""),
            *(
                [
                    "  "
                    + " ".join(
                        part
                        for part in [
                            (
                                f"--cluster-eps {cluster_eps}"
                                if cluster_eps is not None
                                else ""
                            ),
                            (
                                f"--cluster-min-samples {cluster_min_samples}"
                                if cluster_min_samples is not None
                                else ""
                            ),
                        ]
                        if part
                    )
                ]
                if cluster_eps is not None or cluster_min_samples is not None
                else []
            ),
            "```",
            "",
        ]
    )
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def export_artifacts(
    input_dir: Path,
    output_dir: Path,
    stages: Sequence[str],
    result_dir: Path = Path("results/cpp"),
    limit: int = 100,
    cluster_top: int = 100,
    text_limit: int = 2000,
    vector_head: int = 8,
    cluster_eps: float | None = None,
    cluster_min_samples: int | None = None,
) -> dict[str, Any]:
    if limit < 1 or cluster_top < 1 or text_limit < 1 or vector_head < 0:
        raise ValueError("limit、cluster_top、text_limit 必须大于 0，vector_head 不得小于 0")

    requested_stages = set(stages)
    stages = [
        stage
        for stage in (
            "dataset",
            "embeddings",
            "clusters",
            "judgment",
            "synthesis",
        )
        if stage in requested_stages
    ]
    if not stages:
        raise ValueError("至少需要选择一个导出阶段")

    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, Any] = {}
    inputs: dict[str, Any] = {}
    embedding_counts: dict[str, int] | None = None

    if "dataset" in stages:
        path = input_dir / "dataset.pkl"
        print(f"导出 dataset: {path}")
        summaries["dataset"] = export_dataset(path, output_dir, limit, text_limit)
        inputs["dataset"] = _path_metadata(path)

    if "embeddings" in stages:
        path = input_dir / "embeddings.pkl"
        print(f"导出 embeddings: {path}")
        summaries["embeddings"] = export_embeddings(
            path, output_dir, limit, text_limit, vector_head
        )
        embedding_counts = {
            project["project"]: project["snippets"]
            for project in summaries["embeddings"]["projects"]
        }
        inputs["embeddings"] = _path_metadata(path)
    elif "clusters" in stages and (input_dir / "embeddings.pkl").exists():
        embedding_path = input_dir / "embeddings.pkl"
        embedding_data = pd.read_pickle(embedding_path)
        _validate_columns(embedding_data, EMBEDDING_COLUMNS, "embeddings")
        embedding_counts = {
            row["pros_name"]: len(row["pros_src"])
            for _, row in embedding_data.iterrows()
        }
        del embedding_data
        gc.collect()
        inputs["embeddings_reference"] = _path_metadata(embedding_path)

    if "clusters" in stages:
        path = input_dir / "clusters.pkl"
        print(f"导出 clusters: {path}")
        summaries["clusters"] = export_clusters(
            path,
            output_dir,
            cluster_top,
            text_limit,
            embedding_counts,
            cluster_eps,
            cluster_min_samples,
        )
        inputs["clusters"] = _path_metadata(path)

    for stage in ("judgment", "synthesis"):
        if stage in stages:
            artifact_root = input_dir if stage == "judgment" else result_dir
            print(f"导出 {stage}: {artifact_root}")
            summary, path_metadata = export_agent_results(
                artifact_root,
                output_dir,
                stage,
                limit,
                text_limit,
                legacy_result_dir=result_dir,
            )
            summaries[stage] = summary
            inputs[stage] = path_metadata

    preview_names = {
        "dataset": ["dataset.summary.json", "dataset.preview.json"],
        "embeddings": ["embeddings.summary.json", "embeddings.preview.json"],
        "clusters": [
            "clusters.summary.json",
            "clusters.top100.json" if cluster_top == 100 else "clusters.top.json",
        ],
        "judgment": ["judgment.summary.json", "judgment.preview.json"],
        "synthesis": ["synthesis.summary.json", "synthesis.preview.json"],
    }
    generated_files = [
        file_name for stage in stages for file_name in preview_names[stage]
    ]
    generated_files.extend(["README.md", "manifest.json"])
    manifest = {
        "format_version": 1,
        "generated_at": _now_iso(),
        "policy": {
            "canonical_format": "pickle",
            "readable_format": "json",
            "readable_outputs_are_pipeline_inputs": False,
        },
        "input_dir": str(input_dir),
        "result_dir": str(result_dir),
        "output_dir": str(output_dir),
        "stages": list(stages),
        "parameters": {
            "limit": limit,
            "cluster_top_per_project": cluster_top,
            "text_limit": text_limit,
            "vector_head": vector_head,
            "cluster_eps": cluster_eps,
            "cluster_min_samples": cluster_min_samples,
        },
        "inputs": inputs,
        "generated_files": generated_files,
    }
    _write_json(output_dir / "manifest.json", manifest)
    _write_readme(
        output_dir,
        input_dir,
        result_dir,
        stages,
        limit,
        cluster_top,
        text_limit,
        vector_head,
        cluster_eps,
        cluster_min_samples,
    )
    print(f"可读产物已保存到: {output_dir}")
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将流水线 PKL 导出为全量汇总 JSON 与限量分析预览"
    )
    parser.add_argument("--input-dir", type=Path, default=Path("outputs/cpp"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/cpp/readables")
    )
    parser.add_argument("--result-dir", type=Path, default=Path("results/cpp"))
    parser.add_argument(
        "--stages",
        nargs="+",
        choices=[
            "dataset",
            "embeddings",
            "clusters",
            "judgment",
            "synthesis",
        ],
        default=["dataset", "embeddings", "clusters"],
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--cluster-top", type=int, default=100)
    parser.add_argument("--text-limit", type=int, default=2000)
    parser.add_argument("--vector-head", type=int, default=8)
    parser.add_argument("--cluster-eps", type=float)
    parser.add_argument("--cluster-min-samples", type=int)
    args = parser.parse_args()

    export_artifacts(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        stages=args.stages,
        result_dir=args.result_dir,
        limit=args.limit,
        cluster_top=args.cluster_top,
        text_limit=args.text_limit,
        vector_head=args.vector_head,
        cluster_eps=args.cluster_eps,
        cluster_min_samples=args.cluster_min_samples,
    )


if __name__ == "__main__":
    main()
