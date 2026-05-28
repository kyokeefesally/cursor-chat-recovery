"""Mutation actions invoked by the TUI, separated so they are unit-testable."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

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
