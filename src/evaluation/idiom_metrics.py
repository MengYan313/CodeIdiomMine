"""C++ 代码习语的留一项目评估指标。

同一个训练习语集合同时用于测试项目上的 IC 与 ISP：

* IC_macro：逐函数 AST 节点覆盖率的宏平均；
* IC_micro：所有测试函数 AST 节点的总体覆盖率；
* IC：IC_macro 与 IC_micro 的算术平均；
* ISP：训练习语中至少有一个变体在测试项目复现的比例；
* F1：最终 IC 与 ISP 的调和平均；
* 习语库结构：种类数、簇成员数、跨文件支持数和完整子树 AvgAST。

当前流水线尚未产出参数化 AST 模板。评估器因此把同一候选簇保存的来源实例
视为模板变体，并执行保留 C++ 关键字/运算符、抽象标识符和字面量的结构化词法
匹配。该匹配比空白子串稳定，同时仍要求候选节点类型一致。
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from ..common.logging import get_logger
from ..common.node_kinds import BLOCK_KINDS, FUNCTION_KINDS, STATEMENT_KINDS

logger = get_logger(__name__)

CPP_LANGUAGE = "cpp"
MIN_CANDIDATE_CHILDREN = 5
CANDIDATE_KINDS = FUNCTION_KINDS | BLOCK_KINDS | STATEMENT_KINDS

_CPP_KEYWORDS = {
    "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand",
    "bitor", "bool", "break", "case", "catch", "char", "char8_t",
    "char16_t", "char32_t", "class", "compl", "concept", "const",
    "consteval", "constexpr", "constinit", "const_cast", "continue",
    "co_await", "co_return", "co_yield", "decltype", "default", "delete",
    "do", "double", "dynamic_cast", "else", "enum", "explicit", "export",
    "extern", "false", "float", "for", "friend", "goto", "if", "inline",
    "int", "long", "mutable", "namespace", "new", "noexcept", "not",
    "not_eq", "nullptr", "operator", "or", "or_eq", "private", "protected",
    "public", "register", "reinterpret_cast", "requires", "return", "short",
    "signed", "sizeof", "static", "static_assert", "static_cast", "struct",
    "switch", "template", "this", "thread_local", "throw", "true", "try",
    "typedef", "typeid", "typename", "union", "unsigned", "using", "virtual",
    "void", "volatile", "wchar_t", "while", "xor", "xor_eq",
}
_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*\Z")
_NUMBER_RE = re.compile(
    r"(?:0[xX][0-9A-Fa-f']+|0[bB][01']+|(?:\d[\d']*)(?:\.\d[\d']*)?"
    r"(?:[eEpP][+-]?\d[\d']*)?)(?:[uUlLfFzZ]*)\Z"
)
_STRING_RE = re.compile(r"(?:u8|u|U|L)?\"(?:\\.|[^\"\\])*\"\Z", re.DOTALL)
_CHAR_RE = re.compile(r"(?:u8|u|U|L)?'(?:\\.|[^'\\])*'\Z", re.DOTALL)
_CPP_TOKEN_RE = re.compile(
    r'(?:u8|u|U|L)?R"[^\s(]{0,16}\(.*?\)[^\s"]{0,16}"'
    r'|(?:u8|u|U|L)?"(?:\\.|[^"\\])*"'
    r"|(?:u8|u|U|L)?'(?:\\.|[^'\\])*'"
    r"|//[^\n]*|/\*.*?\*/"
    r"|[A-Za-z_$][A-Za-z0-9_$]*"
    r"|0[xX][0-9A-Fa-f']+|0[bB][01']+"
    r"|(?:\d[\d']*)(?:\.\d[\d']*)?(?:[eEpP][+-]?\d[\d']*)?[uUlLfFzZ]*"
    r"|<=>|>>=|<<=|->\*|\.\*|::|->|\+\+|--|&&|\|\||==|!=|<=|>=|"
    r"\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>|##|\.\.\."
    r"|[^\s]",
    re.DOTALL,
)


def _parse_extent(extent: str) -> Tuple[int, int, int, int]:
    """解析 extent 字符串为 ``(start_line, start_col, end_line, end_col)``。"""
    match = re.fullmatch(r"(\d+)-(\d+)-(\d+)-(\d+)", extent or "")
    if match:
        return tuple(map(int, match.groups()))
    raise ValueError(f"无效的 extent 格式: {extent}")


def _is_within_extent(extent_root: str, extent_cur: str) -> bool:
    """判断 ``extent_cur`` 是否位于 ``extent_root`` 内。"""
    try:
        r_sl, r_sc, r_el, r_ec = _parse_extent(extent_root)
        c_sl, c_sc, c_el, c_ec = _parse_extent(extent_cur)
        return (
            (r_sl < c_sl or (r_sl == c_sl and r_sc <= c_sc))
            and (r_el > c_el or (r_el == c_el and r_ec >= c_ec))
        )
    except (TypeError, ValueError):
        return False


def _get_subtree_size(node_info_list: List[Dict], root_extent: str) -> int:
    """从 DFS AST 列表计算以 ``root_extent`` 为根的完整子树节点数。"""
    for root_idx, node_info in enumerate(node_info_list):
        if node_info.get("extent") != root_extent:
            continue
        root_depth = int(node_info.get("depth", 0) or 0)
        end = root_idx + 1
        while end < len(node_info_list):
            if int(node_info_list[end].get("depth", 0) or 0) <= root_depth:
                break
            end += 1
        return end - root_idx
    return 0


def _normalize_code(code: str) -> str:
    """仅折叠空白；用于精确去重和兼容旧调用。"""
    return " ".join(str(code or "").split())


@lru_cache(maxsize=100_000)
def _canonical_code_tokens(code: str) -> Tuple[str, ...]:
    """生成适合当前非参数化候选的结构化词法 token 序列。"""
    tokens: List[str] = []
    for match in _CPP_TOKEN_RE.finditer(str(code or "")):
        token = match.group(0)
        if token.startswith("//") or token.startswith("/*"):
            continue
        if _STRING_RE.fullmatch(token) or "R\"" in token:
            tokens.append("STR")
        elif _CHAR_RE.fullmatch(token):
            tokens.append("CHAR")
        elif _NUMBER_RE.fullmatch(token):
            tokens.append("NUM")
        elif _IDENTIFIER_RE.fullmatch(token) and token not in _CPP_KEYWORDS:
            tokens.append("ID")
        else:
            tokens.append(token)
    return tuple(tokens)


def _code_signature(code: str) -> str:
    return " ".join(_canonical_code_tokens(str(code or "")))


def _code_match(idiom_code: str, func_code: str) -> bool:
    """判断抽象后的习语 token 序列是否连续出现在函数中。"""
    idiom_signature = _code_signature(idiom_code)
    if not idiom_signature:
        return False
    function_signature = _code_signature(func_code)
    return f" {idiom_signature} " in f" {function_signature} "


def load_idioms(idiom_path: str) -> List[Dict[str, Any]]:
    with open(idiom_path, "rb") as file:
        return pickle.load(file)


def load_dataset(dataset_path: str) -> pd.DataFrame:
    return pd.read_pickle(dataset_path)


def _build_project_index(data: pd.DataFrame) -> Dict[str, int]:
    index: Dict[str, int] = {}
    for i in range(len(data)):
        row = data.iloc[i]
        project = row.get("project", row.get("pros_name"))
        if project is not None:
            index[str(project)] = i
    return index


def _match_file_path(idiom_file: str, dataset_files: Sequence[str]) -> Optional[int]:
    """优先精确路径；仅在后缀或 basename 唯一时使用宽松匹配。"""
    idiom_norm = str(idiom_file or "").replace("\\", "/")
    normalized = [str(path).replace("\\", "/") for path in dataset_files]
    exact = [i for i, path in enumerate(normalized) if path == idiom_norm]
    if len(exact) == 1:
        return exact[0]

    suffix = [
        i for i, path in enumerate(normalized)
        if path.endswith(f"/{idiom_norm}") or idiom_norm.endswith(f"/{path}")
    ]
    if len(suffix) == 1:
        return suffix[0]

    basename = os.path.basename(idiom_norm)
    basename_matches = [
        i for i, path in enumerate(normalized) if os.path.basename(path) == basename
    ]
    return basename_matches[0] if len(basename_matches) == 1 else None


def _is_source_info(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 4
        and isinstance(value[3], dict)
    )


def _flatten_source_infos(value: Any) -> Iterable[Sequence[Any]]:
    if _is_source_info(value):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten_source_infos(item)


def _idiom_source_infos(idiom: Dict[str, Any]) -> List[Sequence[Any]]:
    source_infos = list(_flatten_source_infos(idiom.get("source_infos")))
    if source_infos:
        return source_infos
    return list(_flatten_source_infos(idiom.get("info")))


def _candidate_extent(info: Sequence[Any]) -> str:
    node_info = info[3] if len(info) >= 4 and isinstance(info[3], dict) else {}
    return str(node_info.get("extent") or (info[2] if len(info) >= 3 else ""))


def _candidate_kind(info: Sequence[Any]) -> str:
    node_info = info[3] if len(info) >= 4 and isinstance(info[3], dict) else {}
    return str(node_info.get("kind") or "")


def _candidate_code(info: Sequence[Any]) -> str:
    node_info = info[3] if len(info) >= 4 and isinstance(info[3], dict) else {}
    return str(node_info.get("code_snippet") or "")


def _idiom_patterns(idiom: Dict[str, Any]) -> set[Tuple[str, str]]:
    patterns: set[Tuple[str, str]] = set()
    source_infos = _idiom_source_infos(idiom)
    for info in source_infos:
        signature = _code_signature(_candidate_code(info))
        if signature:
            patterns.add((_candidate_kind(info), signature))

    center = _code_signature(str(idiom.get("center_point") or ""))
    if center:
        representative_kind = _candidate_kind(source_infos[0]) if source_infos else ""
        patterns.add((representative_kind, center))
    return patterns


def _build_pattern_index(
    idioms: Sequence[Dict[str, Any]],
) -> Dict[Tuple[str, str], set[int]]:
    index: Dict[Tuple[str, str], set[int]] = defaultdict(set)
    for idiom_idx, idiom in enumerate(idioms):
        for pattern in _idiom_patterns(idiom):
            index[pattern].add(idiom_idx)
    return dict(index)


def _subtree_end(func_ast: Sequence[Dict[str, Any]], root_idx: int) -> int:
    root_depth = int(func_ast[root_idx].get("depth", 0) or 0)
    end = root_idx + 1
    while end < len(func_ast):
        if int(func_ast[end].get("depth", 0) or 0) <= root_depth:
            break
        end += 1
    return end


def _covered_interval_size(intervals: List[Tuple[int, int]]) -> int:
    if not intervals:
        return 0
    covered = 0
    start, end = sorted(intervals)[0]
    for next_start, next_end in sorted(intervals)[1:]:
        if next_start > end:
            covered += end - start
            start, end = next_start, next_end
        else:
            end = max(end, next_end)
    return covered + end - start


def compute_coverage_stats(
    idioms: List[Dict[str, Any]],
    data: pd.DataFrame,
    project_name: str,
    project_idx: int,
    included_file_indices: Optional[set[int]] = None,
) -> Dict[str, Any]:
    """在一个测试项目上计算宏/微 IC，并返回复现的习语集合。"""
    empty = {
        "IC_macro": 0.0,
        "IC_micro": 0.0,
        "IC": 0.0,
        "matched_idiom_indices": set(),
        "matched_node_count": 0,
        "total_node_count": 0,
        "function_count": 0,
        "function_coverage_sum": 0.0,
        "match_count": 0,
    }
    if not idioms or data is None or data.empty or project_idx < 0:
        return empty

    row = data.iloc[project_idx]
    if str(row.get("project", row.get("pros_name", ""))) != str(project_name):
        return empty
    func_asts = row.get("func_ast", [])
    pattern_index = _build_pattern_index(idioms)
    if not pattern_index:
        return empty

    coverage_values: List[float] = []
    matched_idioms: set[int] = set()
    matched_nodes = 0
    total_nodes = 0
    match_count = 0

    for file_idx, file_functions in enumerate(func_asts):
        if included_file_indices is not None and file_idx not in included_file_indices:
            continue
        for func_ast in file_functions:
            if not func_ast:
                continue
            intervals: List[Tuple[int, int]] = []
            for node_idx, node_info in enumerate(func_ast):
                kind = str(node_info.get("kind") or "")
                if kind not in CANDIDATE_KINDS:
                    continue
                if int(node_info.get("ast_num", 0) or 0) < MIN_CANDIDATE_CHILDREN:
                    continue
                signature = _code_signature(str(node_info.get("code_snippet") or ""))
                if not signature:
                    continue
                idiom_indices = set(pattern_index.get((kind, signature), ()))
                idiom_indices.update(pattern_index.get(("", signature), ()))
                if not idiom_indices:
                    continue
                matched_idioms.update(idiom_indices)
                intervals.append((node_idx, _subtree_end(func_ast, node_idx)))
                match_count += 1

            function_nodes = len(func_ast)
            function_covered = _covered_interval_size(intervals)
            coverage_values.append(function_covered / function_nodes)
            matched_nodes += function_covered
            total_nodes += function_nodes

    if not coverage_values:
        return empty
    ic_macro = sum(coverage_values) / len(coverage_values)
    ic_micro = matched_nodes / total_nodes if total_nodes else 0.0
    return {
        "IC_macro": ic_macro,
        "IC_micro": ic_micro,
        "IC": (ic_macro + ic_micro) / 2,
        "matched_idiom_indices": matched_idioms,
        "matched_node_count": matched_nodes,
        "total_node_count": total_nodes,
        "function_count": len(coverage_values),
        "function_coverage_sum": sum(coverage_values),
        "match_count": match_count,
    }


def compute_idiom_coverage(
    idioms: List[Dict[str, Any]],
    data: pd.DataFrame,
    project_name: str,
    project_idx: int,
) -> float:
    """返回 ``(IC_macro + IC_micro) / 2``。"""
    return float(
        compute_coverage_stats(idioms, data, project_name, project_idx)["IC"]
    )


def compute_idiom_set_precision(
    training_idioms: List[Dict[str, Any]],
    test_func_srcs: List[str],
) -> float:
    """计算训练习语中至少一个变体在测试函数复现的比例。"""
    if not training_idioms or not test_func_srcs:
        return 0.0
    test_signatures = [f" {_code_signature(src)} " for src in test_func_srcs if src]
    matched = 0
    for idiom in training_idioms:
        signatures = {signature for _, signature in _idiom_patterns(idiom)}
        if any(
            f" {signature} " in function_signature
            for signature in signatures
            for function_signature in test_signatures
        ):
            matched += 1
    return matched / len(training_idioms)


def compute_f1(ic: float, isp: float) -> float:
    """计算 IC 与 ISP 的调和平均数。"""
    if ic <= 0 or isp <= 0:
        return 0.0
    return 2 * ic * isp / (ic + isp)


def _representative_info(idiom: Dict[str, Any]) -> Optional[Sequence[Any]]:
    infos = list(_flatten_source_infos(idiom.get("info")))
    if infos:
        return infos[0]
    source_infos = _idiom_source_infos(idiom)
    return source_infos[0] if source_infos else None


def _locate_representative_size(
    idiom: Dict[str, Any],
    data: Optional[pd.DataFrame],
    project_index: Dict[str, int],
) -> float:
    info = _representative_info(idiom)
    if info is not None:
        node_info = info[3] if isinstance(info[3], dict) else {}
        subtree_size = float(node_info.get("subtree_size", 0) or 0)
        if subtree_size > 0:
            return subtree_size

        if data is not None and not data.empty:
            project_idx = project_index.get(str(info[0]), -1)
            if project_idx >= 0:
                row = data.iloc[project_idx]
                file_idx = _match_file_path(str(info[1]), row.get("cppFile", []))
                if file_idx is not None:
                    extent = _candidate_extent(info)
                    func_asts = row.get("func_ast", [])
                    if file_idx < len(func_asts):
                        for func_ast in func_asts[file_idx]:
                            size = _get_subtree_size(func_ast, extent)
                            if size > 0:
                                return float(size)

    average_subtree_size = float(idiom.get("avg_subtree_size", 0) or 0)
    if average_subtree_size > 0:
        return average_subtree_size
    return 1.0 + float(idiom.get("avg_ast_num", 0) or 0)


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def compute_idiom_size_stats(
    idioms: List[Dict[str, Any]],
    data: Optional[pd.DataFrame],
) -> Dict[str, float]:
    if not idioms:
        return {"mean": 0.0, "median": 0.0, "q1": 0.0, "q3": 0.0, "iqr": 0.0}
    project_index = _build_project_index(data) if data is not None and not data.empty else {}
    sizes = [_locate_representative_size(i, data, project_index) for i in idioms]
    q1 = _percentile(sizes, 0.25)
    q3 = _percentile(sizes, 0.75)
    return {
        "mean": sum(sizes) / len(sizes),
        "median": _percentile(sizes, 0.5),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
    }


def compute_idiom_library_stats(
    idioms: List[Dict[str, Any]],
    data: pd.DataFrame,
    project_name: str,
    project_idx: int,
) -> Dict[str, Any]:
    """按簇统计习语库规模；AvgAST 为“簇内实例均值”的簇宏平均。

    每个输入记录代表一种习语，``source_infos`` 中的每个代码片段都是该
    习语的实例。这样大簇的全部成员参与簇大小、跨文件支持与 AST 规模，
    同时最终 AvgAST 不会被单个超大簇完全支配。
    """
    empty = {
        "idiom_type_count": 0,
        "avg_cluster_size": 0.0,
        "avg_cross_file_support": 0.0,
        "AvgAST": 0.0,
        "total_cluster_instances": 0,
        "total_cross_file_support": 0,
        "ast_measured_type_count": 0,
        "ast_type_mean_sum": 0.0,
    }
    if not idioms or data is None or data.empty or project_idx < 0:
        return empty

    row = data.iloc[project_idx]
    if str(row.get("project", row.get("pros_name", ""))) != str(project_name):
        return empty
    files = row.get("cppFile", [])
    func_asts = row.get("func_ast", [])

    cluster_infos: List[List[Sequence[Any]]] = []
    requested_extents: Dict[int, set[str]] = defaultdict(set)
    cluster_sizes: List[int] = []
    file_supports: List[int] = []
    for idiom in idioms:
        infos = _idiom_source_infos(idiom)
        cluster_infos.append(infos)
        cluster_sizes.append(len(infos) if infos else int(idiom.get("cnt", 0) or 0))
        supported_files: set[int] = set()
        for info in infos:
            file_idx = _match_file_path(str(info[1]), files)
            if file_idx is None:
                continue
            supported_files.add(file_idx)
            node_info = info[3] if isinstance(info[3], dict) else {}
            if not node_info.get("subtree_size"):
                requested_extents[file_idx].add(_candidate_extent(info))
        file_supports.append(len(supported_files))

    subtree_sizes: Dict[Tuple[int, str], int] = {}
    for file_idx, extents in requested_extents.items():
        if file_idx >= len(func_asts):
            continue
        for func_ast in func_asts[file_idx]:
            for node_idx, node_info in enumerate(func_ast):
                extent = str(node_info.get("extent") or "")
                if extent in extents:
                    subtree_sizes[(file_idx, extent)] = _subtree_end(func_ast, node_idx) - node_idx

    cluster_ast_means: List[float] = []
    for idiom, infos in zip(idioms, cluster_infos):
        instance_sizes: List[float] = []
        for info in infos:
            node_info = info[3] if isinstance(info[3], dict) else {}
            size = float(node_info.get("subtree_size", 0) or 0)
            if size <= 0:
                file_idx = _match_file_path(str(info[1]), files)
                if file_idx is not None:
                    size = float(
                        subtree_sizes.get((file_idx, _candidate_extent(info)), 0)
                    )
            if size > 0:
                instance_sizes.append(size)
        if instance_sizes:
            cluster_ast_means.append(sum(instance_sizes) / len(instance_sizes))
        else:
            fallback = float(idiom.get("avg_subtree_size", 0) or 0)
            if fallback > 0:
                cluster_ast_means.append(fallback)

    type_count = len(idioms)
    ast_mean_sum = sum(cluster_ast_means)
    return {
        "idiom_type_count": type_count,
        "avg_cluster_size": sum(cluster_sizes) / type_count,
        "avg_cross_file_support": sum(file_supports) / type_count,
        "AvgAST": (
            ast_mean_sum / len(cluster_ast_means) if cluster_ast_means else 0.0
        ),
        "total_cluster_instances": sum(cluster_sizes),
        "total_cross_file_support": sum(file_supports),
        "ast_measured_type_count": len(cluster_ast_means),
        "ast_type_mean_sum": ast_mean_sum,
    }


def compute_avg_idiom_size(
    idioms: List[Dict[str, Any]],
    data: Optional[pd.DataFrame],
    project_name: str,
    project_idx: int = -1,
) -> float:
    """兼容既有 API；使用候选 extent 而不是包含它的函数根 extent。"""
    del project_name, project_idx
    return compute_idiom_size_stats(idioms, data)["mean"]


def _get_all_func_srcs(data: pd.DataFrame, project_idx: int) -> List[str]:
    if data is None or data.empty or project_idx < 0:
        return []
    result: List[str] = []
    for file_functions in data.iloc[project_idx].get("func_src", []):
        if isinstance(file_functions, list):
            result.extend(str(source) for source in file_functions if source)
    return result


def _deduplicate_idioms(idioms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按候选类型和空白归一化源码精确去重，并合并来源证据。"""
    deduplicated: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for idiom in idioms:
        source_infos = _idiom_source_infos(idiom)
        kind = _candidate_kind(source_infos[0]) if source_infos else ""
        key = (kind, _normalize_code(str(idiom.get("center_point") or "")))
        if not key[1]:
            continue
        if key not in deduplicated:
            record = dict(idiom)
            record["source_infos"] = list(source_infos)
            deduplicated[key] = record
            continue
        existing = deduplicated[key]
        existing_infos = list(existing.get("source_infos") or [])
        existing_infos.extend(source_infos)
        existing["source_infos"] = existing_infos
        existing["cnt"] = int(existing.get("cnt", 0) or 0) + int(
            idiom.get("cnt", 0) or 0
        )
    return list(deduplicated.values())


def _stable_file_split(
    project_name: str,
    files: Sequence[str],
    test_fraction: float,
) -> Tuple[set[int], set[int]]:
    """按稳定哈希划分文件，避免依赖 Python 的随机哈希种子。"""
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction 必须位于 (0, 1)")
    file_count = len(files)
    if file_count == 0:
        return set(), set()
    if file_count == 1:
        return set(), {0}
    ordered = sorted(
        range(file_count),
        key=lambda index: hashlib.sha256(
            f"{project_name}\0{str(files[index]).replace(os.sep, '/')}".encode("utf-8")
        ).digest(),
    )
    test_count = min(file_count - 1, max(1, round(file_count * test_fraction)))
    test_indices = set(ordered[:test_count])
    return set(range(file_count)) - test_indices, test_indices


def _restrict_idioms_to_training_files(
    idioms: List[Dict[str, Any]],
    dataset_files: Sequence[str],
    training_file_indices: set[int],
) -> List[Dict[str, Any]]:
    """只保留训练文件提供的模板变体，防止测试实例进入匹配器。"""
    restricted: List[Dict[str, Any]] = []
    for idiom in idioms:
        training_infos = []
        for info in _idiom_source_infos(idiom):
            file_idx = _match_file_path(str(info[1]), dataset_files)
            if file_idx in training_file_indices:
                training_infos.append(info)
        if not training_infos:
            continue
        record = dict(idiom)
        record["info"] = training_infos[0]
        record["source_infos"] = training_infos
        record["center_point"] = _candidate_code(training_infos[0])
        record["cnt"] = len(training_infos)
        restricted.append(record)
    return _deduplicate_idioms(restricted)


def evaluate_project(
    project_name: str,
    idiom_path: str,
    data: pd.DataFrame,
    project_idx: int,
    all_idioms: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """以当前项目为测试集、其他项目的习语为训练输出执行一个 fold。"""
    del idiom_path
    training_projects = sorted(repo for repo in all_idioms if repo != project_name)
    training_idioms = _deduplicate_idioms(
        [
            idiom
            for repo in training_projects
            for idiom in all_idioms.get(repo, [])
        ]
    )
    coverage = compute_coverage_stats(
        training_idioms, data, project_name, project_idx
    )
    matched_idiom_count = len(coverage["matched_idiom_indices"])
    isp = matched_idiom_count / len(training_idioms) if training_idioms else 0.0
    ic_macro = float(coverage["IC_macro"])
    ic_micro = float(coverage["IC_micro"])
    ic = float(coverage["IC"])
    size_stats = compute_idiom_size_stats(training_idioms, data)

    return {
        "project": project_name,
        "training_projects": training_projects,
        "IC_macro": round(ic_macro, 4),
        "IC_micro": round(ic_micro, 4),
        "IC": round(ic, 4),
        "ISP": round(isp, 4),
        "F1": round(compute_f1(ic, isp), 4),
        "avg_idiom_size": round(size_stats["mean"], 2),
        "median_idiom_size": round(size_stats["median"], 2),
        "idiom_size_iqr": round(size_stats["iqr"], 2),
        "idiom_count": len(training_idioms),
        "matched_idiom_count": matched_idiom_count,
        "matched_node_count": int(coverage["matched_node_count"]),
        "total_node_count": int(coverage["total_node_count"]),
        "function_count": int(coverage["function_count"]),
        "function_coverage_sum": float(coverage["function_coverage_sum"]),
        "match_count": int(coverage["match_count"]),
    }


def evaluate_project_file_split(
    project_name: str,
    data: pd.DataFrame,
    project_idx: int,
    project_idioms: List[Dict[str, Any]],
    test_fraction: float,
) -> Dict[str, Any]:
    """在同一项目内按文件划分训练/测试并计算同集合 IC/ISP。"""
    row = data.iloc[project_idx]
    files = row.get("cppFile", [])
    training_files, test_files = _stable_file_split(
        project_name, files, test_fraction
    )
    training_idioms = _restrict_idioms_to_training_files(
        project_idioms, files, training_files
    )
    coverage = compute_coverage_stats(
        training_idioms,
        data,
        project_name,
        project_idx,
        included_file_indices=test_files,
    )
    matched_idiom_count = len(coverage["matched_idiom_indices"])
    isp = matched_idiom_count / len(training_idioms) if training_idioms else 0.0
    ic_macro = float(coverage["IC_macro"])
    ic_micro = float(coverage["IC_micro"])
    ic = float(coverage["IC"])
    size_stats = compute_idiom_size_stats(training_idioms, data)
    return {
        "project": project_name,
        "training_projects": [project_name],
        "training_file_count": len(training_files),
        "test_file_count": len(test_files),
        "test_fraction": test_fraction,
        "IC_macro": round(ic_macro, 4),
        "IC_micro": round(ic_micro, 4),
        "IC": round(ic, 4),
        "ISP": round(isp, 4),
        "F1": round(compute_f1(ic, isp), 4),
        "avg_idiom_size": round(size_stats["mean"], 2),
        "median_idiom_size": round(size_stats["median"], 2),
        "idiom_size_iqr": round(size_stats["iqr"], 2),
        "idiom_count": len(training_idioms),
        "matched_idiom_count": matched_idiom_count,
        "matched_node_count": int(coverage["matched_node_count"]),
        "total_node_count": int(coverage["total_node_count"]),
        "function_count": int(coverage["function_count"]),
        "function_coverage_sum": float(coverage["function_coverage_sum"]),
        "match_count": int(coverage["match_count"]),
    }


def evaluate_mock_cluster_file_split(
    project_name: str,
    data: pd.DataFrame,
    project_idx: int,
    project_idioms: List[Dict[str, Any]],
    test_fraction: float,
) -> Dict[str, Any]:
    """把冻结模拟簇的全部成员视作已知实例，验证覆盖与指标公式。

    聚类本身使用过全量项目，因此这里只是评价器的 evidence-oracle 冒烟，
    不能用于估计真实的未知测试集泛化能力。
    """
    row = data.iloc[project_idx]
    files = row.get("cppFile", [])
    func_asts = row.get("func_ast", [])
    training_files, test_files = _stable_file_split(project_name, files, test_fraction)

    training_idioms: List[Dict[str, Any]] = []
    matched_idioms: set[int] = set()
    evidence_by_file: Dict[int, Dict[str, set[int]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for idiom in project_idioms:
        training_infos: List[Sequence[Any]] = []
        test_infos: List[Tuple[int, Sequence[Any]]] = []
        for info in _idiom_source_infos(idiom):
            file_idx = _match_file_path(str(info[1]), files)
            if file_idx in training_files:
                training_infos.append(info)
            elif file_idx in test_files:
                test_infos.append((file_idx, info))
        if not training_infos:
            continue
        training_idx = len(training_idioms)
        record = dict(idiom)
        record["info"] = training_infos[0]
        record["source_infos"] = training_infos
        record["center_point"] = _candidate_code(training_infos[0])
        record["cnt"] = len(training_infos)
        training_idioms.append(record)
        if test_infos:
            matched_idioms.add(training_idx)
        for file_idx, info in test_infos:
            evidence_by_file[file_idx][_candidate_extent(info)].add(training_idx)

    coverage_values: List[float] = []
    matched_nodes = 0
    total_nodes = 0
    match_count = 0
    for file_idx in sorted(test_files):
        extent_index = evidence_by_file.get(file_idx, {})
        for func_ast in func_asts[file_idx]:
            if not func_ast:
                continue
            intervals: List[Tuple[int, int]] = []
            for node_idx, node_info in enumerate(func_ast):
                idiom_indices = extent_index.get(str(node_info.get("extent") or ""))
                if not idiom_indices:
                    continue
                intervals.append((node_idx, _subtree_end(func_ast, node_idx)))
                match_count += 1
            function_covered = _covered_interval_size(intervals)
            coverage_values.append(function_covered / len(func_ast))
            matched_nodes += function_covered
            total_nodes += len(func_ast)

    ic_macro = sum(coverage_values) / len(coverage_values) if coverage_values else 0.0
    ic_micro = matched_nodes / total_nodes if total_nodes else 0.0
    ic = (ic_macro + ic_micro) / 2
    isp = len(matched_idioms) / len(training_idioms) if training_idioms else 0.0
    size_stats = compute_idiom_size_stats(training_idioms, data)
    return {
        "project": project_name,
        "training_projects": [project_name],
        "training_file_count": len(training_files),
        "test_file_count": len(test_files),
        "test_fraction": test_fraction,
        "IC_macro": round(ic_macro, 4),
        "IC_micro": round(ic_micro, 4),
        "IC": round(ic, 4),
        "ISP": round(isp, 4),
        "F1": round(compute_f1(ic, isp), 4),
        "avg_idiom_size": round(size_stats["mean"], 2),
        "median_idiom_size": round(size_stats["median"], 2),
        "idiom_size_iqr": round(size_stats["iqr"], 2),
        "idiom_count": len(training_idioms),
        "matched_idiom_count": len(matched_idioms),
        "matched_node_count": matched_nodes,
        "total_node_count": total_nodes,
        "function_count": len(coverage_values),
        "function_coverage_sum": sum(coverage_values),
        "match_count": match_count,
    }


def _artifact_pattern(stage: str) -> Tuple[str, str]:
    if stage == "judgment":
        return "*_idiom.pkl", "_idiom"
    if stage == "synthesis":
        return "*_idiom_syn.pkl", "_idiom_syn"
    raise ValueError(f"未知评价阶段: {stage}")


def evaluate_cpp(
    idiom_dir: str,
    dataset_path: str,
    output_path: str,
    artifact_stage: str = "judgment",
    evaluation_mode: str = "leave_one_project_out",
    test_fraction: float = 0.2,
) -> Dict[str, Any]:
    """对所有 C++ 项目执行留一项目评价并保存 JSON。"""
    idiom_root = Path(idiom_dir)
    pattern, suffix = _artifact_pattern(artifact_stage)
    idiom_files = sorted(idiom_root.glob(pattern)) if idiom_root.exists() else []
    if not idiom_files:
        logger.warning("未找到习语文件: %s/%s", idiom_root, pattern)
        return {}

    all_idioms: Dict[str, List[Dict[str, Any]]] = {}
    for path in idiom_files:
        repo = path.stem.removesuffix(suffix)
        all_idioms[repo] = load_idioms(str(path))

    if not os.path.exists(dataset_path):
        logger.warning("数据集不存在，无法执行 AST 匹配: %s", dataset_path)
        return {}
    data = load_dataset(dataset_path)
    project_index = _build_project_index(data)
    has_mock_inputs = any(
        "mock_provenance" in idiom
        for idioms in all_idioms.values()
        for idiom in idioms
    )
    if evaluation_mode == "mock_cluster_file_split" and not has_mock_inputs:
        raise ValueError("mock_cluster_file_split 只允许带 mock_provenance 的模拟产物")

    project_results: List[Dict[str, Any]] = []
    for project_name, project_idx in project_index.items():
        if evaluation_mode == "leave_one_project_out":
            result = evaluate_project(
                project_name=project_name,
                idiom_path=str(idiom_root / f"{project_name}{suffix}.pkl"),
                data=data,
                project_idx=project_idx,
                all_idioms=all_idioms,
            )
        elif evaluation_mode == "within_project_file_split":
            result = evaluate_project_file_split(
                project_name=project_name,
                data=data,
                project_idx=project_idx,
                project_idioms=all_idioms.get(project_name, []),
                test_fraction=test_fraction,
            )
        elif evaluation_mode == "mock_cluster_file_split":
            result = evaluate_mock_cluster_file_split(
                project_name=project_name,
                data=data,
                project_idx=project_idx,
                project_idioms=all_idioms.get(project_name, []),
                test_fraction=test_fraction,
            )
        else:
            raise ValueError(f"未知评价模式: {evaluation_mode}")
        library_stats = compute_idiom_library_stats(
            all_idioms.get(project_name, []),
            data,
            project_name,
            project_idx,
        )
        result.update(
            {
                "idiom_type_count": library_stats["idiom_type_count"],
                "avg_cluster_size": round(library_stats["avg_cluster_size"], 4),
                "avg_cross_file_support": round(
                    library_stats["avg_cross_file_support"], 4
                ),
                "AvgAST": round(library_stats["AvgAST"], 2),
                "total_cluster_instances": library_stats["total_cluster_instances"],
                "total_cross_file_support": library_stats["total_cross_file_support"],
                "ast_measured_type_count": library_stats["ast_measured_type_count"],
                "ast_type_mean_sum": library_stats["ast_type_mean_sum"],
            }
        )
        project_results.append(result)
        logger.info(
            "项目 %s: IC_macro=%.4f, IC_micro=%.4f, IC=%.4f, ISP=%.4f, "
            "F1=%.4f, types=%d, avg_cluster=%.2f, avg_files=%.2f, AvgAST=%.2f",
            project_name,
            result["IC_macro"],
            result["IC_micro"],
            result["IC"],
            result["ISP"],
            result["F1"],
            result["idiom_type_count"],
            result["avg_cluster_size"],
            result["avg_cross_file_support"],
            result["AvgAST"],
        )

    if not project_results:
        payload = {"language": CPP_LANGUAGE, "projects": [], "summary": {}}
    else:
        count = len(project_results)
        matched_nodes = sum(r["matched_node_count"] for r in project_results)
        total_nodes = sum(r["total_node_count"] for r in project_results)
        function_count = sum(r["function_count"] for r in project_results)
        function_coverage_sum = sum(
            r["function_coverage_sum"] for r in project_results
        )
        matched_idioms = sum(r["matched_idiom_count"] for r in project_results)
        evaluated_idioms = sum(r["idiom_count"] for r in project_results)
        type_count = sum(r["idiom_type_count"] for r in project_results)
        cluster_instances = sum(
            r["total_cluster_instances"] for r in project_results
        )
        cross_file_support = sum(
            r["total_cross_file_support"] for r in project_results
        )
        measured_ast_types = sum(
            r["ast_measured_type_count"] for r in project_results
        )
        ast_type_mean_sum = sum(r["ast_type_mean_sum"] for r in project_results)
        repository_macro = {
            "IC_macro": round(
                sum(r["IC_macro"] for r in project_results) / count, 4
            ),
            "IC_micro": round(
                sum(r["IC_micro"] for r in project_results) / count, 4
            ),
            "IC": round(sum(r["IC"] for r in project_results) / count, 4),
            "ISP": round(sum(r["ISP"] for r in project_results) / count, 4),
            "F1": round(sum(r["F1"] for r in project_results) / count, 4),
            "idiom_type_count": round(
                sum(r["idiom_type_count"] for r in project_results) / count, 2
            ),
            "avg_cluster_size": round(
                sum(r["avg_cluster_size"] for r in project_results) / count, 4
            ),
            "avg_cross_file_support": round(
                sum(r["avg_cross_file_support"] for r in project_results) / count,
                4,
            ),
            "AvgAST": round(sum(r["AvgAST"] for r in project_results) / count, 2),
        }
        global_ic_macro = (
            function_coverage_sum / function_count if function_count else 0.0
        )
        global_ic_micro = matched_nodes / total_nodes if total_nodes else 0.0
        global_ic = (global_ic_macro + global_ic_micro) / 2
        global_isp = matched_idioms / evaluated_idioms if evaluated_idioms else 0.0
        global_metrics = {
            "IC_macro": round(global_ic_macro, 4),
            "IC_micro": round(global_ic_micro, 4),
            "IC": round(global_ic, 4),
            "ISP": round(global_isp, 4),
            "F1": round(compute_f1(global_ic, global_isp), 4),
            "idiom_type_count": type_count,
            "avg_cluster_size": round(
                cluster_instances / type_count, 4
            ) if type_count else 0.0,
            "avg_cross_file_support": round(
                cross_file_support / type_count, 4
            ) if type_count else 0.0,
            "AvgAST": round(
                ast_type_mean_sum / measured_ast_types, 2
            ) if measured_ast_types else 0.0,
            "matched_idiom_count": matched_idioms,
            "evaluated_idiom_count": evaluated_idioms,
            "total_cluster_instances": cluster_instances,
            "matched_node_count": matched_nodes,
            "total_node_count": total_nodes,
            "function_count": function_count,
        }
        payload = {
            "language": CPP_LANGUAGE,
            "evaluation_mode": evaluation_mode,
            "artifact_stage": artifact_stage,
            "matcher": (
                "cluster_membership_evidence_oracle"
                if evaluation_mode == "mock_cluster_file_split"
                else "cpp_lexical_structure_v1"
            ),
            "is_mock_evaluation": has_mock_inputs,
            "mock_warning": (
                "聚类在文件划分前已使用完整项目；该结果只验证指标实现，不能作为论文实验。"
                if has_mock_inputs and evaluation_mode in {
                    "within_project_file_split",
                    "mock_cluster_file_split",
                }
                else (
                    "冻结的聚类集合被模拟为习语；该结果未经过 LLM 或人工质量判定。"
                    if has_mock_inputs
                    else None
                )
            ),
            "projects": project_results,
            "repository_macro": repository_macro,
            "global": global_metrics,
            "summary": repository_macro,
        }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("评估结果已保存至 %s", output)
    return payload


def run_evaluation(
    idiom_dir: Optional[str] = None,
    dataset_path: Optional[str] = None,
    output_path: Optional[str] = None,
    artifact_stage: str = "judgment",
    evaluation_mode: str = "leave_one_project_out",
    test_fraction: float = 0.2,
) -> Dict[str, Any]:
    project_root = Path(__file__).resolve().parents[2]
    idiom_dir = idiom_dir or str(project_root / "results" / CPP_LANGUAGE)
    dataset_path = dataset_path or str(project_root / "outputs" / CPP_LANGUAGE / "dataset.pkl")
    output_path = output_path or str(project_root / "results" / CPP_LANGUAGE / "eval.json")
    logger.info("代码习语评估，模式: %s", evaluation_mode)
    logger.info("习语目录: %s", idiom_dir)
    logger.info("数据集: %s", dataset_path)
    logger.info("输出: %s", output_path)
    return evaluate_cpp(
        idiom_dir=idiom_dir,
        dataset_path=dataset_path,
        output_path=output_path,
        artifact_stage=artifact_stage,
        evaluation_mode=evaluation_mode,
        test_fraction=test_fraction,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "C++ 代码习语评估：计算 IC_macro、IC_micro、IC、ISP、F1 "
            "及习语库规模结构"
        )
    )
    parser.add_argument("--idiom-dir", "-i", default=None, help="默认 results/cpp")
    parser.add_argument("--dataset", "-d", default=None, help="默认 outputs/cpp/dataset.pkl")
    parser.add_argument("--output", "-o", default=None, help="默认 results/cpp/eval.json")
    parser.add_argument(
        "--stage",
        choices=("judgment", "synthesis"),
        default="judgment",
        help="评价判断或合成产物，默认 judgment",
    )
    parser.add_argument(
        "--mode",
        choices=(
            "leave_one_project_out",
            "within_project_file_split",
            "mock_cluster_file_split",
        ),
        default="leave_one_project_out",
        help="留一项目泛化、项目内文件划分或冻结簇证据模拟",
    )
    parser.add_argument(
        "--test-fraction",
        type=float,
        default=0.2,
        help="项目内文件划分的测试比例，默认 0.2",
    )
    args = parser.parse_args()
    run_evaluation(
        idiom_dir=args.idiom_dir,
        dataset_path=args.dataset,
        output_path=args.output,
        artifact_stage=args.stage,
        evaluation_mode=args.mode,
        test_fraction=args.test_fraction,
    )


if __name__ == "__main__":
    main()
