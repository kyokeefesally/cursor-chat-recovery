#!/usr/bin/env python3
"""Build a synthetic chat.db that mirrors the real Messages schema.

Used to exercise the reader without a Mac. Only the columns the reader touches are
recreated — the real table has ~90 columns, most of which are irrelevant here.
"""

from __future__ import annotations

import plistlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from imessage_query import datetime_to_apple_ns  # noqa: E402

SCHEMA = """
CREATE TABLE handle (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL,
    country TEXT,
    service TEXT NOT NULL,
    uncanonicalized_id TEXT
);
CREATE TABLE chat (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE NOT NULL,
    style INTEGER,
    state INTEGER,
    account_id TEXT,
    chat_identifier TEXT,
    service_name TEXT,
    room_name TEXT,
    display_name TEXT
);
CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE NOT NULL,
    text TEXT,
    handle_id INTEGER DEFAULT 0,
    service TEXT,
    date INTEGER,
    date_read INTEGER,
    is_from_me INTEGER DEFAULT 0,
    is_audio_message INTEGER DEFAULT 0,
    item_type INTEGER DEFAULT 0,
    other_handle INTEGER DEFAULT 0,
    group_title TEXT,
    group_action_type INTEGER DEFAULT 0,
    associated_message_guid TEXT,
    associated_message_type INTEGER DEFAULT 0,
    balloon_bundle_id TEXT,
    expressive_send_style_id TEXT,
    message_summary_info BLOB,
    attributedBody BLOB,
    thread_originator_guid TEXT,
    date_retracted INTEGER DEFAULT 0
);
CREATE TABLE attachment (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE NOT NULL,
    filename TEXT,
    mime_type TEXT,
    transfer_name TEXT
);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER, message_date INTEGER);
CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
"""


def encode_attributed_body(text: str) -> bytes:
    """Approximate an NSKeyedArchiver typedstream blob well enough to test decoding.

    Reproduces the part the heuristic decoder actually walks: the NSString class
    marker, a 5-byte preamble, and the length-prefixed UTF-8 payload.
    """
    payload = text.encode("utf-8")
    if len(payload) < 128:
        length_prefix = bytes([len(payload)])
    else:
        length_prefix = b"\x81" + len(payload).to_bytes(2, "little")
    return (
        b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01\x40\x84\x84\x84"
        b"NSMutableAttributedString\x00\x84\x84\x12NSAttributedString"
        b"\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84"
        b"NSString\x01\x94\x84\x01\x2b" + length_prefix + payload + b"\x86\x84\x02"
    )


def build(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    people = {
        "alex": "+15550100001",
        "ben": "+15550100002",
        "cara": "+15550100003",
        "dev": "dev@example.com",
        "erin": "+15550100005",
        "finn": "+15550100006",
    }
    handle_ids = {}
    for name, handle in people.items():
        cursor = conn.execute(
            "INSERT INTO handle (id, country, service) VALUES (?, 'us', 'iMessage')", (handle,)
        )
        handle_ids[name] = cursor.lastrowid

    group_id = conn.execute(
        """INSERT INTO chat (guid, style, chat_identifier, service_name, display_name)
           VALUES ('iMessage;+;chat9001', 43, 'chat9001', 'iMessage', 'Sierra Trip 🏔️')"""
    ).lastrowid
    solo_id = conn.execute(
        """INSERT INTO chat (guid, style, chat_identifier, service_name, display_name)
           VALUES ('iMessage;-;+15550100001', 45, '+15550100001', 'iMessage', '')"""
    ).lastrowid

    for name in people:
        conn.execute("INSERT INTO chat_handle_join VALUES (?, ?)", (group_id, handle_ids[name]))
    conn.execute("INSERT INTO chat_handle_join VALUES (?, ?)", (solo_id, handle_ids["alex"]))

    base = datetime.now(timezone.utc).astimezone() - timedelta(days=9)
    counter = {"n": 0}

    def add(chat_id, sender, text, *, offset_hours, from_me=False, use_attributed=False,
            reply_to=None, tapback=None, target=None, item_type=0, group_action=0,
            other=None, edited=False, unsent=False, attachment=None, group_title=None):
        counter["n"] += 1
        guid = f"GUID-{counter['n']:04d}"
        when = datetime_to_apple_ns(base + timedelta(hours=offset_hours))
        summary = plistlib.dumps({"ec": {"0": [{"t": b""}]}}) if edited else None
        row = conn.execute(
            """INSERT INTO message
               (guid, text, handle_id, service, date, is_from_me, item_type, other_handle,
                group_title, group_action_type, associated_message_guid,
                associated_message_type, message_summary_info, attributedBody,
                thread_originator_guid, date_retracted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                guid,
                None if use_attributed else text,
                0 if from_me else handle_ids.get(sender, 0),
                "iMessage",
                when,
                1 if from_me else 0,
                item_type,
                handle_ids.get(other, 0) if other else 0,
                group_title,
                group_action,
                f"p:0/{target}" if target else None,
                tapback or 0,
                summary,
                encode_attributed_body(text) if use_attributed else None,
                reply_to,
                when if unsent else 0,
            ),
        )
        message_id = row.lastrowid
        conn.execute(
            "INSERT INTO chat_message_join VALUES (?, ?, ?)", (chat_id, message_id, when)
        )
        if attachment:
            attachment_id = conn.execute(
                "INSERT INTO attachment (guid, filename, mime_type, transfer_name) "
                "VALUES (?, ?, ?, ?)",
                (f"ATT-{message_id}", f"~/Library/.../{attachment}", "image/jpeg", attachment),
            ).lastrowid
            conn.execute(
                "INSERT INTO message_attachment_join VALUES (?, ?)", (message_id, attachment_id)
            )
        return guid

    # A compressed stand-in for the real thing: logistics, drop-outs, a reply
    # thread, tapbacks, an edit, an unsend, an attachment, and a group event.
    add(group_id, "alex", "Ok locking in dates: Aug 22-24, Sierras", offset_hours=1)
    permit = add(group_id, "alex", "Got the permit for Little Lakes Valley 🎉", offset_hours=1.2)
    add(group_id, "ben", "", offset_hours=1.3, tapback=2000, target=permit)
    add(group_id, "cara", "", offset_hours=1.4, tapback=2001, target=permit)
    add(group_id, None, "That's the one with the lake basin right?", offset_hours=2,
        from_me=True, reply_to=permit)
    add(group_id, "alex", "yep, 5 lakes in the first 3 miles", offset_hours=2.1)
    add(group_id, "ben", "I'm out unfortunately — sister's wedding that weekend",
        offset_hours=25, use_attributed=True)
    add(group_id, "cara", "noooo", offset_hours=25.1)
    add(group_id, "dev", "I can drive, got the 4Runner. Room for 4 + packs",
        offset_hours=26, use_attributed=True)
    add(group_id, "erin", "Still a maybe for me, waiting on work travel to be confirmed",
        offset_hours=48)
    add(group_id, "finn", "here's the elevation profile", offset_hours=50,
        attachment="elevation.jpg")
    add(group_id, None, "Bear canisters — do we have enough?", offset_hours=52, from_me=True)
    add(group_id, "alex", "I have 2, need 1 more", offset_hours=52.5, edited=True)
    add(group_id, "cara", "wait actually", offset_hours=53, unsent=True)
    add(group_id, "cara", "I have one you can borrow", offset_hours=53.1)
    add(group_id, "alex", "", offset_hours=60, item_type=1, group_action=0, other="finn")
    add(group_id, "erin", "work travel got moved, I'm IN 🎒", offset_hours=100)
    add(group_id, None, "let's gooo", offset_hours=100.2, from_me=True)
    add(group_id, "alex", "", offset_hours=101, item_type=2, group_title="Sierra Trip 🏔️")
    add(group_id, "ben", "jealous. take pics", offset_hours=120)
    add(group_id, "dev", "Leaving Fri 6am, meeting at the Chevron on Main", offset_hours=190)

    add(solo_id, "alex", "hey did you see the group chat", offset_hours=5)
    add(solo_id, None, "yeah just caught up", offset_hours=5.2, from_me=True)

    conn.commit()
    conn.close()
    print(f"wrote fixture: {path}")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fixture/chat.db"))
