#!/usr/bin/env python3
"""
Read messages out of the macOS Messages database (``~/Library/Messages/chat.db``).

This is the data layer for the iMessage assistant. It does not summarize anything;
it produces a clean, speaker-attributed, chronologically ordered transcript for a
single conversation over a bounded time window, which is then handed to Claude.

Subcommands
-----------
  doctor                 Check that the database is readable and report what's wrong if not.
  list                   List conversations, most recently active first.
  export                 Export one conversation's messages over a time window.
  stats                  Per-sender message counts for a conversation/window.

Everything runs read-only against a snapshot copy of the database, so it can never
modify Messages and it works while Messages.app is running (the live file is often
locked by WAL).

macOS only. Requires Full Disk Access for the terminal running it.
"""

from __future__ import annotations

import argparse
import atexit
import json
import plistlib
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Apple's Core Data epoch: 2001-01-01 00:00:00 UTC, as a Unix timestamp.
APPLE_EPOCH_OFFSET = 978_307_200

DEFAULT_DB = Path.home() / "Library" / "Messages" / "chat.db"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROSTER = REPO_ROOT / "config" / "roster.json"

# message.associated_message_type values for tapbacks.
TAPBACKS = {
    2000: "loved",
    2001: "liked",
    2002: "disliked",
    2003: "laughed at",
    2004: "emphasized",
    2005: "questioned",
    2006: "reacted to",
}
TAPBACK_EMOJI = {
    "loved": "❤️",
    "liked": "👍",
    "disliked": "👎",
    "laughed at": "😂",
    "emphasized": "‼️",
    "questioned": "❓",
    "reacted to": "🩷",
}

# U+FFFC OBJECT REPLACEMENT CHARACTER — placeholder where an attachment sits inline.
OBJ_REPLACEMENT = "￼"


# --------------------------------------------------------------------------------------
# time handling
# --------------------------------------------------------------------------------------

def apple_to_datetime(value: int | None) -> datetime | None:
    """Convert a Messages timestamp to an aware local datetime.

    Ventura-era databases store nanoseconds since the Apple epoch; databases written
    before macOS 10.13 store seconds. Both show up in the wild (an old chat.db that
    has been migrated forward keeps some legacy rows), so pick based on magnitude
    rather than assuming.
    """
    if not value:
        return None
    seconds = value / 1_000_000_000 if abs(value) > 1e11 else float(value)
    return datetime.fromtimestamp(seconds + APPLE_EPOCH_OFFSET, tz=timezone.utc).astimezone()


def datetime_to_apple_ns(dt: datetime) -> int:
    return int((dt.timestamp() - APPLE_EPOCH_OFFSET) * 1_000_000_000)


_RELATIVE = re.compile(r"^(\d+(?:\.\d+)?)\s*([hdwmy])$", re.IGNORECASE)
_UNIT_HOURS = {"h": 1, "d": 24, "w": 24 * 7, "m": 24 * 30, "y": 24 * 365}


def parse_when(text: str, *, end_of_day: bool = False) -> datetime | None:
    """Parse a time bound: ``14d``, ``36h``, ``3w``, ``6m``, ``2026-07-01``, ``all``.

    Returns None for "all" (meaning: no bound). Relative values are measured back
    from now; absolute dates are interpreted in the machine's local timezone.
    """
    text = text.strip().lower()
    if text in {"all", "forever", "everything", "始"}:
        return None

    match = _RELATIVE.match(text)
    if match:
        amount, unit = float(match.group(1)), match.group(2).lower()
        return datetime.now().astimezone() - timedelta(hours=amount * _UNIT_HOURS[unit])

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt in {"%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"} and end_of_day:
            parsed = parsed.replace(hour=23, minute=59, second=59)
        return parsed.astimezone()

    raise ValueError(
        f"could not parse time {text!r}; use e.g. 14d, 36h, 3w, 6m, 2026-07-01, or all"
    )


# --------------------------------------------------------------------------------------
# database access
# --------------------------------------------------------------------------------------

class DatabaseUnavailable(RuntimeError):
    """chat.db could not be opened — almost always a Full Disk Access problem."""


def open_db(path: Path) -> sqlite3.Connection:
    """Open a read-only snapshot of chat.db.

    Messages keeps the live database in WAL mode and holds locks on it, so we copy
    the database plus its -wal/-shm sidecars to a temp directory first. Copying the
    sidecars matters: without them recent messages are invisible, because they are
    still sitting in the write-ahead log and have not been checkpointed into the
    main file yet.
    """
    if not path.exists():
        raise DatabaseUnavailable(f"no Messages database at {path}")

    try:
        staging = Path(tempfile.mkdtemp(prefix="imessage-assistant-"))
        # A real chat.db can be several GB. Always clean the snapshot up, or repeated
        # runs quietly fill the disk.
        atexit.register(shutil.rmtree, staging, ignore_errors=True)
        snapshot = staging / "chat.db"
        shutil.copy2(path, snapshot)
        for suffix in ("-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, snapshot.with_name(snapshot.name + suffix))
    except PermissionError as exc:
        raise DatabaseUnavailable(
            f"permission denied reading {path}.\n"
            "Grant Full Disk Access to your terminal:\n"
            "  System Settings → Privacy & Security → Full Disk Access → add Terminal/iTerm/VS Code,\n"
            "then fully quit and reopen that app (a window reload is not enough)."
        ) from exc

    conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def columns_of(conn: sqlite3.Connection, table: str) -> set[str]:
    """Column names for a table.

    The Messages schema changes between macOS releases — ``thread_originator_guid``
    arrived with inline replies, ``date_retracted`` with unsend. Query what actually
    exists instead of assuming, so this keeps working on older and newer machines.
    """
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


# --------------------------------------------------------------------------------------
# message body decoding
# --------------------------------------------------------------------------------------

def _decode_typedstream(blob: bytes) -> str | None:
    """Decode attributedBody properly, if the optional typedstream package is present."""
    try:
        from typedstream.stream import TypedStreamReader  # type: ignore
    except Exception:
        return None

    try:
        strings = [
            event for event in TypedStreamReader.from_data(blob) if isinstance(event, str)
        ]
    except Exception:
        return None

    # The archive leads with class names (NSString, NSMutableString, NSDictionary,
    # NSAttributedString...); the message body is the first payload string after them.
    for value in strings:
        if not value.startswith("NS") and value.strip():
            return value
    return None


def _decode_heuristic(blob: bytes) -> str | None:
    """Pull the body text out of an NSKeyedArchiver blob without any dependencies.

    Layout after the ``NSString`` class marker is a short preamble, then a
    length-prefixed UTF-8 run. Lengths under 128 use a single byte; longer strings
    use a 0x81 marker followed by a little-endian uint16.
    """
    marker = blob.find(b"NSString")
    if marker == -1:
        return None

    body = blob[marker + len(b"NSString") :]
    body = body[5:]  # class-reference preamble
    if not body:
        return None

    if body[0] == 0x81:
        if len(body) < 3:
            return None
        length = int.from_bytes(body[1:3], "little")
        body = body[3:]
    elif body[0] == 0x82:
        if len(body) < 5:
            return None
        length = int.from_bytes(body[1:5], "little")
        body = body[5:]
    else:
        length = body[0]
        body = body[1:]

    if length <= 0 or length > len(body):
        return None
    return body[:length].decode("utf-8", errors="replace")


def decode_body(text: str | None, attributed_body: bytes | None) -> str:
    """Best available plain text for a message.

    Modern macOS often leaves ``message.text`` NULL and stores the body only in
    ``attributedBody``. Ignoring that silently drops a large share of a recent
    conversation, so fall back to decoding the archive.
    """
    if text:
        return clean_text(text)
    if attributed_body:
        decoded = _decode_typedstream(attributed_body) or _decode_heuristic(attributed_body)
        if decoded:
            return clean_text(decoded)
    return ""


def clean_text(value: str) -> str:
    value = value.replace(OBJ_REPLACEMENT, " ")
    value = unicodedata.normalize("NFC", value)
    value = value.replace(" ", "\n").replace(" ", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def was_edited(message_summary_info: bytes | None) -> bool:
    if not message_summary_info:
        return False
    try:
        payload = plistlib.loads(message_summary_info)
    except Exception:
        return False
    return bool(payload.get("ec"))


def strip_guid_prefix(guid: str | None) -> str | None:
    """Tapback targets are stored as ``p:0/<guid>`` or ``bp:<guid>``."""
    if not guid:
        return None
    return guid.rsplit("/", 1)[-1] if "/" in guid else guid.split(":", 1)[-1]


# --------------------------------------------------------------------------------------
# contact resolution
# --------------------------------------------------------------------------------------

def normalize_handle(handle: str | None) -> str:
    """Normalize a phone number or email into a comparable key."""
    if not handle:
        return ""
    handle = handle.strip().lower()
    if "@" in handle:
        return handle
    digits = re.sub(r"\D", "", handle)
    return digits[-10:] if len(digits) >= 10 else digits


def load_roster(path: Path) -> dict[str, str]:
    """Load the hand-maintained handle → display name map."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"warning: {path} is not valid JSON ({exc}); ignoring it", file=sys.stderr)
        return {}

    people = raw.get("people", raw) if isinstance(raw, dict) else raw
    mapping: dict[str, str] = {}
    if isinstance(people, dict):
        # {"+15551234567": "Alex"}
        for handle, name in people.items():
            mapping[normalize_handle(handle)] = name
    else:
        # [{"name": "Alex", "handles": ["+1555...", "alex@me.com"]}]
        for person in people:
            name = person.get("name")
            if not name:
                continue
            for handle in person.get("handles", []):
                mapping[normalize_handle(handle)] = name
    mapping.pop("", None)
    return mapping


def load_address_book() -> dict[str, str]:
    """Map handles to names from the local Contacts database, best effort."""
    roots = list(
        (Path.home() / "Library" / "Application Support" / "AddressBook").glob(
            "Sources/*/AddressBook-v22.abcddb"
        )
    )
    roots += [Path.home() / "Library" / "Application Support" / "AddressBook" / "AddressBook-v22.abcddb"]

    mapping: dict[str, str] = {}
    for db_path in roots:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error:
            continue
        try:
            query = """
                SELECT r.ZFIRSTNAME AS first, r.ZLASTNAME AS last,
                       r.ZORGANIZATION AS org, v.{column} AS handle
                FROM ZABCDRECORD r
                JOIN {table} v ON v.ZOWNER = r.Z_PK
                WHERE v.{column} IS NOT NULL
            """
            sources = [("ZABCDPHONENUMBER", "ZFULLNUMBER"), ("ZABCDEMAILADDRESS", "ZADDRESS")]
            for table, column in sources:
                try:
                    rows = conn.execute(query.format(table=table, column=column)).fetchall()
                except sqlite3.Error:
                    continue
                for row in rows:
                    name = " ".join(filter(None, [row["first"], row["last"]])).strip()
                    name = name or (row["org"] or "").strip()
                    key = normalize_handle(row["handle"])
                    if name and key:
                        mapping.setdefault(key, name)
        finally:
            conn.close()
    return mapping


class NameResolver:
    """Resolve raw handles to human names, preferring the roster over Contacts."""

    def __init__(self, roster: dict[str, str], address_book: dict[str, str], me: str = "Me"):
        self.roster = roster
        self.address_book = address_book
        self.me = me
        self.unresolved: set[str] = set()

    def resolve(self, handle: str | None, *, is_from_me: bool = False) -> str:
        if is_from_me:
            return self.me
        if not handle:
            return "Unknown"
        key = normalize_handle(handle)
        name = self.roster.get(key) or self.address_book.get(key)
        if name:
            return name
        self.unresolved.add(handle)
        return format_handle(handle)


def format_handle(handle: str) -> str:
    """Render a bare handle readably when no name is known."""
    if "@" in handle:
        return handle
    digits = re.sub(r"\D", "", handle)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return handle


# --------------------------------------------------------------------------------------
# chat lookup
# --------------------------------------------------------------------------------------

def list_chats(conn: sqlite3.Connection, resolver: NameResolver, *, limit: int = 40,
               search: str | None = None) -> list[dict]:
    """Conversations ordered by most recent activity.

    Rows in ``chat`` are per-service (a group can exist once for iMessage and again
    for SMS), so collapse on the participant set to avoid showing near-duplicates.
    """
    rows = conn.execute(
        """
        SELECT c.ROWID AS chat_id, c.guid, c.chat_identifier, c.display_name,
               c.style, MAX(m.date) AS last_date, COUNT(m.ROWID) AS message_count
        FROM chat c
        JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
        JOIN message m ON m.ROWID = cmj.message_id
        GROUP BY c.ROWID
        ORDER BY last_date DESC
        """
    ).fetchall()

    chats = []
    for row in rows:
        participants = chat_participants(conn, row["chat_id"], resolver)
        name = (row["display_name"] or "").strip()
        if not name:
            # Unnamed group chats show up in Messages as the participant list.
            name = ", ".join(participants) if participants else (row["chat_identifier"] or "Unknown")
        chats.append(
            {
                "chat_id": row["chat_id"],
                "guid": row["guid"],
                "identifier": row["chat_identifier"],
                "name": name,
                "is_group": row["style"] == 43 or len(participants) > 1,
                "participants": participants,
                "message_count": row["message_count"],
                "last_message_at": iso(apple_to_datetime(row["last_date"])),
            }
        )

    if search:
        needle = search.lower()
        chats = [
            chat
            for chat in chats
            if needle in chat["name"].lower()
            or needle in (chat["identifier"] or "").lower()
            or any(needle in person.lower() for person in chat["participants"])
        ]

    return chats[:limit]


def chat_participants(conn: sqlite3.Connection, chat_id: int, resolver: NameResolver) -> list[str]:
    rows = conn.execute(
        """
        SELECT h.id AS handle
        FROM chat_handle_join chj
        JOIN handle h ON h.ROWID = chj.handle_id
        WHERE chj.chat_id = ?
        """,
        (chat_id,),
    ).fetchall()
    names = {resolver.resolve(row["handle"]) for row in rows}
    return sorted(names)


def resolve_chat(conn: sqlite3.Connection, resolver: NameResolver, selector: str) -> dict:
    """Find one conversation from a name, GUID, chat id, or participant name.

    Raises with the candidate list when the selector is ambiguous, so the caller can
    disambiguate instead of silently summarizing the wrong conversation.
    """
    chats = list_chats(conn, resolver, limit=10_000)

    if selector.isdigit():
        exact = [chat for chat in chats if chat["chat_id"] == int(selector)]
        if exact:
            return exact[0]

    lowered = selector.lower().strip()
    exact = [
        chat
        for chat in chats
        if lowered in {chat["name"].lower(), (chat["guid"] or "").lower(),
                       (chat["identifier"] or "").lower()}
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return max(exact, key=lambda chat: chat["message_count"])

    partial = [
        chat
        for chat in chats
        if lowered in chat["name"].lower()
        or lowered in (chat["identifier"] or "").lower()
        or any(lowered in person.lower() for person in chat["participants"])
    ]
    if not partial:
        raise LookupError(
            f"no conversation matched {selector!r}. Run `list` to see what's available."
        )
    if len(partial) == 1:
        return partial[0]

    lines = "\n".join(
        f"  [{chat['chat_id']}] {chat['name']}  ({chat['message_count']} msgs, "
        f"last {chat['last_message_at']})"
        for chat in partial[:12]
    )
    raise LookupError(f"{selector!r} matched {len(partial)} conversations:\n{lines}\n"
                      "Re-run with --chat <id> to pick one.")


# --------------------------------------------------------------------------------------
# message export
# --------------------------------------------------------------------------------------

def fetch_messages(conn: sqlite3.Connection, chat_id: int, resolver: NameResolver,
                   since: datetime | None, until: datetime | None) -> list[dict]:
    available = columns_of(conn, "message")

    optional = [
        "associated_message_type",
        "associated_message_guid",
        "thread_originator_guid",
        "message_summary_info",
        "item_type",
        "group_action_type",
        "group_title",
        "date_retracted",
        "is_audio_message",
        "balloon_bundle_id",
        "expressive_send_style_id",
    ]
    selected = ["m.ROWID AS rowid", "m.guid", "m.date", "m.is_from_me", "m.text",
                "m.attributedBody", "m.service", "m.handle_id"]
    selected += [f"m.{column}" for column in optional if column in available]

    clauses = ["cmj.chat_id = ?"]
    params: list = [chat_id]
    if since is not None:
        clauses.append("m.date >= ?")
        params.append(datetime_to_apple_ns(since))
    if until is not None:
        clauses.append("m.date <= ?")
        params.append(datetime_to_apple_ns(until))

    sql = f"""
        SELECT {', '.join(selected)}, h.id AS handle, other.id AS other_handle
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        LEFT JOIN handle h ON h.ROWID = m.handle_id
        LEFT JOIN handle other ON other.ROWID = m.other_handle
        WHERE {' AND '.join(clauses)}
        ORDER BY m.date ASC, m.ROWID ASC
    """
    if "other_handle" not in available:
        sql = sql.replace(", other.id AS other_handle", ", NULL AS other_handle")
        sql = sql.replace("LEFT JOIN handle other ON other.ROWID = m.other_handle", "")

    rows = conn.execute(sql, params).fetchall()
    attachments = fetch_attachments(conn, [row["rowid"] for row in rows])

    messages: list[dict] = []
    for row in rows:
        keys = row.keys()
        assoc_type = row["associated_message_type"] if "associated_message_type" in keys else 0
        message = {
            "rowid": row["rowid"],
            "guid": row["guid"],
            "timestamp": apple_to_datetime(row["date"]),
            "sender": resolver.resolve(row["handle"], is_from_me=bool(row["is_from_me"])),
            "is_from_me": bool(row["is_from_me"]),
            "text": decode_body(row["text"], row["attributedBody"]),
            "service": row["service"],
            "attachments": attachments.get(row["rowid"], []),
            "tapback_type": assoc_type or 0,
            "tapback_target": strip_guid_prefix(
                row["associated_message_guid"] if "associated_message_guid" in keys else None
            ),
            "reply_to": row["thread_originator_guid"] if "thread_originator_guid" in keys else None,
            "edited": was_edited(
                row["message_summary_info"] if "message_summary_info" in keys else None
            ),
            "unsent": bool(row["date_retracted"]) if "date_retracted" in keys else False,
            "item_type": row["item_type"] if "item_type" in keys else 0,
            "group_action_type": row["group_action_type"] if "group_action_type" in keys else 0,
            "group_title": row["group_title"] if "group_title" in keys else None,
            "other_party": resolver.resolve(row["other_handle"]) if row["other_handle"] else None,
            "reactions": [],
        }
        messages.append(message)

    return attach_reactions(messages)


def fetch_attachments(conn: sqlite3.Connection, message_ids: list[int]) -> dict[int, list[dict]]:
    if not message_ids:
        return {}
    result: dict[int, list[dict]] = {}
    # SQLite caps host parameters (999 by default), so page through the ids.
    for start in range(0, len(message_ids), 500):
        batch = message_ids[start : start + 500]
        placeholders = ",".join("?" * len(batch))
        rows = conn.execute(
            f"""
            SELECT maj.message_id AS message_id, a.filename, a.mime_type, a.transfer_name
            FROM message_attachment_join maj
            JOIN attachment a ON a.ROWID = maj.attachment_id
            WHERE maj.message_id IN ({placeholders})
            """,
            batch,
        ).fetchall()
        for row in rows:
            name = row["transfer_name"] or (
                Path(row["filename"]).name if row["filename"] else "attachment"
            )
            result.setdefault(row["message_id"], []).append(
                {"name": name, "mime_type": row["mime_type"] or "unknown"}
            )
    return result


def attach_reactions(messages: list[dict]) -> list[dict]:
    """Fold tapbacks into the messages they target.

    Keeping them as standalone lines triples the transcript length and buries the
    actual conversation, and "Ben liked a message" is useless without the referent.
    """
    by_guid = {message["guid"]: message for message in messages}
    kept: list[dict] = []

    for message in messages:
        kind = message["tapback_type"]
        if 2000 <= kind <= 2999:
            target = by_guid.get(message["tapback_target"])
            label = TAPBACKS.get(kind, "reacted to")
            if target is not None:
                target["reactions"].append({"sender": message["sender"], "kind": label})
                continue
            # Target is outside the window — keep a compact standalone line.
            message["text"] = f"[{label} an earlier message]"
        elif 3000 <= kind <= 3999:
            # Removed reaction: drop it and take the matching add with it.
            target = by_guid.get(message["tapback_target"])
            if target is not None:
                target["reactions"] = [
                    reaction
                    for reaction in target["reactions"]
                    if reaction["sender"] != message["sender"]
                ]
            continue
        kept.append(message)

    return kept


def describe_system_event(message: dict) -> str | None:
    """Render a non-text row (joins, leaves, renames) as a readable event line."""
    if not message["item_type"]:
        return None
    who = message["other_party"] or message["sender"]
    item_type = message["item_type"]
    if item_type == 1:
        action = "removed" if message["group_action_type"] == 1 else "added"
        return f"— {message['sender']} {action} {who}"
    if item_type == 2:
        return f"— {message['sender']} named the conversation “{message['group_title'] or '?'}”"
    if item_type == 3:
        return f"— {who} left the conversation"
    if item_type == 6:
        return f"— {message['sender']} started a FaceTime call"
    return f"— [group event from {message['sender']}]"


# --------------------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------------------

def iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def render_transcript(chat: dict, messages: list[dict], since: datetime | None,
                      until: datetime | None, resolver: NameResolver) -> str:
    out: list[str] = []
    window = f"{iso(since) or 'beginning'} → {iso(until) or 'now'}"
    kind = "group" if chat["is_group"] else "1:1"

    out.append(f"# {chat['name']}")
    out.append(f"Type: {kind} · {len(chat['participants'])} other participant(s)")
    out.append(f"Participants: {', '.join(chat['participants']) or 'unknown'} (+ {resolver.me})")
    out.append(f"Window: {window}")
    out.append(f"Messages in window: {len(messages)}")
    if resolver.unresolved:
        unknown = ", ".join(sorted(resolver.unresolved)[:10])
        out.append(f"Unresolved handles (no name known): {unknown}")
    out.append("")
    out.append("Format: [HH:MM] Sender: text · reactions on the following line · "
               "`↩` marks a reply to an earlier message.")
    out.append("")

    by_guid = {message["guid"]: message for message in messages}
    current_day: str | None = None

    for message in messages:
        stamp = message["timestamp"]
        day = stamp.strftime("%A %Y-%m-%d") if stamp else "unknown date"
        if day != current_day:
            out.append("")
            out.append(f"## {day}")
            current_day = day

        clock = stamp.strftime("%H:%M") if stamp else "--:--"

        event = describe_system_event(message)
        if event:
            out.append(f"[{clock}] {event}")
            continue

        body = message["text"]
        if message["unsent"]:
            body = "[message unsent]"
        if message["attachments"]:
            names = ", ".join(
                f"{item['name']} ({item['mime_type'].split('/')[0]})"
                for item in message["attachments"][:4]
            )
            body = f"{body} [attached: {names}]".strip()
        if message["edited"]:
            body = f"{body} (edited)"
        if not body:
            continue

        prefix = ""
        if message["reply_to"]:
            parent = by_guid.get(message["reply_to"])
            if parent is not None:
                quoted = (parent["text"] or "")[:45]
                prefix = f"↩ re {parent['sender']}: “{quoted}…” — "
            else:
                prefix = "↩ (reply to an earlier message) — "

        body = body.replace("\n", "\n        ")
        out.append(f"[{clock}] {message['sender']}: {prefix}{body}")

        if message["reactions"]:
            grouped: dict[str, list[str]] = {}
            for reaction in message["reactions"]:
                grouped.setdefault(reaction["kind"], []).append(reaction["sender"])
            rendered = " · ".join(
                f"{TAPBACK_EMOJI.get(kind, kind)} {', '.join(sorted(set(people)))}"
                for kind, people in grouped.items()
            )
            out.append(f"        ↳ {rendered}")

    return "\n".join(out).strip() + "\n"


def render_jsonl(messages: list[dict]) -> str:
    lines = []
    for message in messages:
        record = dict(message)
        record["timestamp"] = iso(record["timestamp"])
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def render_stats(chat: dict, messages: list[dict]) -> str:
    counts: dict[str, int] = {}
    reactions: dict[str, int] = {}
    first = last = None
    for message in messages:
        counts[message["sender"]] = counts.get(message["sender"], 0) + 1
        for reaction in message["reactions"]:
            reactions[reaction["sender"]] = reactions.get(reaction["sender"], 0) + 1
        if message["timestamp"]:
            first = first or message["timestamp"]
            last = message["timestamp"]

    out = [f"{chat['name']} — {len(messages)} messages"]
    if first and last:
        out.append(f"{iso(first)} → {iso(last)}")
    out.append("")
    for sender, count in sorted(counts.items(), key=lambda item: -item[1]):
        share = 100 * count / max(len(messages), 1)
        out.append(f"  {sender:<24} {count:>5}  ({share:4.1f}%)  "
                   f"{reactions.get(sender, 0)} reactions given")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def build_resolver(args) -> NameResolver:
    roster = load_roster(Path(args.roster)) if args.roster else {}
    address_book = {} if args.no_contacts else load_address_book()
    return NameResolver(roster, address_book, me=args.me)


def command_doctor(args) -> int:
    print(f"Platform: {sys.platform}")
    if sys.platform != "darwin":
        print("FAIL  Not macOS. The Messages database only exists on a Mac.")
        return 1

    path = Path(args.db)
    print(f"Database: {path}")
    if not path.exists():
        print("FAIL  File does not exist. Is Messages set up on this Mac?")
        return 1
    print(f"OK    Exists ({path.stat().st_size / 1_048_576:.1f} MB)")

    try:
        conn = open_db(path)
    except DatabaseUnavailable as exc:
        print(f"FAIL  {exc}")
        return 1
    print("OK    Readable (Full Disk Access is granted)")

    with conn:
        total = conn.execute("SELECT COUNT(*) FROM message").fetchone()[0]
        chats = conn.execute("SELECT COUNT(*) FROM chat").fetchone()[0]
        newest = conn.execute("SELECT MAX(date) FROM message").fetchone()[0]
    print(f"OK    {total:,} messages across {chats:,} conversations")
    print(f"OK    Most recent message: {iso(apple_to_datetime(newest))}")

    roster_path = Path(args.roster) if args.roster else DEFAULT_ROSTER
    if roster_path.exists():
        print(f"OK    Roster loaded: {len(load_roster(roster_path))} handles mapped")
    else:
        print(f"WARN  No roster at {roster_path} — names fall back to Contacts, then raw numbers.")

    contacts = {} if args.no_contacts else load_address_book()
    print(f"{'OK  ' if contacts else 'WARN'}  Contacts database: {len(contacts)} handles mapped")

    try:
        import typedstream  # type: ignore  # noqa: F401
        print("OK    typedstream installed (exact attributedBody decoding)")
    except ImportError:
        print("INFO  typedstream not installed — using the built-in decoder "
              "(fine; `pip install pytypedstream` for edge cases)")
    return 0


def command_list(args) -> int:
    resolver = build_resolver(args)
    with open_db(Path(args.db)) as conn:
        chats = list_chats(conn, resolver, limit=args.limit, search=args.search)

    if args.json:
        print(json.dumps(chats, indent=2, ensure_ascii=False))
        return 0

    if not chats:
        print("No conversations matched.")
        return 1

    for chat in chats:
        tag = "group" if chat["is_group"] else "1:1"
        print(f"[{chat['chat_id']:>5}] {chat['name']}")
        print(f"        {tag} · {chat['message_count']} msgs · last {chat['last_message_at']}")
        if chat["is_group"]:
            print(f"        with: {', '.join(chat['participants'])}")
    return 0


def command_export(args) -> int:
    resolver = build_resolver(args)
    since = parse_when(args.since) if args.since else None
    until = parse_when(args.until, end_of_day=True) if args.until else None

    with open_db(Path(args.db)) as conn:
        chat = resolve_chat(conn, resolver, args.chat)
        messages = fetch_messages(conn, chat["chat_id"], resolver, since, until)

    if args.max_messages and len(messages) > args.max_messages:
        dropped = len(messages) - args.max_messages
        print(
            f"warning: {len(messages)} messages in window; keeping the most recent "
            f"{args.max_messages} and dropping {dropped} older ones. "
            "Narrow --since, or export in date slices, to cover them.",
            file=sys.stderr,
        )
        messages = messages[-args.max_messages :]

    if args.format == "jsonl":
        output = render_jsonl(messages)
    elif args.format == "stats":
        output = render_stats(chat, messages)
    else:
        output = render_transcript(chat, messages, since, until, resolver)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output)
        print(f"Wrote {len(messages)} messages to {out_path}")
    else:
        sys.stdout.write(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="imessage_query.py",
        description="Read conversations out of the macOS Messages database.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="path to chat.db")
    parser.add_argument("--roster", default=str(DEFAULT_ROSTER),
                        help="JSON file mapping handles to names")
    parser.add_argument("--me", default="Me", help="display name for your own messages")
    parser.add_argument("--no-contacts", action="store_true",
                        help="skip the macOS Contacts lookup")

    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="verify setup and permissions")
    doctor.set_defaults(func=command_doctor)

    listing = subparsers.add_parser("list", help="list conversations")
    listing.add_argument("--limit", type=int, default=40)
    listing.add_argument("--search", help="filter by chat name or participant")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=command_list)

    export = subparsers.add_parser("export", help="export one conversation")
    export.add_argument("--chat", required=True,
                        help="chat name, participant name, GUID, or numeric id from `list`")
    export.add_argument("--since", default="14d",
                        help="lower time bound: 14d, 36h, 3w, 6m, 2026-07-01, or all")
    export.add_argument("--until", help="upper time bound (same formats)")
    export.add_argument("--format", choices=["transcript", "jsonl", "stats"],
                        default="transcript")
    export.add_argument("--max-messages", type=int, default=4000,
                        help="cap on messages returned; 0 disables the cap")
    export.add_argument("--out", help="write to a file instead of stdout")
    export.set_defaults(func=command_export)

    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except (DatabaseUnavailable, LookupError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
