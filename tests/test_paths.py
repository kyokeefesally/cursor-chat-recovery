import pytest

from cursor_chat_recovery import paths


def test_decode_ssh_remote_host():
    auth = "ssh-remote+7b22686f73744e616d65223a22616c636964227d"
    assert paths.decode_ssh_remote_host(auth) == "alcid"

def test_decode_ssh_remote_host_invalid():
    assert paths.decode_ssh_remote_host("not-ssh-remote") is None
    assert paths.decode_ssh_remote_host("ssh-remote+zz") is None

def test_locate_cursor_dirs_windows(monkeypatch, tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"
    (appdata / "Cursor" / "User" / "globalStorage").mkdir(parents=True)
    (appdata / "Cursor" / "User" / "workspaceStorage").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(paths.sys, "platform", "win32")
    loc = paths.locate_cursor_dirs()
    assert loc.global_storage_db.name == "state.vscdb"
    assert loc.workspace_storage_dir.name == "workspaceStorage"

def test_locate_cursor_dirs_macos(monkeypatch, tmp_path):
    home = tmp_path
    (home / "Library/Application Support/Cursor/User/globalStorage").mkdir(parents=True)
    (home / "Library/Application Support/Cursor/User/workspaceStorage").mkdir(parents=True)
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    loc = paths.locate_cursor_dirs()
    assert "Library/Application Support/Cursor" in loc.global_storage_db.as_posix()

def test_locate_cursor_dirs_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "nope"))
    monkeypatch.setattr(paths.sys, "platform", "win32")
    with pytest.raises(paths.CursorNotFound):
        paths.locate_cursor_dirs()
