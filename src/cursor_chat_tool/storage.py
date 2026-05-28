"""SQLite I/O for globalStorage state.vscdb. Read-only here; mutation in a later task."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ReadOnlyViolation(Exception):
    """Raised when a write is attempted on a read-only Storage handle."""


@dataclass
class Storage:
    db_path: Path
    _con: sqlite3.Connection
    _readonly: bool

    @classmethod
    def open_readonly(cls, db_path: Path) -> Storage:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
        return cls(db_path=Path(db_path), _con=con, _readonly=True)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._con

    @property
    def readonly(self) -> bool:
        return self._readonly

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def read_headers(self) -> dict[str, Any]:
        row = self._con.execute(
            "SELECT value FROM ItemTable WHERE key='composer.composerHeaders'"
        ).fetchone()
        if not row:
            return {"allComposers": []}
        return json.loads(row[0])  # type: ignore[no-any-return]

    def read_kv(self, key: str) -> dict[str, Any] | None:
        row = self._con.execute(
            "SELECT value FROM cursorDiskKV WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def read_kv_by_prefix(self, prefix: str) -> list[tuple[str, dict[str, Any]]]:
        rows = self._con.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE ?",
            (prefix + "%",),
        ).fetchall()
        return [(str(k), json.loads(v)) for k, v in rows]

    def count_kv_by_prefix(self, prefix: str) -> int:
        row = self._con.execute(
            "SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE ?",
            (prefix + "%",),
        ).fetchone()
        return int(row[0])

    def write_headers(self, _headers: dict[str, Any]) -> None:
        if self._readonly:
            raise ReadOnlyViolation("write_headers called on read-only Storage")
        raise NotImplementedError
