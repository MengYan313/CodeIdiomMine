"""为 C++ 实验数据集生成可复算的源码、解析和候选统计。

本脚本只读取源码快照并调用 CodeIdiomMine 的 Tree-sitter Parser，不执行目标
仓库中的构建、安装、测试或二进制。单仓库分析会写出紧凑的 JSON 证据；汇总模式
只读取这些实际产物，不在报告中写死统计数字。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import resource
import statistics
import subprocess
import time
from typing import Any, Iterable, Mapping

import pandas as pd

from src.parser.ast_parser import ASTParser
from src.parser.candidates import QUALITY_PROFILE, select_candidates
from src.parser.file_scanner import FileScanner


SCHEMA_VERSION = 1
DATASET_EXTENSIONS = frozenset(
    {".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx"}
)
ENTITY_KINDS = {
    "class": frozenset({"class_specifier"}),
    "struct": frozenset({"struct_specifier"}),
    "enum": frozenset({"enum_specifier"}),
    "template": frozenset(
        {
            "template_declaration",
            "template_instantiation",
            "template_method",
            "template_function",
        }
    ),
    "lambda": frozenset({"lambda_expression"}),
    "namespace": frozenset({"namespace_definition"}),
    "type": frozenset(
        {
            "alias_declaration",
            "class_specifier",
            "concept_definition",
            "enum_specifier",
            "struct_specifier",
            "type_definition",
        }
    ),
    "include": frozenset({"preproc_include"}),
    "call": frozenset({"call_expression"}),
}
CLASS_LIKE_KINDS = frozenset({"class_specifier", "struct_specifier"})
PARSER_SOURCE_PATHS = (
    Path("src/parser/ast_parser.py"),
    Path("src/parser/candidates.py"),
    Path("src/parser/cpp_adapter.py"),
    Path("src/parser/file_scanner.py"),
    Path("src/parser/repo2data.py"),
    Path("src/parser/semantic_slicer.py"),
)
FORMAL_STATUSES = frozenset({"保留", "条件保留"})
HISTORICAL_STATUS = "阶段2后排除"
REMOVED_STATUS = "淘汰"
ANALYSIS_COMPLEXITY_TIERS = ("低", "中", "高")
ANALYSIS_COMPLEXITY_INDICATORS = (
    "effective_line_count",
    "selected_file_count",
    "candidate_count",
)
BUILD_FILE_SYSTEMS = {
    "BUILD": "Bazel",
    "BUILD.bazel": "Bazel",
    "BUCK": "Buck",
    "CMakeLists.txt": "CMake",
    "Makefile": "Make",
    "configure.ac": "Autotools",
    "meson.build": "Meson",
}


def _git_output(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repository), *arguments],
        text=True,
    ).strip()


def _iter_tree_nodes(root: Any) -> Iterable[Any]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _is_method(node: Any) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in CLASS_LIKE_KINDS:
            return True
        if parent.type in {"function_definition", "translation_unit"}:
            return False
        parent = parent.parent
    return False


def _decode_source(source: bytes) -> tuple[str, str]:
    try:
        return source.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return source.decode("latin-1"), "latin-1"


def _effective_line_count(text: str) -> int:
    """计算确定性的非空、非纯注释物理行数。

    该口径不尝试执行预处理器；字符串中的注释符通过一个轻量词法状态机保护。
    """
    count = 0
    in_block_comment = False
    for line in text.splitlines():
        index = 0
        has_code = False
        quote: str | None = None
        escaped = False
        while index < len(line):
            char = line[index]
            next_char = line[index + 1] if index + 1 < len(line) else ""
            if in_block_comment:
                if char == "*" and next_char == "/":
                    in_block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if quote is not None:
                has_code = True
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                index += 1
                continue
            if char in {'"', "'"}:
                quote = char
                has_code = True
                index += 1
                continue
            if char == "/" and next_char == "/":
                break
            if char == "/" and next_char == "*":
                in_block_comment = True
                index += 2
                continue
            if not char.isspace():
                has_code = True
            index += 1
        count += int(has_code)
    return count


def _relative_posix(path: Path, repository: Path) -> tuple[str, bool]:
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(repository.resolve(strict=True))
        return relative.as_posix(), False
    except (FileNotFoundError, ValueError):
        try:
            return path.relative_to(repository).as_posix(), True
        except ValueError:
            return path.as_posix(), True


def _call_name(node: Any) -> str:
    function = node.child_by_field_name("function")
    if function is None:
        return ""
    try:
        return function.text.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _include_target(node: Any) -> str:
    try:
        text = node.text.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else text


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _parser_source_digest() -> str:
    digest = hashlib.sha256()
    for path in PARSER_SOURCE_PATHS:
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


def analyze_repository(
    repository: Path,
    *,
    project: str,
    output_path: Path,
) -> dict[str, Any]:
    repository = repository.resolve()
    scanner = FileScanner()
    selected_paths = [Path(path) for path in scanner._scan_project_files(str(repository))]
    selected_paths.sort(key=lambda path: path.as_posix())

    all_supported_paths = sorted(
        (
            path
            for path in repository.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and path.suffix.lower() in DATASET_EXTENSIONS
        ),
        key=lambda path: path.as_posix(),
    )

    parser = ASTParser()
    started_at = time.perf_counter()
    files: list[dict[str, Any]] = []
    entity_counts: Counter[str] = Counter()
    candidate_counts: Counter[str] = Counter()
    basename_paths: defaultdict[str, list[str]] = defaultdict(list)
    include_targets: Counter[str] = Counter()
    call_targets: Counter[str] = Counter()
    error_categories: Counter[str] = Counter()
    source_totals: Counter[str] = Counter()
    parse_totals: Counter[str] = Counter()
    inventory_hash = hashlib.sha256()

    for path in selected_paths:
        relative_path, path_escape = _relative_posix(path, repository)
        basename_paths[path.name].append(relative_path)
        record: dict[str, Any] = {
            "path": relative_path,
            "basename": path.name,
            "path_escape": path_escape,
            "is_symlink": path.is_symlink(),
        }
        if path_escape:
            error_categories["path_escape"] += 1
        if path.is_symlink():
            error_categories["symlink_file"] += 1

        try:
            source = path.read_bytes()
        except Exception as exc:
            record.update(
                {
                    "status": "failed",
                    "failure_stage": "read",
                    "failure": type(exc).__name__,
                    "message": str(exc),
                }
            )
            error_categories["read_failure"] += 1
            parse_totals["failed_file_count"] += 1
            files.append(record)
            continue

        text, encoding = _decode_source(source)
        physical_lines = len(text.splitlines())
        effective_lines = _effective_line_count(text)
        source_sha256 = hashlib.sha256(source).hexdigest()
        source_totals.update(
            {
                "byte_count": len(source),
                "physical_line_count": physical_lines,
                "effective_line_count": effective_lines,
            }
        )
        if encoding != "utf-8":
            error_categories["encoding_fallback"] += 1
        inventory_hash.update(relative_path.encode("utf-8"))
        inventory_hash.update(b"\0")
        inventory_hash.update(source_sha256.encode("ascii"))
        inventory_hash.update(b"\n")

        tree = parser.parse_file(str(path), source_root=str(repository))
        if tree is None:
            diagnostics = dict(parser.last_file_diagnostics)
            record.update(
                {
                    "status": "failed",
                    "failure_stage": "parse",
                    "failure": diagnostics.get("failure", "parse_failure"),
                    "message": diagnostics.get("message", ""),
                    "encoding": encoding,
                    "byte_count": len(source),
                    "physical_line_count": physical_lines,
                    "effective_line_count": effective_lines,
                    "source_sha256": source_sha256,
                }
            )
            error_categories["parse_failure"] += 1
            parse_totals["failed_file_count"] += 1
            files.append(record)
            continue

        diagnostics = dict(parser.last_file_diagnostics)
        raw = diagnostics.get("raw", {})
        nodes = list(_iter_tree_nodes(tree.root_node))
        kind_counts = Counter(node.type for node in nodes)
        file_entities: dict[str, int] = {}
        for entity, kinds in ENTITY_KINDS.items():
            value = sum(kind_counts[kind] for kind in kinds)
            file_entities[entity] = value
            entity_counts[entity] += value
        raw_function_nodes = [
            node for node in nodes if node.type == parser.adapter.function_definition_kind
        ]
        method_count = sum(_is_method(node) for node in raw_function_nodes)
        file_entities["function_definition"] = len(raw_function_nodes)
        file_entities["method_definition"] = method_count
        entity_counts["function_definition"] += len(raw_function_nodes)
        entity_counts["method_definition"] += method_count

        for node in nodes:
            if node.type == "preproc_include":
                target = _include_target(node)
                if target:
                    include_targets[target] += 1
            elif node.type == "call_expression":
                name = _call_name(node)
                if name:
                    call_targets[name] += 1

        function_nodes = parser.get_function_nodes(tree, str(path))
        file_candidates: Counter[str] = Counter()
        semantic_slice_count = 0
        empty_function_source_count = 0
        for function_node in function_nodes:
            function_ast: list[dict[str, Any]] = []
            parser.traverse_ast(function_node, str(path), function_ast)
            parser.calculate_ast_num(function_ast)
            if not function_ast or not str(function_ast[0].get("code_snippet") or ""):
                empty_function_source_count += 1
            semantic_slice_count += (
                len(function_ast[0].get("semantic_slices", [])) if function_ast else 0
            )
            for candidate in select_candidates(
                function_ast,
                profile=QUALITY_PROFILE,
            ):
                key = (
                    "semantic_def_use"
                    if candidate.origin == "semantic_def_use"
                    else candidate.level
                )
                file_candidates[key] += 1
                candidate_counts[key] += 1

        error_count = int(raw.get("error_count", 0) or 0)
        missing_count = int(raw.get("missing_count", 0) or 0)
        macro_related = int(raw.get("macro_related_error_count", 0) or 0)
        if error_count or missing_count:
            error_categories[
                "preprocessor_or_macro"
                if macro_related
                else "syntax_or_recovery"
            ] += 1
        if int(raw.get("function_definition_count", 0) or 0) and not function_nodes:
            error_categories["key_entity_missing"] += 1
        if not function_nodes:
            error_categories["empty_function_output"] += 1
        if empty_function_source_count:
            error_categories["empty_function_source"] += empty_function_source_count

        parse_totals.update(
            {
                "parsed_file_count": 1,
                "clean_file_count": int(
                    not error_count and not missing_count
                ),
                "anomalous_file_count": int(bool(error_count or missing_count)),
                "recovered_file_count": int(
                    bool(diagnostics.get("recovery", {}).get("used"))
                ),
                "error_count": error_count,
                "missing_count": missing_count,
                "macro_related_error_count": macro_related,
                "ast_node_count": int(raw.get("node_count", 0) or 0),
                "significant_byte_count": int(
                    raw.get("significant_byte_count", 0) or 0
                ),
                "reliable_significant_byte_count": int(
                    raw.get("reliable_significant_byte_count", 0) or 0
                ),
                "selected_function_count": len(function_nodes),
                "semantic_slice_count": semantic_slice_count,
                "empty_function_source_count": empty_function_source_count,
            }
        )
        record.update(
            {
                "status": diagnostics.get("status", "unknown"),
                "encoding": encoding,
                "byte_count": len(source),
                "physical_line_count": physical_lines,
                "effective_line_count": effective_lines,
                "source_sha256": source_sha256,
                "error_count": error_count,
                "missing_count": missing_count,
                "macro_related_error_count": macro_related,
                "ast_coverage": float(raw.get("ast_coverage", 0.0) or 0.0),
                "recovery_used": bool(
                    diagnostics.get("recovery", {}).get("used")
                ),
                "selected_function_count": len(function_nodes),
                "semantic_slice_count": semantic_slice_count,
                "empty_function_source_count": empty_function_source_count,
                "entities": file_entities,
                "candidates": dict(sorted(file_candidates.items())),
            }
        )
        files.append(record)

    elapsed_seconds = time.perf_counter() - started_at
    for key in (
        "byte_count",
        "physical_line_count",
        "effective_line_count",
    ):
        source_totals.setdefault(key, 0)
    for key in (
        "parsed_file_count",
        "failed_file_count",
        "clean_file_count",
        "anomalous_file_count",
        "recovered_file_count",
        "error_count",
        "missing_count",
        "macro_related_error_count",
        "ast_node_count",
        "significant_byte_count",
        "reliable_significant_byte_count",
        "selected_function_count",
        "semantic_slice_count",
        "empty_function_source_count",
    ):
        parse_totals.setdefault(key, 0)
    attempted = len(selected_paths)
    parsed = parse_totals["parsed_file_count"]
    significant = parse_totals["significant_byte_count"]
    reliable = parse_totals["reliable_significant_byte_count"]
    basename_collisions = {
        basename: sorted(paths)
        for basename, paths in basename_paths.items()
        if len(paths) > 1
    }
    relative_paths = [record["path"] for record in files]
    deterministic_evidence = {
        "project": project,
        "commit": _git_output(repository, "rev-parse", "HEAD"),
        "parser_source_sha256": _parser_source_digest(),
        "source_inventory_sha256": inventory_hash.hexdigest(),
        "selected_relative_paths": relative_paths,
        "parse_counts": dict(sorted(parse_totals.items())),
        "entity_counts": dict(sorted(entity_counts.items())),
        "candidate_counts": dict(sorted(candidate_counts.items())),
        "error_categories": dict(sorted(error_categories.items())),
        "file_evidence": [
            {
                key: value
                for key, value in record.items()
                if key not in {"message"}
            }
            for record in files
        ],
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "repository": {
            "path": repository.as_posix(),
            "remote_url": _git_output(repository, "remote", "get-url", "origin"),
            "commit": _git_output(repository, "rev-parse", "HEAD"),
            "commit_date": _git_output(repository, "log", "-1", "--format=%cI"),
            "is_shallow": _git_output(
                repository, "rev-parse", "--is-shallow-repository"
            )
            == "true",
        },
        "configuration": {
            "scanner": "FileScanner current contract",
            "candidate_profile": QUALITY_PROFILE,
            "dataset_extensions": sorted(DATASET_EXTENSIONS),
            "codeidiommine_commit": _git_output(
                Path.cwd(), "rev-parse", "HEAD"
            ),
            "parser_source_sha256": _parser_source_digest(),
        },
        "source": {
            "all_supported_file_count": len(all_supported_paths),
            "selected_file_count": attempted,
            "scanner_excluded_supported_file_count": (
                len(all_supported_paths) - attempted
            ),
            **dict(sorted(source_totals.items())),
            "source_inventory_sha256": inventory_hash.hexdigest(),
        },
        "paths": {
            "unique_relative_path_count": len(set(relative_paths)),
            "duplicate_relative_path_count": (
                len(relative_paths) - len(set(relative_paths))
            ),
            "path_escape_count": sum(
                bool(record.get("path_escape")) for record in files
            ),
            "symlink_file_count": sum(
                bool(record.get("is_symlink")) for record in files
            ),
            "basename_collision_group_count": len(basename_collisions),
            "basename_collision_file_count": sum(
                len(paths) for paths in basename_collisions.values()
            ),
            "basename_collisions": basename_collisions,
        },
        "parse": {
            "attempted_file_count": attempted,
            **dict(sorted(parse_totals.items())),
            "file_success_rate": parsed / attempted if attempted else 0.0,
            "ast_coverage": reliable / significant if significant else 1.0,
            "elapsed_seconds": elapsed_seconds,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "entities": dict(sorted(entity_counts.items())),
        "candidates": dict(sorted(candidate_counts.items())),
        "relationships": {
            "include_occurrence_count": sum(include_targets.values()),
            "unique_include_target_count": len(include_targets),
            "call_occurrence_count": sum(call_targets.values()),
            "unique_call_target_count": len(call_targets),
            "namespace_definition_count": entity_counts["namespace"],
            "type_declaration_count": entity_counts["type"],
            "cross_file_binding_capability": "unavailable",
            "ambiguous_binding_policy": "record-capability-without-guessing",
        },
        "errors": {
            "categories": dict(sorted(error_categories.items())),
            "failed_files": [
                {
                    key: record.get(key)
                    for key in (
                        "path",
                        "failure_stage",
                        "failure",
                        "message",
                    )
                }
                for record in files
                if record.get("status") == "failed"
            ],
        },
        "output_integrity": {
            "file_record_count": len(files),
            "missing_file_record_count": attempted - len(files),
            "empty_function_output_file_count": error_categories[
                "empty_function_output"
            ],
            "empty_function_source_count": parse_totals[
                "empty_function_source_count"
            ],
            "invalid_json_count": 0,
        },
        "deterministic_digest": _canonical_digest(deterministic_evidence),
        "files": files,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    json.loads(output_path.read_text(encoding="utf-8"))
    report["output_integrity"]["json_valid"] = True
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def aggregate_reports(analysis_root: Path, output_path: Path) -> dict[str, Any]:
    reports = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(analysis_root.glob("*/analysis.json"))
    ]
    totals: Counter[str] = Counter()
    entities: Counter[str] = Counter()
    candidates: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    projects: list[dict[str, Any]] = []
    for report in reports:
        parse = report["parse"]
        source = report["source"]
        totals.update(
            {
                "project_count": 1,
                "selected_file_count": int(source["selected_file_count"]),
                "effective_line_count": int(source.get("effective_line_count", 0)),
                "attempted_file_count": int(parse["attempted_file_count"]),
                "parsed_file_count": int(parse.get("parsed_file_count", 0)),
                "failed_file_count": int(parse.get("failed_file_count", 0)),
                "significant_byte_count": int(
                    parse.get("significant_byte_count", 0)
                ),
                "reliable_significant_byte_count": int(
                    parse.get("reliable_significant_byte_count", 0)
                ),
                "error_count": int(parse.get("error_count", 0)),
                "missing_count": int(parse.get("missing_count", 0)),
                "selected_function_count": int(
                    parse.get("selected_function_count", 0)
                ),
                "elapsed_seconds": float(parse["elapsed_seconds"]),
            }
        )
        entities.update(report["entities"])
        candidates.update(report["candidates"])
        errors.update(report["errors"]["categories"])
        projects.append(
            {
                "project": report["project"],
                "commit": report["repository"]["commit"],
                "selected_file_count": source["selected_file_count"],
                "effective_line_count": source.get("effective_line_count", 0),
                "file_success_rate": parse["file_success_rate"],
                "ast_coverage": parse["ast_coverage"],
                "selected_function_count": parse.get(
                    "selected_function_count", 0
                ),
                "candidate_count": sum(report["candidates"].values()),
                "deterministic_digest": report["deterministic_digest"],
            }
        )
    attempted = totals["attempted_file_count"]
    significant = totals["significant_byte_count"]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "analysis_root": analysis_root.as_posix(),
        "totals": {
            **dict(sorted(totals.items())),
            "file_success_rate": (
                totals["parsed_file_count"] / attempted if attempted else 0.0
            ),
            "ast_coverage": (
                totals["reliable_significant_byte_count"] / significant
                if significant
                else 1.0
            ),
        },
        "entities": dict(sorted(entities.items())),
        "candidates": dict(sorted(candidates.items())),
        "errors": dict(sorted(errors.items())),
        "projects": projects,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    json.loads(output_path.read_text(encoding="utf-8"))
    return summary


def _load_github_metadata(
    *,
    slug: str,
    github_full_name: str,
    metadata_root: Path,
    search_path: Path,
) -> dict[str, Any]:
    exact_path = metadata_root / f"{slug}.json"
    if exact_path.exists():
        return json.loads(exact_path.read_text(encoding="utf-8"))
    search = json.loads(search_path.read_text(encoding="utf-8"))
    for item in search.get("items", []):
        if str(item.get("full_name", "")).lower() == github_full_name.lower():
            return item
    raise ValueError(f"缺少 GitHub 元数据: {github_full_name}")


def _license_evidence(repository: Path) -> list[dict[str, Any]]:
    evidence = []
    for path in sorted(repository.iterdir(), key=lambda value: value.name.lower()):
        lower_name = path.name.lower()
        if (
            path.is_file()
            and (
                lower_name.startswith("license")
                or lower_name.startswith("copying")
            )
        ):
            evidence.append(
                {
                    "path": path.name,
                    "sha256": _sha256_path(path),
                }
            )
    return evidence


def _build_file_evidence(repository: Path) -> dict[str, Any]:
    paths_by_system: defaultdict[str, list[str]] = defaultdict(list)
    for path in repository.rglob("*"):
        if (
            not path.is_file()
            or ".git" in path.parts
            or path.name not in BUILD_FILE_SYSTEMS
        ):
            continue
        paths_by_system[BUILD_FILE_SYSTEMS[path.name]].append(
            path.relative_to(repository).as_posix()
        )
    return {
        system: {
            "file_count": len(paths),
            "sample_paths": sorted(paths)[:25],
        }
        for system, paths in sorted(paths_by_system.items())
    }


def _clone_commands(
    *,
    github_full_name: str,
    slug: str,
    commit: str,
    sparse_paths: list[str],
) -> list[str]:
    destination = f"repos/{slug}"
    commands = [
        f"git init {destination}",
        (
            f"git -C {destination} remote add origin "
            f"https://github.com/{github_full_name}.git"
        ),
    ]
    if sparse_paths:
        commands.extend(
            [
                f"git -C {destination} sparse-checkout init --cone",
                (
                    f"git -C {destination} sparse-checkout set "
                    + " ".join(sparse_paths)
                ),
            ]
        )
    commands.extend(
        [
            f"git -C {destination} fetch --depth 1 origin {commit}",
            f"git -C {destination} checkout --detach FETCH_HEAD",
        ]
    )
    return commands


def _compact_analysis(
    report: Mapping[str, Any],
    artifact_path: Path,
) -> dict[str, Any]:
    paths = report["paths"]
    return {
        "artifact_path": artifact_path.as_posix(),
        "artifact_size_bytes": artifact_path.stat().st_size,
        "artifact_sha256": _sha256_path(artifact_path),
        "configuration": report["configuration"],
        "source": report["source"],
        "paths": {
            key: value
            for key, value in paths.items()
            if key != "basename_collisions"
        },
        "parse": report["parse"],
        "entities": report["entities"],
        "candidates": report["candidates"],
        "relationships": report["relationships"],
        "errors": {
            "categories": report["errors"]["categories"],
            "failed_file_count": len(report["errors"]["failed_files"]),
        },
        "output_integrity": report["output_integrity"],
        "deterministic_digest": report["deterministic_digest"],
    }


def _phase_statistics(
    projects: list[dict[str, Any]],
    phase: str,
) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    entities: Counter[str] = Counter()
    candidates: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    affected_projects: defaultdict[str, list[str]] = defaultdict(list)
    for project in projects:
        if project["selection"]["status"] not in FORMAL_STATUSES:
            continue
        report = project["parse"][phase]
        totals.update(
            {
                "source_file_count": int(
                    report["source"]["selected_file_count"]
                ),
                "effective_line_count": int(
                    report["source"]["effective_line_count"]
                ),
                "parsed_file_count": int(
                    report["parse"].get("parsed_file_count", 0)
                ),
                "failed_file_count": int(
                    report["parse"].get("failed_file_count", 0)
                ),
                "anomalous_file_count": int(
                    report["parse"].get("anomalous_file_count", 0)
                ),
                "selected_function_count": int(
                    report["parse"].get("selected_function_count", 0)
                ),
                "error_count": int(report["parse"].get("error_count", 0)),
                "missing_count": int(
                    report["parse"].get("missing_count", 0)
                ),
                "significant_byte_count": int(
                    report["parse"].get("significant_byte_count", 0)
                ),
                "reliable_significant_byte_count": int(
                    report["parse"].get(
                        "reliable_significant_byte_count", 0
                    )
                ),
                "duplicate_relative_path_count": int(
                    report["paths"]["duplicate_relative_path_count"]
                ),
                "path_escape_count": int(
                    report["paths"]["path_escape_count"]
                ),
                "symlink_file_count": int(
                    report["paths"]["symlink_file_count"]
                ),
            }
        )
        entities.update(report["entities"])
        candidates.update(report["candidates"])
        errors.update(report["errors"]["categories"])
        for category, count in report["errors"]["categories"].items():
            if int(count):
                affected_projects[category].append(project["slug"])
    attempted_files = (
        totals["parsed_file_count"] + totals["failed_file_count"]
    )
    significant_bytes = totals["significant_byte_count"]
    return {
        "totals": {
            **dict(sorted(totals.items())),
            "file_success_rate": (
                totals["parsed_file_count"] / attempted_files
                if attempted_files
                else 0.0
            ),
            "anomalous_file_rate": (
                totals["anomalous_file_count"] / attempted_files
                if attempted_files
                else 0.0
            ),
            "ast_coverage": (
                totals["reliable_significant_byte_count"] / significant_bytes
                if significant_bytes
                else 1.0
            ),
            "candidate_count": sum(candidates.values()),
        },
        "entities": dict(sorted(entities.items())),
        "candidates": dict(sorted(candidates.items())),
        "errors": {
            "counts": dict(sorted(errors.items())),
            "affected_projects": {
                key: sorted(value)
                for key, value in sorted(affected_projects.items())
            },
        },
    }


def _numeric_distribution(values: list[int]) -> dict[str, Any]:
    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
        "sum": sum(values),
    }


def _average_rank_percentiles(values: Mapping[str, int]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = max(len(ordered) - 1, 1)
    percentiles: dict[str, float] = {}
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        percentile = ((start + end - 1) / 2) / denominator
        for slug, _ in ordered[start:end]:
            percentiles[slug] = percentile
        start = end
    return percentiles


def _apply_dataset_classification(
    projects: list[dict[str, Any]],
    policy: Mapping[str, Any],
) -> None:
    formal = [
        project
        for project in projects
        if project["selection"]["status"] in FORMAL_STATUSES
    ]
    allowed_domains = set(policy["primary_domain"]["categories"])
    actual_domains = {
        project["classification"]["primary_domain"] for project in formal
    }
    if actual_domains != allowed_domains:
        raise ValueError("正式项目主领域与分类政策不一致")
    if tuple(policy["analysis_complexity"]["indicators"]) != (
        ANALYSIS_COMPLEXITY_INDICATORS
    ):
        raise ValueError("分析复杂度指标与分类政策不一致")

    indicator_values = {
        "effective_line_count": {
            project["slug"]: int(
                project["parse"]["final"]["source"]["effective_line_count"]
            )
            for project in formal
        },
        "selected_file_count": {
            project["slug"]: int(
                project["parse"]["final"]["source"]["selected_file_count"]
            )
            for project in formal
        },
        "candidate_count": {
            project["slug"]: sum(
                project["parse"]["final"]["candidates"].values()
            )
            for project in formal
        },
    }
    percentiles = {
        indicator: _average_rank_percentiles(values)
        for indicator, values in indicator_values.items()
    }
    scores = {
        project["slug"]: statistics.fmean(
            values[project["slug"]] for values in percentiles.values()
        )
        for project in formal
    }
    ordered_slugs = sorted(scores, key=lambda slug: (scores[slug], slug))
    tier_by_slug = {
        slug: ANALYSIS_COMPLEXITY_TIERS[
            min(index * len(ANALYSIS_COMPLEXITY_TIERS) // len(formal), 2)
        ]
        for index, slug in enumerate(ordered_slugs)
    }
    for project in formal:
        slug = project["slug"]
        project["classification"]["analysis_complexity"] = {
            "tier": tier_by_slug[slug],
            "score": round(scores[slug], 6),
            "indicator_values": {
                indicator: values[slug]
                for indicator, values in indicator_values.items()
            },
            "indicator_percentiles": {
                indicator: round(values[slug], 6)
                for indicator, values in percentiles.items()
            },
        }


def _formal_statistics(
    projects: list[dict[str, Any]],
    *,
    reference_date: str,
) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    entities: Counter[str] = Counter()
    candidates: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    standards: Counter[str] = Counter()
    project_types: Counter[str] = Counter()
    licenses: Counter[str] = Counter()
    build_systems: Counter[str] = Counter()
    idiom_focus: Counter[str] = Counter()
    primary_domains: Counter[str] = Counter()
    complexity_tiers: Counter[str] = Counter()
    domain_by_complexity: dict[str, Counter[str]] = defaultdict(Counter)
    scale_buckets: Counter[str] = Counter()
    file_buckets: Counter[str] = Counter()
    star_buckets: Counter[str] = Counter()
    stars: list[int] = []
    forks: list[int] = []
    effective_lines: list[int] = []
    source_files: list[int] = []
    activity_ages: list[int] = []
    archived_count = 0
    reference = datetime.fromisoformat(reference_date)
    for project in projects:
        if project["selection"]["status"] not in FORMAL_STATUSES:
            continue
        final = project["parse"]["final"]
        totals.update(
            {
                "project_count": 1,
                "seed_project_count": int(project["selection"]["seed_project"]),
                "source_file_count": int(final["source"]["selected_file_count"]),
                "effective_line_count": int(
                    final["source"]["effective_line_count"]
                ),
                "parsed_file_count": int(final["parse"]["parsed_file_count"]),
                "failed_file_count": int(final["parse"]["failed_file_count"]),
                "selected_function_count": int(
                    final["parse"]["selected_function_count"]
                ),
                "error_count": int(final["parse"]["error_count"]),
                "missing_count": int(final["parse"]["missing_count"]),
                "significant_byte_count": int(
                    final["parse"]["significant_byte_count"]
                ),
                "reliable_significant_byte_count": int(
                    final["parse"]["reliable_significant_byte_count"]
                ),
            }
        )
        entities.update(final["entities"])
        candidates.update(final["candidates"])
        errors.update(final["errors"]["categories"])
        selection = project["selection"]
        standards[selection["cpp_standard"]] += 1
        project_types[selection["project_type"]] += 1
        licenses[project["license"]["spdx"]] += 1
        build_systems.update(selection["build_systems"])
        idiom_focus.update(selection["idiom_focus"])
        classification = project["classification"]
        primary_domain = classification["primary_domain"]
        complexity_tier = classification["analysis_complexity"]["tier"]
        primary_domains[primary_domain] += 1
        complexity_tiers[complexity_tier] += 1
        domain_by_complexity[primary_domain][complexity_tier] += 1
        github = project["github"]
        star_count = int(github["stars_at_retrieval"])
        fork_count = int(github["forks_at_retrieval"])
        line_count = int(final["source"]["effective_line_count"])
        file_count = int(final["source"]["selected_file_count"])
        stars.append(star_count)
        forks.append(fork_count)
        effective_lines.append(line_count)
        source_files.append(file_count)
        archived_count += int(github["archived"])
        pushed_at = datetime.fromisoformat(
            str(github["pushed_at"]).replace("Z", "+00:00")
        )
        reference_value = reference.replace(tzinfo=pushed_at.tzinfo)
        activity_ages.append((reference_value - pushed_at).days)
        scale_buckets[
            (
                "<2,000"
                if line_count < 2000
                else "2,000～9,999"
                if line_count < 10000
                else "10,000～99,999"
                if line_count < 100000
                else ">=100,000"
            )
        ] += 1
        file_buckets[
            (
                "<10"
                if file_count < 10
                else "10～99"
                if file_count < 100
                else "100～999"
                if file_count < 1000
                else ">=1,000"
            )
        ] += 1
        star_buckets[
            (
                "<5,000"
                if star_count < 5000
                else "5,000～9,999"
                if star_count < 10000
                else "10,000～24,999"
                if star_count < 25000
                else ">=25,000"
            )
        ] += 1
    parsed_files = totals["parsed_file_count"]
    attempted_files = parsed_files + totals["failed_file_count"]
    significant_bytes = totals["significant_byte_count"]
    return {
        "totals": {
            **dict(sorted(totals.items())),
            "file_success_rate": (
                parsed_files / attempted_files
                if attempted_files
                else 0.0
            ),
            "ast_coverage": (
                totals["reliable_significant_byte_count"] / significant_bytes
                if significant_bytes
                else 1.0
            ),
            "candidate_count": sum(candidates.values()),
        },
        "entities": dict(sorted(entities.items())),
        "candidates": dict(sorted(candidates.items())),
        "errors": dict(sorted(errors.items())),
        "diversity": {
            "cpp_standards": dict(sorted(standards.items())),
            "project_types": dict(sorted(project_types.items())),
            "licenses": dict(sorted(licenses.items())),
            "build_systems": dict(sorted(build_systems.items())),
            "idiom_focus": dict(sorted(idiom_focus.items())),
        },
        "classification": {
            "primary_domains": dict(sorted(primary_domains.items())),
            "analysis_complexity_tiers": {
                tier: complexity_tiers[tier]
                for tier in ANALYSIS_COMPLEXITY_TIERS
            },
            "primary_domain_by_analysis_complexity": {
                domain: {
                    tier: counts[tier]
                    for tier in ANALYSIS_COMPLEXITY_TIERS
                }
                for domain, counts in sorted(domain_by_complexity.items())
            },
        },
        "metadata_distribution": {
            "stars": _numeric_distribution(stars),
            "forks": _numeric_distribution(forks),
            "star_buckets": dict(sorted(star_buckets.items())),
            "archived_project_count": archived_count,
            "active_within_365_days_count": sum(
                age <= 365 for age in activity_ages
            ),
            "activity_age_days": _numeric_distribution(activity_ages),
        },
        "scale_distribution": {
            "effective_lines": _numeric_distribution(effective_lines),
            "source_files": _numeric_distribution(source_files),
            "effective_line_buckets": dict(sorted(scale_buckets.items())),
            "source_file_buckets": dict(sorted(file_buckets.items())),
        },
        "parser_comparison": {
            phase: _phase_statistics(projects, phase)
            for phase in ("baseline", "final")
        },
    }


def build_manifest(
    *,
    selection_path: Path,
    repositories_root: Path,
    metadata_root: Path,
    search_path: Path,
    baseline_root: Path,
    final_root: Path,
    output_path: Path,
    statistics_output_path: Path,
) -> dict[str, Any]:
    selection_payload = json.loads(selection_path.read_text(encoding="utf-8"))
    previous_projects = {}
    if output_path.exists():
        previous_manifest = json.loads(
            output_path.read_text(encoding="utf-8")
        )
        previous_projects = {
            project["slug"]: project
            for project in previous_manifest["projects"]
        }
    project_entries: list[dict[str, Any]] = []
    for annotation in selection_payload["projects"]:
        slug = annotation["slug"]
        repository = repositories_root / slug
        selection = {
            key: value
            for key, value in annotation.items()
            if key
            not in {
                "slug",
                "github_full_name",
                "license_spdx",
                "primary_domain",
                "sparse_paths",
            }
        }
        if annotation["status"] == REMOVED_STATUS and not repository.exists():
            project = previous_projects[slug]
            project["selection"] = selection
            project.pop("classification", None)
            project_entries.append(project)
            continue
        commit = _git_output(repository, "rev-parse", "HEAD")
        github_metadata = _load_github_metadata(
            slug=slug,
            github_full_name=annotation["github_full_name"],
            metadata_root=metadata_root,
            search_path=search_path,
        )
        baseline_path = baseline_root / slug / "analysis.json"
        final_path = final_root / slug / "analysis.json"
        baseline_report = json.loads(
            baseline_path.read_text(encoding="utf-8")
        )
        final_report = json.loads(final_path.read_text(encoding="utf-8"))
        baseline = _compact_analysis(baseline_report, baseline_path)
        final = _compact_analysis(final_report, final_path)
        sparse_paths = list(annotation.get("sparse_paths", []))
        canonical_dataset_path = final_root / slug / "dataset.pkl"
        canonical_audit_path = final_root / slug / "dataset.audit.json"
        canonical_artifacts = {}
        for artifact_name, artifact_path in (
            ("dataset", canonical_dataset_path),
            ("audit", canonical_audit_path),
        ):
            canonical_artifacts[artifact_name] = {
                "path": artifact_path.as_posix(),
                "exists": artifact_path.exists(),
                "size_bytes": (
                    artifact_path.stat().st_size
                    if artifact_path.exists()
                    else None
                ),
                "sha256": (
                    _sha256_path(artifact_path)
                    if artifact_path.exists()
                    else None
                ),
            }
        project_entries.append(
            {
                "slug": slug,
                "github": {
                    "full_name": annotation["github_full_name"],
                    "url": github_metadata["html_url"],
                    "description": github_metadata.get("description"),
                    "default_branch": github_metadata["default_branch"],
                    "primary_language": github_metadata["language"],
                    "repository_size_kib": github_metadata["size"],
                    "stars_at_retrieval": github_metadata[
                        "stargazers_count"
                    ],
                    "forks_at_retrieval": github_metadata["forks_count"],
                    "archived": bool(github_metadata["archived"]),
                    "created_at": github_metadata["created_at"],
                    "updated_at": github_metadata["updated_at"],
                    "pushed_at": github_metadata["pushed_at"],
                    "metadata_retrieved_at": selection_payload[
                        "retrieved_at"
                    ],
                },
                "revision": {
                    "commit": commit,
                    "commit_date": _git_output(
                        repository, "log", "-1", "--format=%cI"
                    ),
                    "local_path": repository.as_posix(),
                    "remote_url": _git_output(
                        repository, "remote", "get-url", "origin"
                    ),
                    "is_shallow": (
                        _git_output(
                            repository,
                            "rev-parse",
                            "--is-shallow-repository",
                        )
                        == "true"
                    ),
                    "sparse_paths": sparse_paths,
                    "reproduction_commands": _clone_commands(
                        github_full_name=annotation["github_full_name"],
                        slug=slug,
                        commit=commit,
                        sparse_paths=sparse_paths,
                    ),
                },
                "license": {
                    "spdx": annotation["license_spdx"],
                    "root_file_evidence": _license_evidence(repository),
                },
                "selection": selection,
                **(
                    {
                        "classification": {
                            "primary_domain": annotation["primary_domain"]
                        }
                    }
                    if annotation["status"] in FORMAL_STATUSES
                    else {}
                ),
                "scope": {
                    "included_extensions": sorted(DATASET_EXTENSIONS),
                    "included_roots": sparse_paths or ["."],
                    "sparse_paths": sparse_paths,
                    "build_file_evidence": _build_file_evidence(repository),
                    "scanner_exclusions": {
                        "directory_names": sorted(
                            FileScanner.EXCLUDED_DIRECTORY_NAMES
                        ),
                        "directory_prefixes": list(
                            FileScanner.EXCLUDED_DIRECTORY_PREFIXES
                        ),
                        "generated_file_patterns": [
                            pattern.pattern
                            for pattern in FileScanner.GENERATED_FILE_PATTERNS
                        ],
                    },
                },
                "parse": {
                    "baseline": baseline,
                    "final": final,
                    "canonical_dataset_path": (
                        canonical_dataset_path.as_posix()
                    ),
                    "canonical_audit_path": (
                        canonical_audit_path.as_posix()
                    ),
                    "canonical_artifacts": canonical_artifacts,
                    "reproduction_command": (
                        ".venv/bin/python -m src.parser.repo2data "
                        f"--input {repositories_root.as_posix()} "
                        f"--project {slug} "
                        f"--output {canonical_dataset_path.as_posix()} "
                        "--audit-output "
                        f"{canonical_audit_path.as_posix()}"
                    ),
                    "analysis_commands": {
                        "baseline": (
                            ".venv/bin/python -m "
                            "scripts.analyze_cpp_dataset analyze-repo "
                            f"--repo {repository.as_posix()} "
                            f"--project {slug} "
                            f"--output {baseline_path.as_posix()}"
                        ),
                        "final": (
                            ".venv/bin/python -m "
                            "scripts.analyze_cpp_dataset analyze-repo "
                            f"--repo {repository.as_posix()} "
                            f"--project {slug} "
                            f"--output {final_path.as_posix()}"
                        ),
                    },
                },
            }
        )

    project_entries.sort(key=lambda value: value["slug"])
    classification_policy = selection_payload["classification_policy"]
    _apply_dataset_classification(project_entries, classification_policy)
    statistics = _formal_statistics(
        project_entries,
        reference_date=selection_payload["retrieved_at"],
    )
    statistics["selection"] = {
        "candidate_count": len(project_entries),
        "new_candidate_count": sum(
            not value["selection"]["seed_project"]
            for value in project_entries
        ),
        "seed_project_count": sum(
            value["selection"]["seed_project"]
            for value in project_entries
        ),
        "status_counts": dict(
            sorted(
                Counter(
                    value["selection"]["status"]
                    for value in project_entries
                ).items()
            )
        ),
    }
    statistics_payload = {
        "schema_version": 1,
        "generated_from": output_path.as_posix(),
        "selection_source": selection_path.as_posix(),
        "screened_at": selection_payload.get("screened_at"),
        "selection_policy": selection_payload["selection_policy"],
        "classification_policy": classification_policy,
        **statistics,
    }
    manifest = {
        "schema_version": 1,
        "dataset_name": "CodeIdiomMine C++ 实验数据集",
        "generated_at": selection_payload["retrieved_at"],
        "screened_at": selection_payload.get("screened_at"),
        "selection_policy": selection_payload["selection_policy"],
        "classification_policy": classification_policy,
        "source": {
            "platform": "GitHub 公开仓库",
            "candidate_search_limit": 35,
            "examined_candidate_count": len(project_entries),
            "new_candidate_count": sum(
                not value["selection"]["seed_project"]
                for value in project_entries
            ),
            "seed_project_count": sum(
                value["selection"]["seed_project"]
                for value in project_entries
            ),
            "formal_project_count": statistics["totals"]["project_count"],
            "historical_project_count": sum(
                value["selection"]["status"] == HISTORICAL_STATUS
                for value in project_entries
            ),
            "removed_project_count": sum(
                value["selection"]["status"] == REMOVED_STATUS
                for value in project_entries
            ),
            "selection_source": selection_path.as_posix(),
            "github_search_snapshot": search_path.as_posix(),
        },
        "parser": {
            "backend": "tree-sitter-cpp",
            "zero_build_parsing": True,
            "candidate_profile": QUALITY_PROFILE,
            "baseline_codeidiommine_commit": project_entries[0]["parse"][
                "baseline"
            ]["configuration"]["codeidiommine_commit"],
            "final_codeidiommine_commit": project_entries[0]["parse"][
                "final"
            ]["configuration"]["codeidiommine_commit"],
            "final_parser_source_sha256": project_entries[0]["parse"][
                "final"
            ]["configuration"]["parser_source_sha256"],
            "baseline_root": baseline_root.as_posix(),
            "final_root": final_root.as_posix(),
        },
        "statistics_path": statistics_output_path.as_posix(),
        "statistics": statistics,
        "projects": project_entries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    statistics_output_path.parent.mkdir(parents=True, exist_ok=True)
    statistics_output_path.write_text(
        json.dumps(
            statistics_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    json.loads(output_path.read_text(encoding="utf-8"))
    json.loads(statistics_output_path.read_text(encoding="utf-8"))
    return manifest


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    formal_projects = [
        project
        for project in manifest["projects"]
        if project["selection"]["status"] in FORMAL_STATUSES
    ]
    historical_projects = [
        project
        for project in manifest["projects"]
        if project["selection"]["status"] == HISTORICAL_STATUS
    ]
    removed_projects = [
        project
        for project in manifest["projects"]
        if project["selection"]["status"] == REMOVED_STATUS
    ]
    policy = manifest["selection_policy"]
    if frozenset(policy["formal_statuses"]) != FORMAL_STATUSES:
        errors.append("正式项目状态策略与校验器不一致")
    if policy["historical_status"] != HISTORICAL_STATUS:
        errors.append("历史项目状态策略与校验器不一致")
    if policy["excluded_status"] != REMOVED_STATUS:
        errors.append("淘汰项目状态策略与校验器不一致")
    if manifest["source"]["formal_project_count"] != len(formal_projects):
        errors.append("清单正式项目数与项目状态不一致")
    if manifest["source"]["historical_project_count"] != len(
        historical_projects
    ):
        errors.append("清单历史项目数与项目状态不一致")
    if manifest["source"]["removed_project_count"] != len(removed_projects):
        errors.append("清单淘汰项目数与项目状态不一致")
    if manifest["statistics"]["totals"]["project_count"] != len(
        formal_projects
    ):
        errors.append("正式统计项目数与项目状态不一致")
    classification_inputs = [
        {
            "slug": project["slug"],
            "selection": {"status": project["selection"]["status"]},
            "classification": {
                "primary_domain": project["classification"]["primary_domain"]
            },
            "parse": {
                "final": {
                    "source": project["parse"]["final"]["source"],
                    "candidates": project["parse"]["final"]["candidates"],
                }
            },
        }
        for project in formal_projects
    ]
    _apply_dataset_classification(
        classification_inputs,
        manifest["classification_policy"],
    )
    expected_classification = {
        project["slug"]: project["classification"]
        for project in classification_inputs
    }
    for project in formal_projects:
        if project["classification"] != expected_classification[
            project["slug"]
        ]:
            errors.append(f"{project['slug']}: 数据集分类不可复算")
    if any("classification" in project for project in historical_projects):
        errors.append("阶段2后排除项目不应进入正式分类")
    classification_statistics = manifest["statistics"]["classification"]
    domain_counts = Counter(
        project["classification"]["primary_domain"]
        for project in formal_projects
    )
    tier_counts = Counter(
        project["classification"]["analysis_complexity"]["tier"]
        for project in formal_projects
    )
    if classification_statistics["primary_domains"] != dict(
        sorted(domain_counts.items())
    ):
        errors.append("主领域汇总与逐项目分类不一致")
    if classification_statistics["analysis_complexity_tiers"] != {
        tier: tier_counts[tier] for tier in ANALYSIS_COMPLEXITY_TIERS
    }:
        errors.append("分析复杂度汇总与逐项目分类不一致")
    domain_by_tier: dict[str, Counter[str]] = defaultdict(Counter)
    for project in formal_projects:
        classification = project["classification"]
        domain_by_tier[classification["primary_domain"]][
            classification["analysis_complexity"]["tier"]
        ] += 1
    if classification_statistics[
        "primary_domain_by_analysis_complexity"
    ] != {
        domain: {
            tier: counts[tier] for tier in ANALYSIS_COMPLEXITY_TIERS
        }
        for domain, counts in sorted(domain_by_tier.items())
    }:
        errors.append("主领域与分析复杂度交叉汇总不一致")
    slugs = [project["slug"] for project in manifest["projects"]]
    if len(slugs) != len(set(slugs)):
        errors.append("项目 slug 不唯一")
    if not 20 <= len(formal_projects) <= 30:
        errors.append(f"正式项目数超出 20～30: {len(formal_projects)}")
    for project in manifest["projects"]:
        slug = project["slug"]
        repository = Path(project["revision"]["local_path"])
        status = project["selection"]["status"]
        if status == REMOVED_STATUS:
            if repository.exists():
                errors.append(f"{slug}: 已淘汰仓库仍存在于本地")
            continue
        if status not in FORMAL_STATUSES and status != HISTORICAL_STATUS:
            errors.append(f"{slug}: 未知筛选状态 {status}")
            continue
        if not repository.is_dir():
            errors.append(f"{slug}: 缺少应保留的本地仓库")
            continue
        if _git_output(repository, "rev-parse", "HEAD") != project[
            "revision"
        ]["commit"]:
            errors.append(f"{slug}: 本地 commit 与清单不一致")
        final = project["parse"]["final"]
        paths = final["paths"]
        if int(paths["duplicate_relative_path_count"]):
            errors.append(f"{slug}: 存在重复仓库相对路径")
        if int(paths["path_escape_count"]):
            errors.append(f"{slug}: 存在越界路径")
        if int(paths["symlink_file_count"]):
            errors.append(f"{slug}: 存在符号链接输入")
        dataset_path = Path(project["parse"]["canonical_dataset_path"])
        audit_path = Path(project["parse"]["canonical_audit_path"])
        if not dataset_path.exists():
            errors.append(f"{slug}: 缺少 canonical dataset.pkl")
            continue
        if not audit_path.exists():
            errors.append(f"{slug}: 缺少 canonical audit JSON")
            continue
        for artifact_name, artifact_path in (
            ("dataset", dataset_path),
            ("audit", audit_path),
        ):
            artifact = project["parse"]["canonical_artifacts"][
                artifact_name
            ]
            if artifact_path.stat().st_size != artifact["size_bytes"]:
                errors.append(f"{slug}: {artifact_name} 文件大小不一致")
            if _sha256_path(artifact_path) != artifact["sha256"]:
                errors.append(f"{slug}: {artifact_name} SHA-256 不一致")
        data = pd.read_pickle(dataset_path)
        if data.columns.tolist() != [
            "project",
            "cppFile",
            "func_ast",
            "func_src",
        ]:
            errors.append(f"{slug}: dataset.pkl Schema 不正确")
        if data["project"].tolist() != [slug]:
            errors.append(f"{slug}: dataset.pkl 项目标识不正确")
        paths_in_pickle = list(data.iloc[0]["cppFile"])
        if len(paths_in_pickle) != len(set(paths_in_pickle)):
            errors.append(f"{slug}: dataset.pkl 路径重复")
        if any(
            Path(path).is_absolute() or ".." in Path(path).parts
            for path in paths_in_pickle
        ):
            errors.append(f"{slug}: dataset.pkl 存在非仓库相对路径")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit["projects"] != [slug]:
            errors.append(f"{slug}: audit 项目标识不正确")
        if audit["summary"]["scanned_file_count"] != final["source"][
            "selected_file_count"
        ]:
            errors.append(f"{slug}: audit 与统计扫描文件数不一致")
        if audit["summary"]["selected_function_count"] != final["parse"][
            "selected_function_count"
        ]:
            errors.append(f"{slug}: audit 与统计函数数不一致")
    result = {
        "manifest": manifest_path.as_posix(),
        "formal_project_count": len(formal_projects),
        "historical_project_count": len(historical_projects),
        "removed_project_count": len(removed_projects),
        "checked_project_count": len(formal_projects)
        + len(historical_projects),
        "excluded_project_count": len(manifest["projects"]) - len(formal_projects),
        "error_count": len(errors),
        "errors": errors,
        "valid": not errors,
    }
    if errors:
        raise ValueError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze-repo", help="分析一个固定仓库")
    analyze.add_argument("--repo", type=Path, required=True)
    analyze.add_argument("--project", required=True)
    analyze.add_argument("--output", type=Path, required=True)

    aggregate = subparsers.add_parser("aggregate", help="汇总实际单仓库产物")
    aggregate.add_argument("--analysis-root", type=Path, required=True)
    aggregate.add_argument("--output", type=Path, required=True)

    manifest = subparsers.add_parser(
        "build-manifest",
        help="从人工筛选注释和实际产物生成正式清单",
    )
    manifest.add_argument("--selection", type=Path, required=True)
    manifest.add_argument("--repositories-root", type=Path, required=True)
    manifest.add_argument("--metadata-root", type=Path, required=True)
    manifest.add_argument("--search-snapshot", type=Path, required=True)
    manifest.add_argument("--baseline-root", type=Path, required=True)
    manifest.add_argument("--final-root", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--statistics-output", type=Path, required=True)

    validate = subparsers.add_parser(
        "validate-manifest",
        help="校验清单、本地仓库与 canonical Parser 产物一致性",
    )
    validate.add_argument("--manifest", type=Path, required=True)

    arguments = parser.parse_args()
    if arguments.command == "analyze-repo":
        report = analyze_repository(
            arguments.repo,
            project=arguments.project,
            output_path=arguments.output,
        )
        print(
            json.dumps(
                {
                    "project": report["project"],
                    "files": report["source"]["selected_file_count"],
                    "success_rate": report["parse"]["file_success_rate"],
                    "functions": report["parse"]["selected_function_count"],
                    "candidates": sum(report["candidates"].values()),
                    "output": arguments.output.as_posix(),
                },
                ensure_ascii=False,
            )
        )
    elif arguments.command == "aggregate":
        summary = aggregate_reports(arguments.analysis_root, arguments.output)
        print(
            json.dumps(
                {
                    "projects": summary["totals"]["project_count"],
                    "files": summary["totals"]["selected_file_count"],
                    "success_rate": summary["totals"]["file_success_rate"],
                    "output": arguments.output.as_posix(),
                },
                ensure_ascii=False,
            )
        )
    elif arguments.command == "build-manifest":
        manifest_payload = build_manifest(
            selection_path=arguments.selection,
            repositories_root=arguments.repositories_root,
            metadata_root=arguments.metadata_root,
            search_path=arguments.search_snapshot,
            baseline_root=arguments.baseline_root,
            final_root=arguments.final_root,
            output_path=arguments.output,
            statistics_output_path=arguments.statistics_output,
        )
        print(
            json.dumps(
                {
                    "projects": len(manifest_payload["projects"]),
                    "formal_projects": manifest_payload["source"][
                        "formal_project_count"
                    ],
                    "output": arguments.output.as_posix(),
                },
                ensure_ascii=False,
            )
        )
    else:
        result = validate_manifest(arguments.manifest)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
