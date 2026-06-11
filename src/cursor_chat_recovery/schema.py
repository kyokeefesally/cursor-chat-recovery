"""Schema fingerprint, mismatch detection, and agent-prompt generation."""
from __future__ import annotations

import json
from typing import Any, Protocol

from cursor_chat_recovery.model import SchemaReport

SCHEMA_VERSION = "2026-05-a"

EXPECTED_TABLES = {"ItemTable", "cursorDiskKV"}
EXPECTED_KEYS = {"composer.composerHeaders"}
EXPECTED_HEADER_REQUIRED = {"composerId", "createdAt", "workspaceIdentifier"}
EXPECTED_HEADER_EXPECTED = {"name", "lastUpdatedAt", "type"}
EXPECTED_WS_IDENTIFIER_REQUIRED = {"id"}
EXPECTED_KV_PREFIXES = {"composerData:", "bubbleId:"}


class _Queryable(Protocol):
    def execute(self, sql: str, *parameters: Any) -> Any: ...


def detect_mismatch(con: _Queryable) -> SchemaReport:
    missing: list[str] = []
    unexpected: list[str] = []
    samples: dict[str, object] = {}

    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in EXPECTED_TABLES:
        if t not in tables:
            missing.append(f"table:{t}")

    if "ItemTable" in tables:
        row = con.execute(
            "SELECT value FROM ItemTable WHERE key='composer.composerHeaders'"
        ).fetchone()
        if not row:
            missing.append("key:composer.composerHeaders")
        else:
            try:
                data = json.loads(row[0])
                if "allComposers" not in data or not isinstance(data["allComposers"], list):
                    missing.append("composer.composerHeaders.allComposers (list)")
                else:
                    sample_headers = data["allComposers"][:3]
                    samples["header_sample"] = sample_headers[0] if sample_headers else None
                    for h in sample_headers:
                        for f in EXPECTED_HEADER_REQUIRED:
                            if f not in h:
                                missing.append(f"header.{f}")
                        wid = h.get("workspaceIdentifier") or {}
                        for f in EXPECTED_WS_IDENTIFIER_REQUIRED:
                            if f not in wid:
                                missing.append(f"workspaceIdentifier.{f}")
            except json.JSONDecodeError:
                missing.append("composer.composerHeaders (invalid JSON)")

    if "cursorDiskKV" in tables:
        for prefix in EXPECTED_KV_PREFIXES:
            row = con.execute(
                "SELECT key FROM cursorDiskKV WHERE key LIKE ? LIMIT 1",
                (prefix + "%",),
            ).fetchone()
            if not row:
                count = con.execute("SELECT COUNT(*) FROM cursorDiskKV").fetchone()[0]
                if count > 0:
                    missing.append(f"cursorDiskKV.{prefix}*")

    return SchemaReport(
        ok=(not missing),
        schema_version=SCHEMA_VERSION,
        missing=sorted(set(missing)),
        unexpected=sorted(set(unexpected)),
        samples=samples,
    )


def agent_prompt(report: SchemaReport) -> str:
    return f"""You are updating cursor-chat-recovery to a new Cursor schema version.

Current expected schema (cursor_chat_recovery/schema.py):
  SCHEMA_VERSION = "{report.schema_version}"
  ItemTable key "composer.composerHeaders" -> JSON {{allComposers: [Header, ...]}}
  Each Header must have: {sorted(EXPECTED_HEADER_REQUIRED)}
  Each header.workspaceIdentifier must have: {sorted(EXPECTED_WS_IDENTIFIER_REQUIRED)}
  cursorDiskKV must contain rows with key prefixes: {sorted(EXPECTED_KV_PREFIXES)}

Observed on this machine:
  Missing or differently-shaped:
    {chr(10).join('    ' + m for m in report.missing) if report.missing else '    (none)'}
  Sample header:
    {json.dumps(report.samples.get('header_sample'), indent=4, default=str)}

Please:
  1) Update schema.py constants to match the new shape.
  2) Update storage.read_headers() and operations.load_chat() if field paths moved.
  3) Bump SCHEMA_VERSION and update CHANGELOG.
  4) Add a test fixture under tests/fixtures/ reflecting this version.
"""
