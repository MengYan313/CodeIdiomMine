"""当前 Parser 数据集的 train/test 视图。"""

from __future__ import annotations

from typing import Any

import pandas as pd


FILE_COLUMNS = ("cppFile", "func_ast", "func_src", "split")


def file_indices(row: pd.Series, split: str) -> set[int]:
    return {
        index
        for index, value in enumerate(row["split"])
        if value == split
    }


def select_split(data: pd.DataFrame, split: str) -> pd.DataFrame:
    """保留每个项目指定 split 的文件及其平行字段。"""
    rows: list[dict[str, Any]] = []
    for _, row in data.iterrows():
        indices = sorted(file_indices(row, split))
        selected = row.to_dict()
        for column in FILE_COLUMNS:
            selected[column] = [row[column][index] for index in indices]
        rows.append(selected)
    return pd.DataFrame(rows, columns=data.columns)
