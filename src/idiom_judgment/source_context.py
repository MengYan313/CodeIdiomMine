"""阶段3/4共享的只读、哈希校验源码范围加载。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping


def _extent_lines(extent: str) -> tuple[int, int] | None:
    parts = str(extent).split("-")
    if len(parts) != 4:
        return None
    try:
        start_line, _, end_line, _ = map(int, parts)
    except ValueError:
        return None
    if start_line < 1 or end_line < start_line:
        return None
    return start_line, end_line


def representative_source_identity(
    project: str,
    representative_info: Any,
) -> tuple[str, str, str] | None:
    """返回严格的仓库、文件和函数/区域范围身份。"""

    if (
        not isinstance(representative_info, (list, tuple))
        or len(representative_info) < 4
    ):
        return None
    info_project, relative_path, extent, _ = representative_info[:4]
    if str(info_project) != str(project) or _extent_lines(str(extent)) is None:
        return None
    return str(info_project), str(relative_path), str(extent)


def representative_source_sha256(representative_info: Any) -> str:
    if (
        not isinstance(representative_info, (list, tuple))
        or len(representative_info) < 4
        or not isinstance(representative_info[3], Mapping)
    ):
        return ""
    return str(representative_info[3].get("source_sha256") or "")


def _project_root(source_root: Path, project: str) -> Path:
    nested = source_root / project
    return nested if nested.is_dir() else source_root


def load_verified_source_context(
    *,
    project: str,
    representative_info: Any,
    source_root: str | Path | None,
    max_lines: int = 300,
    max_chars: int = 12000,
) -> tuple[str, dict[str, Any]]:
    """读取代表函数/区域；任何身份、路径、哈希或预算问题都安全返回空上下文。"""

    evidence: dict[str, Any] = {
        "mode": "automatic_verified_source_extent",
        "required": False,
        "available": False,
        "verified": False,
        "failure_kind": "",
        "char_count": 0,
        "line_count": 0,
    }
    if source_root is None:
        evidence["failure_kind"] = "source_root_not_supplied"
        return "", evidence

    identity = representative_source_identity(project, representative_info)
    if identity is None:
        evidence["failure_kind"] = "invalid_source_identity"
        return "", evidence
    info_project, relative_path, extent_text = identity
    evidence["source_identity"] = {
        "project": info_project,
        "relative_path": relative_path,
        "extent": extent_text,
    }

    expected_hash = representative_source_sha256(representative_info)
    if not expected_hash:
        evidence["failure_kind"] = "source_hash_missing"
        return "", evidence

    root = _project_root(Path(source_root).resolve(), project)
    file_path = (root / relative_path).resolve()
    try:
        file_path.relative_to(root)
    except ValueError:
        evidence["failure_kind"] = "source_path_escape"
        return "", evidence
    if not file_path.is_file():
        evidence["failure_kind"] = "source_file_missing"
        return "", evidence

    raw = file_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_hash:
        evidence["failure_kind"] = "source_hash_mismatch"
        return "", evidence

    extent = _extent_lines(extent_text)
    if extent is None:
        evidence["failure_kind"] = "invalid_source_extent"
        return "", evidence
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    start, end = extent
    if end > len(lines):
        evidence["failure_kind"] = "source_extent_out_of_bounds"
        return "", evidence
    if end - start + 1 > max_lines:
        evidence["failure_kind"] = "source_line_budget_exceeded"
        return "", evidence

    selected = "\n".join(lines[start - 1 : end])
    if len(selected) > max_chars:
        evidence["failure_kind"] = "source_char_budget_exceeded"
        return "", evidence
    evidence.update(
        {
            "available": True,
            "verified": True,
            "failure_kind": "",
            "source_sha256": digest,
            "char_count": len(selected),
            "line_count": end - start + 1,
        }
    )
    return selected, evidence
