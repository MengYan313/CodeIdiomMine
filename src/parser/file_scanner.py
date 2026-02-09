"""
文件扫描器
用于扫描指定目录下的源代码文件
"""

import os
from typing import List, Dict

from ..logger import get_logger

# 创建日志记录器
logger = get_logger(__name__)


class FileScanner:
    """扫描源代码文件"""
    
    # 语言到文件扩展名的映射
    LANGUAGE_EXTENSIONS = {
        "cpp": [".cpp", ".cc", ".cxx", ".c++", ".hpp", ".h", ".hxx"],
        "python": [".py"],
        "java": [".java"],
        "javascript": [".js", ".jsx", ".ts", ".tsx"],
    }
    
    def __init__(self, language: str):
        """
        初始化文件扫描器
        
        Args:
            language: 编程语言名称
        """
        self.language = language.lower()
        self.extensions = self.LANGUAGE_EXTENSIONS.get(
            self.language, 
            self.LANGUAGE_EXTENSIONS["cpp"]
        )
        self.projects: List[str] = []
        self.pro_file_list: List[List[str]] = []
    
    def get_projects(self, base_path: str) -> List[str]:
        """
        获取基础路径下的所有项目目录
        
        Args:
            base_path: 基础路径，例如 CodeIdiomMine/repo/cpp
            
        Returns:
            项目名称列表
        """
        if not os.path.exists(base_path):
            logger.error(f"路径不存在: {base_path}")
            return []
        
        projects = []
        for item in os.listdir(base_path):
            item_path = os.path.join(base_path, item)
            if os.path.isdir(item_path):
                projects.append(item)
        
        projects.sort()
        self.projects = projects
        logger.info(f"找到 {len(projects)} 个项目")
        logger.debug(f"项目列表: {projects}")
        return projects
    
    def get_all_source_files(self, base_path: str) -> List[List[str]]:
        """
        获取所有项目的源代码文件
        
        Args:
            base_path: 基础路径，例如 CodeIdiomMine/repo/cpp
            
        Returns:
            二维列表，第一维是项目，第二维是该项目的文件列表
        """
        if not self.projects:
            self.get_projects(base_path)
        
        pro_file_list = []
        
        for project_name in self.projects:
            project_path = os.path.join(base_path, project_name)
            files_list = self._scan_project_files(project_path)
            pro_file_list.append(files_list)
        
        self.pro_file_list = pro_file_list
        return pro_file_list
    
    def _scan_project_files(self, project_path: str) -> List[str]:
        """
        扫描单个项目目录下的所有源代码文件
        
        Args:
            project_path: 项目路径
            
        Returns:
            文件路径列表
        """
        files_list = []
        
        for root, dirs, files in os.walk(project_path):
            # 跳过测试目录和隐藏目录
            if any(skip in root.lower() for skip in ["test", "__pycache__", ".git", ".svn"]):
                continue
            
            for file_name in files:
                # 检查文件扩展名
                if any(file_name.endswith(ext) for ext in self.extensions):
                    # 跳过测试文件
                    if "test" in file_name.lower() and self.language != "python":
                        continue
                    file_path = os.path.join(root, file_name)
                    files_list.append(file_path)
        
        return files_list
    
    def filter_valid_files(self, func_asts: List[List[List[Dict]]], 
                          func_srcs: List[List[List[str]]]) -> tuple:
        """
        过滤掉没有有效函数的文件
        
        Args:
            func_asts: 函数 AST 节点列表（3D: 项目-文件-函数）
            func_srcs: 函数源代码列表（3D: 项目-文件-函数）
            
        Returns:
            (pro_files, pro_funcs, pro_funcs_src) 元组
        """
        pro_files = []
        pro_funcs = []
        pro_funcs_src = []
        
        for i in range(len(self.projects)):
            pro_files_ = []
            pro_funcs_ = []
            pro_funcs_src_ = []
            
            for j in range(len(func_asts[i])):
                if func_asts[i][j] is not None and len(func_asts[i][j]) != 0:
                    pro_files_.append(self.pro_file_list[i][j])
                    pro_funcs_.append(func_asts[i][j])
                    pro_funcs_src_.append(func_srcs[i][j])
            
            pro_files.append(pro_files_)
            pro_funcs.append(pro_funcs_)
            pro_funcs_src.append(pro_funcs_src_)
        
        return pro_files, pro_funcs, pro_funcs_src

