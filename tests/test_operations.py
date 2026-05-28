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
