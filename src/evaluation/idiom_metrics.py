"""
代码习语评估指标

实现以下指标：
1. IC (Idiom Coverage): 函数中被习语匹配的 AST 节点比例
2. ISP (Idiom Set Precision): 训练习语在测试集中重现的比例
3. F1: IC 与 ISP 的调和平均数
4. 平均习语规模: 习语包含的 AST 节点数量
"""

import json
import os
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..common.logging import get_logger

logger = get_logger(__name__)

CPP_LANGUAGE = "cpp"


def _parse_extent(extent: str) -> Tuple[int, int, int, int]:
    """解析 extent 字符串为 (start_line, start_col, end_line, end_col)"""
    match = re.match(r"(\d+)-(\d+)-(\d+)-(\d+)", extent)
    if match:
        return tuple(map(int, match.groups()))
    raise ValueError(f"无效的 extent 格式: {extent}")


def _is_within_extent(extent_root: str, extent_cur: str) -> bool:
    """判断 extent_cur 是否在 extent_root 的范围内（即 extent_cur 是 extent_root 的后代）"""
    try:
        r_sl, r_sc, r_el, r_ec = _parse_extent(extent_root)
        c_sl, c_sc, c_el, c_ec = _parse_extent(extent_cur)
        return (
            (r_sl < c_sl or (r_sl == c_sl and r_sc <= c_sc))
            and (r_el > c_el or (r_el == c_el and r_ec >= c_ec))
        )
    except Exception:
        return False


def _get_subtree_size(node_info_list: List[Dict], root_extent: str) -> int:
    """
    计算以 root_extent 为根的子树中的 AST 节点数量

    node_info_list 按深度优先顺序排列，找到根节点后统计其子树节点数
    """
    root_idx = None
    root_depth = None
    for i, node_info in enumerate(node_info_list):
        if node_info.get("extent") == root_extent:
            root_idx = i
            root_depth = node_info.get("depth", 0)
            break
    if root_idx is None:
        return 0

    count = 1  # 根节点
    for i in range(root_idx + 1, len(node_info_list)):
        depth = node_info_list[i].get("depth", 0)
        if depth <= root_depth:
            break
        count += 1
    return count


def _normalize_code(code: str) -> str:
    """标准化代码字符串用于匹配（去除多余空白）"""
    if not code:
        return ""
    return " ".join(code.split())


def _code_match(idiom_code: str, func_code: str) -> bool:
    """判断习语代码是否出现在函数代码中（子串匹配，标准化后）"""
    idiom_norm = _normalize_code(idiom_code)
    func_norm = _normalize_code(func_code)
    return idiom_norm and idiom_norm in func_norm


def load_idioms(idiom_path: str) -> List[Dict[str, Any]]:
    """加载习语 pkl 文件"""
    with open(idiom_path, "rb") as f:
        return pickle.load(f)


def load_dataset(dataset_path: str) -> pd.DataFrame:
    """加载 AST 数据集"""
    return pd.read_pickle(dataset_path)


def _build_project_index(data: pd.DataFrame) -> Dict[str, int]:
    """构建项目名到行索引的映射"""
    index = {}
    for i in range(len(data)):
        row = data.iloc[i]
        proj = row.get("project", row.get("pros_name"))
        if proj is not None:
            index[str(proj)] = i
    return index


def _match_file_path(idiom_file: str, dataset_files: List[str]) -> Optional[int]:
    """
    匹配习语的 file_name 与数据集中的文件路径
    支持 basename 或路径后缀匹配
    """
    idiom_basename = os.path.basename(idiom_file)
    idiom_norm = idiom_file.replace("\\", "/")
    for j, df_file in enumerate(dataset_files):
        df_norm = str(df_file).replace("\\", "/")
        if idiom_file == df_file or idiom_norm == df_norm:
            return j
        if os.path.basename(df_norm) == idiom_basename:
            return j
        if idiom_norm.endswith(idiom_basename) or df_norm.endswith(idiom_basename):
            return j
    return None


def compute_idiom_coverage(
    idioms: List[Dict],
    data: pd.DataFrame,
    project_name: str,
    project_idx: int,
) -> float:
    """
    计算 Idiom Coverage (IC): 函数中被习语匹配的 AST 节点比例

    对当前项目的每个函数，统计被习语覆盖的节点数 / 总节点数，再对所有函数取平均
    """
    if not idioms or data is None or project_idx < 0:
        return 0.0

    row = data.iloc[project_idx]
    files = row["cppFile"] if "cppFile" in row else row.get("cppFile", [])
    func_asts = row["func_ast"] if "func_ast" in row else row.get("func_ast", [])

    if not files or not func_asts:
        return 0.0

    # 对每个函数计算覆盖比例
    coverage_list = []
    for file_idx, func_list in enumerate(func_asts):
        for func_ast in func_list:
            total_nodes = len(func_ast)
            if total_nodes == 0:
                continue
            # 收集属于当前函数的习语根 extent
            idiom_roots = []
            for idiom in idioms:
                info = idiom.get("info")
                if not info or not isinstance(info, (list, tuple)) or len(info) < 3:
                    continue
                pro_name, file_name, extent_root = info[0], info[1], info[2]
                if str(pro_name) != str(project_name):
                    continue
                if _match_file_path(file_name, files) != file_idx:
                    continue
                # 检查 extent_root 是否属于当前函数的某个节点
                for node_info in func_ast:
                    if node_info.get("extent") == extent_root:
                        idiom_roots.append(extent_root)
                        break

            # 统计被覆盖的节点数（节点在任一习语子树内即算覆盖）
            covered_count = 0
            for node_info in func_ast:
                ext = node_info.get("extent", "")
                for root_ext in idiom_roots:
                    if ext == root_ext or _is_within_extent(root_ext, ext):
                        covered_count += 1
                        break
            coverage_list.append(covered_count / total_nodes)

    if not coverage_list:
        return 0.0
    return sum(coverage_list) / len(coverage_list)


def compute_idiom_set_precision(
    training_idioms: List[Dict],
    test_func_srcs: List[str],
) -> float:
    """
    计算 Idiom Set Precision (ISP): 训练习语在测试集中重现的比例

    ISP = |{习语 in 训练集 : 习语在测试集中出现}| / |训练集习语数|
    """
    if not training_idioms:
        return 0.0

    if not test_func_srcs:
        return 0.0

    reappear_count = 0
    for idiom in training_idioms:
        center = idiom.get("center_point", "")
        for func_src in test_func_srcs:
            if func_src and _code_match(center, func_src):
                reappear_count += 1
                break

    return reappear_count / len(training_idioms)


def compute_f1(ic: float, isp: float) -> float:
    """计算 IC 与 ISP 的调和平均数"""
    if ic <= 0 and isp <= 0:
        return 0.0
    if ic <= 0 or isp <= 0:
        return 0.0
    return 2 * ic * isp / (ic + isp)


def compute_avg_idiom_size(
    idioms: List[Dict],
    data: Optional[pd.DataFrame],
    project_name: str,
    project_idx: int = -1,
) -> float:
    """
    计算平均习语规模（AST 节点数量）

    若数据集可用，从 AST 中计算子树大小；否则使用 avg_ast_num 的近似 (1 + avg_ast_num)
    """
    if not idioms:
        return 0.0

    sizes = []
    for idiom in idioms:
        info = idiom.get("info")
        if data is not None and project_idx >= 0 and info and isinstance(info, (list, tuple)) and len(info) >= 3:
            pro_name, file_name, extent_root = info[0], info[1], info[2]
            if str(pro_name) != str(project_name):
                continue
            row = data.iloc[project_idx]
            files = row.get("cppFile", row.get("cppFile", []))
            func_asts = row.get("func_ast", [])
            file_idx = _match_file_path(file_name, files)
            if file_idx is not None and file_idx < len(func_asts):
                for func_ast in func_asts[file_idx]:
                    size = _get_subtree_size(func_ast, extent_root)
                    if size > 0:
                        sizes.append(size)
                        break
        else:
            # 使用 avg_ast_num 近似：根节点 + 直接子节点数
            avg_ast = idiom.get("avg_ast_num", 0)
            sizes.append(1 + avg_ast)

    if not sizes:
        # 全部回退到 avg_ast_num
        for idiom in idioms:
            sizes.append(1 + idiom.get("avg_ast_num", 0))
    return sum(sizes) / len(sizes) if sizes else 0.0


def _get_all_func_srcs(data: pd.DataFrame, project_idx: int) -> List[str]:
    """获取某项目所有函数的源代码"""
    row = data.iloc[project_idx]
    func_srcs = row.get("func_src", [])
    result = []
    for file_funcs in func_srcs:
        result.extend(file_funcs if isinstance(file_funcs, list) else [])
    return result


def evaluate_project(
    project_name: str,
    idiom_path: str,
    data: pd.DataFrame,
    project_idx: int,
    all_idioms: Dict[str, List[Dict]],
) -> Dict[str, Any]:
    """
    对单个项目计算评估指标

    Args:
        project_name: 项目名称
        idiom_path: 该项目习语文件路径
        data: 数据集
        project_idx: 项目在数据集中的索引
        all_idioms: 所有项目的习语 {repo: [idioms]}

    Returns:
        包含 IC, ISP, F1, avg_idiom_size 的字典
    """
    idioms = load_idioms(idiom_path) if os.path.exists(idiom_path) else []
    if not idioms:
        return {
            "project": project_name,
            "IC": 0.0,
            "ISP": 0.0,
            "F1": 0.0,
            "avg_idiom_size": 0.0,
            "idiom_count": 0,
        }

    # 计算 IC
    ic = compute_idiom_coverage(idioms, data, project_name, project_idx)

    # ISP: 留一法，当前项目为测试集，其余为训练集
    training_idioms = []
    for repo, repo_idioms in all_idioms.items():
        if repo != project_name:
            training_idioms.extend(repo_idioms)
    test_func_srcs = _get_all_func_srcs(data, project_idx)
    isp = compute_idiom_set_precision(training_idioms, test_func_srcs)

    # 计算 F1
    f1 = compute_f1(ic, isp)

    # 平均习语规模
    avg_size = compute_avg_idiom_size(idioms, data, project_name, project_idx)

    return {
        "project": project_name,
        "IC": round(ic, 4),
        "ISP": round(isp, 4),
        "F1": round(f1, 4),
        "avg_idiom_size": round(avg_size, 2),
        "idiom_count": len(idioms),
    }


def evaluate_cpp(
    idiom_dir: str,
    dataset_path: str,
    output_path: str,
) -> Dict[str, Any]:
    """
    对 C++ 项目的所有习语结果进行评估并汇总

    对每个项目计算 IC, ISP, F1, avg_idiom_size，最后汇总到 results/cpp/eval.json

    Args:
        idiom_dir: 习语目录，如 results/cpp
        dataset_path: 数据集路径，如 outputs/cpp/dataset.pkl
        output_path: 汇总结果输出路径，如 results/cpp/eval.json
    """
    idiom_dir = Path(idiom_dir)
    os.makedirs(idiom_dir, exist_ok=True)

    # 查找所有 idiom 文件
    idiom_files = list(idiom_dir.glob("*_idiom.pkl"))
    if not idiom_files:
        logger.warning(f"未找到习语文件: {idiom_dir}/*_idiom.pkl")
        return {}

    # 加载所有习语
    all_idioms: Dict[str, List[Dict]] = {}
    for f in idiom_files:
        repo = f.stem.replace("_idiom", "")
        all_idioms[repo] = load_idioms(str(f))

    # 加载数据集
    data = None
    proj_index = {}
    if os.path.exists(dataset_path):
        data = load_dataset(dataset_path)
        proj_index = _build_project_index(data)
    else:
        logger.warning(f"数据集不存在: {dataset_path}，IC 和 avg_idiom_size 将使用近似值")

    # 按项目评估
    project_results = []
    for repo, idioms in all_idioms.items():
        idiom_path = idiom_dir / f"{repo}_idiom.pkl"
        if not idiom_path.exists():
            continue
        project_idx = proj_index.get(repo, -1)
        if data is None or project_idx < 0:
            project_idx = -1
        result = evaluate_project(
            project_name=repo,
            idiom_path=str(idiom_path),
            data=data if data is not None else pd.DataFrame(),
            project_idx=project_idx,
            all_idioms=all_idioms,
        )
        project_results.append(result)
        logger.info(f"  项目 {repo}: IC={result['IC']:.4f}, ISP={result['ISP']:.4f}, "
                    f"F1={result['F1']:.4f}, avg_size={result['avg_idiom_size']:.2f}")

    # 汇总
    if not project_results:
        summary = {"language": CPP_LANGUAGE, "projects": [], "summary": {}}
    else:
        n = len(project_results)
        summary = {
            "language": CPP_LANGUAGE,
            "projects": project_results,
            "summary": {
                "IC": round(sum(r["IC"] for r in project_results) / n, 4),
                "ISP": round(sum(r["ISP"] for r in project_results) / n, 4),
                "F1": round(sum(r["F1"] for r in project_results) / n, 4),
                "avg_idiom_size": round(sum(r["avg_idiom_size"] for r in project_results) / n, 2),
                "total_projects": n,
                "total_idioms": sum(r["idiom_count"] for r in project_results),
            },
        }

    # 保存
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info(f"评估结果已保存至 {output_path}")
    return summary


def run_evaluation(
    idiom_dir: Optional[str] = None,
    dataset_path: Optional[str] = None,
    output_path: Optional[str] = None,
):
    """
    运行评估的入口函数

    Args:
        idiom_dir: 习语目录，默认 results/cpp
        dataset_path: 数据集路径，默认 outputs/cpp/dataset.pkl
        output_path: 输出路径，默认 results/cpp/eval.json
    """
    project_root = Path(__file__).parent.parent.parent
    idiom_dir = idiom_dir or str(project_root / "result" / CPP_LANGUAGE)
    dataset_path = dataset_path or str(project_root / "output" / CPP_LANGUAGE / "dataset.pkl")
    output_path = output_path or str(project_root / "result" / CPP_LANGUAGE / "eval.json")

    logger.info("=" * 60)
    logger.info("代码习语评估")
    logger.info("=" * 60)
    logger.info("语言: C++")
    logger.info(f"习语目录: {idiom_dir}")
    logger.info(f"数据集: {dataset_path}")
    logger.info(f"输出: {output_path}")

    evaluate_cpp(
        idiom_dir=idiom_dir,
        dataset_path=dataset_path,
        output_path=output_path,
    )


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="代码习语评估：计算 IC、ISP、F1、平均习语规模")
    parser.add_argument(
        "--idiom-dir", "-i",
        default=None,
        help="习语目录，默认 results/cpp",
    )
    parser.add_argument(
        "--dataset", "-d",
        default=None,
        help="数据集路径，默认 outputs/cpp/dataset.pkl",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="输出路径，默认 results/cpp/eval.json",
    )

    args = parser.parse_args()

    run_evaluation(
        idiom_dir=args.idiom_dir,
        dataset_path=args.dataset,
        output_path=args.output,
    )


# 模块运行命令（从项目根目录运行）：
# 运行示例：python -m src.evaluation.idiom_metrics
# 运行示例：python -m src.evaluation.idiom_metrics -i results/cpp -d outputs/cpp/dataset.pkl -o results/cpp/eval.json

if __name__ == "__main__":
    main()
