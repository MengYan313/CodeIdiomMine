"""基于 tree-sitter-cpp 的 C++ AST 解析器。"""

import os
import re
from typing import Dict, List, Optional
import tree_sitter
from tree_sitter import Language, Parser

from ..common.node_kinds import FUNCTION_KINDS
from ..common.logging import get_logger

# 创建日志记录器
logger = get_logger(__name__)


class ASTParser:
    """使用 tree-sitter 解析代码文件的 AST"""
    
    def __init__(self):
        """初始化 C++ AST 解析器。"""
        logger.info("初始化 C++ AST 解析器")
        self.parser = self._init_parser()
        logger.info("AST 解析器初始化完成")
        # 源码字节缓存：仅缓存最近一次 parse_file 的文件，避免每个 AST 节点
        # 都重新打开同一个文件（提取片段的结果完全不变，仅消除重复磁盘 IO）。
        self._cached_path: Optional[str] = None
        self._cached_source: bytes = b""
        
    def _init_parser(self) -> Parser:
        """加载 tree-sitter-cpp grammar 并初始化解析器。"""
        try:
            import tree_sitter_cpp

            cpp_language = Language(tree_sitter_cpp.language())
            logger.debug("成功加载 tree-sitter-cpp grammar")
        except ImportError as e:
            error_msg = "无法导入 C++ grammar。请安装: pip install tree-sitter-cpp"
            logger.error(error_msg)
            raise ImportError(error_msg) from e
        
        parser = Parser(cpp_language)
        return parser
    
    def parse_file(self, file_path: str) -> Optional[tree_sitter.Tree]:
        """
        解析文件为 AST
        
        Args:
            file_path: 源文件路径
            
        Returns:
            AST 树对象，如果解析失败返回 None
        """
        try:
            with open(file_path, "rb") as f:
                source_code = f.read()
            self._cached_path = file_path
            self._cached_source = source_code
            tree = self.parser.parse(source_code)
            logger.debug(f"成功解析文件: {file_path}")
            return tree
        except Exception as e:
            logger.error(f"解析文件失败 {file_path}: {e}")
            return None
    
    def get_function_nodes(self, tree: tree_sitter.Tree, file_path: str) -> List[tree_sitter.Node]:
        """
        提取函数定义节点
        
        Args:
            tree: AST 树
            file_path: 源文件路径（用于过滤节点）
            
        Returns:
            函数节点列表
        """
        if tree is None:
            return []
        
        func_nodes = []
        processed_ranges = []
        
        def traverse(node: tree_sitter.Node, depth: int = 0):
            """递归遍历 AST 节点"""
            # 检查节点类型是否在函数类型列表中
            node_type = node.type
            
            if node_type in FUNCTION_KINDS:
                # 获取节点范围
                start_point = node.start_point
                end_point = node.end_point
                current_range = (
                    start_point[0] + 1,  # tree-sitter 使用 0-based，转换为 1-based
                    end_point[0] + 1
                )
                
                # 检查是否嵌套在其他已处理的函数中
                is_nested = any(
                    start_line <= current_range[0] and current_range[1] <= end_line
                    for start_line, end_line in processed_ranges
                )
                
                if not is_nested:
                    func_nodes.append(node)
                    processed_ranges.append(current_range)
            
            # 递归遍历子节点
            for child in node.children:
                traverse(child, depth + 1)
        
        traverse(tree.root_node)
        return func_nodes
    
    def traverse_ast(self, node: tree_sitter.Node, file_path: str, 
                     node_info_list: List[Dict], depth: int = 0) -> int:
        """
        遍历 AST 节点，提取节点信息
        
        Args:
            node: 当前 AST 节点
            file_path: 源文件路径
            node_info_list: 存储节点信息的列表
            depth: 当前深度
            
        Returns:
            遍历的节点总数
        """
        count = 0
        
        try:
            count += 1
            start_point = node.start_point
            end_point = node.end_point
            
            # 提取代码片段
            code_snippet = self.get_code_snippet(node, file_path)
            
            # 构建节点信息字典
            node_info = {
                "depth": depth,
                "extent": f"{start_point[0] + 1}-{start_point[1]}-{end_point[0] + 1}-{end_point[1]}",
                "kind": node.type,
                "type_kind": None,  # tree-sitter 不直接提供类型信息
                "type_spelling": None,
                "spelling": self._get_node_name(node),
                "displayname": self._get_node_name(node),
                "code_snippet": code_snippet,
                "ast_num": 0  # 先设为 0，后续会更新
            }
            
            node_info_list.append(node_info)
        except Exception as e:
            logger.debug(f"警告: 跳过节点 due to error: {e}")
        
        # 递归遍历子节点
        for child in node.children:
            count += self.traverse_ast(child, file_path, node_info_list, depth + 1)
        
        return count
    
    def calculate_ast_num(self, node_info_list: List[Dict]) -> None:
        """
        计算每个节点的直接子节点数量，更新 ast_num 字段
        
        Args:
            node_info_list: 节点信息列表（按深度优先顺序）
        """
        if not node_info_list:
            return
        
        # 为每个节点计算其直接子节点数量
        for i, node_info in enumerate(node_info_list):
            current_depth = node_info["depth"]
            child_count = 0
            
            # 查找下一个节点，统计深度为 current_depth + 1 的连续节点数量
            j = i + 1
            while j < len(node_info_list):
                next_depth = node_info_list[j]["depth"]
                
                # 如果是直接子节点（深度为当前深度 + 1）
                if next_depth == current_depth + 1:
                    child_count += 1
                    j += 1
                # 如果深度更深，跳过（孙节点及更深层）
                elif next_depth > current_depth + 1:
                    j += 1
                # 如果深度回退到当前层或更浅，停止
                else:
                    break
            
            node_info["ast_num"] = child_count
            # DFS 序列中一棵子树连续占据 [i, j)，因此该值是包含根节点的
            # 完整子树规模。保留 ast_num 的历史“直接子节点数”语义。
            node_info["subtree_size"] = j - i
    
    def _get_node_name(self, node: tree_sitter.Node) -> Optional[str]:
        """获取节点的名称（如果存在）"""
        # 尝试从子节点中查找标识符
        for child in node.children:
            if child.type in ["identifier", "type_identifier", "field_identifier"]:
                return self._decode_bytes(child.text)
        return None
    
    def _decode_bytes(self, data: bytes) -> str:
        """
        智能解码字节数据，自动检测编码
        
        Args:
            data: 字节数据
            
        Returns:
            解码后的字符串
        """
        if not data:
            return ""
        
        # 检测 UTF-16 BOM
        if data.startswith(b'\xff\xfe') or data.startswith(b'\xfe\xff'):
            try:
                return data.decode('utf-16')
            except Exception:
                pass
        
        # 检测是否为 UTF-16（每个字符后跟 \x00）
        if len(data) > 2 and data[1:2] == b'\x00' and data[3:4] == b'\x00':
            try:
                return data.decode('utf-16-le')
            except Exception:
                pass
        
        # 尝试 UTF-8
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            pass
        
        # 尝试 Latin-1（几乎总是成功）
        try:
            return data.decode('latin-1')
        except Exception:
            pass
        
        # 最后使用 UTF-8 忽略错误
        return data.decode('utf-8', errors='ignore')
    
    def get_code_snippet(self, node: tree_sitter.Node, file_path: str) -> Optional[str]:
        """
        根据节点范围提取代码片段，并移除注释
        
        Args:
            node: AST 节点
            file_path: 源文件路径
            
        Returns:
            清理后的代码片段
        """
        try:
            # 使用字节范围直接提取文本（更高效）
            # 复用 parse_file 缓存的源码字节；遍历单个文件 AST 时这能避免
            # 对同一文件成百上千次重复读取。
            if file_path == self._cached_path:
                source_bytes = self._cached_source
            else:
                with open(file_path, "rb") as f:
                    source_bytes = f.read()

            start_byte = node.start_byte
            end_byte = node.end_byte
            snippet_bytes = source_bytes[start_byte:end_byte]
            
            # 自动检测并处理编码
            snippet = self._decode_bytes(snippet_bytes)
            
            # 移除注释和多余换行
            snippet = self.remove_single_line_comments(snippet)
            snippet = self.remove_multi_line_comments(snippet)
            snippet = self.remove_extra_newlines(snippet)
            
            return snippet.strip()
        except Exception as e:
            logger.error(f"无法读取文件 {file_path}: {e}")
            return None
    
    def remove_single_line_comments(self, code: str) -> str:
        """移除 C++ 单行注释。"""
        return re.sub(r"//.*?$", "", code, flags=re.MULTILINE)
    
    def remove_multi_line_comments(self, code: str) -> str:
        """移除 C++ 块注释。"""
        return re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    
    def remove_extra_newlines(self, code: str) -> str:
        """移除多余的换行符"""
        pattern = r"\n\s*\n"
        code = re.sub(pattern, "\n", code)
        return code
