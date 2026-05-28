import json as _json
import shutil


def test_cli_list_json(minimal_db, workspace_storage_dir, monkeypatch, capsys):
    from cursor_chat_tool import cli
    rc = cli.main([
        "--list", "--json",
        "--global-db", str(minimal_db),
        "--workspace-storage", str(workspace_storage_dir),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = _json.loads(out)
    assert any(w["id"] == "ws-alpha" for w in parsed)


def test_cli_export_to_stdout(minimal_db, workspace_storage_dir, capsys):
    from cursor_chat_tool import cli
    rc = cli.main([
        "--export", "c-alpha-1",
        "--format", "markdown",
        "--global-db", str(minimal_db),
        "--workspace-storage", str(workspace_storage_dir),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Alpha chat 1" in out


def test_cli_reassign_requires_yes(minimal_db, workspace_storage_dir, tmp_path):
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    from cursor_chat_tool import cli
    rc = cli.main([
        "--reassign", "c-alpha-1", "ws-beta",
        "--global-db", str(work),
        "--workspace-storage", str(workspace_storage_dir),
    ])
    assert rc != 0


def test_cli_reassign_with_yes(minimal_db, workspace_storage_dir, tmp_path):
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    backup_dir = tmp_path / "backups"
    from cursor_chat_tool import cli
    rc = cli.main([
        "--reassign", "c-alpha-1", "ws-beta",
        "--yes",
        "--global-db", str(work),
        "--workspace-storage", str(workspace_storage_dir),
        "--backup-dir", str(backup_dir),
        "--no-cursor-check",
    ])
    assert rc == 0
