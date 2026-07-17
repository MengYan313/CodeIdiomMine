"""
主入口文件
将仓库中的源代码解析为 AST，提取函数节点和代码片段
"""

import os
import argparse
import pandas as pd
from typing import List

from .ast_parser import ASTParser
from .file_scanner import FileScanner
from ..common.logging import get_logger

# 创建日志记录器
logger = get_logger(__name__)


def parse_repository(input_path: str, output_path: str):
    """
    解析仓库中的所有源代码文件
    
    Args:
        input_path: 输入路径，例如 CodeIdiomMine/repos/cpp
        output_path: 输出路径，例如 CodeIdiomMine/outputs/cpp
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
    projects = scanner.get_projects(input_path)
    logger.info(f"找到 {len(projects)} 个项目: {projects}")
    
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
    
    # 遍历每个项目
    for i, project_name in enumerate(projects):
        logger.info(f"\n处理项目 [{i+1}/{len(projects)}]: {project_name}")
        funcs_in_pro = []  # 存储当前项目的所有函数 AST（2D: 文件-函数）
        funcs_in_pro_src = []  # 存储当前项目的所有函数源代码（2D: 文件-函数）
        
        # 遍历项目中的每个文件
        for j, file_path in enumerate(pro_file_list[i]):
            logger.info(f"  处理文件 [{j+1}/{len(pro_file_list[i])}]: {os.path.basename(file_path)}")
            
            try:
                # 解析文件为 AST
                tree = parser.parse_file(file_path)
                if tree is None:
                    logger.warning(f"    跳过文件（解析失败）: {file_path}")
                    funcs_in_pro.append([])
                    funcs_in_pro_src.append([])
                    continue
                
                # 提取函数节点
                func_nodes = parser.get_function_nodes(tree, file_path)
                
                if not func_nodes:
                    logger.debug(f"    未找到函数节点: {file_path}")
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
                
                funcs_in_pro.append(file_func_asts)
                funcs_in_pro_src.append(file_func_srcs)
                
            except Exception as e:
                logger.error(f"    错误: 处理文件失败 {file_path}: {e}", exc_info=True)
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
        default='repos/cpp',
        help='输入项目路径（例如: repos/cpp）'
    )
    parser.add_argument(
        '--output', '-o',
        default='outputs/cpp/dataset.pkl',
        help='输出数据文件路径（例如: outputs/cpp/dataset.pkl）'
    )
    args = parser.parse_args()
    
    # 解析仓库
    parse_repository(args.input, args.output)


# 模块运行命令（从项目根目录运行）：
# python -m src.parser.repo2data --input repos/cpp --output outputs/cpp/dataset.pkl
# nohup python -m src.parser.repo2data --input repos/cpp --output outputs/cpp/dataset.pkl > logs/repo2data.log 2>&1 &

if __name__ == "__main__":
    main()
