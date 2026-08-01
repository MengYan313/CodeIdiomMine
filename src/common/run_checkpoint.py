"""长时批处理的可选 SQLite 断点续跑存储。"""

from __future__ import annotations

import pickle
import sqlite3
from pathlib import Path
from typing import Any


class RunCheckpoint:
    """按输入位置保存批处理结果。"""

    def __init__(
        self,
        path: str | Path,
        *,
        resume: bool = False,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS records "
            "(position INTEGER PRIMARY KEY, payload BLOB NOT NULL)"
        )
        if not resume:
            self._connection.execute("DELETE FROM records")
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
