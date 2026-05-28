import sqlite3

from cursor_chat_tool import schema


def _ro(db):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def test_minimal_db_passes(minimal_db):
    con = _ro(minimal_db)
    report = schema.detect_mismatch(con)
    assert report.ok
    assert report.missing == []
    assert report.schema_version == schema.SCHEMA_VERSION


def test_drift_db_flags_missing_field(drift_db):
    con = _ro(drift_db)
    report = schema.detect_mismatch(con)
    assert not report.ok
    assert any("composerId" in m for m in report.missing)


def test_corrupt_db_flags_missing_tables(corrupt_db):
    con = _ro(corrupt_db)
    report = schema.detect_mismatch(con)
    assert not report.ok
    assert any("ItemTable" in m or "cursorDiskKV" in m for m in report.missing)


def test_agent_prompt_includes_diff(drift_db):
    con = _ro(drift_db)
    report = schema.detect_mismatch(con)
    prompt = schema.agent_prompt(report)
    assert schema.SCHEMA_VERSION in prompt
    assert "composerId" in prompt
    assert "schema.py" in prompt
