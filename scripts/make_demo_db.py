"""Generate a synthetic Cursor database for demos, screenshots, and GIFs.

Creates a fake-but-realistic global state.vscdb plus a matching workspaceStorage
directory, so recordings never show real project names or client data.

Usage:
    python scripts/make_demo_db.py [outdir]    # default: ./demo

Then run the TUI against it (safe — your real Cursor data is untouched):

    cursor-chat-recovery --global-db demo/state.vscdb \
        --workspace-storage demo/workspaceStorage \
        --backup-dir demo/backups --no-cursor-check
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
import uuid
from pathlib import Path

HOUR = 3_600_000
DAY = 24 * HOUR


def _header(composer_id: str, name: str, created_ms: int, ws_id: str, ws_uri: str) -> dict:
    return {
        "type": "head",
        "composerId": composer_id,
        "name": name,
        "createdAt": created_ms,
        "lastUpdatedAt": created_ms + 2 * HOUR,
        "unifiedMode": "agent",
        "forceMode": "edit",
        "isArchived": False,
        "isDraft": False,
        "subtitle": "",
        "workspaceIdentifier": {
            "id": ws_id,
            "uri": {"external": ws_uri, "scheme": "file"},
        },
    }


def _bubble(kind: int, text: str, ts_ms: int) -> dict:
    # kind: 1=user, 2=assistant in Cursor's encoding
    return {"bubbleId": uuid.uuid4().hex[:12], "type": kind, "text": text, "createdAt": ts_ms}


def _conversation(created_ms: int, turns: list[tuple[int, str]]) -> list[dict]:
    return [_bubble(kind, text, created_ms + i * 60_000) for i, (kind, text) in enumerate(turns)]


def build(outdir: Path) -> None:
    now = int(time.time() * 1000)

    # Workspace identities. "old-laptop" has chats but no storage dir -> shows
    # as orphan; the demo story is reattaching its chats to acme-website.
    ws = {
        "acme": ("a3f8c2d41b9e7f60", "file:///home/kuba/projects/acme-website"),
        "acme_old": ("9d71e0b452c8a3f1", "file:///media/old-laptop/dev/acme-website"),
        "pipeline": ("c44b1a86f02d9e35", "file:///home/kuba/projects/data-pipeline"),
        "dotfiles": ("57e9d3a0c1b24f88", "file:///home/kuba/dotfiles"),
    }

    chats: list[tuple[str, str, int, list[tuple[int, str]]]] = [
        # (workspace key, chat name, created_ms, turns)
        ("acme", "Add OAuth login flow", now - 2 * DAY, [
            (1, "Add Google OAuth to the login page. We already use NextAuth."),
            (2, "I'll add the Google provider to the NextAuth config, wire the client ID "
                "and secret through env vars, and update the login form with a "
                "'Continue with Google' button.\n\nFiles changed:\n"
                "- src/auth/config.ts\n- src/components/LoginForm.tsx\n- .env.example"),
            (1, "Looks good, but redirect to /dashboard after login, not /."),
            (2, "Done — set the callback redirect to /dashboard and added a regression "
                "test for the redirect target."),
        ]),
        ("acme", "Fix CSS grid collapsing on mobile", now - 5 * DAY, [
            (1, "The pricing cards stack weirdly below 640px, third card overflows."),
            (2, "The grid uses a fixed minmax(280px, 1fr) which overflows narrow "
                "viewports. I changed it to repeat(auto-fit, minmax(min(280px, 100%), "
                "1fr)) so cards wrap instead of overflowing."),
        ]),
        ("acme", "Refactor API client error handling", now - 9 * DAY, [
            (1, "Every fetch call handles errors differently. Unify it."),
            (2, "I extracted an apiFetch wrapper that normalizes errors into an "
                "ApiError type with status, code, and a user-safe message, then "
                "migrated all 14 call sites to it."),
            (1, "Add retry with backoff for 429s."),
            (2, "Added exponential backoff (250ms base, 3 attempts) for 429 and 503, "
                "with jitter, plus unit tests for the retry schedule."),
        ]),
        # Chats stranded on the old workspace identity (the orphan to rescue).
        ("acme_old", "Set up Stripe webhooks", now - 40 * DAY, [
            (1, "Wire up Stripe webhooks for subscription created/updated/cancelled."),
            (2, "Added /api/webhooks/stripe with signature verification, idempotency "
                "keys, and handlers for the three subscription events. Local testing "
                "via `stripe listen --forward-to localhost:3000`."),
        ]),
        ("acme_old", "Debug flaky deploy on CI", now - 45 * DAY, [
            (1, "Deploys fail maybe one time in five with a timeout during asset upload."),
            (2, "The upload step had no retry and a 30s timeout shared across all "
                "assets. I gave each asset its own timeout and two retries — the runs "
                "you flagged would all have passed under this policy."),
        ]),
        ("acme_old", "Migrate database to Postgres 16", now - 52 * DAY, [
            (1, "Plan the migration from PG 13 to 16, zero downtime if possible."),
            (2, "Proposed plan: logical replication to a 16 replica, cut over behind "
                "PgBouncer with a 2-minute write pause, rollback path kept for 48h. "
                "Full runbook in docs/migrations/pg16.md."),
        ]),
        ("acme_old", "Write landing page copy", now - 60 * DAY, [
            (1, "Draft hero copy. Audience: small agencies. Tone: confident, no fluff."),
            (2, "Three options drafted, each with headline + subhead + CTA. Option B "
                "tested best against your tone notes: 'Ship client work twice as "
                "fast — without the agency chaos.'"),
        ]),
        ("pipeline", "Speed up nightly ETL", now - 1 * DAY, [
            (1, "The nightly job takes 4 hours now. Where does the time go?"),
            (2, "Profiled it: 70% is row-by-row upserts into the warehouse. Switched "
                "to staged COPY + MERGE, which brings the job to ~35 minutes on the "
                "same data volume."),
        ]),
        ("pipeline", "Add data quality checks", now - 6 * DAY, [
            (1, "Add basic DQ checks before the publish step."),
            (2, "Added row-count deltas, null-rate thresholds, and schema drift "
                "detection; failures block publish and page #data-alerts."),
        ]),
        ("pipeline", "Backfill March events", now - 12 * DAY, [
            (1, "We lost March 3-7 events in the raw layer. Backfill from the vendor API."),
            (2, "Wrote a chunked backfill with checkpointing — re-runnable, rate-limit "
                "aware, verified counts match the vendor dashboard for all five days."),
        ]),
        ("dotfiles", "Tmux + Neovim clipboard sync", now - 20 * DAY, [
            (1, "Yanking in Neovim inside tmux over SSH doesn't reach my local clipboard."),
            (2, "Enabled OSC 52: set clipboard provider in Neovim to osc52 and added "
                "`set -g allow-passthrough on` to tmux.conf. Works over SSH now."),
        ]),
        ("dotfiles", "Starship prompt tweaks", now - 33 * DAY, [
            (1, "Trim the prompt: drop the time module, shorten the path to 3 segments."),
            (2, "Updated starship.toml: removed [time], set truncation_length = 3 and "
                "truncate_to_repo = true."),
        ]),
    ]

    headers = []
    composer_bubbles: dict[str, list[dict]] = {}
    for ws_key, name, created, turns in chats:
        ws_id, ws_uri = ws[ws_key]
        cid = uuid.uuid4().hex[:16]
        headers.append(_header(cid, name, created, ws_id, ws_uri))
        composer_bubbles[cid] = _conversation(created, turns)

    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)

    db_path = outdir / "state.vscdb"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    con.execute(
        "INSERT INTO ItemTable VALUES (?, ?)",
        ("composer.composerHeaders", json.dumps({"allComposers": headers})),
    )
    for cid, bubbles in composer_bubbles.items():
        composer_data = {
            "composerId": cid,
            "conversation": [b["bubbleId"] for b in bubbles],
            "createdAt": bubbles[0]["createdAt"],
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

    # Storage dirs exist for live workspaces; "acme_old" gets none -> orphan.
    ws_root = outdir / "workspaceStorage"
    for key in ("acme", "pipeline", "dotfiles"):
        d = ws_root / ws[key][0]
        d.mkdir(parents=True)
        (d / "state.vscdb").write_bytes(b"")

    print(f"Demo data written to {outdir}/")
    print("Run the TUI against it with:\n")
    print(f"  cursor-chat-recovery --global-db {db_path} \\")
    print(f"      --workspace-storage {ws_root} \\")
    print(f"      --backup-dir {outdir / 'backups'} --no-cursor-check")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo"))
