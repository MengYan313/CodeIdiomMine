"""按冻结清单或目录确定性读取 C/C++ 源文件。"""

import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List

from ..common.logging import get_logger

# 创建日志记录器
logger = get_logger(__name__)


class FileScanner:
    """扫描 C/C++ 源文件，并实施通用的安全与语料清洗边界。"""

    CPP_EXTENSIONS = frozenset(
        {".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx"}
    )
    EXCLUDED_DIRECTORY_NAMES = frozenset(
        {
            "__pycache__",
            "_build",
            "_deps",
            "3rd-party",
            "3rdparty",
            "benchmark",
            "benchmarks",
            "build",
            "builds",
            "deps",
            "dist",
            "example",
            "examples",
            "extern",
            "external",
            "gen",
            "generated",
            "node_modules",
            "out",
            "sample",
            "samples",
            "subprojects",
            "test",
            "testdata",
            "testing",
            "tests",
            "third-party",
            "third_party",
            "vendor",
            "vendors",
        }
    )
    EXCLUDED_DIRECTORY_PREFIXES = (
        "bazel-",
        "cmake-build-",
    )
    GENERATED_FILE_PATTERNS = (
        re.compile(r"(?:^|[._-])generated(?:[._-]|$)", re.IGNORECASE),
        re.compile(r"\.(?:pb|grpc)\.(?:cc|h)$", re.IGNORECASE),
        re.compile(r"^(?:moc_|ui_).+\.(?:cc|cpp|h|hpp)$", re.IGNORECASE),
    )
    
    def __init__(self):
        self.projects: List[str] = []
        self.pro_file_list: List[List[str]] = []
        self.base_path: Path | None = None
        self.file_splits: Dict[str, Dict[str, str]] = {}
        self.last_scan_diagnostics: Dict[str, Any] = {}
    
    def get_projects(
        self,
        base_path: str,
        project_names: List[str] | None = None,
    ) -> List[str]:
        """
        获取基础路径下的所有项目目录
        
        Args:
            base_path: 基础路径，例如 CodeIdiomMine/repos
            project_names: 可选的精确项目目录名列表；省略时扫描全部项目
            
        Returns:
            项目名称列表
        """
        base = Path(base_path)
        if not base.exists():
            logger.error(f"路径不存在: {base_path}")
            return []

        self.base_path = base.resolve()
        available_projects = sorted(
            item.name
            for item in base.iterdir()
            if item.is_dir() and not item.is_symlink() and not item.name.startswith(".")
        )
        if project_names is None:
            projects = available_projects
        else:
            requested_projects = sorted(set(project_names))
            invalid_names = [
                name
                for name in requested_projects
                if Path(name).name != name or name in {"", ".", ".."}
            ]
            if invalid_names:
                raise ValueError(
                    f"项目名必须是单个安全目录名: {invalid_names}"
                )
            missing_projects = sorted(
                set(requested_projects) - set(available_projects)
            )
            if missing_projects:
                raise ValueError(
                    f"找不到指定项目目录: {missing_projects}"
                )
            projects = requested_projects
        self.projects = projects
        logger.info(f"找到 {len(projects)} 个项目")
        logger.debug(f"项目列表: {projects}")
        return projects
    
    def get_all_source_files(self, base_path: str) -> List[List[str]]:
        """
        获取所有项目的源代码文件
        
        Args:
            base_path: 基础路径，例如 CodeIdiomMine/repos
            
        Returns:
            二维列表，第一维是项目，第二维是该项目的文件列表
        """
        if not self.projects:
            self.get_projects(base_path)
        
        manifest_path = Path(base_path) / "dataset-manifest.json"
        if manifest_path.exists():
            return self._files_from_manifest(manifest_path)

        pro_file_list = []
        project_diagnostics: Dict[str, Any] = {}
        
        for project_name in self.projects:
            project_path = os.path.join(base_path, project_name)
            files_list, diagnostics = self._scan_project_files_with_diagnostics(
                project_path
            )
            pro_file_list.append(files_list)
            project_diagnostics[project_name] = diagnostics
        
        self.pro_file_list = pro_file_list
        self.last_scan_diagnostics = {
            "extensions": sorted(self.CPP_EXTENSIONS),
            "excluded_directory_names": sorted(self.EXCLUDED_DIRECTORY_NAMES),
            "excluded_directory_prefixes": list(
                self.EXCLUDED_DIRECTORY_PREFIXES
            ),
            "projects": project_diagnostics,
            "summary": {
                "project_count": len(self.projects),
                "selected_file_count": sum(
                    len(files) for files in pro_file_list
                ),
                "excluded_directory_count": sum(
                    int(value["excluded_directory_count"])
                    for value in project_diagnostics.values()
                ),
                "excluded_test_file_count": sum(
                    int(value["excluded_test_file_count"])
                    for value in project_diagnostics.values()
                ),
                "excluded_generated_file_count": sum(
                    int(value["excluded_generated_file_count"])
                    for value in project_diagnostics.values()
                ),
                "excluded_symlink_count": sum(
                    int(value["excluded_symlink_count"])
                    for value in project_diagnostics.values()
                ),
                "excluded_path_escape_count": sum(
                    int(value["excluded_path_escape_count"])
                    for value in project_diagnostics.values()
                ),
            },
        }
        return pro_file_list

    def _files_from_manifest(self, manifest_path: Path) -> List[List[str]]:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        corpus = manifest["corpus"]
        groups = manifest["projects" if corpus == "project" else "targets"]
        selected = {group["name"]: group for group in groups}
        project_files: List[List[str]] = []
        diagnostics: Dict[str, Any] = {}
        self.file_splits = {}

        for project in self.projects:
            root = self.base_path / project
            client_dirs = (
                {path.name.lower(): path.name for path in root.iterdir() if path.is_dir()}
                if corpus == "library"
                else {}
            )
            paths: List[str] = []
            splits: Dict[str, str] = {}
            for record in selected[project]["files"]:
                if corpus == "project":
                    relative = Path(record["path"])
                else:
                    client = client_dirs[record["repository"].replace("/", "__").lower()]
                    relative = Path(client) / record["path"]
                path = root / relative
                if not path.is_file():
                    raise FileNotFoundError(path)
                relative_posix = relative.as_posix()
                paths.append(str(path))
                splits[relative_posix] = record["split"]
            project_files.append(paths)
            self.file_splits[project] = splits
            diagnostics[project] = {
                "selected_file_count": len(paths),
                "excluded_directory_count": 0,
                "excluded_test_file_count": 0,
                "excluded_generated_file_count": 0,
                "excluded_symlink_count": 0,
                "excluded_path_escape_count": 0,
                "excluded_directories": [],
                "excluded_files": [],
            }

        self.pro_file_list = project_files
        self.last_scan_diagnostics = {
            "source": manifest_path.as_posix(),
            "projects": diagnostics,
            "summary": {
                "project_count": len(self.projects),
                "selected_file_count": sum(map(len, project_files)),
                "excluded_directory_count": 0,
                "excluded_test_file_count": 0,
                "excluded_generated_file_count": 0,
                "excluded_symlink_count": 0,
                "excluded_path_escape_count": 0,
            },
        }
        return project_files
    
    def _scan_project_files(self, project_path: str) -> List[str]:
        """
        扫描单个项目目录下的所有源代码文件
        
        Args:
            project_path: 项目路径
            
        Returns:
            文件路径列表
        """
        files, _ = self._scan_project_files_with_diagnostics(project_path)
        return files

    def _scan_project_files_with_diagnostics(
        self,
        project_path: str,
    ) -> tuple[List[str], Dict[str, Any]]:
        project_root = Path(project_path).resolve(strict=True)
        files_list: List[tuple[str, str]] = []
        diagnostics: Dict[str, Any] = {
            "selected_file_count": 0,
            "excluded_directory_count": 0,
            "excluded_test_file_count": 0,
            "excluded_generated_file_count": 0,
            "excluded_symlink_count": 0,
            "excluded_path_escape_count": 0,
            "excluded_directories": [],
            "excluded_files": [],
        }

        for root, dirs, files in os.walk(project_root, followlinks=False):
            root_path = Path(root)
            retained_dirs = []
            for directory_name in sorted(dirs):
                directory_path = root_path / directory_name
                reason = self._excluded_directory_reason(
                    directory_path, project_root
                )
                if reason is None:
                    retained_dirs.append(directory_name)
                    continue
                diagnostics["excluded_directory_count"] += 1
                if reason == "symlink":
                    diagnostics["excluded_symlink_count"] += 1
                elif reason == "path_escape":
                    diagnostics["excluded_path_escape_count"] += 1
                diagnostics["excluded_directories"].append(
                    {
                        "path": self._display_relative(
                            directory_path, project_root
                        ),
                        "reason": reason,
                    }
                )
            dirs[:] = retained_dirs

            for file_name in sorted(files):
                file_path = root_path / file_name
                if file_path.suffix.lower() not in self.CPP_EXTENSIONS:
                    continue
                reason = self._excluded_file_reason(file_path, project_root)
                if reason is not None:
                    if reason == "test-file":
                        diagnostics["excluded_test_file_count"] += 1
                    elif reason == "generated-file":
                        diagnostics["excluded_generated_file_count"] += 1
                    elif reason == "symlink":
                        diagnostics["excluded_symlink_count"] += 1
                    elif reason == "path_escape":
                        diagnostics["excluded_path_escape_count"] += 1
                    diagnostics["excluded_files"].append(
                        {
                            "path": self._display_relative(
                                file_path, project_root
                            ),
                            "reason": reason,
                        }
                    )
                    continue
                relative_path = file_path.relative_to(project_root).as_posix()
                files_list.append((relative_path, str(file_path)))

        files_list.sort(key=lambda value: value[0])
        diagnostics["selected_file_count"] = len(files_list)
        diagnostics["excluded_directories"].sort(
            key=lambda value: (value["path"], value["reason"])
        )
        diagnostics["excluded_files"].sort(
            key=lambda value: (value["path"], value["reason"])
        )
        return [file_path for _, file_path in files_list], diagnostics

    def _excluded_directory_reason(
        self,
        path: Path,
        project_root: Path,
    ) -> str | None:
        if path.is_symlink():
            return "symlink"
        name = path.name.lower()
        if name.startswith("."):
            return "hidden-directory"
        if (
            name in self.EXCLUDED_DIRECTORY_NAMES
            or any(name.startswith(prefix) for prefix in self.EXCLUDED_DIRECTORY_PREFIXES)
        ):
            return "excluded-directory"
        try:
            path.resolve(strict=True).relative_to(project_root)
        except (FileNotFoundError, ValueError):
            return "path_escape"
        return None

    def _excluded_file_reason(
        self,
        path: Path,
        project_root: Path,
    ) -> str | None:
        if path.is_symlink():
            return "symlink"
        try:
            path.resolve(strict=True).relative_to(project_root)
        except (FileNotFoundError, ValueError):
            return "path_escape"
        stem_tokens = {
            token
            for token in re.split(r"[^a-z0-9]+", path.stem.lower())
            if token
        }
        if stem_tokens & {"test", "tests", "unittest", "unittests"}:
            return "test-file"
        if any(pattern.search(path.name) for pattern in self.GENERATED_FILE_PATTERNS):
            return "generated-file"
        return None

    def _display_relative(self, path: Path, project_root: Path) -> str:
        try:
            return path.relative_to(project_root).as_posix()
        except ValueError:
            return path.as_posix()

    def repository_relative_path(
        self,
        project_name: str,
        file_path: str,
    ) -> str:
        """返回仓库相对 POSIX ID；越界路径直接失败。"""
        if self.base_path is None:
            raise RuntimeError("尚未初始化扫描根目录")
        project_root = (self.base_path / project_name).resolve(strict=True)
        return (
            Path(file_path)
            .resolve(strict=True)
            .relative_to(project_root)
            .as_posix()
        )
    
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
        pro_splits = []
        
        for i in range(len(self.projects)):
            pro_files_ = []
            pro_funcs_ = []
            pro_funcs_src_ = []
            pro_splits_ = []
            
            for j in range(len(func_asts[i])):
                if func_asts[i][j] is not None and len(func_asts[i][j]) != 0:
                    relative_path = self.repository_relative_path(
                        self.projects[i],
                        self.pro_file_list[i][j],
                    )
                    pro_files_.append(relative_path)
                    pro_funcs_.append(func_asts[i][j])
                    pro_funcs_src_.append(func_srcs[i][j])
                    pro_splits_.append(
                        self.file_splits.get(self.projects[i], {}).get(
                            relative_path,
                            "train",
                        )
                    )
            
            pro_files.append(pro_files_)
            pro_funcs.append(pro_funcs_)
            pro_funcs_src.append(pro_funcs_src_)
            pro_splits.append(pro_splits_)
        
        return pro_files, pro_funcs, pro_funcs_src, pro_splits
