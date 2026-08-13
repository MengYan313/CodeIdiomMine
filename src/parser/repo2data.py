"""
主入口文件
将仓库中的源代码解析为 AST，提取函数节点和代码片段
"""

import os
import argparse
import json
from pathlib import Path
import pandas as pd
from typing import Any, Dict, List, Optional

from .ast_parser import ASTParser
from .file_scanner import FileScanner
from .fragment_builder import build_fragment_file
from ..common.logging import get_logger
from ..common.progress import progress

# 创建日志记录器
logger = get_logger(__name__)


def parse_repository(
    input_path: str,
    output_path: str,
    audit_output_path: Optional[str] = None,
    fragment_output_path: Optional[str] = None,
    embedding_model: str = "unixcoder",
    max_input_tokens: Optional[int] = None,
    local_files_only: bool = False,
    projects: Optional[List[str]] = None,
):
    """
    解析仓库中的所有源代码文件
    
    Args:
        input_path: 输入路径，例如 CodeIdiomMine/repos
        output_path: 输出路径，例如 outputs/cli11/stage0/dataset.pkl
        fragment_output_path: 可选的 Parser model-ready 片段输出路径
        projects: 可选的精确项目目录名列表；省略时解析全部项目
    """
    logger.info("=" * 60)
    logger.info("代码仓库解析")
    logger.info("=" * 60)
    logger.info(f"输入路径: {input_path}")
    logger.info(f"输出路径: {output_path}")
    logger.info("编程语言: C++")
    
    # 初始化文件扫描器
    scanner = FileScanner()
    
    # 获取所有项目
    selected_projects = scanner.get_projects(input_path, projects)
    logger.info(
        f"找到 {len(selected_projects)} 个项目: {selected_projects}"
    )
    
    # 获取所有源代码文件
    pro_file_list = scanner.get_all_source_files(input_path)
    total_files = sum(len(files) for files in pro_file_list)
    logger.info(f"总共找到 {total_files} 个源文件")
    
    # 初始化 AST 解析器
    logger.info("初始化 C++ AST 解析器...")
    parser = ASTParser()
    
    # 存储所有项目的函数 AST 和源代码
    pro_func_ast = []  # 3D: 项目-文件-函数
    pro_func_ast_src = []  # 3D: 项目-文件-函数
    file_diagnostics: List[Dict[str, Any]] = []
    
    # 遍历每个项目
    for i, project_name in enumerate(selected_projects):
        logger.info(
            f"\n处理项目 [{i+1}/{len(selected_projects)}]: {project_name}"
        )
        project_path = os.path.join(input_path, project_name)
        funcs_in_pro = []  # 存储当前项目的所有函数 AST（2D: 文件-函数）
        funcs_in_pro_src = []  # 存储当前项目的所有函数源代码（2D: 文件-函数）
        
        # 遍历项目中的每个文件
        project_files = progress(
            pro_file_list[i],
            desc=f"解析 {project_name}",
            unit="文件",
            leave=False,
        )
        for j, file_path in enumerate(project_files):
            logger.info(f"  处理文件 [{j+1}/{len(pro_file_list[i])}]: {os.path.basename(file_path)}")
            
            try:
                # 解析文件为 AST
                tree = parser.parse_file(file_path, source_root=project_path)
                if tree is None:
                    logger.warning(f"    跳过文件（解析失败）: {file_path}")
                    diagnostics = dict(parser.last_file_diagnostics)
                    diagnostics["project"] = project_name
                    diagnostics["input_path"] = file_path
                    file_diagnostics.append(diagnostics)
                    funcs_in_pro.append([])
                    funcs_in_pro_src.append([])
                    continue
                
                # 提取函数节点
                func_nodes = parser.get_function_nodes(tree, file_path)
                diagnostics = dict(parser.last_file_diagnostics)
                diagnostics["project"] = project_name
                diagnostics["input_path"] = file_path
                
                if not func_nodes:
                    logger.debug(f"    未找到函数节点: {file_path}")
                    diagnostics["selected_function_count"] = 0
                    diagnostics["semantic_slice_count"] = 0
                    file_diagnostics.append(diagnostics)
                    funcs_in_pro.append([])
                    funcs_in_pro_src.append([])
                    continue
                
                logger.debug(f"    找到 {len(func_nodes)} 个函数节点")
                
                # 遍历每个函数节点，提取 AST 信息
                file_func_asts = []
                file_func_srcs = []
                
                for func_node in func_nodes:
                    node_info_list = []
                    parser.traverse_ast(func_node, file_path, node_info_list)
                    
                    # 计算每个节点的子节点数量
                    parser.calculate_ast_num(node_info_list)
                    
                    if node_info_list:
                        file_func_asts.append(node_info_list)
                        # 提取函数源代码
                        func_src = parser.get_code_snippet(func_node, file_path)
                        file_func_srcs.append(func_src if func_src else "")
                
                diagnostics["selected_function_count"] = len(file_func_asts)
                diagnostics["semantic_slice_count"] = sum(
                    len(function_ast[0].get("semantic_slices", []))
                    for function_ast in file_func_asts
                    if function_ast
                )
                file_diagnostics.append(diagnostics)
                funcs_in_pro.append(file_func_asts)
                funcs_in_pro_src.append(file_func_srcs)
                
            except Exception as e:
                logger.error(f"    错误: 处理文件失败 {file_path}: {e}", exc_info=True)
                diagnostics = dict(parser.last_file_diagnostics)
                diagnostics.update(
                    {
                        "project": project_name,
                        "input_path": file_path,
                        "status": "failed",
                        "failure": type(e).__name__,
                        "message": str(e),
                    }
                )
                file_diagnostics.append(diagnostics)
                funcs_in_pro.append([])
                funcs_in_pro_src.append([])
        
        pro_func_ast.append(funcs_in_pro)
        pro_func_ast_src.append(funcs_in_pro_src)
        logger.info(f"  项目 {project_name} 处理完成")
    
    # 过滤掉没有有效函数的文件
    logger.info("\n过滤无效文件...")
    pro_files, pro_funcs, pro_funcs_src = scanner.filter_valid_files(
        pro_func_ast, pro_func_ast_src
    )
    
    # 保存数据
    save_data(scanner, pro_files, pro_funcs, pro_funcs_src, output_path)
    resolved_audit_path = audit_output_path or str(
        Path(output_path).with_suffix(".audit.json")
    )
    save_parse_audit(
        input_path=input_path,
        output_path=output_path,
        audit_output_path=resolved_audit_path,
        projects=selected_projects,
        scanned_files=pro_file_list,
        file_diagnostics=file_diagnostics,
        scan_diagnostics=scanner.last_scan_diagnostics,
    )
    if fragment_output_path is not None:
        build_fragment_file(
            dataset_path=output_path,
            output_path=fragment_output_path,
            model=embedding_model,
            max_input_tokens=max_input_tokens,
            local_files_only=local_files_only,
        )


def save_parse_audit(
    *,
    input_path: str,
    output_path: str,
    audit_output_path: str,
    projects: List[str],
    scanned_files: List[List[str]],
    file_diagnostics: List[Dict[str, Any]],
    scan_diagnostics: Optional[Dict[str, Any]] = None,
) -> None:
    """保存所有扫描文件的解析、恢复和未覆盖证据，不改变 pickle Schema。"""
    status_counts: Dict[str, int] = {}
    for record in file_diagnostics:
        status = str(record.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "scanned_file_count": sum(len(files) for files in scanned_files),
        "diagnostic_file_count": len(file_diagnostics),
        "failed_file_count": sum(
            str(record.get("status") or "") == "failed"
            for record in file_diagnostics
        ),
        "recovered_file_count": sum(
            bool(record.get("recovery", {}).get("used"))
            for record in file_diagnostics
        ),
        "error_count": sum(
            int(record.get("raw", {}).get("error_count", 0) or 0)
            for record in file_diagnostics
        ),
        "missing_count": sum(
            int(record.get("raw", {}).get("missing_count", 0) or 0)
            for record in file_diagnostics
        ),
        "selected_function_count": sum(
            int(record.get("selected_function_count", 0) or 0)
            for record in file_diagnostics
        ),
        "semantic_slice_count": sum(
            int(record.get("semantic_slice_count", 0) or 0)
            for record in file_diagnostics
        ),
        "status_counts": status_counts,
    }
    payload = {
        "parser_backend": "tree-sitter-cpp",
        "dataset_schema": ["project", "cppFile", "func_ast", "func_src"],
        "input_path": input_path,
        "output_path": output_path,
        "projects": projects,
        "scan": scan_diagnostics or {},
        "summary": summary,
        "files": sorted(
            file_diagnostics,
            key=lambda record: (
                str(record.get("project") or ""),
                str(record.get("source_path") or record.get("input_path") or ""),
            ),
        ),
    }
    audit_path = Path(audit_output_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("解析审计已保存到: %s", audit_output_path)


def save_data(scanner: FileScanner, pro_files: List[List[str]], 
              pro_funcs: List[List[List[dict]]], 
              pro_funcs_src: List[List[List[str]]], 
              output_path: str):
    """
    保存解析结果到 pickle 文件
    
    Args:
        scanner: 文件扫描器实例
        pro_files: 文件路径列表（2D: 项目-文件）
        pro_funcs: 函数 AST 列表（3D: 项目-文件-函数）
        pro_funcs_src: 函数源代码列表（3D: 项目-文件-函数）
        output_path: 输出文件路径
    """
    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"输出目录: {output_dir}")
    
    # 创建 DataFrame
    data = pd.DataFrame({
        'project': scanner.projects,
        'cppFile': pro_files,  # 保持与原项目兼容的列名
        'func_ast': pro_funcs,
        'func_src': pro_funcs_src
    })
    
    total_files = sum(len(files) for files in pro_files)
    total_funcs = sum(sum(len(funcs) for funcs in proj) for proj in pro_funcs)
    
    logger.info(f"\n数据统计:")
    logger.info(f"  项目数: {len(scanner.projects)}")
    logger.info(f"  总文件数: {total_files}")
    logger.info(f"  总函数数: {total_funcs}")
    logger.info(f"\n数据列: {data.columns.tolist()}")
    logger.info(f"数据形状: {data.shape}")
    
    # 保存为 pickle
    pd.to_pickle(data, output_path)
    logger.info(f"\n数据已保存到: {output_path}")
    logger.info("=" * 60)
    logger.info("解析完成！")
    logger.info("=" * 60)


def read_data(data_file_path: str):
    """
    读取保存的数据
    
    Args:
        data_file_path: 数据文件路径
        
    Returns:
        DataFrame
    """
    return pd.read_pickle(data_file_path)


def main():
    """测试解析功能"""
    parser = argparse.ArgumentParser(
        description='将仓库源代码解析为 AST 并提取函数节点'
    )
    parser.add_argument(
        '--input', '-i',
        default='repos',
        help='输入项目路径（例如: repos）'
    )
    parser.add_argument(
        '--output', '-o',
        default='outputs/cli11/stage0/dataset.pkl',
        help='输出数据文件路径（例如: outputs/cli11/stage0/dataset.pkl）'
    )
    parser.add_argument(
        '--audit-output',
        default=None,
        help='解析审计 JSON 路径；默认与 dataset 同目录并命名为 dataset.audit.json',
    )
    parser.add_argument(
        '--fragment-output',
        default=None,
        help='可选：在 Parser 阶段同时生成 model-ready fragments.pkl',
    )
    parser.add_argument(
        '--embedding-model',
        default='unixcoder',
        help='片段长度合同所针对的 embedding 模型（默认: unixcoder）',
    )
    parser.add_argument(
        '--max-input-tokens',
        type=int,
        default=None,
        help='可选的更严格总 token 上限；只能收紧模型配置值',
    )
    parser.add_argument(
        '--local-files-only',
        action='store_true',
        help='构建片段时只使用本地 tokenizer 缓存，禁止下载',
    )
    parser.add_argument(
        '--project',
        action='append',
        default=None,
        help='只解析指定项目目录；可重复传入，省略时解析全部项目',
    )
    args = parser.parse_args()
    
    # 解析仓库
    parse_repository(
        args.input,
        args.output,
        args.audit_output,
        args.fragment_output,
        args.embedding_model,
        args.max_input_tokens,
        args.local_files_only,
        args.project,
    )


if __name__ == "__main__":
    main()
