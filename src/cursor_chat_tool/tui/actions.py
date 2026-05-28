"""Mutation actions invoked by the TUI, separated so they are unit-testable."""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

from cursor_chat_tool import operations, storage
from cursor_chat_tool.model import ReassignResult


def perform_reassign(
    global_db: Path,
    backup_dir: Path,
    composer_ids: list[str],
    target_ws_id: str,
    cursor_running_check: Callable[[], bool] = storage._default_cursor_running_check,
) -> ReassignResult:
    s = storage.Storage.open_rw(
        global_db, backup_dir=backup_dir, cursor_running_check=cursor_running_check
    )
    try:
        s.ensure_session_backup()
        return operations.reassign_chats(s, composer_ids, target_ws_id=target_ws_id)
    finally:
        s.close()


def export_chats(
    global_db: Path,
    composer_ids: list[str],
    out_dir: Path,
    fmt: str = "markdown",
) -> list[Path]:
    """Export each chat to out_dir as <safe-name>-<short-id>.<ext>.

    Returns the written paths. Reads only, so it is safe in read-only mode.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = "json" if fmt == "json" else "md"
    written: list[Path] = []
    with storage.Storage.open_readonly(global_db) as s:
        for cid in composer_ids:
            chat = operations.load_chat(s, cid)
            name = chat.header.name or chat.header.composer_id
            safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "chat"
            path = out_dir / f"{safe}-{cid[:8]}.{ext}"
            path.write_text(
                operations.export_chat(chat, fmt=cast("Literal['markdown', 'json']", fmt)),
                encoding="utf-8",
            )
            written.append(path)
    return written
