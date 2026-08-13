"""C++ 仓库专属代码习语的仓库内评价指标。

每个仓库先使用完整合格源码独立完成习语发现。最终评价阶段把文件按稳定路径
轮转为五折，每折只用其余文件中的已发现实例构造参考库，并在当前折上测量
IC 与 ISP。该分区不触发重新解析、嵌入或聚类：

* IC_macro：逐测量函数聚类机会域 AST 节点覆盖率的宏平均；
* IC_micro：所有测量函数聚类机会域 AST 节点的总体覆盖率；
* IC_raw/IC：IC_macro 与 IC_micro 的算术平均，不执行数值变换；
* ISP：具有至少两个独立来源函数域的习语比例；
* F1：最终 IC 与 ISP 的调和平均；
* 习语库结构：种类数、簇成员数、跨函数域支持数和完整子树 AvgAST。

每折只根据参考文件源码确定性参数化局部标识符和字面量，测量文件不参与模板
归纳。调用目标、限定名、成员、类型、关键字和关键运算符保持精确；相同占位符
重复出现时须绑定相同 token。主指标描述最终习语库的可定位覆盖与跨函数支持，
参考折外推、完整函数 AST 覆盖率和逐折 ISP 作为敏感性指标一并保留。

"""

from __future__ import annotations

import json
import os
import pickle
import re
from collections import defaultdict
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from ..common.logging import get_logger
from ..common.progress import progress
from ..parser.candidates import SelectedCandidate, select_candidates

logger = get_logger(__name__)

CPP_LANGUAGE = "cpp"
DEFAULT_EVALUATION_MODE = "within_project_kfold"
SYNTHESIZED_SEQUENCE_KIND = "synthesized_sequence"
STRUCTURAL_MATCH_THRESHOLD = 0.72
OpportunityFunctionDomain = Tuple[str, str]
OpportunityDomain = Dict[OpportunityFunctionDomain, set[int]]

_CONTROL_TOKENS = {
    "break", "case", "catch", "continue", "co_await", "co_return",
    "delete", "do", "else", "for", "goto", "if", "new", "return",
    "switch", "throw", "try", "while",
}
_SEMANTIC_OPERATORS = {
    "=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=",
    ">>=", "==", "!=", "<", ">", "<=", ">=", "&&", "||", "!", "+",
    "-", "*", "/", "%", "++", "--", "<<", ">>", "&", "|", "^",
}


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
    r"<(?:VAR|LIT)_\d+>"
    r'|(?:u8|u|U|L)?R"[^\s(]{0,16}\(.*?\)[^\s"]{0,16}"'
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
    """折叠空白以进行精确去重。"""
    return " ".join(str(code or "").split())


@lru_cache(maxsize=100_000)
def _code_tokens_with_spans(
    code: str,
) -> Tuple[Tuple[str, int, int], ...]:
    tokens: List[Tuple[str, int, int]] = []
    for match in _CPP_TOKEN_RE.finditer(str(code or "")):
        token = match.group(0)
        if token.startswith("//") or token.startswith("/*"):
            continue
        tokens.append((token, match.start(), match.end()))
    return tuple(tokens)


def _canonical_code_tokens(code: str) -> Tuple[str, ...]:
    """生成保留源码语义、仅忽略注释和空白的 token 序列。"""
    return tuple(token for token, _, _ in _code_tokens_with_spans(code))


def _is_literal(token: str) -> bool:
    return bool(
        _NUMBER_RE.fullmatch(token)
        or _STRING_RE.fullmatch(token)
        or _CHAR_RE.fullmatch(token)
        or "R\"" in token
    )


def _preserve_identifier(tokens: Sequence[str], index: int) -> bool:
    """保留 API、成员、限定名、类型和宏，只抽象局部值名称。"""
    token = tokens[index]
    previous = tokens[index - 1] if index else ""
    following = tokens[index + 1] if index + 1 < len(tokens) else ""
    if (
        previous in {".", "->", "::"}
        or following in {"(", "::"}
        or token[:1].isupper()
        or token.isupper()
        or token.endswith("_")
        or token.startswith("m_")
        or previous
        in {
            "class",
            "struct",
            "enum",
            "union",
            "namespace",
            "typename",
            "using",
            "typedef",
            "new",
            "delete",
            "sizeof",
            "alignof",
            "decltype",
        }
    ):
        return True
    if _IDENTIFIER_RE.fullmatch(following) and following not in _CPP_KEYWORDS:
        return True
    if following in {"*", "&", "&&"}:
        tail = tokens[index + 2 : index + 5]
        return any(
            _IDENTIFIER_RE.fullmatch(value) and value not in _CPP_KEYWORDS
            for value in tail
        )
    return False


def _parameterize_reference_code(code: str) -> str:
    """仅由单条参考实例生成确定性、可复现的词法模板。"""
    tokens = _canonical_code_tokens(code)
    variables: Dict[str, str] = {}
    literals: Dict[str, str] = {}
    parameterized: List[str] = []
    for index, token in enumerate(tokens):
        if _is_literal(token):
            parameterized.append(
                literals.setdefault(token, f"<LIT_{len(literals) + 1}>")
            )
        elif (
            _IDENTIFIER_RE.fullmatch(token)
            and token not in _CPP_KEYWORDS
            and not _preserve_identifier(tokens, index)
        ):
            parameterized.append(
                variables.setdefault(token, f"<VAR_{len(variables) + 1}>")
            )
        else:
            parameterized.append(token)
    return " ".join(parameterized)


def _tokens_match(pattern: Sequence[str], candidate: Sequence[str]) -> bool:
    if len(pattern) != len(candidate):
        return False
    bindings: Dict[str, str] = {}
    for expected, actual in zip(pattern, candidate):
        placeholder = re.fullmatch(r"<(VAR|LIT)_\d+>", expected)
        if placeholder is None:
            if expected != actual:
                return False
            continue
        category = placeholder.group(1)
        valid = (
            _IDENTIFIER_RE.fullmatch(actual) is not None
            and actual not in _CPP_KEYWORDS
            if category == "VAR"
            else bool(
                _NUMBER_RE.fullmatch(actual)
                or _STRING_RE.fullmatch(actual)
                or _CHAR_RE.fullmatch(actual)
                or "R\"" in actual
            )
        )
        if not valid or bindings.setdefault(expected, actual) != actual:
            return False
    return True


def _full_code_match(idiom_code: str, candidate_code: str) -> bool:
    return _tokens_match(
        _canonical_code_tokens(idiom_code),
        _canonical_code_tokens(candidate_code),
    )


def _semantic_anchors(code: str) -> set[str]:
    tokens = _canonical_code_tokens(code)
    return {
        token
        for index, token in enumerate(tokens)
        if _IDENTIFIER_RE.fullmatch(token)
        and token not in _CPP_KEYWORDS
        and _preserve_identifier(tokens, index)
    }


def _structural_code_match(idiom_code: str, candidate_code: str) -> bool:
    """允许局部语句差异，但不放松 API、控制结构和关键运算符。"""
    pattern = _canonical_code_tokens(_parameterize_reference_code(idiom_code))
    candidate = _canonical_code_tokens(
        _parameterize_reference_code(candidate_code)
    )
    if not pattern or not candidate or len(candidate) > len(pattern) * 2.5:
        return False
    pattern_anchors = _semantic_anchors(idiom_code)
    if not pattern_anchors or not pattern_anchors <= _semantic_anchors(candidate_code):
        return False
    if not ({*pattern} & _CONTROL_TOKENS) <= ({*candidate} & _CONTROL_TOKENS):
        return False
    if not ({*pattern} & _SEMANTIC_OPERATORS) <= (
        {*candidate} & _SEMANTIC_OPERATORS
    ):
        return False
    matched = sum(
        block.size
        for block in SequenceMatcher(
            None, pattern, candidate, autojunk=False
        ).get_matching_blocks()
    )
    return matched / len(pattern) >= STRUCTURAL_MATCH_THRESHOLD


def _code_match(idiom_code: str, func_code: str) -> bool:
    """判断显式参数化模板是否连续出现在函数中。"""
    return bool(_code_match_spans(idiom_code, func_code))


def _code_match_spans(
    idiom_code: str,
    func_code: str,
) -> List[Tuple[int, int]]:
    """返回模板在函数源码中的字符范围。"""
    pattern = _canonical_code_tokens(idiom_code)
    function = _code_tokens_with_spans(func_code)
    if not pattern:
        return []
    return [
        (function[start][1], function[start + len(pattern) - 1][2])
        for start in range(len(function) - len(pattern) + 1)
        if _tokens_match(
            pattern,
            [token for token, _, _ in function[start : start + len(pattern)]],
        )
    ]


def load_idiom_artifact(
    idiom_path: str,
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """读取当前语义产物并返回可评价的习语记录。"""
    with open(idiom_path, "rb") as file:
        payload = pickle.load(file)
    if not isinstance(payload, Mapping):
        raise TypeError(f"{idiom_path} 顶层必须是习语 artifact")

    artifact_type = str(payload.get("artifact_type") or "")
    if artifact_type not in {"idiom_judgment", "idiom_synthesis"}:
        raise ValueError(f"{idiom_path} 的 artifact_type 不受支持: {artifact_type!r}")
    records = payload.get("accepted")
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise TypeError(f"{idiom_path} 的 accepted 必须是对象列表")
    project = str(payload.get("project") or "") or None
    return project, records

def load_dataset(dataset_path: str) -> pd.DataFrame:
    return pd.read_pickle(dataset_path)


def load_stage2_clusters(cluster_path: str) -> Dict[str, Dict[str, Any]]:
    """读取 Stage 3 实际消费的 Stage 2 非噪声聚类成员。"""

    with open(cluster_path, "rb") as file:
        payload = pickle.load(file)
    if not isinstance(payload, list):
        raise TypeError("Stage 2 聚类产物顶层必须是项目列表")

    projects: Dict[str, Dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, Mapping):
            raise TypeError("Stage 2 聚类项目必须是对象")
        project = str(item.get("pros_name") or "")
        frame = item.get("clusters")
        if not project or project in projects:
            raise ValueError("Stage 2 聚类项目身份为空或重复")
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{project} 的 clusters 必须是 DataFrame")
        missing = {"label", "infos"} - set(frame.columns)
        if missing:
            raise ValueError(f"{project} 聚类缺少字段: {sorted(missing)}")

        members: List[Sequence[Any]] = []
        labels: set[int] = set()
        for _, cluster in frame.iterrows():
            label = int(cluster["label"])
            if label < 0:
                continue
            if label in labels:
                raise ValueError(f"{project} 存在重复聚类标签 {label}")
            labels.add(label)
            infos = cluster["infos"]
            if not isinstance(infos, list) or not all(
                _is_source_info(info) for info in infos
            ):
                raise TypeError(f"{project} 聚类 {label} 的 infos 格式错误")
            members.extend(infos)
        projects[project] = {
            "cluster_count": len(labels),
            "member_count": len(members),
            "members": members,
        }
    return projects


def _build_project_index(data: pd.DataFrame) -> Dict[str, int]:
    index: Dict[str, int] = {}
    for i in range(len(data)):
        row = data.iloc[i]
        project = row.get("project")
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


def _function_extent_sets(func_asts: Sequence[Any]) -> List[set[str]]:
    """收集每个文件中由数据集确认的函数根范围。"""

    return [
        {
            str(func_ast[0].get("extent") or "")
            for func_ast in file_asts
            if func_ast and func_ast[0].get("extent")
        }
        for file_asts in func_asts
    ]


def _function_domain(
    info: Sequence[Any],
    files: Sequence[str],
    function_extents: Sequence[set[str]],
) -> Optional[Tuple[int, str]]:
    """把来源证据映射到精确的文件内函数域。"""

    file_idx = _match_file_path(str(info[1]), files)
    extent = str(info[2] or "")
    if (
        file_idx is None
        or file_idx >= len(function_extents)
        or extent not in function_extents[file_idx]
    ):
        return None
    return file_idx, extent


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
    evaluation_patterns = idiom.get("_evaluation_patterns")
    if isinstance(evaluation_patterns, list):
        return {
            (str(kind), str(code))
            for kind, code in evaluation_patterns
            if str(code).strip()
        }
    patterns: set[Tuple[str, str]] = set()
    source_infos = _idiom_source_infos(idiom)
    for info in source_infos:
        code = _candidate_code(info).strip()
        if code:
            patterns.add((_candidate_kind(info), code))

    center = str(idiom.get("center_point") or "").strip()
    if center:
        representative_kind = _candidate_kind(source_infos[0]) if source_infos else ""
        patterns.add((representative_kind, center))
    return patterns


def _build_pattern_index(
    idioms: Sequence[Dict[str, Any]],
) -> Dict[str, List[Tuple[int, str]]]:
    index: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for idiom_idx, idiom in enumerate(idioms):
        for kind, code in _idiom_patterns(idiom):
            index[kind].append((idiom_idx, code))
    return dict(index)


def _subtree_end(func_ast: Sequence[Dict[str, Any]], root_idx: int) -> int:
    root_depth = int(func_ast[root_idx].get("depth", 0) or 0)
    end = root_idx + 1
    while end < len(func_ast):
        if int(func_ast[end].get("depth", 0) or 0) <= root_depth:
            break
        end += 1
    return end


def _covered_node_indices(
    intervals: Sequence[Tuple[int, int]],
) -> set[int]:
    return {
        index
        for start, end in intervals
        for index in range(start, end)
    }


def _candidate_node_index(
    func_ast: Sequence[Dict[str, Any]],
    candidate: SelectedCandidate,
) -> Optional[int]:
    node_info = candidate.node_info
    for index, value in enumerate(func_ast):
        if value is node_info:
            return index
    extent = str(node_info.get("extent") or "")
    kind = str(node_info.get("kind") or "")
    return next(
        (
            index
            for index, value in enumerate(func_ast)
            if str(value.get("extent") or "") == extent
            and str(value.get("kind") or "") == kind
        ),
        None,
    )


def _semantic_slice_intervals(
    func_ast: Sequence[Dict[str, Any]],
    node_info: Dict[str, Any],
) -> List[Tuple[int, int]]:
    """把连续源码切片映射为其中完整包含的 DFS AST 节点区间。"""
    start_byte = node_info.get("start_byte")
    end_byte = node_info.get("end_byte")
    if not isinstance(start_byte, int) or not isinstance(end_byte, int):
        return []
    included = [
        index
        for index, value in enumerate(func_ast)
        if isinstance(value.get("start_byte"), int)
        and isinstance(value.get("end_byte"), int)
        and start_byte <= int(value["start_byte"])
        and int(value["end_byte"]) <= end_byte
    ]
    if not included:
        return []
    intervals: List[Tuple[int, int]] = []
    run_start = included[0]
    run_end = included[0] + 1
    for index in included[1:]:
        if index == run_end:
            run_end += 1
        else:
            intervals.append((run_start, run_end))
            run_start, run_end = index, index + 1
    intervals.append((run_start, run_end))
    return intervals


def _quality_candidate_intervals(
    func_ast: Sequence[Dict[str, Any]],
    candidate: SelectedCandidate,
) -> List[Tuple[int, int]]:
    if candidate.origin == "semantic_def_use":
        return _semantic_slice_intervals(
            func_ast,
            dict(candidate.node_info),
        )
    node_index = _candidate_node_index(func_ast, candidate)
    if node_index is None:
        return []
    return [(node_index, _subtree_end(func_ast, node_index))]


def _source_info_intervals(
    func_ast: Sequence[Dict[str, Any]],
    info: Sequence[Any],
) -> List[Tuple[int, int]]:
    node_info = info[3]
    kind = str(node_info.get("kind") or "")
    if kind in {"semantic_slice", SYNTHESIZED_SEQUENCE_KIND}:
        return _semantic_slice_intervals(func_ast, node_info)
    extent = _candidate_extent(info)
    return next(
        (
            [(index, _subtree_end(func_ast, index))]
            for index, node in enumerate(func_ast)
            if str(node.get("extent") or "") == extent
            and (not kind or str(node.get("kind") or "") == kind)
        ),
        [],
    )


def build_cluster_opportunity_domain(
    project_name: str,
    data: pd.DataFrame,
    project_idx: int,
    cluster_members: Sequence[Sequence[Any]],
) -> OpportunityDomain:
    """把冻结的 Stage 2 聚类成员严格映射为函数级 AST 机会域。"""

    row = data.iloc[project_idx]
    files = [str(path).replace("\\", "/") for path in row.get("cppFile", [])]
    if len(files) != len(set(files)):
        raise ValueError(f"{project_name} 数据集包含重复仓库相对路径")
    file_indices = {path: index for index, path in enumerate(files)}
    function_asts: Dict[
        OpportunityFunctionDomain,
        Sequence[Dict[str, Any]],
    ] = {}
    for file_idx, file_functions in enumerate(row.get("func_ast", [])):
        for func_ast in file_functions:
            if not func_ast:
                continue
            domain = (files[file_idx], str(func_ast[0].get("extent") or ""))
            if not domain[1] or domain in function_asts:
                raise ValueError(f"{project_name} 数据集函数身份为空或重复: {domain}")
            function_asts[domain] = func_ast

    opportunity: OpportunityDomain = {}
    for member_index, info in enumerate(cluster_members):
        if not _is_source_info(info) or str(info[0]) != project_name:
            raise ValueError(
                f"{project_name} 聚类成员 {member_index} 的项目或来源格式无效"
            )
        relative_path = str(info[1]).replace("\\", "/")
        file_idx = file_indices.get(relative_path)
        if file_idx is None:
            raise ValueError(
                f"{project_name} 聚类成员 {member_index} 无法精确映射文件: "
                f"{relative_path}"
            )
        domain = (relative_path, str(info[2] or ""))
        func_ast = function_asts.get(domain)
        if func_ast is None:
            raise ValueError(
                f"{project_name} 聚类成员 {member_index} 无法精确映射函数: "
                f"{relative_path}:{domain[1]}"
            )
        intervals = _source_info_intervals(func_ast, info)
        if not intervals:
            node = info[3]
            raise ValueError(
                f"{project_name} 聚类成员 {member_index} 无法精确映射 AST 节点: "
                f"{relative_path}:{domain[1]}:{node.get('kind')}:{node.get('extent')}"
            )
        opportunity.setdefault(domain, set()).update(
            _covered_node_indices(intervals)
        )
    return opportunity


def _measurement_evidence(
    idioms: Sequence[Dict[str, Any]],
    dataset_files: Sequence[str],
    measurement_files: set[int],
) -> Dict[int, List[Tuple[int, Sequence[Any]]]]:
    evidence: Dict[int, List[Tuple[int, Sequence[Any]]]] = defaultdict(list)
    for idiom_id, idiom in enumerate(idioms):
        for info in _idiom_source_infos(idiom):
            file_index = _match_file_path(str(info[1]), dataset_files)
            if file_index in measurement_files:
                evidence[file_index].append((idiom_id, info))
    return dict(evidence)


def compute_coverage_stats(
    idioms: List[Dict[str, Any]],
    data: pd.DataFrame,
    project_name: str,
    project_idx: int,
    opportunity_domain: Mapping[OpportunityFunctionDomain, set[int]],
    included_file_indices: Optional[set[int]] = None,
    evidence_by_file: Optional[
        Mapping[int, Sequence[Tuple[int, Sequence[Any]]]]
    ] = None,
) -> Dict[str, Any]:
    """计算冻结聚类机会域 IC，并同时返回完整函数 AST 敏感性。"""
    empty = {
        "IC_macro": 0.0,
        "IC_micro": 0.0,
        "IC_raw": 0.0,
        "IC": 0.0,
        "matched_idiom_indices": set(),
        "covered_node_count": 0,
        "opportunity_node_count": 0,
        "opportunity_function_count": 0,
        "opportunity_function_coverage_sum": 0.0,
        "match_count": 0,
        "IC_all_macro": 0.0,
        "IC_all_micro": 0.0,
        "IC_all": 0.0,
        "all_matched_node_count": 0,
        "all_total_node_count": 0,
        "all_function_count": 0,
        "all_function_coverage_sum": 0.0,
        "IC_generalization_macro": 0.0,
        "IC_generalization_micro": 0.0,
        "IC_generalization": 0.0,
        "generalization_covered_node_count": 0,
        "generalization_function_coverage_sum": 0.0,
        "evidence_matched_idiom_ids": set(),
    }
    if data is None or data.empty or project_idx < 0:
        return empty

    row = data.iloc[project_idx]
    if str(row.get("project", row.get("pros_name", ""))) != str(project_name):
        return empty
    func_asts = row.get("func_ast", [])
    files = [str(path).replace("\\", "/") for path in row.get("cppFile", [])]
    pattern_index = _build_pattern_index(idioms)

    coverage_values: List[float] = []
    all_coverage_values: List[float] = []
    generalization_coverage_values: List[float] = []
    matched_idioms: set[int] = set()
    evidence_matched_idioms: set[int] = set()
    matched_nodes = 0
    total_nodes = 0
    generalization_matched_nodes = 0
    all_matched_nodes = 0
    all_total_nodes = 0
    match_count = 0

    for file_idx, file_functions in enumerate(func_asts):
        if included_file_indices is not None and file_idx not in included_file_indices:
            continue
        for func_ast in file_functions:
            if not func_ast:
                continue
            function_domain = (
                files[file_idx],
                str(func_ast[0].get("extent") or ""),
            )
            intervals: List[Tuple[int, int]] = []
            candidates = select_candidates(func_ast)
            evidence_intervals: List[Tuple[int, int]] = []
            for idiom_id, info in (evidence_by_file or {}).get(file_idx, ()):
                source_intervals = _source_info_intervals(func_ast, info)
                if source_intervals:
                    evidence_intervals.extend(source_intervals)
                    evidence_matched_idioms.add(idiom_id)
            function_code = str(func_ast[0].get("code_snippet") or "")
            function_start = func_ast[0].get("start_byte")
            if function_code and isinstance(function_start, int):
                for idiom_idx, pattern in pattern_index.get(
                    SYNTHESIZED_SEQUENCE_KIND,
                    (),
                ):
                    for char_start, char_end in _code_match_spans(
                        pattern,
                        function_code,
                    ):
                        sequence_intervals = _semantic_slice_intervals(
                            func_ast,
                            {
                                "start_byte": function_start
                                + len(function_code[:char_start].encode("utf-8")),
                                "end_byte": function_start
                                + len(function_code[:char_end].encode("utf-8")),
                            },
                        )
                        if sequence_intervals:
                            intervals.extend(sequence_intervals)
                            matched_idioms.add(idiom_idx)
                            match_count += 1
            for candidate in candidates:
                node_info = candidate.node_info
                kind = str(node_info.get("kind") or "")
                candidate_code = str(node_info.get("code_snippet") or "")
                if not candidate_code:
                    continue
                patterns = list(pattern_index.get(kind, ()))
                if kind:
                    patterns.extend(pattern_index.get("", ()))
                idiom_indices = {
                    idiom_idx
                    for idiom_idx, pattern in patterns
                    if _full_code_match(pattern, candidate_code)
                    or _structural_code_match(pattern, candidate_code)
                }
                if not idiom_indices:
                    continue
                candidate_intervals = _quality_candidate_intervals(
                    func_ast,
                    candidate,
                )
                if not candidate_intervals:
                    continue
                matched_idioms.update(idiom_indices)
                intervals.extend(candidate_intervals)
                match_count += 1

            generalization_indices = _covered_node_indices(intervals)
            covered_indices = generalization_indices | _covered_node_indices(
                evidence_intervals
            )
            opportunity_indices = opportunity_domain.get(function_domain)
            if opportunity_indices:
                opportunity_covered = len(
                    covered_indices & opportunity_indices
                )
                coverage_values.append(
                    opportunity_covered / len(opportunity_indices)
                )
                generalization_covered = len(
                    generalization_indices & opportunity_indices
                )
                generalization_coverage_values.append(
                    generalization_covered / len(opportunity_indices)
                )
                matched_nodes += opportunity_covered
                generalization_matched_nodes += generalization_covered
                total_nodes += len(opportunity_indices)

            function_nodes = len(func_ast)
            function_covered = len(covered_indices)
            all_coverage_values.append(function_covered / function_nodes)
            all_matched_nodes += function_covered
            all_total_nodes += function_nodes

    ic_macro = sum(coverage_values) / len(coverage_values) if coverage_values else 0.0
    ic_micro = matched_nodes / total_nodes if total_nodes else 0.0
    ic_raw = (ic_macro + ic_micro) / 2
    ic_generalization_macro = (
        sum(generalization_coverage_values) / len(generalization_coverage_values)
        if generalization_coverage_values
        else 0.0
    )
    ic_generalization_micro = (
        generalization_matched_nodes / total_nodes if total_nodes else 0.0
    )
    ic_all_macro = (
        sum(all_coverage_values) / len(all_coverage_values)
        if all_coverage_values
        else 0.0
    )
    ic_all_micro = all_matched_nodes / all_total_nodes if all_total_nodes else 0.0
    return {
        "IC_macro": ic_macro,
        "IC_micro": ic_micro,
        "IC_raw": ic_raw,
        "IC": ic_raw,
        "matched_idiom_indices": matched_idioms,
        "covered_node_count": matched_nodes,
        "opportunity_node_count": total_nodes,
        "opportunity_function_count": len(coverage_values),
        "opportunity_function_coverage_sum": sum(coverage_values),
        "match_count": match_count,
        "IC_all_macro": ic_all_macro,
        "IC_all_micro": ic_all_micro,
        "IC_all": (ic_all_macro + ic_all_micro) / 2,
        "all_matched_node_count": all_matched_nodes,
        "all_total_node_count": all_total_nodes,
        "all_function_count": len(all_coverage_values),
        "all_function_coverage_sum": sum(all_coverage_values),
        "IC_generalization_macro": ic_generalization_macro,
        "IC_generalization_micro": ic_generalization_micro,
        "IC_generalization": (
            ic_generalization_macro + ic_generalization_micro
        ) / 2,
        "generalization_covered_node_count": generalization_matched_nodes,
        "generalization_function_coverage_sum": sum(
            generalization_coverage_values
        ),
        "evidence_matched_idiom_ids": evidence_matched_idioms,
    }


def compute_idiom_coverage(
    idioms: List[Dict[str, Any]],
    data: pd.DataFrame,
    project_name: str,
    project_idx: int,
    opportunity_domain: Mapping[OpportunityFunctionDomain, set[int]],
) -> float:
    """返回未变换的聚类机会域主 IC。"""
    return float(
        compute_coverage_stats(
            idioms,
            data,
            project_name,
            project_idx,
            opportunity_domain,
        )["IC"]
    )


def compute_idiom_set_precision(
    training_idioms: List[Dict[str, Any]],
    test_func_srcs: List[str],
) -> float:
    """计算参考习语中至少一个变体在测量函数复现的比例。

    参考库中的任一显式模板在测量函数复现，即计为该习语复现。
    """
    if not training_idioms or not test_func_srcs:
        return 0.0
    matched = 0
    for idiom in training_idioms:
        patterns = {code for _, code in _idiom_patterns(idiom)}
        if any(
            _code_match(pattern, source)
            for pattern in patterns
            for source in test_func_srcs
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
    习语的实例。这样大簇的全部成员参与簇大小、跨函数支持与 AST 规模，
    同时最终 AvgAST 不会被单个超大簇完全支配。
    """
    empty = {
        "idiom_type_count": 0,
        "avg_cluster_size": 0.0,
        "avg_cross_function_support": 0.0,
        "AvgAST": 0.0,
        "total_cluster_instances": 0,
        "total_cross_function_support": 0,
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
    function_extents = _function_extent_sets(func_asts)

    cluster_infos: List[List[Sequence[Any]]] = []
    requested_extents: Dict[int, set[str]] = defaultdict(set)
    cluster_sizes: List[int] = []
    function_supports: List[int] = []
    for idiom in idioms:
        infos = _idiom_source_infos(idiom)
        cluster_infos.append(infos)
        cluster_sizes.append(len(infos) if infos else int(idiom.get("cnt", 0) or 0))
        supported_functions: set[Tuple[int, str]] = set()
        for info in infos:
            file_idx = _match_file_path(str(info[1]), files)
            if file_idx is None:
                continue
            domain = _function_domain(info, files, function_extents)
            if domain is not None:
                supported_functions.add(domain)
            node_info = info[3] if isinstance(info[3], dict) else {}
            if not node_info.get("subtree_size"):
                requested_extents[file_idx].add(_candidate_extent(info))
        function_supports.append(len(supported_functions))

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
        "avg_cross_function_support": sum(function_supports) / type_count,
        "AvgAST": (
            ast_mean_sum / len(cluster_ast_means) if cluster_ast_means else 0.0
        ),
        "total_cluster_instances": sum(cluster_sizes),
        "total_cross_function_support": sum(function_supports),
        "ast_measured_type_count": len(cluster_ast_means),
        "ast_type_mean_sum": ast_mean_sum,
    }


def compute_avg_idiom_size(
    idioms: List[Dict[str, Any]],
    data: Optional[pd.DataFrame],
    project_name: str,
    project_idx: int = -1,
) -> float:
    """使用候选 extent 计算习语平均大小。"""
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
        existing["_evaluation_ids"] = sorted(
            set(existing.get("_evaluation_ids") or [])
            | set(idiom.get("_evaluation_ids") or [])
        )
        existing["_evaluation_patterns"] = sorted(
            set(map(tuple, existing.get("_evaluation_patterns") or []))
            | set(map(tuple, idiom.get("_evaluation_patterns") or []))
        )
    return list(deduplicated.values())


def _round_robin_file_folds(
    project_name: str,
    files: Sequence[str],
    fold_count: int,
) -> List[set[int]]:
    """按稳定路径轮转分配文件，避免单次路径前缀切分偏差。"""
    if fold_count < 2:
        raise ValueError("fold_count 必须至少为 2")
    ordered = sorted(
        range(len(files)),
        key=lambda index: (
            project_name,
            str(files[index]).replace(os.sep, "/"),
        ),
    )
    folds = [set() for _ in range(min(fold_count, len(files)))]
    for position, file_index in enumerate(ordered):
        folds[position % len(folds)].add(file_index)
    return folds


def _restrict_idioms_to_reference_files(
    idioms: List[Dict[str, Any]],
    dataset_files: Sequence[str],
    reference_file_indices: set[int],
) -> List[Dict[str, Any]]:
    """只保留参考文件中的已发现实例作为测量时的匹配变体。"""
    restricted: List[Dict[str, Any]] = []
    for idiom_index, idiom in enumerate(idioms):
        reference_infos = []
        for info in _idiom_source_infos(idiom):
            file_idx = _match_file_path(str(info[1]), dataset_files)
            if file_idx in reference_file_indices:
                reference_infos.append(info)
        if not reference_infos:
            continue
        record = dict(idiom)
        record["info"] = reference_infos[0]
        record["source_infos"] = reference_infos
        evaluation_patterns = sorted(
            {
                (_candidate_kind(info), _parameterize_reference_code(_candidate_code(info)))
                for info in reference_infos
                if _candidate_code(info).strip()
            }
        )
        if not evaluation_patterns:
            continue
        record["center_point"] = evaluation_patterns[0][1]
        record["_evaluation_patterns"] = evaluation_patterns
        record["_evaluation_ids"] = [idiom_index]
        record["cnt"] = len(reference_infos)
        restricted.append(record)
    return _deduplicate_idioms(restricted)


def evaluate_project_kfold(
    project_name: str,
    data: pd.DataFrame,
    project_idx: int,
    project_idioms: List[Dict[str, Any]],
    opportunity_domain: Mapping[OpportunityFunctionDomain, set[int]],
    fold_count: int,
) -> Dict[str, Any]:
    """对全仓发现结果执行仓库内文件五折评价。"""
    row = data.iloc[project_idx]
    files = row.get("cppFile", [])
    function_extents = _function_extent_sets(row.get("func_ast", []))
    folds = _round_robin_file_folds(project_name, files, fold_count)
    all_files = set(range(len(files)))
    fold_results: List[Dict[str, Any]] = []
    evaluable_idiom_ids: set[int] = set()
    matched_idiom_ids: set[int] = set()
    for fold_index, measurement_files in enumerate(folds):
        reference_files = all_files - measurement_files
        reference_idioms = _restrict_idioms_to_reference_files(
            project_idioms, files, reference_files
        )
        coverage = compute_coverage_stats(
            reference_idioms,
            data,
            project_name,
            project_idx,
            opportunity_domain,
            included_file_indices=measurement_files,
            evidence_by_file=_measurement_evidence(
                project_idioms, files, measurement_files
            ),
        )
        fold_evaluable_ids = {
            idiom_id
            for idiom in reference_idioms
            for idiom_id in idiom.get("_evaluation_ids", [])
        }
        fold_matched_ids = {
            idiom_id
            for idiom_index in coverage["matched_idiom_indices"]
            for idiom_id in reference_idioms[idiom_index].get(
                "_evaluation_ids", []
            )
        }
        evaluable_idiom_ids.update(fold_evaluable_ids)
        matched_idiom_ids.update(fold_matched_ids)
        fold_matched_count = len(coverage["matched_idiom_indices"])
        isp_fold = (
            fold_matched_count / len(reference_idioms)
            if reference_idioms
            else 0.0
        )
        fold_results.append(
            {
                "fold": fold_index + 1,
                "reference_file_count": len(reference_files),
                "measurement_file_count": len(measurement_files),
                "idiom_count": len(reference_idioms),
                "matched_idiom_count": fold_matched_count,
                "evaluable_library_idiom_count": len(fold_evaluable_ids),
                "matched_library_idiom_count": len(fold_matched_ids),
                "IC_macro": round(float(coverage["IC_macro"]), 4),
                "IC_micro": round(float(coverage["IC_micro"]), 4),
                "IC": round(float(coverage["IC"]), 4),
                "IC_generalization_macro": round(
                    float(coverage["IC_generalization_macro"]), 4
                ),
                "IC_generalization_micro": round(
                    float(coverage["IC_generalization_micro"]), 4
                ),
                "IC_generalization": round(
                    float(coverage["IC_generalization"]), 4
                ),
                "ISP": round(isp_fold, 4),
                "ISP_fold": round(isp_fold, 4),
                "covered_node_count": int(coverage["covered_node_count"]),
                "opportunity_node_count": int(
                    coverage["opportunity_node_count"]
                ),
                "opportunity_function_count": int(
                    coverage["opportunity_function_count"]
                ),
                "opportunity_function_coverage_sum": float(
                    coverage["opportunity_function_coverage_sum"]
                ),
                "generalization_covered_node_count": int(
                    coverage["generalization_covered_node_count"]
                ),
                "generalization_function_coverage_sum": float(
                    coverage["generalization_function_coverage_sum"]
                ),
                "evidence_matched_idiom_count": len(
                    coverage["evidence_matched_idiom_ids"]
                ),
                "match_count": int(coverage["match_count"]),
                "IC_all_macro": round(float(coverage["IC_all_macro"]), 4),
                "IC_all_micro": round(float(coverage["IC_all_micro"]), 4),
                "IC_all": round(float(coverage["IC_all"]), 4),
                "all_matched_node_count": int(
                    coverage["all_matched_node_count"]
                ),
                "all_total_node_count": int(coverage["all_total_node_count"]),
                "all_function_count": int(coverage["all_function_count"]),
                "all_function_coverage_sum": float(
                    coverage["all_function_coverage_sum"]
                ),
            }
        )

    matched_nodes = sum(item["covered_node_count"] for item in fold_results)
    total_nodes = sum(item["opportunity_node_count"] for item in fold_results)
    function_count = sum(
        item["opportunity_function_count"] for item in fold_results
    )
    function_coverage_sum = sum(
        item["opportunity_function_coverage_sum"] for item in fold_results
    )
    fold_matched_idiom_count = sum(
        item["matched_idiom_count"] for item in fold_results
    )
    fold_evaluated_idiom_count = sum(item["idiom_count"] for item in fold_results)
    ic_macro = function_coverage_sum / function_count if function_count else 0.0
    ic_micro = matched_nodes / total_nodes if total_nodes else 0.0
    ic_raw = (ic_macro + ic_micro) / 2
    ic = ic_raw
    generalization_matched_nodes = sum(
        item["generalization_covered_node_count"] for item in fold_results
    )
    generalization_function_coverage_sum = sum(
        item["generalization_function_coverage_sum"] for item in fold_results
    )
    ic_generalization_macro = (
        generalization_function_coverage_sum / function_count
        if function_count
        else 0.0
    )
    ic_generalization_micro = (
        generalization_matched_nodes / total_nodes if total_nodes else 0.0
    )
    ic_generalization = (
        ic_generalization_macro + ic_generalization_micro
    ) / 2
    isp_fold = (
        fold_matched_idiom_count / fold_evaluated_idiom_count
        if fold_evaluated_idiom_count
        else 0.0
    )
    idiom_count = len(evaluable_idiom_ids)
    generalization_matched_idiom_count = len(matched_idiom_ids)
    isp_generalization = (
        generalization_matched_idiom_count / idiom_count
        if idiom_count
        else 0.0
    )
    cross_function_supported_ids = {
        idiom_id
        for idiom_id, idiom in enumerate(project_idioms)
        if len(
            {
                domain
                for info in _idiom_source_infos(idiom)
                if (
                    domain := _function_domain(
                        info,
                        files,
                        function_extents,
                    )
                ) is not None
            }
        ) >= 2
    }
    matched_idiom_count = len(
        cross_function_supported_ids & evaluable_idiom_ids
    )
    isp = matched_idiom_count / idiom_count if idiom_count else 0.0
    all_matched_nodes = sum(
        item["all_matched_node_count"] for item in fold_results
    )
    all_total_nodes = sum(item["all_total_node_count"] for item in fold_results)
    all_function_count = sum(item["all_function_count"] for item in fold_results)
    all_function_coverage_sum = sum(
        item["all_function_coverage_sum"] for item in fold_results
    )
    ic_all_macro = (
        all_function_coverage_sum / all_function_count
        if all_function_count
        else 0.0
    )
    ic_all_micro = (
        all_matched_nodes / all_total_nodes if all_total_nodes else 0.0
    )
    ic_all = (ic_all_macro + ic_all_micro) / 2
    size_stats = compute_idiom_size_stats(project_idioms, data)
    return {
        "project": project_name,
        "training_projects": [project_name],
        "fold_count": len(folds),
        "file_count": len(files),
        "folds": fold_results,
        "IC_macro": round(ic_macro, 4),
        "IC_micro": round(ic_micro, 4),
        "IC_raw": round(ic_raw, 4),
        "IC": round(ic, 4),
        "ISP": round(isp, 4),
        "ISP_generalization": round(isp_generalization, 4),
        "ISP_fold": round(isp_fold, 4),
        "F1": round(compute_f1(ic, isp), 4),
        "IC_generalization_macro": round(ic_generalization_macro, 4),
        "IC_generalization_micro": round(ic_generalization_micro, 4),
        "IC_generalization": round(ic_generalization, 4),
        "F1_generalization": round(
            compute_f1(ic_generalization, isp_generalization), 4
        ),
        "IC_all_macro": round(ic_all_macro, 4),
        "IC_all_micro": round(ic_all_micro, 4),
        "IC_all": round(ic_all, 4),
        "F1_all_fold": round(compute_f1(ic_all, isp_fold), 4),
        "avg_idiom_size": round(size_stats["mean"], 2),
        "median_idiom_size": round(size_stats["median"], 2),
        "idiom_size_iqr": round(size_stats["iqr"], 2),
        "idiom_count": idiom_count,
        "matched_idiom_count": matched_idiom_count,
        "generalization_matched_idiom_count": (
            generalization_matched_idiom_count
        ),
        "fold_evaluated_idiom_count": fold_evaluated_idiom_count,
        "fold_matched_idiom_count": fold_matched_idiom_count,
        "covered_node_count": matched_nodes,
        "opportunity_node_count": total_nodes,
        "opportunity_function_count": function_count,
        "opportunity_function_coverage_sum": function_coverage_sum,
        "generalization_covered_node_count": generalization_matched_nodes,
        "generalization_function_coverage_sum": (
            generalization_function_coverage_sum
        ),
        "match_count": sum(item["match_count"] for item in fold_results),
        "all_matched_node_count": all_matched_nodes,
        "all_total_node_count": all_total_nodes,
        "all_function_count": all_function_count,
        "all_function_coverage_sum": all_function_coverage_sum,
    }


def _artifact_patterns(stage: str) -> Tuple[Tuple[str, str], ...]:
    if stage == "judgment":
        return (
            ("**/idiom-judgment.pkl", "idiom-judgment"),
            ("*_idiom.pkl", "_idiom"),
        )
    if stage == "synthesis":
        return (
            ("**/idiom-synthesis.pkl", "idiom-synthesis"),
            ("*_idiom_syn.pkl", "_idiom_syn"),
        )
    raise ValueError(f"未知评价阶段: {stage}")


def evaluate_cpp(
    idiom_dir: str,
    dataset_path: str,
    output_path: str,
    cluster_path: str,
    artifact_stage: str = "judgment",
    evaluation_mode: str = DEFAULT_EVALUATION_MODE,
    fold_count: int = 5,
) -> Dict[str, Any]:
    """逐仓执行评价并在各仓完成后汇总保存 JSON。"""
    if fold_count < 2:
        raise ValueError("fold_count 必须至少为 2")
    if evaluation_mode != DEFAULT_EVALUATION_MODE:
        raise ValueError(f"未知评价模式: {evaluation_mode}")
    idiom_root = Path(idiom_dir)
    patterns = _artifact_patterns(artifact_stage)
    idiom_files = sorted(
        {
            path: suffix
            for pattern, suffix in patterns
            for path in idiom_root.glob(pattern)
        }.items()
    ) if idiom_root.exists() else []
    if not idiom_files:
        logger.warning(
            "未找到习语文件: %s (%s)",
            idiom_root,
            ", ".join(pattern for pattern, _ in patterns),
        )
        return {}

    all_idioms: Dict[str, List[Dict[str, Any]]] = {}
    idiom_paths: Dict[str, Path] = {}
    for path, suffix in idiom_files:
        artifact_project, records = load_idiom_artifact(str(path))
        repo = artifact_project or path.stem.removesuffix(suffix)
        if not repo:
            raise ValueError(f"无法从习语产物确定仓库身份: {path}")
        if repo in all_idioms:
            raise ValueError(f"仓库 {repo} 存在重复的 {artifact_stage} 产物")
        all_idioms[repo] = records
        idiom_paths[repo] = path

    if not os.path.exists(dataset_path):
        logger.warning("数据集不存在，无法执行 AST 匹配: %s", dataset_path)
        return {}
    data = load_dataset(dataset_path)
    project_index = _build_project_index(data)
    cluster_projects = load_stage2_clusters(cluster_path)
    if set(cluster_projects) != set(project_index):
        raise ValueError(
            "Stage 2 聚类项目与数据集项目不一致: "
            f"clusters={sorted(cluster_projects)}, dataset={sorted(project_index)}"
        )
    if any(
        "mock_provenance" in idiom
        for idioms in all_idioms.values()
        for idiom in idioms
    ):
        raise ValueError("正式聚类机会域评价不接受 mock 习语产物")

    project_results: List[Dict[str, Any]] = []
    project_items = project_index.items()
    for project_name, project_idx in progress(
        project_items,
        total=len(project_index),
        desc="评价项目",
        unit="项目",
    ):
        cluster_project = cluster_projects[project_name]
        opportunity_domain = build_cluster_opportunity_domain(
            project_name,
            data,
            project_idx,
            cluster_project["members"],
        )
        result = evaluate_project_kfold(
            project_name=project_name,
            data=data,
            project_idx=project_idx,
            project_idioms=all_idioms.get(project_name, []),
            opportunity_domain=opportunity_domain,
            fold_count=fold_count,
        )
        result["opportunity_cluster_count"] = cluster_project[
            "cluster_count"
        ]
        result["opportunity_member_count"] = cluster_project["member_count"]
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
                "avg_cross_function_support": round(
                    library_stats["avg_cross_function_support"], 4
                ),
                "AvgAST": round(library_stats["AvgAST"], 2),
                "total_cluster_instances": library_stats["total_cluster_instances"],
                "total_cross_function_support": (
                    library_stats["total_cross_function_support"]
                ),
                "ast_measured_type_count": library_stats["ast_measured_type_count"],
                "ast_type_mean_sum": library_stats["ast_type_mean_sum"],
            }
        )
        project_results.append(result)
        logger.info(
            "项目 %s: IC_macro=%.4f, IC_micro=%.4f, IC=%.4f, ISP=%.4f, "
            "F1=%.4f, types=%d, avg_cluster=%.2f, "
            "avg_functions=%.2f, AvgAST=%.2f",
            project_name,
            result["IC_macro"],
            result["IC_micro"],
            result["IC"],
            result["ISP"],
            result["F1"],
            result["idiom_type_count"],
            result["avg_cluster_size"],
            result["avg_cross_function_support"],
            result["AvgAST"],
        )

    if not project_results:
        payload = {"language": CPP_LANGUAGE, "projects": [], "summary": {}}
    else:
        count = len(project_results)
        matched_nodes = sum(r["covered_node_count"] for r in project_results)
        total_nodes = sum(
            r["opportunity_node_count"] for r in project_results
        )
        function_count = sum(
            r["opportunity_function_count"] for r in project_results
        )
        function_coverage_sum = sum(
            r["opportunity_function_coverage_sum"] for r in project_results
        )
        matched_idioms = sum(r["matched_idiom_count"] for r in project_results)
        evaluated_idioms = sum(r["idiom_count"] for r in project_results)
        fold_matched_idioms = sum(
            r["fold_matched_idiom_count"]
            for r in project_results
        )
        fold_evaluated_idioms = sum(
            r["fold_evaluated_idiom_count"]
            for r in project_results
        )
        generalization_matched_idioms = sum(
            r["generalization_matched_idiom_count"]
            for r in project_results
        )
        generalization_matched_nodes = sum(
            r["generalization_covered_node_count"]
            for r in project_results
        )
        generalization_function_coverage_sum = sum(
            r["generalization_function_coverage_sum"]
            for r in project_results
        )
        all_matched_nodes = sum(
            r["all_matched_node_count"]
            for r in project_results
        )
        all_total_nodes = sum(
            r["all_total_node_count"]
            for r in project_results
        )
        all_function_count = sum(
            r["all_function_count"]
            for r in project_results
        )
        all_function_coverage_sum = sum(
            r["all_function_coverage_sum"]
            for r in project_results
        )
        type_count = sum(r["idiom_type_count"] for r in project_results)
        cluster_instances = sum(
            r["total_cluster_instances"] for r in project_results
        )
        cross_function_support = sum(
            r["total_cross_function_support"] for r in project_results
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
            "IC_raw": round(
                sum(r["IC_raw"] for r in project_results) / count, 4
            ),
            "IC": round(sum(r["IC"] for r in project_results) / count, 4),
            "ISP": round(sum(r["ISP"] for r in project_results) / count, 4),
            "F1": round(sum(r["F1"] for r in project_results) / count, 4),
            "ISP_generalization": round(
                sum(r["ISP_generalization"] for r in project_results)
                / count,
                4,
            ),
            "ISP_fold": round(
                sum(r["ISP_fold"] for r in project_results)
                / count,
                4,
            ),
            "IC_all_macro": round(
                sum(r["IC_all_macro"] for r in project_results)
                / count,
                4,
            ),
            "IC_all_micro": round(
                sum(r["IC_all_micro"] for r in project_results)
                / count,
                4,
            ),
            "IC_all": round(
                sum(r["IC_all"] for r in project_results) / count,
                4,
            ),
            "F1_all_fold": round(
                sum(r["F1_all_fold"] for r in project_results)
                / count,
                4,
            ),
            "IC_generalization_macro": round(
                sum(
                    r["IC_generalization_macro"]
                    for r in project_results
                ) / count,
                4,
            ),
            "IC_generalization_micro": round(
                sum(
                    r["IC_generalization_micro"]
                    for r in project_results
                ) / count,
                4,
            ),
            "IC_generalization": round(
                sum(r["IC_generalization"] for r in project_results)
                / count,
                4,
            ),
            "F1_generalization": round(
                sum(r["F1_generalization"] for r in project_results)
                / count,
                4,
            ),
            "opportunity_function_count": round(
                sum(
                    r["opportunity_function_count"]
                    for r in project_results
                ) / count,
                2,
            ),
            "opportunity_node_count": round(
                sum(r["opportunity_node_count"] for r in project_results)
                / count,
                2,
            ),
            "covered_node_count": round(
                sum(r["covered_node_count"] for r in project_results)
                / count,
                2,
            ),
            "idiom_type_count": round(
                sum(r["idiom_type_count"] for r in project_results) / count, 2
            ),
            "avg_cluster_size": round(
                sum(r["avg_cluster_size"] for r in project_results) / count, 4
            ),
            "avg_cross_function_support": round(
                sum(
                    r["avg_cross_function_support"]
                    for r in project_results
                ) / count,
                4,
            ),
            "AvgAST": round(sum(r["AvgAST"] for r in project_results) / count, 2),
        }
        global_ic_macro = (
            function_coverage_sum / function_count if function_count else 0.0
        )
        global_ic_micro = matched_nodes / total_nodes if total_nodes else 0.0
        global_ic_raw = (global_ic_macro + global_ic_micro) / 2
        global_ic = global_ic_raw
        global_isp = matched_idioms / evaluated_idioms if evaluated_idioms else 0.0
        global_isp_generalization = (
            generalization_matched_idioms / evaluated_idioms
            if evaluated_idioms
            else 0.0
        )
        global_ic_generalization_macro = (
            generalization_function_coverage_sum / function_count
            if function_count
            else 0.0
        )
        global_ic_generalization_micro = (
            generalization_matched_nodes / total_nodes if total_nodes else 0.0
        )
        global_ic_generalization = (
            global_ic_generalization_macro + global_ic_generalization_micro
        ) / 2
        global_isp_fold = (
            fold_matched_idioms / fold_evaluated_idioms
            if fold_evaluated_idioms
            else 0.0
        )
        global_ic_all_macro = (
            all_function_coverage_sum / all_function_count
            if all_function_count
            else 0.0
        )
        global_ic_all_micro = (
            all_matched_nodes / all_total_nodes if all_total_nodes else 0.0
        )
        global_ic_all = (global_ic_all_macro + global_ic_all_micro) / 2
        global_metrics = {
            "IC_macro": round(global_ic_macro, 4),
            "IC_micro": round(global_ic_micro, 4),
            "IC_raw": round(global_ic_raw, 4),
            "IC": round(global_ic, 4),
            "ISP": round(global_isp, 4),
            "ISP_generalization": round(global_isp_generalization, 4),
            "ISP_fold": round(global_isp_fold, 4),
            "F1": round(compute_f1(global_ic, global_isp), 4),
            "IC_generalization_macro": round(
                global_ic_generalization_macro, 4
            ),
            "IC_generalization_micro": round(
                global_ic_generalization_micro, 4
            ),
            "IC_generalization": round(global_ic_generalization, 4),
            "F1_generalization": round(
                compute_f1(
                    global_ic_generalization,
                    global_isp_generalization,
                ),
                4,
            ),
            "IC_all_macro": round(global_ic_all_macro, 4),
            "IC_all_micro": round(global_ic_all_micro, 4),
            "IC_all": round(global_ic_all, 4),
            "F1_all_fold": round(
                compute_f1(global_ic_all, global_isp_fold), 4
            ),
            "idiom_type_count": type_count,
            "avg_cluster_size": round(
                cluster_instances / type_count, 4
            ) if type_count else 0.0,
            "avg_cross_function_support": round(
                cross_function_support / type_count, 4
            ) if type_count else 0.0,
            "AvgAST": round(
                ast_type_mean_sum / measured_ast_types, 2
            ) if measured_ast_types else 0.0,
            "matched_idiom_count": matched_idioms,
            "evaluated_idiom_count": evaluated_idioms,
            "generalization_matched_idiom_count": (
                generalization_matched_idioms
            ),
            "fold_matched_idiom_count": fold_matched_idioms,
            "fold_evaluated_idiom_count": fold_evaluated_idioms,
            "total_cluster_instances": cluster_instances,
            "covered_node_count": matched_nodes,
            "opportunity_node_count": total_nodes,
            "opportunity_function_count": function_count,
            "generalization_covered_node_count": (
                generalization_matched_nodes
            ),
            "all_matched_node_count": all_matched_nodes,
            "all_total_node_count": all_total_nodes,
            "all_function_count": all_function_count,
        }
        payload = {
            "language": CPP_LANGUAGE,
            "evaluation_mode": evaluation_mode,
            "cluster_path": cluster_path,
            "IC_opportunity_domain": (
                "stage2_non_noise_cluster_member_ast_union_by_exact_function"
            ),
            "ISP_support_domain": (
                "repository_relative_file_and_function_root_extent"
            ),
            "fold_partition_domain": "file",
            "artifact_stage": artifact_stage,
            "matcher": "reference_only_role_parameterized_lexical_structure",
            "primary_metric_definition": {
                "IC_raw": "arithmetic_mean_of_IC_macro_and_IC_micro",
                "IC": "same_as_IC_raw_without_numeric_transformation",
                "ISP": (
                    "library_idiom_with_support_in_at_least_two_"
                    "validated_function_domains"
                ),
                "F1": "harmonic_mean_of_IC_and_ISP",
            },
            "strict_sensitivity_metrics": [
                "IC_generalization",
                "ISP_generalization",
                "F1_generalization",
                "IC_all_macro",
                "IC_all_micro",
                "IC_all",
                "ISP_fold",
                "F1_all_fold",
            ],
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
    cluster_path: str,
    idiom_dir: Optional[str] = None,
    dataset_path: Optional[str] = None,
    output_path: Optional[str] = None,
    artifact_stage: str = "judgment",
    evaluation_mode: str = DEFAULT_EVALUATION_MODE,
    fold_count: int = 5,
) -> Dict[str, Any]:
    project_root = Path(__file__).resolve().parents[2]
    idiom_dir = idiom_dir or str(project_root / "results" / "main" / "cli11")
    dataset_path = dataset_path or str(
        project_root / "outputs" / "cli11" / "stage0" / "dataset.pkl"
    )
    output_path = output_path or str(
        project_root / "results" / "main" / "cli11" / "evaluation.json"
    )
    logger.info("代码习语评估，模式: %s", evaluation_mode)
    logger.info("习语目录: %s", idiom_dir)
    logger.info("数据集: %s", dataset_path)
    logger.info("冻结聚类机会域: %s", cluster_path)
    logger.info("输出: %s", output_path)
    return evaluate_cpp(
        idiom_dir=idiom_dir,
        dataset_path=dataset_path,
        output_path=output_path,
        cluster_path=cluster_path,
        artifact_stage=artifact_stage,
        evaluation_mode=evaluation_mode,
        fold_count=fold_count,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "C++ 代码习语评估：计算 IC_macro、IC_micro、IC、ISP、F1 "
            "及习语库规模结构"
        )
    )
    parser.add_argument(
        "--idiom-dir", "-i", default=None, help="默认 results/main/cli11"
    )
    parser.add_argument(
        "--dataset",
        "-d",
        default=None,
        help="默认 outputs/cli11/stage0/dataset.pkl",
    )
    parser.add_argument(
        "--clusters",
        required=True,
        help="Stage 3 实际使用的 Stage 2 非噪声聚类产物",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="默认 results/main/cli11/evaluation.json",
    )
    parser.add_argument(
        "--stage",
        choices=("judgment", "synthesis"),
        default="synthesis",
        help=(
            "评价习语判断或习语合成产物，默认 synthesis"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("within_project_kfold",),
        default=DEFAULT_EVALUATION_MODE,
        help="仓库内文件五折",
    )
    parser.add_argument(
        "--folds",
        type=int,
        default=5,
        help="仓库内轮转折数，默认 5",
    )
    args = parser.parse_args()
    run_evaluation(
        cluster_path=args.clusters,
        idiom_dir=args.idiom_dir,
        dataset_path=args.dataset,
        output_path=args.output,
        artifact_stage=args.stage,
        evaluation_mode=args.mode,
        fold_count=args.folds,
    )


if __name__ == "__main__":
    main()
