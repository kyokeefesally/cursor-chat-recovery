"""High-level operations over Storage. The only module that mutates."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from cursor_chat_tool.model import (
    ChatHeader,
    Workspace,
    WorkspaceIdentifier,
)
from cursor_chat_tool.paths import decode_ssh_remote_host
from cursor_chat_tool.storage import Storage


def _parse_workspace_identifier(raw: dict[str, Any]) -> WorkspaceIdentifier:
    wid_id = raw.get("id", "")
    config = raw.get("configPath") or {}
    uri_obj = raw.get("uri") or {}
    config_external = config.get("external")
    uri_external = uri_obj.get("external")
    external = config_external or uri_external
    scheme = (config.get("scheme") or uri_obj.get("scheme"))
    is_remote = scheme == "vscode-remote"
    authority = uri_obj.get("authority") or config.get("authority")
    return WorkspaceIdentifier(
        id=str(wid_id),
        uri=external,
        scheme=scheme,
        is_remote=is_remote,
        remote_host=decode_ssh_remote_host(authority),
        config_path=config_external,
    )


def _display_name(ident: WorkspaceIdentifier) -> str:
    if ident.config_path and "Workspaces/" in ident.config_path:
        ts = ident.config_path.rstrip("/").split("/")[-2] if "/" in ident.config_path else "?"
        return f"Untitled ({ts})"
    if ident.uri:
        return ident.uri.rstrip("/").split("/")[-1] or ident.uri
    return f"Orphan {ident.id}"


def list_workspaces(
    storage_: Storage,
    workspace_storage_dir: Path,
    workspaces_config_dir: Path | None = None,
) -> list[Workspace]:
    headers_data = storage_.read_headers()
    all_headers = headers_data.get("allComposers", [])

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    identifiers: dict[str, WorkspaceIdentifier] = {}
    for h in all_headers:
        wid_raw = h.get("workspaceIdentifier") or {}
        ident = _parse_workspace_identifier(wid_raw)
        grouped[ident.id].append(h)
        identifiers.setdefault(ident.id, ident)

    on_disk_ids: set[str] = set()
    obsolete_ids: set[str] = set()
    if workspace_storage_dir.exists():
        for d in workspace_storage_dir.iterdir():
            if d.is_dir():
                on_disk_ids.add(d.name)
                if (d / "obsolete").exists():
                    obsolete_ids.add(d.name)

    results: list[Workspace] = []
    seen_ids: set[str] = set()

    for ws_id, hs in grouped.items():
        ident = identifiers[ws_id]
        created_ats: list[int] = [h["createdAt"] for h in hs if isinstance(h.get("createdAt"), int)]
        first = datetime.fromtimestamp(min(created_ats) / 1000) if created_ats else None
        last = datetime.fromtimestamp(max(created_ats) / 1000) if created_ats else None
        on_disk = ws_id in on_disk_ids
        is_obs = ws_id in obsolete_ids
        config_exists = True
        if ident.config_path and workspaces_config_dir is not None:
            from urllib.parse import unquote, urlparse
            p = unquote(urlparse(ident.config_path).path)
            if p.startswith("/") and len(p) > 2 and p[2] == ":":
                p = p[1:]
            config_exists = Path(p).exists()
        if not on_disk and hs:
            health = "orphan"
        elif is_obs:
            health = "obsolete"
        elif not config_exists:
            health = "config-missing"
        else:
            health = "ok"
        results.append(Workspace(
            identifier=ident,
            chat_count=len(hs),
            first_chat_at=first,
            last_chat_at=last,
            storage_dir_exists=on_disk,
            is_obsolete=is_obs,
            config_exists=config_exists,
            display_name=_display_name(ident),
            health=health,  # type: ignore[arg-type]
        ))
        seen_ids.add(ws_id)

    for ws_id in sorted(on_disk_ids - seen_ids):
        ident = WorkspaceIdentifier(id=ws_id, uri=None, scheme=None,
                                    is_remote=False, remote_host=None, config_path=None)
        results.append(Workspace(
            identifier=ident,
            chat_count=0,
            first_chat_at=None,
            last_chat_at=None,
            storage_dir_exists=True,
            is_obsolete=(ws_id in obsolete_ids),
            config_exists=True,
            display_name=_display_name(ident),
            health="empty-storage",
        ))

    results.sort(key=lambda w: w.last_chat_at or datetime.min, reverse=True)
    return results


def _parse_header(h: dict[str, Any], storage_: Storage) -> ChatHeader:
    cid = h["composerId"]
    created = datetime.fromtimestamp(int(h["createdAt"]) / 1000)
    last_updated = h.get("lastUpdatedAt")
    last_dt = datetime.fromtimestamp(int(last_updated) / 1000) if last_updated else None
    ws_id = (h.get("workspaceIdentifier") or {}).get("id", "")
    return ChatHeader(
        composer_id=cid,
        name=h.get("name"),
        created_at=created,
        last_updated_at=last_dt,
        workspace_id=str(ws_id),
        subtitle=h.get("subtitle"),
        bubble_count_hint=storage_.count_kv_by_prefix(f"bubbleId:{cid}:"),
        raw=h,
    )


def list_chats(
    storage_: Storage,
    workspace_id: str,
    limit: int | None = None,
) -> list[ChatHeader]:
    headers_data = storage_.read_headers()
    matched = [
        h for h in headers_data.get("allComposers", [])
        if (h.get("workspaceIdentifier") or {}).get("id") == workspace_id
    ]
    matched.sort(key=lambda h: h.get("lastUpdatedAt") or h.get("createdAt", 0), reverse=True)
    if limit is not None:
        matched = matched[:limit]
    return [_parse_header(h, storage_) for h in matched]
