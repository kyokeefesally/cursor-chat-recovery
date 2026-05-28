import pytest

from cursor_chat_tool import storage


def test_open_readonly(minimal_db):
    s = storage.Storage.open_readonly(minimal_db)
    headers = s.read_headers()
    assert len(headers["allComposers"]) == 5
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
