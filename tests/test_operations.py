from cursor_chat_tool import operations, storage


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
    sorted_ids = [w.identifier.id for w in ws_list]
    assert sorted_ids.index("ws-epsilon") < sorted_ids.index("ws-alpha")


def test_list_chats_for_workspace_sorted_desc(minimal_db):
    from cursor_chat_tool import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chats = operations.list_chats(s, "ws-alpha")
    assert [c.composer_id for c in chats] == ["c-alpha-2", "c-alpha-1"]
    assert chats[0].bubble_count_hint == 1
    assert chats[1].bubble_count_hint == 2


def test_list_chats_limit(minimal_db):
    from cursor_chat_tool import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chats = operations.list_chats(s, "ws-alpha", limit=1)
    assert len(chats) == 1


def test_load_chat_parses_bubbles(minimal_db):
    from cursor_chat_tool import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chat = operations.load_chat(s, "c-alpha-1")
    assert chat.header.composer_id == "c-alpha-1"
    assert len(chat.bubbles) == 2
    assert chat.bubbles[0].role == "user"
    assert chat.bubbles[1].role == "assistant"
    assert chat.bubbles[1].text == "Hi there"


def test_export_chat_markdown(minimal_db):
    from cursor_chat_tool import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chat = operations.load_chat(s, "c-alpha-1")
    out = operations.export_chat(chat, fmt="markdown")
    assert "# Alpha chat 1" in out
    assert "## USER" in out
    assert "Hi there" in out


def test_export_chat_json(minimal_db):
    import json as _json

    from cursor_chat_tool import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        chat = operations.load_chat(s, "c-alpha-1")
    out = operations.export_chat(chat, fmt="json")
    parsed = _json.loads(out)
    assert parsed["composer_id"] == "c-alpha-1"
    assert len(parsed["bubbles"]) == 2
