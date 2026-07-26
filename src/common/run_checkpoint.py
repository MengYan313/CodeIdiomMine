"""长时批处理的可选 SQLite 断点续跑存储。"""

from __future__ import annotations

import json
import pickle
import sqlite3
from pathlib import Path
from typing import Any, Mapping


class RunCheckpoint:
    """按稳定位置保存 Python 结果；元数据不一致时拒绝错误续跑。"""

    def __init__(
        self,
        path: str | Path,
        *,
        metadata: Mapping[str, Any],
        resume: bool,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        if existed and not resume:
            raise FileExistsError(
                f"checkpoint 已存在: {self.path}；请使用 --resume 或更换路径"
            )
        if not existed and resume:
            raise FileNotFoundError(f"无法续跑，checkpoint 不存在: {self.path}")

        self._connection = sqlite3.connect(self.path)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS records "
            "(position INTEGER PRIMARY KEY, payload BLOB NOT NULL)"
        )
        normalized = json.dumps(
            dict(metadata),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if existed:
            row = self._connection.execute(
                "SELECT value FROM metadata WHERE key = 'run'"
            ).fetchone()
            if row is None or str(row[0]) != normalized:
                self._connection.close()
                raise ValueError("checkpoint 元数据与当前输入或运行配置不一致")
        else:
            self._connection.execute(
                "INSERT INTO metadata(key, value) VALUES('run', ?)",
                (normalized,),
            )
            self._connection.commit()

    def load_records(self) -> dict[int, Any]:
        return {
            int(position): pickle.loads(payload)
            for position, payload in self._connection.execute(
                "SELECT position, payload FROM records ORDER BY position"
            )
        }

    def save_record(self, position: int, value: Any) -> None:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        self._connection.execute(
            "INSERT OR REPLACE INTO records(position, payload) VALUES(?, ?)",
            (int(position), payload),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "RunCheckpoint":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
