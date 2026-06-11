from datetime import datetime

from cursor_chat_recovery import operations, storage
from cursor_chat_recovery.model import WorkspaceIdentifier


def test_coerce_ts_handles_int_str_iso_and_missing():
    # epoch-ms int
    assert operations._coerce_ts(1_700_000_000_000) == datetime.fromtimestamp(1_700_000_000)
    # epoch-ms numeric string
    assert operations._coerce_ts("1700000000000") == datetime.fromtimestamp(1_700_000_000)
    # ISO string
    assert operations._coerce_ts("2026-05-01T12:00:00") == datetime(2026, 5, 1, 12, 0, 0)
    # missing / empty / unparseable → None
    assert operations._coerce_ts(None) is None
    assert operations._coerce_ts("") is None
    assert operations._coerce_ts("not-a-date") is None


def test_parse_bubble_tolerates_string_and_missing_timestamp():
    # real Cursor bubbles sometimes store createdAt as a string or omit it entirely
    b_str = operations._parse_bubble(
        "bubbleId:c:x", {"type": 1, "text": "hi", "createdAt": "1700000000000"}
    )
    assert b_str.role == "user"
    assert b_str.created_at == datetime.fromtimestamp(1_700_000_000)
    b_missing = operations._parse_bubble("bubbleId:c:y", {"type": 2, "text": "yo"})
    assert b_missing.role == "assistant"
    assert b_missing.created_at is None


def test_display_name_special_cases():
    ew = WorkspaceIdentifier(id="empty-window", uri=None, scheme=None,
                             is_remote=False, remote_host=None, config_path=None)
    assert operations._display_name(ew) == "No folder (empty window)"
    bare = WorkspaceIdentifier(id="1778227613463", uri=None, scheme=None,
                               is_remote=False, remote_host=None, config_path=None)
    assert operations._display_name(bare) == "1778227613463"


def test_list_workspaces_classifies_health(minimal_db, workspace_storage_dir):
    with storage.Storage.open_readonly(minimal_db) as s:
        ws_list = operations.list_workspaces(
            s, workspace_storage_dir,
            workspaces_config_dir=workspace_storage_dir.parent / "Workspaces",
        )
    by_id = {w.identifier.id: w for w in ws_list}
    assert by_id["ws-alpha"].chat_count == 2
    assert by_id["ws-alpha"].health == "ok"
    assert by_id["ws-beta"].health == "obsolete"
    assert by_id["ws-gamma"].health == "orphan"
    assert by_id["ws-delta"].health == "empty-storage"
    assert by_id["ws-epsilon"].health == "config-missing"
    # Remote (vscode-remote) configPath can't be stat'd locally → never flagged missing
    assert by_id["ws-remote"].health == "ok"
    assert by_id["ws-remote"].identifier.is_remote is True
    sorted_ids = [w.identifier.id for w in ws_list]
    assert sorted_ids.index("ws-epsilon") < sorted_ids.index("ws-alpha")


def test_list_chats_for_workspace_sorted_desc(minimal_db):
    from cursor_chat_recovery import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chats = operations.list_chats(s, "ws-alpha")
    assert [c.composer_id for c in chats] == ["c-alpha-2", "c-alpha-1"]
    assert chats[0].bubble_count_hint == 1
    assert chats[1].bubble_count_hint == 2


def test_list_chats_limit(minimal_db):
    from cursor_chat_recovery import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chats = operations.list_chats(s, "ws-alpha", limit=1)
    assert len(chats) == 1


def test_load_chat_parses_bubbles(minimal_db):
    from cursor_chat_recovery import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chat = operations.load_chat(s, "c-alpha-1")
    assert chat.header.composer_id == "c-alpha-1"
    assert len(chat.bubbles) == 2
    assert chat.bubbles[0].role == "user"
    assert chat.bubbles[1].role == "assistant"
    assert chat.bubbles[1].text == "Hi there"


def test_export_chat_markdown(minimal_db):
    from cursor_chat_recovery import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chat = operations.load_chat(s, "c-alpha-1")
    out = operations.export_chat(chat, fmt="markdown")
    assert "# Alpha chat 1" in out
    assert "## USER" in out
    assert "Hi there" in out


def test_export_chat_json(minimal_db):
    import json as _json

    from cursor_chat_recovery import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chat = operations.load_chat(s, "c-alpha-1")
    out = operations.export_chat(chat, fmt="json")
    parsed = _json.loads(out)
    assert parsed["composer_id"] == "c-alpha-1"
    assert len(parsed["bubbles"]) == 2


def test_reassign_chats_moves_headers(minimal_db, tmp_path):
    import shutil

    from cursor_chat_recovery import operations, storage
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    backup_dir = tmp_path / "backups"
    s = storage.Storage.open_rw(work, backup_dir=backup_dir, cursor_running_check=lambda: False)
    s.ensure_session_backup()
    res = operations.reassign_chats(s, ["c-alpha-1"], target_ws_id="ws-beta")
    s.close()
    assert res.composer_ids == ["c-alpha-1"]
    assert res.to_workspace_id == "ws-beta"

    s2 = storage.Storage.open_readonly(work)
    h = next(x for x in s2.read_headers()["allComposers"] if x["composerId"] == "c-alpha-1")
    assert h["workspaceIdentifier"]["id"] == "ws-beta"
    s2.close()


def test_reassign_roundtrip_identity(minimal_db, tmp_path):
    import json
    import shutil
    from pathlib import Path

    from cursor_chat_recovery import operations, storage
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    backup_dir = tmp_path / "backups"
    s = storage.Storage.open_rw(work, backup_dir=backup_dir, cursor_running_check=lambda: False)
    s.ensure_session_backup()
    original = s.read_headers()
    res = operations.reassign_chats(s, ["c-alpha-1"], target_ws_id="ws-beta")
    backup = json.loads(Path(res.backup_path).read_text(encoding="utf-8"))
    s.write_headers(backup, op_label="undo")
    s.close()
    s2 = storage.Storage.open_readonly(work)
    restored = s2.read_headers()
    s2.close()
    assert restored == original


def test_merge_workspaces_moves_all_chats(minimal_db, tmp_path):
    import shutil

    from cursor_chat_recovery import operations, storage

    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    backup_dir = tmp_path / "backups"
    s = storage.Storage.open_rw(work, backup_dir=backup_dir, cursor_running_check=lambda: False)
    s.ensure_session_backup()
    res = operations.merge_workspaces(s, source_ws_id="ws-alpha", target_ws_id="ws-beta")
    s.close()
    assert res.chats_moved == 2

    s2 = storage.Storage.open_readonly(work)
    headers = s2.read_headers()["allComposers"]
    alpha_count = sum(
        1 for h in headers
        if (h.get("workspaceIdentifier") or {}).get("id") == "ws-alpha"
    )
    beta_count = sum(
        1 for h in headers
        if (h.get("workspaceIdentifier") or {}).get("id") == "ws-beta"
    )
    s2.close()
    assert alpha_count == 0
    assert beta_count == 3


def test_list_chats_issues_constant_queries(minimal_db, workspace_storage_dir):
    """Bubble counts must come from ONE grouped query, not one scan per chat."""
    from cursor_chat_recovery import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        calls: list[str] = []
        real_execute = s._con.execute

        def spy(sql, *a, **k):
            calls.append(sql)
            return real_execute(sql, *a, **k)

        s._con.execute = spy  # type: ignore[method-assign]
        chats = operations.list_chats(s, "ws-alpha")
        assert len(chats) >= 2
        kv_queries = [q for q in calls if "cursorDiskKV" in q]
        assert len(kv_queries) == 1
        # counts still correct
        by_id = {c.composer_id: c.bubble_count_hint for c in chats}
        assert by_id["c-alpha-1"] and by_id["c-alpha-1"] > 0
