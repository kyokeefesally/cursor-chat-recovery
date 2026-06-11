"""OS-specific Cursor data locations and URI helpers."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


class CursorNotFound(Exception):
    """Raised when Cursor's data directory cannot be located."""


@dataclass(frozen=True)
class CursorLocation:
    data_dir: Path
    global_storage_db: Path
    workspace_storage_dir: Path
    workspaces_dir: Path


def locate_cursor_dirs() -> CursorLocation:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise CursorNotFound("APPDATA env var not set")
        data_dir = Path(appdata) / "Cursor"
    elif sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / "Cursor"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        data_dir = (Path(xdg) if xdg else Path.home() / ".config") / "Cursor"

    user_dir = data_dir / "User"
    global_db = user_dir / "globalStorage" / "state.vscdb"
    ws_dir = user_dir / "workspaceStorage"
    workspaces_dir = data_dir / "Workspaces"

    if not user_dir.exists():
        raise CursorNotFound(f"Cursor user dir not found at {user_dir}")
    return CursorLocation(
        data_dir=data_dir,
        global_storage_db=global_db,
        workspace_storage_dir=ws_dir,
        workspaces_dir=workspaces_dir,
    )


def decode_ssh_remote_host(authority: str | None) -> str | None:
    """ssh-remote+<hex of JSON {hostName: ...}> -> 'hostName' or None."""
    if not authority or not authority.startswith("ssh-remote+"):
        return None
    hex_blob = authority[len("ssh-remote+"):]
    try:
        raw = bytes.fromhex(hex_blob).decode("utf-8")
        obj = json.loads(raw)
        host: str | None = obj.get("hostName")
        return host
    except (ValueError, json.JSONDecodeError):
        return None
