import json
import shutil

import pytest

from cursor_chat_tool import storage


def test_open_readonly(minimal_db):
    s = storage.Storage.open_readonly(minimal_db)
    headers = s.read_headers()
    assert len(headers["allComposers"]) == 6
    s.close()


def test_open_readonly_corrupt_db_still_opens(corrupt_db):
    s = storage.Storage.open_readonly(corrupt_db)
    s.close()


def test_read_kv_by_prefix(minimal_db):
    s = storage.Storage.open_readonly(minimal_db)
    bubbles = s.read_kv_by_prefix("bubbleId:c-alpha-1:")
    assert len(bubbles) == 2
    s.close()


def test_count_kv_by_prefix(minimal_db):
    s = storage.Storage.open_readonly(minimal_db)
    assert s.count_kv_by_prefix("bubbleId:c-alpha-1:") == 2
    assert s.count_kv_by_prefix("bubbleId:nonexistent:") == 0
    s.close()


def test_readonly_rejects_writes(minimal_db):
    s = storage.Storage.open_readonly(minimal_db)
    with pytest.raises(storage.ReadOnlyViolation):
        s.write_headers({"allComposers": []})
    s.close()


def test_open_rw_creates_full_backup_once_per_session(minimal_db, tmp_path):
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    backup_dir = tmp_path / "backups"
    s = storage.Storage.open_rw(work, backup_dir=backup_dir, cursor_running_check=lambda: False)
    p1 = s.ensure_session_backup()
    p2 = s.ensure_session_backup()
    assert p1 == p2 and p1.exists()
    s.close()


def test_open_rw_refuses_if_cursor_running(minimal_db, tmp_path):
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    with pytest.raises(storage.CursorRunning):
        storage.Storage.open_rw(work, backup_dir=tmp_path / "backups",
                                cursor_running_check=lambda: True)


def test_write_headers_creates_per_op_backup_and_persists(minimal_db, tmp_path):
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    backup_dir = tmp_path / "backups"
    s = storage.Storage.open_rw(work, backup_dir=backup_dir, cursor_running_check=lambda: False)
    s.ensure_session_backup()
    before = s.read_headers()
    modified = {"allComposers": before["allComposers"][:1]}
    s.write_headers(modified, op_label="test")
    s.close()

    s2 = storage.Storage.open_readonly(work)
    after = s2.read_headers()
    assert len(after["allComposers"]) == 1
    s2.close()

    backups = list(backup_dir.glob("composerHeaders_*_test.json"))
    assert len(backups) == 1
    restored = json.loads(backups[0].read_text(encoding="utf-8"))
    assert len(restored["allComposers"]) == 6


def test_wal_checkpoint_runs_outside_txn(minimal_db, tmp_path, monkeypatch):
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    s = storage.Storage.open_rw(work, backup_dir=tmp_path / "backups",
                                cursor_running_check=lambda: False)
    s.ensure_session_backup()
    calls: list[str] = []
    real_commit = s._con.commit
    real_execute = s._con.execute

    def tracked_commit():
        calls.append("commit")
        real_commit()

    def tracked_execute(sql, *args, **kwargs):
        if "wal_checkpoint" in sql.lower():
            calls.append("checkpoint")
        return real_execute(sql, *args, **kwargs)

    monkeypatch.setattr(s._con, "commit", tracked_commit)
    monkeypatch.setattr(s._con, "execute", tracked_execute)
    s.write_headers({"allComposers": []}, op_label="checkpoint-test")
    s.close()
    assert calls.index("commit") < calls.index("checkpoint")
