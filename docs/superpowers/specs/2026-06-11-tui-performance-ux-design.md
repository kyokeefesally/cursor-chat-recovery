# TUI performance & UX overhaul — design

Date: 2026-06-11
Status: approved for implementation (user delegated design authority; requirements
stated in session: speed + loading cues, move-chat discoverability/help, clearer
pick-target identification, plus any other improvements found during study).

## Problems

1. **Slow with large histories.** `Storage.count_kv_by_prefix` and
   `read_kv_by_prefix` use `LIKE 'prefix%'`. SQLite's default case-insensitive
   `LIKE` cannot use the `cursorDiskKV` primary-key index, so each call is a
   full table scan of a table that is often hundreds of MB to GBs in real
   installs. `operations.list_chats` calls `count_kv_by_prefix` once **per
   chat** via `_parse_header`, so opening a workspace with N chats does N full
   scans. `load_chat` adds two more (prefix read + recount). All of this runs
   synchronously inside prompt_toolkit key handlers, freezing the UI with no
   feedback.

2. **Move-chats flow is undiscoverable.** The only hint footer is static,
   global, and partly wrong (`[s] sort` applies only to the workspaces screen;
   `r`, `e`, `space` are never mentioned). There is no help screen.

3. **Pick-target screen is ambiguous.** It renders `display_name (workspace_id)`.
   Display names collide (same folder name in different parents) and ids are
   meaningless to users and not shown anywhere else; the workspaces screen
   identifies projects by path.

4. Additional issues found while studying:
   - `WorkspacesScreen.filter_text` exists but no key binding ever sets it —
     dead feature.
   - No scroll handling anywhere: the selection cursor walks off-screen on long
     lists; the messages screen has no scrolling at all (long chats are
     unreadable past one screenful).
   - No select-all/clear-selection on the chats screen; no indication of how
     many chats are selected.
   - No sort indicator (you can press `s` but can't see the current sort).
   - `ExportPathScreen` pretends to be editable but `enter` submits the default
     regardless of the buffer.

## Goals

- Opening a workspace or chat is near-instant on multi-GB DBs; any operation
  that may still take noticeable time shows an animated loading cue.
- Every screen advertises its key bindings in a context-sensitive footer; `?`
  opens a full help screen.
- The pick-target screen identifies workspaces the same way the workspaces
  screen does (name + path + chat count + last activity), with filter support.
- Lists scroll properly; messages are scrollable.

Non-goals: changing the data model, the CLI surface (other than docs), or the
mutation/backup semantics.

## Design

### 1. Storage: indexed range scans + bulk counts

- Replace `LIKE ?` with key-range comparisons that always use the PK index:
  `WHERE key >= :prefix AND key < :prefix || X'F8FFFFFF'`-style upper bound —
  concretely `key >= ?` and `key < prefix + '￿'` (keys are ASCII UUID/
  hex-based, so any char above ASCII works as an exclusive upper bound).
  Applied to `read_kv_by_prefix` and `count_kv_by_prefix`.
- New `Storage.count_kv_grouped(prefix: str) -> dict[str, int]`: one indexed
  range scan over `bubbleId:` keys returning counts grouped by composer id
  (`SELECT key FROM cursorDiskKV WHERE key >= ? AND key < ?`, group in Python
  by splitting the key — avoids fragile SQL string surgery and never reads
  `value`, so the scan is index-only).
- `operations.list_chats` calls `count_kv_grouped("bubbleId:")` once and passes
  counts into `_parse_header` instead of issuing a per-chat count.
- `operations.load_chat` sets `bubble_count_hint=len(bubbles)` instead of
  re-counting.

### 2. Loading cues (async loads)

- Screens that hit the DB (`WorkspacesScreen`, `ChatsScreen`, `MessagesScreen`)
  gain a loading state: constructed instantly with `loading=True`, data loaded
  via `loop.run_in_executor` scheduled with `app.create_background_task`; on
  completion they set their rows and call `app.invalidate()`.
- While loading, `render()` shows a spinner frame (`⠋⠙⠹…` braille cycle keyed
  off `time.monotonic()`); the Application gets `refresh_interval=0.1` so the
  spinner animates.
- Key handlers are safe during loading (empty row list — existing guards
  already handle this).
- Determinism for tests: `AppState` gains `sync_load: bool = False` and
  `run_tui` gains a matching parameter. A screen loads synchronously in
  `__init__` when `state.sync_load` is true **or** no asyncio event loop is
  running (covers unit tests that construct screens directly). Pipe-input
  integration tests pass `sync_load=True` to `run_tui`.

### 3. Footer hints + help screen

- Screen protocol gains `footer_hints() -> str` (each screen returns its own
  hint line; the app footer renders `nav.current.footer_hints()` plus the
  always-on `[?] help  [q] quit`).
- New `HelpScreen` (in `dialogs.py`) pushed by a global `?` binding: lists
  global keys and per-screen keys (static text, grouped by screen).
- Terminology: the user-facing word is **move** (matching user mental model).
  Key `m` is primary on the chats screen; `r` kept as a hidden alias. All
  labels/messages say "Move" ("Move 2 chats to …", "Moved 2 chat(s)…").

### 4. Pick-target screen overhaul

- Renders the same columns as the workspaces screen: NAME, CHATS, LAST
  ACTIVITY, PATH (uri; left-truncated), HEALTH — so a project is identified by
  its path exactly like in the project list.
- Title/header line: `Move N chat(s) from "<source display name>" to:`.
- The source workspace row is shown dimmed and marked `(current)`; `enter` on
  it is a no-op.
- `/` enters filter mode (live substring match on name + path), `enter`
  accepts filter, `esc` clears it; same component as workspaces filter (see 5).
- Confirm screen message includes the target's name **and path**.

### 5. Filter + sort affordances (workspaces + pick-target)

- `/` starts filter entry: footer swaps to a `filter: <text>▌` prompt; printable
  keys append, backspace deletes, `enter` confirms, `esc` cancels/clears.
  Implemented as a small shared mixin/helper so both screens behave the same.
- Active filter is shown in the header area (`filter: foo — 3/12 shown`).
- Sort: header shows the active sort key (`sorted by last activity`); `s`
  cycles as today.
- Chats screen header shows `N selected` when selection is non-empty; new keys:
  `a` select all, `A` clear selection.

### 6. Scrolling

- List screens emit a `[SetCursorPosition]` fragment at the selected row so the
  prompt_toolkit `Window` auto-scrolls to keep the selection visible. The body
  `Window` gets `allow_scroll_beyond_bottom=False`, `wrap_lines=False` for
  lists.
- `MessagesScreen` gets line-based scrolling: `up/down/pgup/pgdn/home/end`
  adjust a scroll cursor; render emits `[SetCursorPosition]` at that line.
  `pgup/pgdn` jump by ~20 lines (terminal-height detection optional).
- Page-up/page-down also bound on list screens (jump 10 rows).

### 7. Misc

- `ExportPathScreen`: make the buffer actually editable (printable keys +
  backspace edit `self.text`; `enter` submits the edited value).
- README: document all key bindings and the help screen.

## Error handling

Unchanged semantics: read-only guard, Cursor-running check, schema-mismatch
root screen, backups before mutation all stay as-is. Async loads catch
exceptions and render the error in place of rows (`Error: <msg>`), never
crashing the app loop.

## Testing

- Unit: range-scan correctness (prefix boundaries, keys with `:` suffixes),
  grouped counts, `list_chats` no longer issuing per-chat counts (assert via
  query counting on a wrapped connection), filter-mode editing, footer hints
  per screen, help screen content, pick-target rendering (path shown, source
  dimmed), move-terminology labels, export-path editing, SetCursorPosition
  fragment present at cursor row, messages scrolling bindings.
- Integration (pipe-input smoke, `sync_load=True`): existing flows plus `?`
  help open/close, `/` filter flow, `m` move flow end-to-end.
- Perf guard: test that `list_chats` over a fixture with K chats issues O(1)
  bubble-count queries (count statements via a connection wrapper), not O(K).
