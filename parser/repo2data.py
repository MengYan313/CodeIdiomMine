"""
主入口文件
将仓库中的源代码解析为 AST，提取函数节点和代码片段
"""

import os
import sys
import argparse
import pandas as pd
from typing import List

# 支持作为模块导入和直接运行
try:
    from .ast_parser import ASTParser
    from .file_scanner import FileScanner
except ImportError:
    # 如果作为脚本直接运行，使用绝对导入
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ast_parser import ASTParser
    from file_scanner import FileScanner


def parse_repository(input_path: str, output_path: str, language: str = "cpp"):
    """
    解析仓库中的所有源代码文件
    
    Args:
        input_path: 输入路径，例如 CodeIdiomMine/repo/cpp
        output_path: 输出路径，例如 CodeIdiomMine/output/cpp
        language: 编程语言名称
    """
    # 初始化文件扫描器
    scanner = FileScanner(language)
    
    # 获取所有项目
    projects = scanner.get_projects(input_path)
    print(f"找到 {len(projects)} 个项目")
    
    # 获取所有源代码文件
    pro_file_list = scanner.get_all_source_files(input_path)
    print(f"总共找到 {sum(len(files) for files in pro_file_list)} 个文件")
    
    # 初始化 AST 解析器
    parser = ASTParser(language)
    
    # 存储所有项目的函数 AST 和源代码
    pro_func_ast = []  # 3D: 项目-文件-函数
    pro_func_ast_src = []  # 3D: 项目-文件-函数
    
    # 遍历每个项目
    for i, project_name in enumerate(projects):
        print(f"\n处理项目 [{i+1}/{len(projects)}]: {project_name}")
        funcs_in_pro = []  # 存储当前项目的所有函数 AST（2D: 文件-函数）
        funcs_in_pro_src = []  # 存储当前项目的所有函数源代码（2D: 文件-函数）
        
        # 遍历项目中的每个文件
        for j, file_path in enumerate(pro_file_list[i]):
            print(f"  处理文件 [{j+1}/{len(pro_file_list[i])}]: {os.path.basename(file_path)}")
            
            try:
                # 解析文件为 AST
                tree = parser.parse_file(file_path)
                if tree is None:
                    funcs_in_pro.append([])
                    funcs_in_pro_src.append([])
                    continue
                
                # 提取函数节点
                func_nodes = parser.get_function_nodes(tree, file_path)
                
                if not func_nodes:
                    funcs_in_pro.append([])
                    funcs_in_pro_src.append([])
                    continue
                
                # 遍历每个函数节点，提取 AST 信息
                file_func_asts = []
                file_func_srcs = []
                
                for func_node in func_nodes:
                    node_info_list = []
                    parser.traverse_ast(func_node, file_path, node_info_list)
                    
                    if node_info_list:
                        file_func_asts.append(node_info_list)
                        # 提取函数源代码
                        func_src = parser.get_code_snippet(func_node, file_path)
                        file_func_srcs.append(func_src if func_src else "")
                
                funcs_in_pro.append(file_func_asts)
                funcs_in_pro_src.append(file_func_srcs)
                
            except Exception as e:
                print(f"    错误: 处理文件失败 {file_path}: {e}")
                funcs_in_pro.append([])
                funcs_in_pro_src.append([])
        
        pro_func_ast.append(funcs_in_pro)
        pro_func_ast_src.append(funcs_in_pro_src)
    
    # 过滤掉没有有效函数的文件
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
    
    # 创建 DataFrame
    data = pd.DataFrame({
        'project': scanner.projects,
        'cppFile': pro_files,  # 保持与原项目兼容的列名
        'func_ast': pro_funcs,
        'func_src': pro_funcs_src
    })
    
    print(f"\n数据统计:")
    print(f"  项目数: {len(scanner.projects)}")
    print(f"  总文件数: {sum(len(files) for files in pro_files)}")
    print(f"  总函数数: {sum(sum(len(funcs) for funcs in proj) for proj in pro_funcs)}")
    print(f"\n数据列: {data.columns.tolist()}")
    print(f"数据形状: {data.shape}")
    
    # 保存为 pickle
    pd.to_pickle(data, output_path)
    print(f"\n数据已保存到: {output_path}")


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
    """主函数"""
    parser = argparse.ArgumentParser(
        description='将仓库源代码解析为 AST 并提取函数节点'
    )
    parser.add_argument(
        '--input', '-i',
        default='../repo/cpp',
        help='输入项目路径（例如: ../repo/cpp）'
    )
    parser.add_argument(
        '--output', '-o',
        default='../output/cpp/dataset.pkl',
        help='输出数据文件路径（例如: ../output/cpp/dataset.pkl）'
    )
    parser.add_argument(
        '--language', '-l',
        default='cpp',
        choices=['cpp', 'python', 'java', 'javascript'],
        help='编程语言类型'
    )
    
    args = parser.parse_args()
    
    # 解析仓库
    parse_repository(args.input, args.output, args.language)


if __name__ == "__main__":
    main()

