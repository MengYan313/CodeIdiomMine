"""Haggis-CPP：面向当前 Tree-sitter C++ AST 的 DP-pTSG 复现。

实现保留 Haggis 的核心统计模型：AST 边上的隐式片段边界、PCFG 基分布、
Dirichlet-process 后验预测概率、collapsed Gibbs 采样和 burn-in 后规则累计。
原作者 Java 入口使用 type-blocked sampler 作为混合加速；本实现使用同仓库也
提供的逐点 collapsed Gibbs 更新，避免把 Java/JDT 运行时或简单频繁子树冒充为
Haggis。解析器、符号编码和采样器差异会写入每个产物的 provenance。
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Counter as CounterType, Dict, Iterable, List, Sequence, Tuple

import pandas as pd

from ..common.logging import get_logger
from ..common.node_kinds import BLOCK_KINDS, FUNCTION_KINDS, STATEMENT_KINDS
from .baseline_common import make_idiom_record, write_project_idioms, write_run_manifest


logger = get_logger(__name__)

HAGGIS_REFERENCE_COMMIT = "8b241a195fe860713c8dbbee387710533b97258c"
CANDIDATE_KINDS = FUNCTION_KINDS | BLOCK_KINDS | STATEMENT_KINDS
FragmentKey = Tuple[str, Tuple[Any, ...]]


@dataclass(eq=False)
class _Node:
    symbol: str
    node_info: Dict[str, Any]
    source_info: Sequence[Any]
    parent: "_Node | None" = None
    children: List["_Node"] = field(default_factory=list)
    root_boundary: bool = False

    @property
    def is_leaf(self) -> bool:
        return not self.children


def _normalize_leaf(kind: str, code: str) -> str:
    lower = kind.lower()
    if "identifier" in lower or lower in {
        "number_literal",
        "string_literal",
        "char_literal",
        "raw_string_literal",
    }:
        return kind
    compact = " ".join(str(code or "").split())
    if compact and len(compact) <= 32 and not any(char.isspace() for char in compact):
        return f"{kind}={compact}"
    return kind


def _node_symbol(node_info: Dict[str, Any], has_children: bool) -> str:
    kind = str(node_info.get("kind") or "UNKNOWN")
    if has_children:
        return kind
    return _normalize_leaf(kind, str(node_info.get("code_snippet") or ""))


def _tree_from_flat_ast(
    project_name: str,
    file_name: str,
    func_ast: Sequence[Dict[str, Any]],
    rng: random.Random,
    percent_roots_init: float,
) -> _Node | None:
    if not func_ast:
        return None
    nodes: List[_Node] = []
    stack: List[Tuple[int, _Node]] = []
    function_extent = str(func_ast[0].get("extent") or "")
    for raw in func_ast:
        depth = int(raw.get("depth", 0) or 0)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1] if stack else None
        source_info = [project_name, file_name, function_extent, raw]
        node = _Node(
            symbol="",
            node_info=raw,
            source_info=source_info,
            parent=parent,
        )
        if parent is not None:
            parent.children.append(node)
        nodes.append(node)
        stack.append((depth, node))

    for node in reversed(nodes):
        node.symbol = _node_symbol(node.node_info, bool(node.children))
    root = nodes[0]
    root.root_boundary = True
    for node in nodes[1:]:
        node.root_boundary = bool(node.children) and rng.random() < percent_roots_init
    return root


def _iter_nodes(root: _Node) -> Iterable[_Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _fragment_key(root: _Node) -> FragmentKey:
    children: List[Any] = []
    for child in root.children:
        if child.root_boundary:
            children.append(("$META", child.symbol))
        else:
            children.append(_fragment_key(child))
    return root.symbol, tuple(children)


def _fragment_node_count(fragment: FragmentKey) -> int:
    count = 1
    for child in fragment[1]:
        if child and child[0] == "$META":
            count += 1
        else:
            count += _fragment_node_count(child)
    return count


def _render_fragment(fragment: FragmentKey) -> str:
    rendered_children = []
    for child in fragment[1]:
        if child and child[0] == "$META":
            rendered_children.append(f"<META:{child[1]}>")
        else:
            rendered_children.append(_render_fragment(child))
    if not rendered_children:
        return fragment[0]
    return f"({fragment[0]} {' '.join(rendered_children)})"


def _cfg_rule(node: _Node) -> Tuple[str, Tuple[str, ...]]:
    return node.symbol, tuple(child.symbol for child in node.children)


class _PointwiseCollapsedGibbsSampler:
    def __init__(
        self,
        trees: Sequence[_Node],
        *,
        alpha: float,
        rng: random.Random,
    ) -> None:
        if alpha <= 0:
            raise ValueError("alpha 必须大于 0")
        self.trees = list(trees)
        self.alpha = alpha
        self.rng = rng
        self.cfg_counts: CounterType[Tuple[str, Tuple[str, ...]]] = Counter()
        self.cfg_root_totals: CounterType[str] = Counter()
        for tree in self.trees:
            for node in _iter_nodes(tree):
                rule = _cfg_rule(node)
                self.cfg_counts[rule] += 1
                self.cfg_root_totals[node.symbol] += 1

        self.grammar: CounterType[FragmentKey] = Counter()
        self.grammar_root_totals: CounterType[str] = Counter()
        for tree in self.trees:
            for node in _iter_nodes(tree):
                if node.root_boundary:
                    self._add(_fragment_key(node))

    def _add(self, fragment: FragmentKey) -> None:
        self.grammar[fragment] += 1
        self.grammar_root_totals[fragment[0]] += 1

    def _remove(self, fragment: FragmentKey) -> None:
        if self.grammar[fragment] <= 0:
            raise RuntimeError("Haggis grammar 计数不一致")
        self.grammar[fragment] -= 1
        self.grammar_root_totals[fragment[0]] -= 1
        if self.grammar[fragment] == 0:
            del self.grammar[fragment]

    def _log_prior(self, fragment: FragmentKey) -> float:
        root_symbol, children = fragment
        child_symbols = tuple(
            child[1] if child and child[0] == "$META" else child[0]
            for child in children
        )
        numerator = self.cfg_counts[(root_symbol, child_symbols)]
        denominator = self.cfg_root_totals[root_symbol]
        if numerator <= 0 or denominator <= 0:
            log_probability = math.log(1e-12)
        else:
            log_probability = math.log(numerator / denominator)
        for child in children:
            if child and child[0] != "$META":
                log_probability += self._log_prior(child)
        return log_probability

    def _log_predictive(
        self,
        fragment: FragmentKey,
        extra_fragments: CounterType[FragmentKey] | None = None,
        extra_roots: CounterType[str] | None = None,
    ) -> float:
        extra_fragments = extra_fragments or Counter()
        extra_roots = extra_roots or Counter()
        log_prior = self._log_prior(fragment)
        prior = math.exp(max(log_prior, -745.0))
        count = self.grammar.get(fragment, 0) + extra_fragments.get(fragment, 0)
        root_count = (
            self.grammar_root_totals.get(fragment[0], 0)
            + extra_roots.get(fragment[0], 0)
        )
        numerator = count + self.alpha * prior
        denominator = root_count + self.alpha
        return math.log(max(numerator, 1e-300)) - math.log(max(denominator, 1e-300))

    @staticmethod
    def _nearest_root(node: _Node) -> _Node:
        current = node.parent
        if current is None:
            raise RuntimeError("不能对树根采样")
        while not current.root_boundary:
            if current.parent is None:
                raise RuntimeError("AST 根必须是 TSG root")
            current = current.parent
        return current

    def _sample_at(self, node: _Node) -> None:
        upper_root = self._nearest_root(node)
        was_split = node.root_boundary

        node.root_boundary = False
        joined = _fragment_key(upper_root)
        node.root_boundary = True
        upper = _fragment_key(upper_root)
        lower = _fragment_key(node)
        node.root_boundary = was_split

        if was_split:
            self._remove(upper)
            self._remove(lower)
        else:
            self._remove(joined)

        log_join = self._log_predictive(joined)
        split_extra_fragments: CounterType[FragmentKey] = Counter({upper: 1})
        split_extra_roots: CounterType[str] = Counter({upper[0]: 1})
        log_split = self._log_predictive(upper) + self._log_predictive(
            lower,
            split_extra_fragments,
            split_extra_roots,
        )
        maximum = max(log_join, log_split)
        join_weight = math.exp(log_join - maximum)
        split_weight = math.exp(log_split - maximum)
        join_probability = join_weight / (join_weight + split_weight)

        node.root_boundary = not (self.rng.random() < join_probability)
        if node.root_boundary:
            self._add(_fragment_key(upper_root))
            self._add(_fragment_key(node))
        else:
            self._add(_fragment_key(upper_root))

    def sample_once(self) -> None:
        sites = [
            node
            for tree in self.trees
            for node in _iter_nodes(tree)
            if node.parent is not None and not node.is_leaf
        ]
        self.rng.shuffle(sites)
        for node in sites:
            self._sample_at(node)


def _eligible_occurrences(trees: Sequence[_Node]) -> Dict[FragmentKey, List[Sequence[Any]]]:
    occurrences: Dict[FragmentKey, List[Sequence[Any]]] = defaultdict(list)
    for tree in trees:
        for node in _iter_nodes(tree):
            if not node.root_boundary:
                continue
            kind = str(node.node_info.get("kind") or "")
            ast_num = int(node.node_info.get("ast_num", 0) or 0)
            code = str(node.node_info.get("code_snippet") or "").strip()
            if kind not in CANDIDATE_KINDS or ast_num < 5 or not code:
                continue
            occurrences[_fragment_key(node)].append(node.source_info)
    return occurrences


def _project_trees(
    row: pd.Series,
    *,
    seed: int,
    percent_roots_init: float,
    max_functions: int | None,
    max_nodes_per_function: int | None,
) -> List[_Node]:
    rng = random.Random(seed)
    project_name = str(row["project"])
    files = row.get("cppFile", [])
    func_asts = row.get("func_ast", [])
    trees: List[_Node] = []
    for file_name, file_functions in zip(files, func_asts):
        for func_ast in file_functions:
            if max_functions is not None and len(trees) >= max_functions:
                return trees
            if max_nodes_per_function is not None and len(func_ast) > max_nodes_per_function:
                continue
            tree = _tree_from_flat_ast(
                project_name,
                str(file_name),
                func_ast,
                rng,
                percent_roots_init,
            )
            if tree is not None:
                trees.append(tree)
    return trees


def mine_haggis_cpp(
    dataset_path: str | Path,
    output_dir: str | Path,
    *,
    iterations: int = 50,
    burn_in_fraction: float = 0.75,
    alpha: float = 1.0,
    seed: int = 0,
    percent_roots_init: float = 0.9,
    min_posterior_support: float = 0.5,
    min_occurrences: int = 3,
    min_files: int = 2,
    min_fragment_nodes: int = 3,
    max_functions_per_project: int | None = None,
    max_nodes_per_function: int | None = None,
) -> Dict[str, int]:
    if iterations < 1:
        raise ValueError("iterations 必须大于等于 1")
    if not 0 <= burn_in_fraction < 1:
        raise ValueError("burn_in_fraction 必须位于 [0, 1)")
    if not 0 <= percent_roots_init <= 1:
        raise ValueError("percent_roots_init 必须位于 [0, 1]")
    if not 0 <= min_posterior_support <= 1:
        raise ValueError("min_posterior_support 必须位于 [0, 1]")
    if min_occurrences < 1 or min_files < 1 or min_fragment_nodes < 1:
        raise ValueError("出现次数、文件数和片段节点数阈值必须为正数")
    if max_functions_per_project is not None and max_functions_per_project < 1:
        raise ValueError("max_functions_per_project 必须为正数或 None")
    if max_nodes_per_function is not None and max_nodes_per_function < 1:
        raise ValueError("max_nodes_per_function 必须为正数或 None")

    dataset_path = Path(dataset_path)
    data = pd.read_pickle(dataset_path)
    burn_in_iterations = math.floor(iterations * burn_in_fraction)
    counts: Dict[str, int] = {}
    project_manifests: List[Dict[str, Any]] = []

    for project_idx in range(len(data)):
        row = data.iloc[project_idx]
        project_name = str(row["project"])
        project_seed = seed + int(
            hashlib.sha256(project_name.encode("utf-8")).hexdigest()[:8], 16
        )
        rng = random.Random(project_seed)
        trees = _project_trees(
            row,
            seed=project_seed,
            percent_roots_init=percent_roots_init,
            max_functions=max_functions_per_project,
            max_nodes_per_function=max_nodes_per_function,
        )
        sampler = _PointwiseCollapsedGibbsSampler(trees, alpha=alpha, rng=rng)
        presence: CounterType[FragmentKey] = Counter()
        occurrence_sum: CounterType[FragmentKey] = Counter()
        source_infos: Dict[FragmentKey, List[Sequence[Any]]] = defaultdict(list)
        collected_samples = 0

        for iteration in range(iterations):
            sampler.sample_once()
            if iteration < burn_in_iterations:
                continue
            collected_samples += 1
            occurrences = _eligible_occurrences(trees)
            for fragment, infos in occurrences.items():
                presence[fragment] += 1
                occurrence_sum[fragment] += len(infos)
                source_infos[fragment].extend(infos)

        candidates: List[Tuple[float, int, int, str, FragmentKey, List[Sequence[Any]]]] = []
        for fragment, sample_count in presence.items():
            posterior_support = sample_count / collected_samples if collected_samples else 0.0
            infos = source_infos[fragment]
            unique_sites = {
                (str(info[1]), str(info[3].get("extent") or info[2]))
                for info in infos
            }
            files = {site[0] for site in unique_sites}
            node_count = _fragment_node_count(fragment)
            if posterior_support < min_posterior_support:
                continue
            if len(unique_sites) < min_occurrences or len(files) < min_files:
                continue
            if node_count < min_fragment_nodes:
                continue
            candidates.append(
                (
                    posterior_support,
                    len(unique_sites),
                    node_count,
                    _render_fragment(fragment),
                    fragment,
                    infos,
                )
            )

        candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))

        idioms: List[Dict[str, Any]] = []
        for posterior_support, occurrence_count, node_count, template, fragment, infos in candidates:
            representative = infos[0]
            center_point = str(representative[3].get("code_snippet") or "").strip()
            idioms.append(
                make_idiom_record(
                    center_point=center_point,
                    source_infos=infos,
                    template=template,
                    provenance={
                        "method": "haggis_cpp",
                        "algorithm": "dp_ptsg_pointwise_collapsed_gibbs",
                        "reference_commit": HAGGIS_REFERENCE_COMMIT,
                        "fragment_template": template,
                        "posterior_sample_support": posterior_support,
                        "mean_sample_occurrences": (
                            occurrence_sum[fragment] / collected_samples
                            if collected_samples
                            else 0.0
                        ),
                        "unique_occurrences": occurrence_count,
                        "fragment_node_count": node_count,
                        "parameters": {
                            "iterations": iterations,
                            "burn_in_fraction": burn_in_fraction,
                            "alpha": alpha,
                            "seed": seed,
                            "percent_roots_init": percent_roots_init,
                        },
                        "adaptation_differences": [
                            "Tree-sitter C++ AST 替代原 Java/JDT AST",
                            "逐点 collapsed Gibbs 替代原命令的 type-blocked 混合加速",
                            "按有序子节点编码，未复用 JDT property binarization",
                            "标识符和字面量按 Tree-sitter 节点类别抽象",
                            "输出投影仅保留函数/块/语句根且 ast_num>=5 的当前评价候选",
                        ],
                    },
                )
            )

        output_path = write_project_idioms(output_dir, project_name, idioms)
        counts[project_name] = len(idioms)
        project_manifests.append(
            {
                "project": project_name,
                "sampled_function_count": len(trees),
                "sampled_node_count": sum(1 for tree in trees for _ in _iter_nodes(tree)),
                "collected_sample_count": collected_samples,
                "output_idiom_count": len(idioms),
            }
        )
        logger.info(
            "Haggis-CPP %s: functions=%d, samples=%d, idioms=%d -> %s",
            project_name,
            len(trees),
            collected_samples,
            len(idioms),
            output_path,
        )

    write_run_manifest(
        output_dir,
        {
            "method": "haggis_cpp",
            "is_mock": False,
            "algorithm": "dp_ptsg_pointwise_collapsed_gibbs",
            "reference": {
                "paper": "Mining Idioms from Source Code (FSE 2014)",
                "repository": "https://github.com/mast-group/codemining-treelm",
                "commit": HAGGIS_REFERENCE_COMMIT,
            },
            "dataset": str(dataset_path),
            "parameters": {
                "iterations": iterations,
                "burn_in_fraction": burn_in_fraction,
                "alpha": alpha,
                "seed": seed,
                "percent_roots_init": percent_roots_init,
                "min_posterior_support": min_posterior_support,
                "min_occurrences": min_occurrences,
                "min_files": min_files,
                "min_fragment_nodes": min_fragment_nodes,
                "max_functions_per_project": max_functions_per_project,
                "max_nodes_per_function": max_nodes_per_function,
            },
            "output_selection": {
                "policy": "all_fragments_passing_haggis_and_cpp_adapter_thresholds",
                "final_idiom_count_cap": None,
            },
            "cpp_candidate_projection": {
                "root_kind_groups": ["function", "block", "statement"],
                "minimum_ast_num": 5,
                "requires_nonempty_source": True,
            },
            "projects": project_manifests,
        },
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Haggis-CPP DP-pTSG baseline")
    parser.add_argument("--dataset", default="outputs/cpp/dataset.pkl")
    parser.add_argument(
        "--output-dir",
        default="results/baselines/haggis-cpp/cpp",
    )
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--burn-in-fraction", type=float, default=0.75)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--percent-roots-init", type=float, default=0.9)
    parser.add_argument("--min-posterior-support", type=float, default=0.5)
    parser.add_argument("--min-occurrences", type=int, default=3)
    parser.add_argument("--min-files", type=int, default=2)
    parser.add_argument("--min-fragment-nodes", type=int, default=3)
    parser.add_argument(
        "--max-functions-per-project",
        type=int,
        default=0,
        help="用于有界 smoke；0 表示全部函数",
    )
    parser.add_argument(
        "--max-nodes-per-function",
        type=int,
        default=0,
        help="用于跳过极端大函数；0 表示不限制",
    )
    args = parser.parse_args()
    mine_haggis_cpp(
        args.dataset,
        args.output_dir,
        iterations=args.iterations,
        burn_in_fraction=args.burn_in_fraction,
        alpha=args.alpha,
        seed=args.seed,
        percent_roots_init=args.percent_roots_init,
        min_posterior_support=args.min_posterior_support,
        min_occurrences=args.min_occurrences,
        min_files=args.min_files,
        min_fragment_nodes=args.min_fragment_nodes,
        max_functions_per_project=(
            None if args.max_functions_per_project == 0 else args.max_functions_per_project
        ),
        max_nodes_per_function=(
            None if args.max_nodes_per_function == 0 else args.max_nodes_per_function
        ),
    )


if __name__ == "__main__":
    main()
