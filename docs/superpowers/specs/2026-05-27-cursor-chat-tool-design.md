# Cursor Chat Tool — Design Spec

**Date:** 2026-05-27
**Status:** Approved for implementation planning
**Repo:** new project, fresh start (does not extend `cursor-chat-recovery.sh`)

## Motivation

Cursor's per-workspace chat history is fragile. A workspace's identity is a hash of its identifier URI; reopening from a different path or saving an Untitled multi-folder workspace to a `.code-workspace` file mints a *new* identity and detaches all prior chats from the user's view. The conversations themselves are not lost — they remain in `globalStorage/state.vscdb` keyed by `composerId` — but the index that drives the chat sidebar (`composer.composerHeaders`) still tags them with the old workspace id, so they don't appear.

The pre-existing `cursor-chat-recovery.sh` operates on per-workspace `state.vscdb` files and is largely a no-op for modern Cursor chats. We are building a new tool from scratch.

## Goals

Interactive TUI to:
1. Inventory all workspaces and chats Cursor knows about on this machine.
2. Surface health states: obsolete, config-missing, orphan, empty-storage.
3. Drill from workspaces → chats → messages.
4. Reassign chats between workspaces and merge whole workspaces.
5. Export chats to markdown/JSON.

## Non-goals (v1)

- Deleting chats or purging orphans.
- Full-text search across messages.
- Modifying `cursorDiskKV` rows (chat content is read-only).
- Remote Cursor server's `~/.cursor-server/` storage (local `globalStorage` only).
- Multi-machine sync or cloud anything.

## Background — Cursor's storage model

```
%APPDATA%\Cursor\User\
├── workspaceStorage\<hash>\
│   ├── state.vscdb            # workspace-level UI scaffolding only
│   ├── workspace.json         # identifier URI for this workspace
│   └── obsolete               # marker file (zero bytes) if GCed
└── globalStorage\
    └── state.vscdb            # ~9 GB on heavy users; THE chat store
        ├── ItemTable
        │   └── key = "composer.composerHeaders"
        │       value = JSON: {"allComposers": [Header, ...]}
        └── cursorDiskKV
            ├── composerData:<UUID>          # full conversation + bubble id list
            ├── bubbleId:<composer>:<bubble> # individual messages
            ├── checkpointId:<composer>:...  # code checkpoints
            ├── codeBlockDiff:<composer>:... # code edits
            ├── messageRequestContext:...
            ├── agentKv:bubbleCheckpoint:... # agent state
            └── composer.content.<sha256>    # content-addressed blobs
```

A `Header` looks like:

```json
{
  "type": "head",
  "composerId": "52d449d7-...",
  "name": "DAPT code review M3.1",
  "createdAt": 1779265552677,
  "lastUpdatedAt": 1779268353100,
  "workspaceIdentifier": {
    "id": "246df445b49acfe1ed9708340e384d4b",
    "configPath": {
      "external": "vscode-remote://ssh-remote+.../alcid.code-workspace",
      "scheme": "vscode-remote",
      "authority": "ssh-remote+7b22686f73744e616d65223a22616c636964227d"
    }
  },
  ...
}
```

The sidebar's chat list = `allComposers` filtered by `workspaceIdentifier.id == <current workspace hash>`. **Reassigning a chat means rewriting that one field on the header.**

ssh-remote authorities encode the host name as a hex-encoded JSON object, e.g. `ssh-remote+7b22686f73744e616d65223a22616c636964227d` decodes to `{"hostName":"alcid"}`.

## Architecture

**Layered: pure core + thin TUI.**

```
cursor-chat-tool/
├── pyproject.toml                  # installable via `uv tool install` or `pipx install`
├── README.md
├── src/cursor_chat_tool/
│   ├── __init__.py
│   ├── paths.py                    # OS detection; locate globalStorage + workspaceStorage
│   ├── schema.py                   # expected field set; detect_mismatch(); agent_prompt()
│   ├── storage.py                  # SQLite open (RO/RW), backups, WAL checkpoint, Cursor-running check
│   ├── model.py                    # dataclasses: Workspace, ChatHeader, Bubble, ChatDetail
│   ├── operations.py               # pure functions: list_workspaces, list_chats, load_chat,
│   │                               #   reassign_chats, merge_workspaces, export_chat
│   ├── tui/
│   │   ├── app.py                  # prompt_toolkit Application, screen stack, breadcrumb
│   │   ├── screen_workspaces.py
│   │   ├── screen_chats.py
│   │   ├── screen_messages.py
│   │   └── dialogs.py
│   └── cli.py                      # entry point; --list/--export/--reassign for headless use
└── tests/
    ├── fixtures/
    │   ├── make_fixture.py
    │   ├── globalStorage_minimal.vscdb
    │   ├── globalStorage_schema_drift.vscdb
    │   └── globalStorage_corrupt.vscdb
    ├── test_paths.py
    ├── test_schema.py
    ├── test_storage.py
    ├── test_operations.py
    ├── test_cli.py
    └── test_tui_smoke.py
```

**Boundaries:**
- `paths`, `schema`, `storage`, `model`, `operations` form the **core**. No `prompt_toolkit` imports below `tui/`. The core is usable as a library.
- `operations` is the **only** module that mutates. Every mutation passes through it and gets uniform backup + transaction handling.
- `tui` is dumb: collects input, calls `operations.*`, renders results. Never touches SQLite directly.
- `cli.py` selects interactive vs. non-interactive based on flags.

## Data model

```python
@dataclass(frozen=True)
class WorkspaceIdentifier:
    id: str                          # workspace storage hash, or numeric-only orphan id
    uri: str | None                  # external URI, if any
    scheme: str | None               # "file" | "vscode-remote" | None
    is_remote: bool
    remote_host: str | None          # decoded from ssh-remote hex blob
    config_path: str | None          # for Untitled multi-folder: Workspaces/<ts>/workspace.json

@dataclass(frozen=True)
class Workspace:
    identifier: WorkspaceIdentifier
    chat_count: int
    first_chat_at: datetime | None
    last_chat_at: datetime | None
    storage_dir_exists: bool         # workspaceStorage/<id>/ present?
    is_obsolete: bool                # has 'obsolete' marker
    config_exists: bool              # for Untitled: Workspaces/<ts>/workspace.json present?
    display_name: str                # derived; "Untitled (<ts>)" / "Orphan <id>" / last path segment
    health: Literal["ok","obsolete","config-missing","orphan","empty-storage"]

@dataclass(frozen=True)
class ChatHeader:
    composer_id: str
    name: str | None
    created_at: datetime
    last_updated_at: datetime | None
    workspace_id: str
    subtitle: str | None
    bubble_count_hint: int | None    # cheap COUNT(*) over bubbleId:<id>:* prefix
    raw: dict                        # full original JSON; preserved for round-trip safety

@dataclass(frozen=True)
class Bubble:
    bubble_id: str
    role: Literal["user","assistant","system","tool","unknown"]
    text: str
    created_at: datetime | None
    raw: dict

@dataclass(frozen=True)
class ChatDetail:
    header: ChatHeader
    bubbles: list[Bubble]
    composer_data_raw: dict
```

Every record carries its `raw` JSON. The tool models the fields it understands and round-trips everything else verbatim — minimal damage if Cursor adds new fields between releases.

## Operations

```python
# Read
def list_workspaces(storage) -> list[Workspace]
def list_chats(storage, workspace_id: str, limit: int | None = None) -> list[ChatHeader]
def load_chat(storage, composer_id: str) -> ChatDetail

# Mutate
def reassign_chats(storage, composer_ids: list[str], target_ws_id: str) -> ReassignResult
def merge_workspaces(storage, source_ws_id: str, target_ws_id: str) -> MergeResult

# Pure
def export_chat(chat: ChatDetail, fmt: Literal["markdown","json"]) -> str
```

Mutation result dataclasses include `backup_path`, `before`, `after`, `applied_changes` so the TUI can render a confirmation + offer "Undo last operation".

**`list_workspaces` algorithm:**
1. Read `composer.composerHeaders`; group by `workspaceIdentifier.id`; aggregate chat counts and date range.
2. Walk `workspaceStorage/*/` and record which `id`s have on-disk dirs and which have `obsolete` markers.
3. Workspaces with on-disk dirs but no headers → `empty-storage`.
4. Header-only groups with no on-disk dir → `orphan`.
5. For Untitled multi-folder workspaces, check whether the `configPath` (`Workspaces/<ts>/workspace.json`) still exists; if not → `config-missing`.
6. Sort by `last_chat_at` descending.

## TUI

**Drill-in/out navigation** with breadcrumb at top. Three screens stacked on a navigation stack.

### Screen 1 — Workspaces
```
Cursor Chat Tool                              [globalStorage: 9.3 GB, 920 chats]
─────────────────────────────────────────────────────────────────────────────
 health  chats  last activity     workspace
─────────────────────────────────────────────────────────────────────────────
> ok      241   2026-05-22 12:01  cc                          file:///c:/Users/kwisc/Documents/cc
  obs.    132   2026-05-20 00:25  Untitled (1778233233740)    [config missing]
  ok      137   2026-05-20 10:25  alcid (Workspace)           ssh-remote+alcid /srv/projects/alcid/...
  orphan    2   2026-05-19 18:00  Orphan 1779206396578        [no storage dir]
─────────────────────────────────────────────────────────────────────────────
 [↑/↓] move  [Enter] open  [m] merge into…  [s] sort  [/] filter  [?] help  [q] quit
```

### Screen 2 — Chats
```
… › alcid (Workspace)                                              137 chats
─────────────────────────────────────────────────────────────────────────────
> 2026-05-20 10:16  Missing Cursor agent conversations          (12 msgs)
  2026-05-09 09:08  DAPT code review M3.1                       (47 msgs)
─────────────────────────────────────────────────────────────────────────────
 [↑/↓] move  [Enter] view  [Space] select  [r] reassign sel…  [e] export sel…  [Esc] back
```

`Space` toggles a selection mark. Status bar shows count of selected. `r`/`e` operate on selection or current row.

### Screen 3 — Messages
```
… › alcid › DAPT code review M3.1                              47 msgs · 2026-05-09
─────────────────────────────────────────────────────────────────────────────
 USER  2026-05-09 09:08
   Please review the M3.1 patch and flag anything that violates the DAPT contract.

 ASSISTANT  2026-05-09 09:09
   I've read the diff for src/dapt/m3_1.py …
─────────────────────────────────────────────────────────────────────────────
 [↑/↓ PgUp/PgDn] scroll  [e] export this chat  [Esc] back
```

### Dialogs
- **Pick target workspace** for reassign/merge: scrollable list with same filter as Screen 1, plus a free-text input for pasting a workspace id.
- **Confirm mutation**: `N chats will be reassigned from <src> to <dst>. Backup at <path>. Proceed? [y/N]`.
- **Result**: backup paths, before/after counts, success/error, optional Undo.
- **Schema mismatch**: blocking modal with copy-pastable agent prompt; Quit or Continue-read-only.

### Global keys
- `?` help overlay
- `q` quit (confirm if unsaved selection)
- `Esc` back one screen

### Sort/filter (Screen 1)
- `s` cycles sort key: last activity / chat count / name / health
- `/` substring filter against `display_name` + URI

### Banners
- Cursor running → top banner "⚠ Cursor running, mutations disabled" (read-only allowed).
- Schema mismatch → modal first thing.
- Empty result → centered hint.

## Schema detection & mismatch handling

`schema.py`:
```python
EXPECTED_TABLES = {"ItemTable", "cursorDiskKV"}
EXPECTED_KEYS = {"composer.composerHeaders"}
EXPECTED_HEADER_FIELDS = {
    "required": {"composerId", "createdAt", "workspaceIdentifier"},
    "expected": {"name", "lastUpdatedAt", "type", "unifiedMode", "forceMode",
                 "isArchived", "isDraft", "subtitle"},
}
EXPECTED_WS_IDENTIFIER_FIELDS = {"id"}
EXPECTED_KV_PREFIXES = {"composerData:", "bubbleId:"}
SCHEMA_VERSION = "2026-05-a"
```

`detect_mismatch(storage) -> SchemaReport` checks: tables present, `composer.composerHeaders` parses as `{allComposers: list}`, sampled headers have required fields, `cursorDiskKV` has at least one row matching each expected prefix.

**On mismatch**, the TUI shows a modal containing what's missing/unexpected plus a copy-pastable agent prompt:

```
You are updating cursor-chat-tool to a new Cursor schema version.

Current expected schema (cursor_chat_tool/schema.py):
  SCHEMA_VERSION = "2026-05-a"
  ItemTable key "composer.composerHeaders" → JSON {allComposers: [...]}
  Each header has fields: composerId, createdAt, workspaceIdentifier{id, uri|configPath}
  cursorDiskKV holds composerData:<UUID>, bubbleId:<composer>:<bubble>

Observed on this machine:
  <auto-filled: missing fields, unexpected fields, sample header dump>

Please:
  1) Update schema.py constants to match the new shape
  2) Update storage.read_headers() and operations.load_chat() if field paths moved
  3) Bump SCHEMA_VERSION and update CHANGELOG
  4) Add a test fixture under tests/fixtures/ reflecting this version
```

User can `[c]` continue read-only or `[q]` quit. Mutations are blocked until the mismatch is resolved.

## Safety model

Every mutation passes through these checks in order:

1. **Cursor-running check** — `tasklist`/`pgrep` for Cursor. If running, abort with a clear message (v1 does not offer to kill it).
2. **Lock pre-check** — open with `BEGIN IMMEDIATE; ROLLBACK;` to confirm a write lock is obtainable.
3. **Per-session full DB backup** — first mutation of a session copies `state.vscdb` to `state.vscdb.fullbackup.<ISO-ts>` (one snapshot per session, not per op).
4. **Per-op headers backup** — before each `composer.composerHeaders` rewrite, dump the current value to `~/.cursor-chat-tool/backups/composerHeaders_<ISO-ts>_<op>.json`.
5. **Transaction discipline** — single `UPDATE`, `commit()`, then `PRAGMA wal_checkpoint(FULL)` *outside* the transaction. (Codifies the bug we hit during manual recovery: PRAGMA inside an open txn raises "database table is locked".)
6. **Result dialog** — shows backup paths and an "Undo last operation" option that re-reads the per-op JSON and writes it back.
7. **Backups retention** — keep last 20 headers backups under `~/.cursor-chat-tool/backups/`; full-DB backups listed but never auto-deleted (user-managed).
8. **Read-only mode** — `--readonly` CLI flag, plus auto-engaged on schema mismatch or detected Cursor-running. All mutating `operations.*` functions check a flag on the `Storage` handle and refuse.

**Deliberately not in v1:** writes to `cursorDiskKV` rows, deletion of any kind, direct touching of `state.vscdb-wal`/`-shm`.

## CLI surface

```
cursor-chat-tool                         # launch TUI
cursor-chat-tool --readonly              # TUI with mutations disabled
cursor-chat-tool --list                  # print workspaces table to stdout, exit
cursor-chat-tool --list --json           # machine-readable
cursor-chat-tool --export <COMPOSER_ID> [--format markdown|json] [-o FILE]
cursor-chat-tool --reassign <COMPOSER_ID>[,<ID>,...] <TARGET_WS_ID>
cursor-chat-tool --merge <SRC_WS_ID> <TARGET_WS_ID>
cursor-chat-tool --version
```

Non-interactive mutations require a `--yes` flag, do all the same safety checks, and print backup paths to stdout.

## Testing strategy

**Fixtures** generated by `tests/fixtures/make_fixture.py` from JSON specs and committed to the repo:
- `globalStorage_minimal.vscdb` — 3 workspaces, ~10 headers, ~30 bubbles; drives most tests.
- `globalStorage_schema_drift.vscdb` — one renamed field (`workspaceIdentifier` → `workspaceId`); exercises mismatch detection.
- `globalStorage_corrupt.vscdb` — missing/empty tables.

Each fixture pairs with a synthetic `workspaceStorage/` tree (obsolete markers, missing dirs) built by the same script.

**Test files:**

| File | Coverage |
|---|---|
| `test_paths.py` | OS detection, ssh-remote hex authority decode |
| `test_schema.py` | `detect_mismatch` on all fixtures; agent-prompt snapshot |
| `test_storage.py` | open RO/RW; backup creation; WAL checkpoint outside txn; lock pre-check |
| `test_operations.py` | `list_workspaces` health classification; `list_chats` ordering+limit; `load_chat` bubble parsing; reassign round-trip; merge; export markdown/json |
| `test_cli.py` | non-interactive paths and exit codes |
| `test_tui_smoke.py` | one smoke test per screen using prompt_toolkit's `create_pipe_input` + `DummyOutput`; asserts breadcrumb + visible row text |

**Critical invariants (each its own test):**
1. **Round-trip identity**: reassign + undo restores `composer.composerHeaders` byte-equal.
2. **Backup-before-write**: assertion in `operations.reassign_chats` that the headers backup file exists on disk before the UPDATE runs; test exercises both happy path and assertion firing.
3. **No-checkpoint-in-txn regression**: verifies `PRAGMA wal_checkpoint` is called after `commit()` and not inside.
4. **Cursor-running guard**: monkeypatch the process check; assert mutations refuse, read-only ops succeed.
5. **Schema-drift fixture**: `detect_mismatch` flags the renamed field; mutations refuse; agent prompt contains the diff.
6. **Empty/corrupt DB**: useful error, non-zero exit, no half-writes.

**Out of v1 testing:** visual regression of the TUI; performance on real ~9 GB DBs (covered manually on the dev machine).

**CI** (`.github/workflows/ci.yml`): matrix on Python 3.10/3.11/3.12, `uv sync --dev`, `uv run pytest`, `uv run ruff check`, `uv run mypy src/`.

## Packaging

- Standard `pyproject.toml` with hatchling or setuptools backend.
- Console script entry point: `cursor-chat-tool = cursor_chat_tool.cli:main`.
- Install with `uv tool install cursor-chat-tool` or `pipx install cursor-chat-tool`.
- Min Python: 3.10 (for `match`, `Literal`, modern type unions).
- Runtime deps: `prompt_toolkit`. stdlib for everything else (sqlite3, json, dataclasses, pathlib).
- Dev deps: `pytest`, `pytest-snapshot` (or syrupy), `ruff`, `mypy`.

## Open items deferred to v2+

- Delete / purge orphans operation.
- Full-text search.
- Remote Cursor server's `~/.cursor-server/` discovery.
- Reading-from-backup mode (open `state.vscdb.backup` instead of live DB to inspect a snapshot).
- Bulk export (one file per chat, organized by workspace).
- VS Code chat data if Cursor's schema ever becomes upstream.
