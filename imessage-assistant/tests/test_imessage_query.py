"""Tests for the chat.db reader, run against a synthetic Messages database.

    python3 -m pytest tests/ -q

No Mac required — tests/make_fixture.py rebuilds the schema locally.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import make_fixture  # noqa: E402
from imessage_query import (  # noqa: E402
    NameResolver,
    apple_to_datetime,
    datetime_to_apple_ns,
    decode_body,
    fetch_messages,
    format_handle,
    list_chats,
    normalize_handle,
    open_db,
    parse_when,
    render_transcript,
    resolve_chat,
)


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("messages") / "chat.db"
    make_fixture.build(path)
    return path


@pytest.fixture(scope="module")
def resolver():
    roster = {
        normalize_handle("+1 (555) 010-0001"): "Alex",
        normalize_handle("5550100002"): "Ben",
        normalize_handle("+15550100003"): "Cara",
        normalize_handle("dev@example.com"): "Dev",
        normalize_handle("+15550100005"): "Erin",
        normalize_handle("+15550100006"): "Finn",
    }
    return NameResolver(roster, {}, me="Kyle")


@pytest.fixture(scope="module")
def messages(db_path, resolver):
    with open_db(db_path) as conn:
        chat = resolve_chat(conn, resolver, "Sierra")
        return chat, fetch_messages(conn, chat["chat_id"], resolver, None, None)


# --- time -----------------------------------------------------------------------------

def test_apple_epoch_roundtrip():
    when = datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc).astimezone()
    assert abs((apple_to_datetime(datetime_to_apple_ns(when)) - when).total_seconds()) < 1


def test_legacy_second_precision_timestamps_are_detected():
    """Pre-10.13 rows store seconds, not nanoseconds; both must decode sanely."""
    seconds = int(datetime(2015, 6, 1, tzinfo=timezone.utc).timestamp() - 978_307_200)
    assert apple_to_datetime(seconds).year == 2015


@pytest.mark.parametrize(
    "text,expected_days",
    [("14d", 14), ("36h", 1.5), ("3w", 21), ("6m", 180), ("2y", 730)],
)
def test_parse_relative_windows(text, expected_days):
    delta = datetime.now().astimezone() - parse_when(text)
    assert abs(delta - timedelta(days=expected_days)) < timedelta(minutes=1)


def test_parse_absolute_and_all():
    assert parse_when("2026-07-01").date() == datetime(2026, 7, 1).date()
    assert parse_when("all") is None
    with pytest.raises(ValueError):
        parse_when("last tuesday-ish")


def test_until_absolute_date_covers_the_whole_day():
    assert parse_when("2026-07-01", end_of_day=True).hour == 23


# --- identity -------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    ["+15550100001", "5550100001", "(555) 010-0001", "+1 555-010-0001", "555.010.0001"],
)
def test_phone_formats_normalize_together(raw):
    assert normalize_handle(raw) == "5550100001"


def test_email_handles_are_case_insensitive():
    assert normalize_handle("Dev@Example.COM") == "dev@example.com"


def test_unknown_handles_are_reported_not_hidden(resolver):
    local = NameResolver({}, {}, me="Kyle")
    assert local.resolve("+15559999999") == "(555) 999-9999"
    assert "+15559999999" in local.unresolved


def test_own_messages_use_the_configured_name(resolver):
    assert resolver.resolve("+15550100001", is_from_me=True) == "Kyle"


def test_format_handle_strips_country_code():
    assert format_handle("+15550100001") == "(555) 010-0001"


# --- body decoding --------------------------------------------------------------------

def test_plain_text_wins_when_present():
    assert decode_body("hello", None) == "hello"


def test_attributed_body_is_decoded_when_text_is_null():
    """Modern macOS leaves message.text NULL; missing this loses most of a chat."""
    blob = make_fixture.encode_attributed_body("I'm out — sister's wedding")
    assert decode_body(None, blob) == "I'm out — sister's wedding"


def test_long_attributed_body_uses_two_byte_length():
    long_text = "we should talk about the food plan " * 12
    blob = make_fixture.encode_attributed_body(long_text)
    assert decode_body(None, blob).strip() == long_text.strip()


def test_emoji_survive_decoding():
    blob = make_fixture.encode_attributed_body("I'm IN 🎒🏔️")
    assert decode_body(None, blob) == "I'm IN 🎒🏔️"


def test_undecodable_body_returns_empty_rather_than_garbage():
    assert decode_body(None, b"\x00\x01\x02not an archive") == ""


# --- chat lookup ----------------------------------------------------------------------

def test_group_and_direct_chats_are_listed(db_path, resolver):
    with open_db(db_path) as conn:
        chats = list_chats(conn, resolver)
    assert [chat["name"] for chat in chats] == ["Sierra Trip 🏔️", "Alex"]
    assert chats[0]["is_group"] is True
    assert chats[1]["is_group"] is False


def test_unnamed_direct_chat_falls_back_to_participant_name(db_path, resolver):
    with open_db(db_path) as conn:
        chats = list_chats(conn, resolver)
    assert chats[1]["name"] == "Alex"


def test_chat_resolves_by_partial_name_and_by_id(db_path, resolver):
    with open_db(db_path) as conn:
        assert resolve_chat(conn, resolver, "sierra")["chat_id"] == 1
        assert resolve_chat(conn, resolver, "1")["chat_id"] == 1


def test_ambiguous_selector_raises_with_candidates(db_path, resolver):
    with open_db(db_path) as conn:
        with pytest.raises(LookupError, match="matched 2 conversations"):
            resolve_chat(conn, resolver, "a")


def test_missing_chat_raises(db_path, resolver):
    with open_db(db_path) as conn:
        with pytest.raises(LookupError, match="no conversation matched"):
            resolve_chat(conn, resolver, "nonexistent")


# --- message assembly -----------------------------------------------------------------

def test_every_participant_is_attributed(messages):
    _, rows = messages
    senders = {row["sender"] for row in rows}
    assert {"Kyle", "Alex", "Ben", "Cara", "Dev", "Erin", "Finn"} <= senders
    assert not any(sender.startswith("(555)") for sender in senders)


def test_messages_are_chronological(messages):
    _, rows = messages
    stamps = [row["timestamp"] for row in rows if row["timestamp"]]
    assert stamps == sorted(stamps)


def test_tapbacks_fold_into_their_target(messages):
    _, rows = messages
    permit = next(row for row in rows if "permit" in row["text"])
    assert {(r["sender"], r["kind"]) for r in permit["reactions"]} == {
        ("Ben", "loved"),
        ("Cara", "liked"),
    }
    # ...and are not left as separate messages.
    assert not any(row["tapback_type"] for row in rows)


def test_replies_point_at_their_parent(messages):
    _, rows = messages
    reply = next(row for row in rows if "lake basin" in row["text"])
    parent = next(row for row in rows if row["guid"] == reply["reply_to"])
    assert parent["sender"] == "Alex"


def test_edited_unsent_and_attachments_are_flagged(messages):
    _, rows = messages
    assert any(row["edited"] for row in rows)
    assert any(row["unsent"] for row in rows)
    assert any(row["attachments"] for row in rows)


def test_group_events_are_captured(messages):
    _, rows = messages
    assert any(row["item_type"] == 1 for row in rows)  # participant added
    assert any(row["item_type"] == 2 for row in rows)  # renamed


def test_time_window_bounds_are_respected(db_path, resolver):
    since = datetime.now().astimezone() - timedelta(days=3)
    with open_db(db_path) as conn:
        rows = fetch_messages(conn, 1, resolver, since, None)
    assert rows
    assert all(row["timestamp"] >= since for row in rows)


def test_window_excludes_the_other_conversation(db_path, resolver):
    with open_db(db_path) as conn:
        rows = fetch_messages(conn, 1, resolver, None, None)
    assert not any("caught up" in row["text"] for row in rows)


# --- rendering ------------------------------------------------------------------------

def test_transcript_has_speakers_dates_and_reactions(messages, resolver):
    chat, rows = messages
    text = render_transcript(chat, rows, None, None, resolver)
    assert "Alex: Ok locking in dates" in text
    assert "## Monday 2026-08-03" in text or "## " in text
    assert "❤️ Ben" in text
    assert "↩ re Alex:" in text
    assert "(edited)" in text
    assert "[message unsent]" in text
    assert "[attached: elevation.jpg" in text
    assert "— Alex added Finn" in text


def test_transcript_header_states_the_window_and_roster(messages, resolver):
    chat, rows = messages
    text = render_transcript(chat, rows, None, None, resolver)
    assert "Participants: Alex, Ben, Cara, Dev, Erin, Finn (+ Kyle)" in text
    assert f"Messages in window: {len(rows)}" in text
