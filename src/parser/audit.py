"""对 C++ Parser 数据集和原始源码执行可重复的质量审计。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import tree_sitter

from .ast_parser import ASTParser
from .candidates import (
    QUALITY_PROFILE,
    SUPPORTED_PROFILES,
    select_candidates,
)
from .file_scanner import FileScanner
from .cpp_adapter import CPP_ADAPTER
from ..common.logging import get_logger
from ..common.node_kinds import BLOCK_KINDS, FUNCTION_KINDS, STATEMENT_KINDS


logger = get_logger(__name__)

AUDIT_SCHEMA_VERSION = 1
WHITESPACE_BYTES = frozenset(b" \t\r\n\v\f")


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _decode_bytes(data: bytes) -> str:
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _legacy_clean(code: str) -> str:
    code = re.sub(r"//.*?$", "", code, flags=re.MULTILINE)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    return re.sub(r"\n\s*\n", "\n", code).strip()


def _normalized_text(code: str) -> str:
    return re.sub(r"\s+", " ", code).strip()


def _extent_tuple(extent: str) -> Optional[Tuple[int, int, int, int]]:
    match = re.fullmatch(r"(\d+)-(\d+)-(\d+)-(\d+)", extent or "")
    if not match:
        return None
    return tuple(map(int, match.groups()))  # type: ignore[return-value]


def _contains_extent(outer: str, inner: str) -> bool:
    outer_value = _extent_tuple(outer)
    inner_value = _extent_tuple(inner)
    if outer_value is None or inner_value is None:
        return False
    osl, osc, oel, oec = outer_value
    isl, isc, iel, iec = inner_value
    return (osl, osc) <= (isl, isc) and (iel, iec) <= (oel, oec)


def _line_offsets(source: bytes) -> List[int]:
    offsets = [0]
    for index, value in enumerate(source):
        if value == 10:
            offsets.append(index + 1)
    return offsets


def _extent_to_bytes(
    extent: str,
    source_size: int,
    line_offsets: Sequence[int],
) -> Optional[Tuple[int, int]]:
    parsed = _extent_tuple(extent)
    if parsed is None:
        return None
    start_line, start_column, end_line, end_column = parsed
    if start_line < 1 or end_line < start_line:
        return None
    if start_line > len(line_offsets) or end_line > len(line_offsets):
        return None
    start = line_offsets[start_line - 1] + start_column
    end = line_offsets[end_line - 1] + end_column
    if not (0 <= start <= end <= source_size):
        return None
    return start, end


def _point_extent(node: tree_sitter.Node) -> str:
    return (
        f"{node.start_point[0] + 1}-{node.start_point[1]}-"
        f"{node.end_point[0] + 1}-{node.end_point[1]}"
    )


def _ranges_intersect(left: Tuple[int, int], right: Tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _percentile(sorted_values: Sequence[int], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _distribution(values: Sequence[int]) -> Dict[str, float | int]:
    ordered = sorted(values)
    if not ordered:
        return {
            "count": 0,
            "min": 0,
            "p25": 0.0,
            "median": 0.0,
            "p75": 0.0,
            "p95": 0.0,
            "max": 0,
            "mean": 0.0,
        }
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p25": _percentile(ordered, 0.25),
        "median": _percentile(ordered, 0.5),
        "p75": _percentile(ordered, 0.75),
        "p95": _percentile(ordered, 0.95),
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def _compact_excerpt(source: bytes, start: int, end: int, limit: int = 160) -> str:
    excerpt = _decode_bytes(source[start:end])
    excerpt = re.sub(r"\s+", " ", excerpt).strip()
    if len(excerpt) > limit:
        return excerpt[: limit - 1] + "…"
    return excerpt


def _unreliable_runs(source: bytes, reliable: bytearray) -> List[Tuple[int, int]]:
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for index, value in enumerate(source):
        unreliable = value not in WHITESPACE_BYTES and not reliable[index]
        if unreliable and start is None:
            start = index
        elif not unreliable and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(source)))
    return runs


@dataclass
class SourceEvidence:
    source_path: str
    project: str
    byte_count: int
    ast_node_count: int
    named_node_count: int
    function_definition_count: int
    error_ranges: List[Tuple[int, int]]
    missing_ranges: List[Tuple[int, int]]
    preprocessor_ranges: List[Tuple[int, int]]
    macro_related_error_count: int
    significant_byte_count: int
    reliable_significant_byte_count: int
    uncovered_runs: List[Tuple[int, int]]
    root_covers_source: bool
    status: str
    anomalies: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def ast_coverage(self) -> float:
        if self.significant_byte_count == 0:
            return 1.0
        return self.reliable_significant_byte_count / self.significant_byte_count


@dataclass
class CandidateAccumulator:
    count: int = 0
    byte_lengths: List[int] = field(default_factory=list)
    line_lengths: List[int] = field(default_factory=list)
    content_hashes: Counter[str] = field(default_factory=Counter)
    normalized_hashes: Counter[str] = field(default_factory=Counter)
    source_ranges: Counter[str] = field(default_factory=Counter)
    structurally_complete: int = 0
    exact_mapping_matches: int = 0
    explicit_mapping_count: int = 0
    range_resolved: int = 0
    long_fragment_count: int = 0
    kinds: Counter[str] = field(default_factory=Counter)
    projects: Counter[str] = field(default_factory=Counter)
    longest_samples: List[Tuple[int, Dict[str, Any]]] = field(default_factory=list)

    def add(
        self,
        *,
        code: str,
        level: str,
        project: str,
        source_path: str,
        node_info: Mapping[str, Any],
        byte_range: Optional[Tuple[int, int]],
        raw_source: Optional[bytes],
        complete: bool,
        long_line_threshold: int,
        long_byte_threshold: int,
    ) -> None:
        self.count += 1
        encoded = code.encode("utf-8", errors="surrogatepass")
        byte_length = len(encoded)
        line_length = code.count("\n") + 1 if code else 0
        self.byte_lengths.append(byte_length)
        self.line_lengths.append(line_length)
        self.content_hashes[hashlib.sha256(encoded).hexdigest()] += 1
        normalized = _normalized_text(code).encode("utf-8", errors="surrogatepass")
        self.normalized_hashes[hashlib.sha256(normalized).hexdigest()] += 1
        extent = str(node_info.get("extent") or "")
        self.source_ranges[f"{project}\0{source_path}\0{extent}"] += 1
        self.kinds[str(node_info.get("kind") or "")] += 1
        self.projects[project] += 1
        if complete:
            self.structurally_complete += 1
        if byte_range is not None:
            self.range_resolved += 1
            if raw_source is not None:
                raw_text = _decode_bytes(
                    raw_source[byte_range[0] : byte_range[1]]
                )
                if node_info.get("start_byte") is None:
                    raw_text = raw_text.strip()
                if code == raw_text:
                    self.exact_mapping_matches += 1
        if (
            node_info.get("source_file_id") is not None
            and node_info.get("start_byte") is not None
            and node_info.get("end_byte") is not None
        ):
            self.explicit_mapping_count += 1
        if line_length >= long_line_threshold or byte_length >= long_byte_threshold:
            self.long_fragment_count += 1

        sample = {
            "project": project,
            "source_path": source_path,
            "extent": extent,
            "kind": node_info.get("kind"),
            "level": level,
            "bytes": byte_length,
            "lines": line_length,
        }
        self.longest_samples.append((byte_length, sample))
        self.longest_samples.sort(key=lambda item: (-item[0], item[1]["source_path"], item[1]["extent"]))
        del self.longest_samples[10:]

    def to_dict(self) -> Dict[str, Any]:
        duplicate_instances = sum(value - 1 for value in self.content_hashes.values())
        normalized_duplicate_instances = sum(
            value - 1 for value in self.normalized_hashes.values()
        )
        duplicate_ranges = sum(value - 1 for value in self.source_ranges.values())
        return {
            "count": self.count,
            "byte_length": _distribution(self.byte_lengths),
            "line_length": _distribution(self.line_lengths),
            "exact_content_unique": len(self.content_hashes),
            "exact_content_duplicate_instances": duplicate_instances,
            "exact_content_duplicate_rate": duplicate_instances / self.count if self.count else 0.0,
            "normalized_content_unique": len(self.normalized_hashes),
            "normalized_content_duplicate_instances": normalized_duplicate_instances,
            "normalized_content_duplicate_rate": (
                normalized_duplicate_instances / self.count if self.count else 0.0
            ),
            "duplicate_source_ranges": duplicate_ranges,
            "structurally_complete": self.structurally_complete,
            "structural_completeness_rate": (
                self.structurally_complete / self.count if self.count else 0.0
            ),
            "range_resolved": self.range_resolved,
            "exact_mapping_matches": self.exact_mapping_matches,
            "exact_mapping_rate": (
                self.exact_mapping_matches / self.count if self.count else 0.0
            ),
            "explicit_mapping_count": self.explicit_mapping_count,
            "explicit_mapping_rate": (
                self.explicit_mapping_count / self.count if self.count else 0.0
            ),
            "long_fragment_count": self.long_fragment_count,
            "kinds": dict(self.kinds.most_common()),
            "projects": dict(sorted(self.projects.items())),
            "longest_samples": [sample for _, sample in self.longest_samples],
        }


def _walk_tree(root: tree_sitter.Node) -> Iterator[Tuple[tree_sitter.Node, bool]]:
    stack: List[Tuple[tree_sitter.Node, bool]] = [(root, False)]
    while stack:
        node, under_error = stack.pop()
        current_under_error = under_error or node.is_error or node.type == "ERROR"
        yield node, current_under_error
        for child in reversed(node.children):
            stack.append((child, current_under_error))


def _audit_source_file(
    parser: ASTParser,
    source_root: Path,
    project: str,
    file_path: Path,
) -> SourceEvidence:
    source_path = (
        file_path.resolve(strict=True)
        .relative_to((source_root / project).resolve(strict=True))
        .as_posix()
    )
    try:
        source = file_path.read_bytes()
        tree = parser.parser.parse(source)
    except Exception as exc:
        return SourceEvidence(
            source_path=source_path,
            project=project,
            byte_count=0,
            ast_node_count=0,
            named_node_count=0,
            function_definition_count=0,
            error_ranges=[],
            missing_ranges=[],
            preprocessor_ranges=[],
            macro_related_error_count=0,
            significant_byte_count=0,
            reliable_significant_byte_count=0,
            uncovered_runs=[],
            root_covers_source=False,
            status="failed",
            anomalies=[{"kind": "read_or_parse_failure", "message": str(exc)}],
        )

    reliable = bytearray(len(source))
    ast_node_count = 0
    named_node_count = 0
    function_definition_count = 0
    error_ranges: List[Tuple[int, int]] = []
    missing_ranges: List[Tuple[int, int]] = []
    preprocessor_ranges: List[Tuple[int, int]] = []
    anomaly_nodes: List[Tuple[str, tree_sitter.Node]] = []

    for node, under_error in _walk_tree(tree.root_node):
        ast_node_count += 1
        named_node_count += int(node.is_named)
        function_definition_count += int(
            CPP_ADAPTER.is_function_definition(node)
        )
        if node.is_error or node.type == "ERROR":
            error_ranges.append((node.start_byte, node.end_byte))
            anomaly_nodes.append(("ERROR", node))
        if node.is_missing:
            missing_ranges.append((node.start_byte, node.end_byte))
            anomaly_nodes.append(("missing", node))
        if CPP_ADAPTER.is_preprocessor(node):
            preprocessor_ranges.append((node.start_byte, node.end_byte))
        if node.child_count == 0 and node.end_byte > node.start_byte and not under_error:
            reliable[node.start_byte : node.end_byte] = b"\x01" * (
                node.end_byte - node.start_byte
            )

    macro_related_error_count = sum(
        1
        for error_range in error_ranges
        if any(_ranges_intersect(error_range, macro_range) for macro_range in preprocessor_ranges)
    )
    significant_byte_count = sum(value not in WHITESPACE_BYTES for value in source)
    reliable_significant_byte_count = sum(
        value not in WHITESPACE_BYTES and reliable[index]
        for index, value in enumerate(source)
    )
    uncovered_runs = _unreliable_runs(source, reliable)
    anomalies = [
        {
            "kind": kind,
            "node_kind": node.type,
            "extent": _point_extent(node),
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
            "excerpt": _compact_excerpt(
                source,
                max(0, node.start_byte - 40),
                min(len(source), max(node.end_byte, node.start_byte + 1) + 40),
            ),
        }
        for kind, node in anomaly_nodes
    ]
    status = "clean"
    if error_ranges or missing_ranges:
        status = "recovered"
    if function_definition_count == 0:
        status = f"{status}_no_function"

    return SourceEvidence(
        source_path=source_path,
        project=project,
        byte_count=len(source),
        ast_node_count=ast_node_count,
        named_node_count=named_node_count,
        function_definition_count=function_definition_count,
        error_ranges=error_ranges,
        missing_ranges=missing_ranges,
        preprocessor_ranges=preprocessor_ranges,
        macro_related_error_count=macro_related_error_count,
        significant_byte_count=significant_byte_count,
        reliable_significant_byte_count=reliable_significant_byte_count,
        uncovered_runs=uncovered_runs,
        root_covers_source=(
            tree.root_node.start_byte == 0 and tree.root_node.end_byte == len(source)
        ),
        status=status,
        anomalies=anomalies,
    )


def _source_evidence_dict(evidence: SourceEvidence) -> Dict[str, Any]:
    return {
        "project": evidence.project,
        "source_path": evidence.source_path,
        "status": evidence.status,
        "byte_count": evidence.byte_count,
        "ast_node_count": evidence.ast_node_count,
        "named_node_count": evidence.named_node_count,
        "function_definition_count": evidence.function_definition_count,
        "error_count": len(evidence.error_ranges),
        "missing_count": len(evidence.missing_ranges),
        "preprocessor_node_count": len(evidence.preprocessor_ranges),
        "macro_related_error_count": evidence.macro_related_error_count,
        "significant_byte_count": evidence.significant_byte_count,
        "reliable_significant_byte_count": evidence.reliable_significant_byte_count,
        "ast_coverage": evidence.ast_coverage,
        "uncovered_significant_range_count": len(evidence.uncovered_runs),
        "uncovered_significant_byte_count": (
            evidence.significant_byte_count - evidence.reliable_significant_byte_count
        ),
        "root_covers_source": evidence.root_covers_source,
        "anomalies": evidence.anomalies,
        "uncovered_ranges": [
            {"start_byte": start, "end_byte": end}
            for start, end in evidence.uncovered_runs
        ],
    }


def _legacy_candidates(
    function_ast: Sequence[Mapping[str, Any]],
) -> Iterator[Tuple[str, int, Mapping[str, Any]]]:
    if len(function_ast) < 10:
        return
    extent_valid = "0-0-0-0"
    for index, node_info in enumerate(function_ast):
        code = str(node_info.get("code_snippet") or "")
        kind = str(node_info.get("kind") or "")
        extent = str(node_info.get("extent") or "")
        ast_num = int(node_info.get("ast_num", 0) or 0)
        if not code or ast_num < 5:
            continue
        if kind in FUNCTION_KINDS:
            yield "function", index, node_info
        elif kind in BLOCK_KINDS:
            yield "region", index, node_info
        elif kind in STATEMENT_KINDS and not _contains_extent(extent_valid, extent):
            extent_valid = extent
            yield "statement", index, node_info


def _subtree_has_error(
    function_ast: Sequence[Mapping[str, Any]],
    root_index: int,
) -> bool:
    root_depth = int(function_ast[root_index].get("depth", 0) or 0)
    for index in range(root_index, len(function_ast)):
        node = function_ast[index]
        if index > root_index and int(node.get("depth", 0) or 0) <= root_depth:
            break
        if str(node.get("kind") or "") == "ERROR":
            return True
    return False


def _aggregate_sources(
    evidence_values: Iterable[SourceEvidence],
) -> Dict[str, Any]:
    values = list(evidence_values)
    significant = sum(value.significant_byte_count for value in values)
    reliable = sum(value.reliable_significant_byte_count for value in values)
    return {
        "scanned_file_count": len(values),
        "read_or_parse_success_count": sum(value.status != "failed" for value in values),
        "clean_file_count": sum(value.status.startswith("clean") for value in values),
        "recovered_file_count": sum(value.status.startswith("recovered") for value in values),
        "failed_file_count": sum(value.status == "failed" for value in values),
        "files_with_function_definitions": sum(
            value.function_definition_count > 0 for value in values
        ),
        "files_without_function_definitions": sum(
            value.status != "failed" and value.function_definition_count == 0
            for value in values
        ),
        "root_source_coverage_count": sum(value.root_covers_source for value in values),
        "ast_node_count": sum(value.ast_node_count for value in values),
        "named_node_count": sum(value.named_node_count for value in values),
        "function_definition_count": sum(
            value.function_definition_count for value in values
        ),
        "error_count": sum(len(value.error_ranges) for value in values),
        "missing_count": sum(len(value.missing_ranges) for value in values),
        "preprocessor_node_count": sum(
            len(value.preprocessor_ranges) for value in values
        ),
        "macro_related_error_count": sum(
            value.macro_related_error_count for value in values
        ),
        "significant_byte_count": significant,
        "reliable_significant_byte_count": reliable,
        "ast_coverage": reliable / significant if significant else 1.0,
        "uncovered_significant_byte_count": significant - reliable,
        "uncovered_significant_range_count": sum(
            len(value.uncovered_runs) for value in values
        ),
    }


def audit_parser(
    *,
    source_root: Path,
    dataset_path: Path,
    output_path: Path,
    elapsed_seconds: Optional[float] = None,
    peak_rss_bytes: Optional[int] = None,
    repeat_dataset_path: Optional[Path] = None,
    candidate_profile: str = QUALITY_PROFILE,
    long_line_threshold: int = 80,
    long_byte_threshold: int = 4000,
) -> Dict[str, Any]:
    """执行全量源码、映射和候选质量审计并写出 JSON。"""
    scanner = FileScanner()
    projects = scanner.get_projects(str(source_root))
    project_files = scanner.get_all_source_files(str(source_root))
    parser = ASTParser()

    source_evidence: Dict[str, SourceEvidence] = {}
    logger.info("开始审计 %s 个扫描文件", sum(map(len, project_files)))
    for project, file_paths in zip(projects, project_files):
        for file_path_value in file_paths:
            file_path = Path(file_path_value)
            evidence = _audit_source_file(parser, source_root, project, file_path)
            source_evidence[f"{project}\0{evidence.source_path}"] = evidence

    data = pd.read_pickle(dataset_path)
    candidate_stats: Dict[str, CandidateAccumulator] = {
        "function": CandidateAccumulator(),
        "region": CandidateAccumulator(),
        "statement": CandidateAccumulator(),
        "semantic_def_use": CandidateAccumulator(),
    }
    dataset_files: set[str] = set()
    dataset_function_roots = 0
    dataset_nodes = 0
    root_kinds: Counter[str] = Counter()
    mapping_total = 0
    mapping_range_resolved = 0
    mapping_exact = 0
    mapping_legacy_transform = 0
    mapping_explicit = 0
    mapping_explicit_byte_range = 0
    mapping_explicit_file_identity = 0
    seen_source_candidates: set[Tuple[str, str, str, str, str]] = set()

    for _, row in data.iterrows():
        project = str(row["project"])
        for file_name, file_functions in zip(row["cppFile"], row["func_ast"]):
            source_path = Path(str(file_name)).as_posix()
            file_path = source_root / project / source_path
            dataset_files.add(f"{project}/{source_path}")
            raw_source: Optional[bytes]
            try:
                raw_source = file_path.read_bytes()
            except OSError:
                raw_source = None
            offsets = _line_offsets(raw_source) if raw_source is not None else []
            evidence = source_evidence.get(f"{project}\0{source_path}")

            for function_ast in file_functions:
                if not function_ast:
                    continue
                dataset_function_roots += 1
                dataset_nodes += len(function_ast)
                root_kinds[str(function_ast[0].get("kind") or "")] += 1

                for node_info in function_ast:
                    mapping_total += 1
                    extent = str(node_info.get("extent") or "")
                    byte_range = None
                    if raw_source is not None:
                        explicit_start = node_info.get("start_byte")
                        explicit_end = node_info.get("end_byte")
                        if (
                            isinstance(explicit_start, int)
                            and isinstance(explicit_end, int)
                            and 0 <= explicit_start <= explicit_end <= len(raw_source)
                        ):
                            byte_range = (explicit_start, explicit_end)
                        else:
                            byte_range = _extent_to_bytes(
                                extent, len(raw_source), offsets
                            )
                    if byte_range is not None:
                        mapping_range_resolved += 1
                        raw_text = _decode_bytes(
                            raw_source[byte_range[0] : byte_range[1]]
                        )
                        code = str(node_info.get("code_snippet") or "")
                        if node_info.get("start_byte") is not None:
                            mapping_exact += int(code == raw_text)
                            mapping_legacy_transform += int(
                                code == _legacy_clean(raw_text)
                            )
                        else:
                            legacy_text = raw_text.strip()
                            mapping_exact += int(code == legacy_text)
                            mapping_legacy_transform += int(
                                code == _legacy_clean(legacy_text)
                            )
                    mapping_explicit += int(
                        node_info.get("source_file_id") is not None
                        and node_info.get("start_byte") is not None
                        and node_info.get("end_byte") is not None
                    )
                    mapping_explicit_byte_range += int(
                        node_info.get("start_byte") is not None
                        and node_info.get("end_byte") is not None
                    )
                    mapping_explicit_file_identity += int(
                        node_info.get("source_file_id") is not None
                    )

                for candidate in select_candidates(
                    function_ast,
                    profile=candidate_profile,
                ):
                    level = candidate.level
                    node_info = candidate.node_info
                    extent = str(node_info.get("extent") or "")
                    candidate_key = (
                        project,
                        str(node_info.get("source_file_id") or source_path),
                        extent,
                        level,
                        candidate.origin,
                    )
                    if candidate_key in seen_source_candidates:
                        continue
                    seen_source_candidates.add(candidate_key)
                    byte_range = None
                    if raw_source is not None:
                        explicit_start = node_info.get("start_byte")
                        explicit_end = node_info.get("end_byte")
                        if (
                            isinstance(explicit_start, int)
                            and isinstance(explicit_end, int)
                            and 0 <= explicit_start <= explicit_end <= len(raw_source)
                        ):
                            byte_range = (explicit_start, explicit_end)
                        else:
                            byte_range = _extent_to_bytes(
                                extent, len(raw_source), offsets
                            )
                    node_index = next(
                        (
                            index
                            for index, value in enumerate(function_ast)
                            if value is node_info
                            or (
                                str(value.get("extent") or "") == extent
                                and str(value.get("kind") or "")
                                == str(node_info.get("kind") or "")
                            )
                        ),
                        None,
                    )
                    complete = not bool(
                        int(node_info.get("parse_flags", 0) or 0) & 0b111
                        or
                        node_info.get("has_error")
                        or node_info.get("is_error")
                        or node_info.get("is_missing")
                    )
                    if node_index is not None:
                        complete = complete and not _subtree_has_error(
                            function_ast, node_index
                        )
                    if byte_range is not None and evidence is not None:
                        complete = complete and not any(
                            _ranges_intersect(byte_range, value)
                            for value in evidence.missing_ranges
                        )
                    statistics_key = (
                        "semantic_def_use"
                        if candidate.origin == "semantic_def_use"
                        else level
                    )
                    candidate_stats[statistics_key].add(
                        code=str(node_info.get("code_snippet") or ""),
                        level=level,
                        project=project,
                        source_path=source_path,
                        node_info=node_info,
                        byte_range=byte_range,
                        raw_source=raw_source,
                        complete=complete,
                        long_line_threshold=long_line_threshold,
                        long_byte_threshold=long_byte_threshold,
                    )

    source_projects = {
        project: _aggregate_sources(
            value for value in source_evidence.values() if value.project == project
        )
        for project in projects
    }
    source_summary = _aggregate_sources(source_evidence.values())
    dataset_digest = _sha256_file(dataset_path)
    repeat_digest = (
        _sha256_file(repeat_dataset_path)
        if repeat_dataset_path is not None and repeat_dataset_path.exists()
        else None
    )
    result: Dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "configuration": {
            "candidate_profile": candidate_profile,
            "long_line_threshold": long_line_threshold,
            "long_byte_threshold": long_byte_threshold,
        },
        "inputs": {
            "source_root": source_root.as_posix(),
            "dataset": dataset_path.as_posix(),
            "dataset_sha256": dataset_digest,
            "dataset_bytes": dataset_path.stat().st_size,
            "repeat_dataset": (
                repeat_dataset_path.as_posix() if repeat_dataset_path else None
            ),
            "repeat_dataset_sha256": repeat_digest,
        },
        "performance": {
            "elapsed_seconds": elapsed_seconds,
            "peak_rss_bytes": peak_rss_bytes,
            "byte_identical_repeat": (
                dataset_digest == repeat_digest if repeat_digest is not None else None
            ),
        },
        "source_summary": source_summary,
        "source_projects": source_projects,
        "dataset_summary": {
            "project_count": len(data),
            "included_file_count": len(dataset_files),
            "omitted_scanned_file_count": len(source_evidence) - len(dataset_files),
            "function_root_count": dataset_function_roots,
            "ast_node_count": dataset_nodes,
            "root_kinds": dict(root_kinds.most_common()),
        },
        "mapping": {
            "node_count": mapping_total,
            "range_resolved_count": mapping_range_resolved,
            "range_resolved_rate": (
                mapping_range_resolved / mapping_total if mapping_total else 0.0
            ),
            "verbatim_match_count": mapping_exact,
            "verbatim_match_rate": mapping_exact / mapping_total if mapping_total else 0.0,
            "legacy_transform_match_count": mapping_legacy_transform,
            "legacy_transform_match_rate": (
                mapping_legacy_transform / mapping_total if mapping_total else 0.0
            ),
            "explicit_byte_mapping_count": mapping_explicit,
            "explicit_byte_mapping_rate": (
                mapping_explicit / mapping_total if mapping_total else 0.0
            ),
            "explicit_byte_range_count": mapping_explicit_byte_range,
            "explicit_byte_range_rate": (
                mapping_explicit_byte_range / mapping_total
                if mapping_total
                else 0.0
            ),
            "explicit_file_identity_count": mapping_explicit_file_identity,
            "explicit_file_identity_rate": (
                mapping_explicit_file_identity / mapping_total
                if mapping_total
                else 0.0
            ),
        },
        "candidates": {
            level: accumulator.to_dict()
            for level, accumulator in candidate_stats.items()
        },
        "file_records": [
            _source_evidence_dict(source_evidence[key])
            for key in sorted(source_evidence)
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("Parser 审计已写入: %s", output_path)
    return result


def main() -> None:
    argument_parser = argparse.ArgumentParser(
        description="审计 C++ Parser 的解析完整性、源码映射和候选片段质量"
    )
    argument_parser.add_argument("--source-root", default="repos")
    argument_parser.add_argument("--dataset", required=True)
    argument_parser.add_argument("--output", required=True)
    argument_parser.add_argument("--elapsed-seconds", type=float)
    argument_parser.add_argument("--peak-rss-bytes", type=int)
    argument_parser.add_argument("--repeat-dataset")
    argument_parser.add_argument(
        "--candidate-profile",
        choices=SUPPORTED_PROFILES,
        default=QUALITY_PROFILE,
        help="候选统计策略（默认: quality-v2；legacy 用于历史基线）",
    )
    argument_parser.add_argument("--long-line-threshold", type=int, default=80)
    argument_parser.add_argument("--long-byte-threshold", type=int, default=4000)
    args = argument_parser.parse_args()

    audit_parser(
        source_root=Path(args.source_root),
        dataset_path=Path(args.dataset),
        output_path=Path(args.output),
        elapsed_seconds=args.elapsed_seconds,
        peak_rss_bytes=args.peak_rss_bytes,
        repeat_dataset_path=(
            Path(args.repeat_dataset) if args.repeat_dataset else None
        ),
        candidate_profile=args.candidate_profile,
        long_line_threshold=args.long_line_threshold,
        long_byte_threshold=args.long_byte_threshold,
    )


if __name__ == "__main__":
    main()
