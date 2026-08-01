"""通用 Tree-sitter AST 操作核心；当前固定装配 C++ Adapter。"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import tree_sitter
from tree_sitter import Parser

from ..common.logging import get_logger
from .cpp_adapter import CPP_ADAPTER, CppAdapter
from .semantic_slicer import extract_semantic_slices

# 创建日志记录器
logger = get_logger(__name__)
_WHITESPACE_BYTES = frozenset(b" \t\r\n\v\f")
_PARSE_FLAG_HAS_ERROR = 1
_PARSE_FLAG_IS_ERROR = 2
_PARSE_FLAG_IS_MISSING = 4
_PARSE_FLAG_SHADOW = 8


class ASTParser:
    """使用 tree-sitter 解析代码文件的 AST"""
    
    def __init__(self):
        """初始化 C++ AST 解析器。"""
        logger.info("初始化 C++ AST 解析器")
        self.adapter: CppAdapter = CPP_ADAPTER
        self.parser = self._init_parser()
        logger.info("AST 解析器初始化完成")
        # 源码字节缓存：仅缓存最近一次 parse_file 的文件，避免每个 AST 节点
        # 都重新打开同一个文件（提取片段的结果完全不变，仅消除重复磁盘 IO）。
        self._cached_path: Optional[str] = None
        self._cached_source: bytes = b""
        self._cached_tree: Optional[tree_sitter.Tree] = None
        self._cached_shadow_tree: Optional[tree_sitter.Tree] = None
        self._source_path: str = ""
        self._source_file_id: str = ""
        self._node_origins: Dict[int, str] = {}
        self.last_file_diagnostics: Dict[str, Any] = {}
        
    def _init_parser(self) -> Parser:
        """通过内部 C++ Adapter 初始化固定 grammar。"""
        try:
            parser = self.adapter.create_parser()
            logger.debug("成功加载 tree-sitter-cpp grammar")
        except ImportError as exc:
            logger.error(str(exc))
            raise
        return parser
    
    def parse_file(
        self,
        file_path: str,
        source_root: Optional[str] = None,
    ) -> Optional[tree_sitter.Tree]:
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
            self._source_path = self._stable_source_path(file_path, source_root)
            self._source_file_id = self._source_path
            self._node_origins.clear()
            tree = self.parser.parse(source_code)
            self._cached_tree = tree
            self._cached_shadow_tree = None

            raw_diagnostics = self._collect_tree_diagnostics(tree)
            shadow_diagnostics: Optional[Dict[str, Any]] = None
            masked_ranges: List[Tuple[int, int]] = []
            recovery_used = False
            if (
                raw_diagnostics["error_count"] > 0
                or raw_diagnostics["missing_count"] > 0
            ):
                shadow_source, masked_ranges = self.adapter.mask_preprocessor(
                    source_code
                )
                if masked_ranges:
                    shadow_tree = self.parser.parse(shadow_source)
                    shadow_diagnostics = self._collect_tree_diagnostics(shadow_tree)
                    raw_score = (
                        raw_diagnostics["error_count"]
                        + raw_diagnostics["missing_count"]
                    )
                    shadow_score = (
                        shadow_diagnostics["error_count"]
                        + shadow_diagnostics["missing_count"]
                    )
                    if (
                        shadow_score < raw_score
                        and shadow_diagnostics["function_definition_count"]
                        >= raw_diagnostics["function_definition_count"]
                    ):
                        self._cached_shadow_tree = shadow_tree
                        recovery_used = True

            self.last_file_diagnostics = {
                "source_path": self._source_path,
                "source_file_id": self._source_file_id,
                "byte_count": len(source_code),
                "status": (
                    "recovered"
                    if raw_diagnostics["error_count"]
                    or raw_diagnostics["missing_count"]
                    else "clean"
                ),
                "raw": raw_diagnostics,
                "recovery": {
                    "strategy": "preprocessor-shadow",
                    "attempted": shadow_diagnostics is not None,
                    "used": recovery_used,
                    "masked_ranges": [
                        {"start_byte": start, "end_byte": end}
                        for start, end in masked_ranges
                    ],
                    "shadow": shadow_diagnostics,
                },
            }
            logger.debug(f"成功解析文件: {file_path}")
            return tree
        except Exception as e:
            self._cached_tree = None
            self._cached_shadow_tree = None
            self.last_file_diagnostics = {
                "source_path": self._stable_source_path(file_path, source_root),
                "status": "failed",
                "failure": type(e).__name__,
                "message": str(e),
            }
            logger.error(f"解析文件失败 {file_path}: {e}")
            return None

    def _stable_source_path(
        self,
        file_path: str,
        source_root: Optional[str],
    ) -> str:
        path = Path(file_path)
        if source_root is None:
            return path.as_posix()
        try:
            return path.resolve().relative_to(Path(source_root).resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def _iter_nodes(
        self,
        root: tree_sitter.Node,
    ) -> Iterable[tree_sitter.Node]:
        stack = [root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def _collect_tree_diagnostics(
        self,
        tree: tree_sitter.Tree,
    ) -> Dict[str, Any]:
        errors: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []
        error_ranges: List[Tuple[int, int]] = []
        preprocessor_ranges: List[Tuple[int, int]] = []
        preprocessor_count = 0
        node_count = 0
        function_count = 0
        reliable = bytearray(len(self._cached_source))
        stack: List[Tuple[tree_sitter.Node, bool]] = [(tree.root_node, False)]
        while stack:
            node, parent_under_error = stack.pop()
            under_error = (
                parent_under_error
                or node.is_error
                or node.type == self.adapter.error_kind
            )
            node_count += 1
            function_count += int(self.adapter.is_function_definition(node))
            preprocessor_count += int(self.adapter.is_preprocessor(node))
            if self.adapter.is_preprocessor(node):
                preprocessor_ranges.append((node.start_byte, node.end_byte))
            if node.is_error or node.type == self.adapter.error_kind:
                errors.append(self._diagnostic_node(node))
                error_ranges.append((node.start_byte, node.end_byte))
            if node.is_missing:
                missing.append(self._diagnostic_node(node))
            if (
                node.child_count == 0
                and node.end_byte > node.start_byte
                and not under_error
            ):
                reliable[node.start_byte : node.end_byte] = b"\x01" * (
                    node.end_byte - node.start_byte
                )
            for child in reversed(node.children):
                stack.append((child, under_error))

        significant_count = sum(
            value not in _WHITESPACE_BYTES for value in self._cached_source
        )
        reliable_significant_count = sum(
            value not in _WHITESPACE_BYTES and reliable[index]
            for index, value in enumerate(self._cached_source)
        )
        uncovered_ranges: List[Dict[str, int]] = []
        start: Optional[int] = None
        for index, value in enumerate(self._cached_source):
            uncovered = value not in _WHITESPACE_BYTES and not reliable[index]
            if uncovered and start is None:
                start = index
            elif not uncovered and start is not None:
                uncovered_ranges.append({"start_byte": start, "end_byte": index})
                start = None
        if start is not None:
            uncovered_ranges.append(
                {"start_byte": start, "end_byte": len(self._cached_source)}
            )
        macro_related_error_count = sum(
            1
            for error_start, error_end in error_ranges
            if any(
                error_start < macro_end and macro_start < error_end
                for macro_start, macro_end in preprocessor_ranges
            )
        )
        root_start = tree.root_node.start_byte
        root_end = tree.root_node.end_byte
        significant_outside_root = sum(
            value not in _WHITESPACE_BYTES
            for value in (
                self._cached_source[:root_start]
                + self._cached_source[root_end:]
            )
        )
        return {
            "node_count": node_count,
            "function_definition_count": function_count,
            "error_count": len(errors),
            "missing_count": len(missing),
            "preprocessor_node_count": preprocessor_count,
            "macro_related_error_count": macro_related_error_count,
            "significant_byte_count": significant_count,
            "reliable_significant_byte_count": reliable_significant_count,
            "ast_coverage": (
                reliable_significant_count / significant_count
                if significant_count
                else 1.0
            ),
            "uncovered_significant_byte_count": (
                significant_count - reliable_significant_count
            ),
            "uncovered_ranges": uncovered_ranges,
            "root_start_byte": root_start,
            "root_end_byte": root_end,
            "root_covers_significant_source": significant_outside_root == 0,
            "errors": errors,
            "missing": missing,
        }

    def _diagnostic_node(self, node: tree_sitter.Node) -> Dict[str, Any]:
        return {
            "kind": node.type,
            "extent": self._extent(node),
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
        }

    def _extent(self, node: tree_sitter.Node) -> str:
        return (
            f"{node.start_point[0] + 1}-{node.start_point[1]}-"
            f"{node.end_point[0] + 1}-{node.end_point[1]}"
        )
    
    def get_function_nodes(
        self,
        tree: tree_sitter.Tree,
        file_path: str,
    ) -> List[tree_sitter.Node]:
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
        
        raw_nodes = self._function_definitions(tree.root_node)
        error_recovery_nodes = self._error_function_boundaries(tree.root_node)
        raw_by_range: Dict[Tuple[int, int], tree_sitter.Node] = {
            (node.start_byte, node.end_byte): node for node in raw_nodes
        }
        if self._cached_shadow_tree is None:
            selected = dict(raw_by_range)
            origins: Dict[Tuple[int, int], str] = {
                key: "raw" for key in selected
            }
        else:
            selected = {}
            origins = {}
            for shadow_node in self._function_definitions(
                self._cached_shadow_tree.root_node
            ):
                key = (shadow_node.start_byte, shadow_node.end_byte)
                raw_node = raw_by_range.get(key)
                if raw_node is not None and (
                    not raw_node.has_error or shadow_node.has_error
                ):
                    selected[key] = raw_node
                    origins[key] = "raw"
                else:
                    selected[key] = shadow_node
                    origins[key] = "preprocessor-shadow"

        for recovery_node in error_recovery_nodes:
            key = (recovery_node.start_byte, recovery_node.end_byte)
            if any(
                start <= key[0] and key[1] <= end
                for start, end in selected
            ):
                continue
            selected[key] = recovery_node
            origins[key] = "error-boundary-recovery"

        func_nodes = sorted(
            selected.values(),
            key=lambda node: (node.start_byte, node.end_byte),
        )
        for node in func_nodes:
            key = (node.start_byte, node.end_byte)
            self._node_origins[node.id] = origins[key]

        raw_ranges = set(raw_by_range)
        recovery = self.last_file_diagnostics.setdefault("recovery", {})
        recovery["selected_function_count"] = len(func_nodes)
        recovery["recovered_function_count"] = sum(
            (node.start_byte, node.end_byte) not in raw_ranges
            or origins[(node.start_byte, node.end_byte)] != "raw"
            for node in func_nodes
        )
        recovery["error_boundary_recovered_count"] = sum(
            origin == "error-boundary-recovery" for origin in origins.values()
        )
        recovery["recovered_function_ranges"] = [
            {
                "start_byte": node.start_byte,
                "end_byte": node.end_byte,
                "extent": self._extent(node),
            }
            for node in func_nodes
            if (
                (node.start_byte, node.end_byte) not in raw_ranges
                or origins[(node.start_byte, node.end_byte)] != "raw"
            )
        ]
        return func_nodes

    def _function_definitions(
        self,
        root: tree_sitter.Node,
    ) -> List[tree_sitter.Node]:
        """只返回具有函数体的定义；类、模板壳和声明不伪装成函数。"""
        functions: List[tree_sitter.Node] = []
        stack = [root]
        while stack:
            node = stack.pop()
            if self.adapter.is_function_definition(node):
                functions.append(node)
            stack.extend(reversed(node.children))
        return functions

    def _error_function_boundaries(
        self,
        root: tree_sitter.Node,
    ) -> List[tree_sitter.Node]:
        """为不完整函数保留可追溯边界，但不把它冒充干净 AST。"""
        recovered: List[tree_sitter.Node] = []
        for node in self._iter_nodes(root):
            if not (node.is_error or node.type == self.adapter.error_kind):
                continue
            descendants = list(self._iter_nodes(node))
            if any(
                self.adapter.is_function_definition(descendant)
                for descendant in descendants[1:]
            ):
                continue
            if not any(
                self.adapter.is_function_declarator(descendant)
                for descendant in descendants[1:]
            ):
                continue
            source = self._cached_source[node.start_byte : node.end_byte]
            if b"{" not in source:
                continue
            recovered.append(node)
        return recovered
    
    def traverse_ast(
        self,
        node: tree_sitter.Node,
        file_path: str,
        node_info_list: List[Dict],
        depth: int = 0,
        _parse_origin: Optional[str] = None,
        _parent_kind: Optional[str] = None,
    ) -> int:
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
        parse_origin = _parse_origin or self._node_origins.get(node.id, "raw")
        reported_kind = (
            "recovered_function"
            if depth == 0 and parse_origin == "error-boundary-recovery"
            else node.type
        )
        
        try:
            count += 1
            start_point = node.start_point
            end_point = node.end_point
            
            # 提取代码片段
            code_snippet = self.get_code_snippet(node, file_path)
            
            # 构建节点信息字典
            node_info = {
                "depth": depth,
                "extent": self._extent(node),
                "kind": reported_kind,
                "type_kind": None,  # tree-sitter 不直接提供类型信息
                "type_spelling": None,
                "spelling": self._get_node_name(node),
                "displayname": self._get_node_name(node),
                "code_snippet": code_snippet,
                "ast_num": 0,  # 先设为 0，后续会更新
                "start_byte": node.start_byte,
                "end_byte": node.end_byte,
                "parse_flags": (
                    (_PARSE_FLAG_HAS_ERROR if node.has_error else 0)
                    | (_PARSE_FLAG_IS_ERROR if node.is_error else 0)
                    | (_PARSE_FLAG_IS_MISSING if node.is_missing else 0)
                    | (
                        _PARSE_FLAG_SHADOW
                        if parse_origin == "preprocessor-shadow"
                        else 0
                    )
                ),
            }
            if reported_kind != node.type:
                node_info["original_kind"] = node.type
            if depth == 0:
                node_info.update(
                    {
                        "source_path": self._source_path,
                        "source_file_id": self._source_file_id,
                        "mapping_exact": True,
                        "parse_origin": parse_origin,
                    }
                )
                if self.adapter.is_function_definition(node):
                    node_info["semantic_slices"] = extract_semantic_slices(
                        node,
                        self._cached_source,
                        source_path=self._source_path,
                        source_file_id=self._source_file_id,
                        parse_origin=parse_origin,
                    )
            
            node_info_list.append(node_info)
        except Exception as e:
            logger.debug(f"警告: 跳过节点 due to error: {e}")
        
        # 递归遍历子节点
        for child in node.children:
            count += self.traverse_ast(
                child,
                file_path,
                node_info_list,
                depth + 1,
                parse_origin,
                node.type,
            )
        
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
            if child.type in self.adapter.name_kinds:
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
        根据节点字节范围提取未经改写的原始代码片段。
        
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
            
            return snippet
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
