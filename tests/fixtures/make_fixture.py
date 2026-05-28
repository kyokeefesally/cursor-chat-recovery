"""Generate synthetic state.vscdb fixtures for tests. Run manually when fixtures need refresh.

Usage:
    python tests/fixtures/make_fixture.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

FIXTURES = Path(__file__).parent


def make_header(composer_id, name, created_ms, ws_id, ws_uri=None, ws_config_path=None):
    wid = {"id": ws_id}
    if ws_config_path:
        wid["configPath"] = {
            "external": f"file:///{ws_config_path.replace(chr(92), '/')}",
            "scheme": "file",
            "path": "/" + ws_config_path.replace("\\", "/"),
        }
    elif ws_uri:
        wid["uri"] = {"external": ws_uri, "scheme": ws_uri.split("://")[0]}
    return {
        "type": "head",
        "composerId": composer_id,
        "name": name,
        "createdAt": created_ms,
        "lastUpdatedAt": created_ms + 1000,
        "unifiedMode": "agent",
        "forceMode": "edit",
        "isArchived": False,
        "isDraft": False,
        "subtitle": f"Subtitle for {name}",
        "workspaceIdentifier": wid,
    }


def make_bubble(bubble_id, kind, text, ts_ms):
    # kind: 1=user, 2=assistant in Cursor's encoding
    return {
        "bubbleId": bubble_id,
        "type": kind,
        "text": text,
        "createdAt": ts_ms,
    }


def write_db(path: Path, headers: list[dict], composer_to_bubbles: dict[str, list[dict]]):
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    con.execute(
        "INSERT INTO ItemTable VALUES (?, ?)",
        ("composer.composerHeaders", json.dumps({"allComposers": headers})),
    )
    for cid, bubbles in composer_to_bubbles.items():
        composer_data = {
            "composerId": cid,
            "conversation": [b["bubbleId"] for b in bubbles],
            "createdAt": bubbles[0]["createdAt"] if bubbles else 0,
        }
        con.execute(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            (f"composerData:{cid}", json.dumps(composer_data)),
        )
        for b in bubbles:
            con.execute(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                (f"bubbleId:{cid}:{b['bubbleId']}", json.dumps(b)),
            )
    con.commit()
    con.close()


def make_minimal():
    """3 workspaces: alpha (ok, 2 chats), beta (obsolete, 1 chat), gamma (orphan, 1 chat).
    Plus one empty-storage workspace dir (delta) with no headers.
    Plus one Untitled workspace pointing at a config path that won't exist (epsilon)."""
    headers = [
        make_header("c-alpha-1", "Alpha chat 1", 1_700_000_000_000, "ws-alpha",
                    ws_uri="file:///tmp/alpha"),
        make_header("c-alpha-2", "Alpha chat 2", 1_700_000_100_000, "ws-alpha",
                    ws_uri="file:///tmp/alpha"),
        make_header("c-beta-1", "Beta chat", 1_700_000_200_000, "ws-beta",
                    ws_uri="file:///tmp/beta"),
        make_header("c-gamma-1", "Gamma orphan chat", 1_700_000_300_000, "ws-gamma",
                    ws_uri="file:///tmp/gamma"),
        make_header("c-epsilon-1", "Untitled chat", 1_700_000_400_000, "ws-epsilon",
                    ws_config_path="Workspaces/1700000000000/workspace.json"),
    ]
    bubbles = {
        "c-alpha-1": [
            make_bubble("b1", 1, "Hello", 1_700_000_000_000),
            make_bubble("b2", 2, "Hi there", 1_700_000_001_000),
        ],
        "c-alpha-2": [make_bubble("b3", 1, "Q", 1_700_000_100_000)],
        "c-beta-1": [make_bubble("b4", 1, "B", 1_700_000_200_000)],
        "c-gamma-1": [make_bubble("b5", 1, "G", 1_700_000_300_000)],
        "c-epsilon-1": [make_bubble("b6", 1, "E", 1_700_000_400_000)],
    }
    write_db(FIXTURES / "globalStorage_minimal.vscdb", headers, bubbles)

    ws_root = FIXTURES / "workspaceStorage"
    if ws_root.exists():
        shutil.rmtree(ws_root)
    for ws_id in ["ws-alpha", "ws-beta", "ws-delta"]:
        (ws_root / ws_id).mkdir(parents=True)
        (ws_root / ws_id / "state.vscdb").write_bytes(b"")
    (ws_root / "ws-beta" / "obsolete").write_text("")
    (ws_root / "ws-epsilon").mkdir()
    (ws_root / "ws-epsilon" / "state.vscdb").write_bytes(b"")


def make_schema_drift():
    """Same shape but composerId renamed to composerID — exercises mismatch detection."""
    headers = [{
        "type": "head",
        "composerID": "c-drift",
        "createdAt": 1_700_000_000_000,
        "workspaceIdentifier": {"id": "ws-drift"},
    }]
    write_db(FIXTURES / "globalStorage_schema_drift.vscdb", headers, {})


def make_corrupt():
    """Missing tables entirely."""
    path = FIXTURES / "globalStorage_corrupt.vscdb"
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE wrong_table (k TEXT)")
    con.commit()
    con.close()


if __name__ == "__main__":
    make_minimal()
    make_schema_drift()
    make_corrupt()
    print("Fixtures written to", FIXTURES)
