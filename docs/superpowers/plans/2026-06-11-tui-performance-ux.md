# TUI Performance & UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the TUI fast on multi-GB Cursor DBs, add loading cues, context-sensitive key hints + help screen, a path-based pick-target screen, filtering, and scrolling.

**Architecture:** Fix the storage layer first (indexed range scans instead of un-indexed `LIKE`, one grouped bubble-count query instead of per-chat scans), then layer TUI improvements on the existing Screen-protocol/NavStack design: a `footer_hints()` protocol method, a `HelpScreen`, `[SetCursorPosition]`-based scrolling, a shared filter-mode helper, a rebuilt `PickTargetScreen`, and async background loading with a spinner.

**Tech Stack:** Python 3.10+, sqlite3, prompt_toolkit 3.x, pytest. Spec: `docs/superpowers/specs/2026-06-11-tui-performance-ux-design.md`.

**Conventions:** mypy strict is on for `src/` — keep annotations complete. Run commands with `uv run`. Commit after each task. All tests: `uv run pytest -q`. Lint: `uv run ruff check src tests`. Types: `uv run mypy`.

---

### Task 1: Storage — indexed range scans + grouped counts

**Files:**
- Modify: `src/cursor_chat_tool/storage.py` (methods `read_kv_by_prefix`, `count_kv_by_prefix`; add `count_kv_grouped`)
- Test: `tests/test_storage.py`

The `cursorDiskKV` table has `key TEXT PRIMARY KEY`. `LIKE 'prefix%'` cannot use that index (default case-insensitive LIKE) → full table scans. Replace with `key >= prefix AND key < prefix + '￿'` (keys are ASCII, so `'￿'` is a valid exclusive upper bound).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_storage.py`:

```python
def test_read_kv_by_prefix_uses_range_not_like(minimal_db):
    from cursor_chat_tool.storage import Storage
    with Storage.open_readonly(minimal_db) as s:
        calls: list[str] = []
        real_execute = s._con.execute

        def spy(sql, *a, **k):
            calls.append(sql)
            return real_execute(sql, *a, **k)

        s._con.execute = spy  # type: ignore[method-assign]
        rows = s.read_kv_by_prefix("bubbleId:c-alpha-1:")
        assert rows  # fixture has bubbles for c-alpha-1
        assert all("LIKE" not in q.upper() for q in calls)


def test_count_kv_by_prefix_uses_range_not_like(minimal_db):
    from cursor_chat_tool.storage import Storage
    with Storage.open_readonly(minimal_db) as s:
        calls: list[str] = []
        real_execute = s._con.execute

        def spy(sql, *a, **k):
            calls.append(sql)
            return real_execute(sql, *a, **k)

        s._con.execute = spy  # type: ignore[method-assign]
        n = s.count_kv_by_prefix("bubbleId:c-alpha-1:")
        assert n >= 1
        assert all("LIKE" not in q.upper() for q in calls)


def test_count_kv_grouped(minimal_db):
    from cursor_chat_tool.storage import Storage
    with Storage.open_readonly(minimal_db) as s:
        counts = s.count_kv_grouped("bubbleId:")
        # Every per-chat count must agree with the single-prefix counter.
        assert counts
        for cid, n in counts.items():
            assert n == s.count_kv_by_prefix(f"bubbleId:{cid}:")
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_storage.py -q`
Expected: `test_count_kv_grouped` FAILS (AttributeError: no `count_kv_grouped`); the LIKE tests FAIL (`LIKE` found in calls).

- [ ] **Step 3: Implement**

In `src/cursor_chat_tool/storage.py`, add a module-level helper and rewrite the three methods:

```python
def _prefix_range(prefix: str) -> tuple[str, str]:
    """Inclusive/exclusive key range covering all keys starting with prefix.

    Keys in cursorDiskKV are ASCII, so '￿' sorts after any suffix.
    """
    return prefix, prefix + "￿"
```

```python
    def read_kv_by_prefix(self, prefix: str) -> list[tuple[str, dict[str, Any]]]:
        lo, hi = _prefix_range(prefix)
        rows = self._con.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ?",
            (lo, hi),
        ).fetchall()
        # Some rows carry NULL values in real Cursor DBs; skip those rather than crash.
        return [(str(k), json.loads(v)) for k, v in rows if v is not None]

    def count_kv_by_prefix(self, prefix: str) -> int:
        lo, hi = _prefix_range(prefix)
        row = self._con.execute(
            "SELECT COUNT(*) FROM cursorDiskKV WHERE key >= ? AND key < ?",
            (lo, hi),
        ).fetchone()
        return int(row[0])

    def count_kv_grouped(self, prefix: str) -> dict[str, int]:
        """Count keys under prefix, grouped by the first ':'-delimited segment
        after the prefix (e.g. composer id for 'bubbleId:'). One index-only scan."""
        lo, hi = _prefix_range(prefix)
        rows = self._con.execute(
            "SELECT key FROM cursorDiskKV WHERE key >= ? AND key < ?",
            (lo, hi),
        ).fetchall()
        counts: dict[str, int] = {}
        plen = len(prefix)
        for (key,) in rows:
            group = str(key)[plen:].split(":", 1)[0]
            counts[group] = counts.get(group, 0) + 1
        return counts
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/cursor_chat_tool/storage.py tests/test_storage.py
git commit -m "perf(storage): replace un-indexed LIKE scans with PK range scans; add grouped counts"
```

---

### Task 2: Operations — O(1) bubble-count queries in list_chats

**Files:**
- Modify: `src/cursor_chat_tool/operations.py` (`_parse_header`, `list_chats`, `load_chat`)
- Test: `tests/test_operations.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_operations.py`:

```python
def test_list_chats_issues_constant_queries(minimal_db, workspace_storage_dir):
    """Bubble counts must come from ONE grouped query, not one scan per chat."""
    from cursor_chat_tool import operations, storage
    with storage.Storage.open_readonly(minimal_db) as s:
        calls: list[str] = []
        real_execute = s._con.execute

        def spy(sql, *a, **k):
            calls.append(sql)
            return real_execute(sql, *a, **k)

        s._con.execute = spy  # type: ignore[method-assign]
        chats = operations.list_chats(s, "ws-alpha")
        assert len(chats) >= 2
        kv_queries = [q for q in calls if "cursorDiskKV" in q]
        assert len(kv_queries) == 1
        # counts still correct
        by_id = {c.composer_id: c.bubble_count_hint for c in chats}
        assert by_id["c-alpha-1"] and by_id["c-alpha-1"] > 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_operations.py::test_list_chats_issues_constant_queries -q`
Expected: FAIL — `len(kv_queries)` equals the number of chats, not 1.

- [ ] **Step 3: Implement**

In `src/cursor_chat_tool/operations.py`:

Change `_parse_header` to take the count explicitly (no Storage dependency):

```python
def _parse_header(h: dict[str, Any], bubble_count: int | None) -> ChatHeader:
    cid = h["composerId"]
    created = _coerce_ts(h.get("createdAt")) or datetime.min
    last_dt = _coerce_ts(h.get("lastUpdatedAt"))
    ws_id = (h.get("workspaceIdentifier") or {}).get("id", "")
    return ChatHeader(
        composer_id=cid,
        name=h.get("name"),
        created_at=created,
        last_updated_at=last_dt,
        workspace_id=str(ws_id),
        subtitle=h.get("subtitle"),
        bubble_count_hint=bubble_count,
        raw=h,
    )
```

In `list_chats`, replace the final return with one grouped count:

```python
    counts = storage_.count_kv_grouped("bubbleId:")
    return [_parse_header(h, counts.get(h["composerId"], 0)) for h in matched]
```

In `load_chat`, replace `header = _parse_header(header_raw, storage_)` with:

```python
    header = _parse_header(header_raw, bubble_count=len(bubbles))
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q` — expected: all pass.
Run: `uv run mypy` — expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/cursor_chat_tool/operations.py tests/test_operations.py
git commit -m "perf(operations): single grouped bubble-count query in list_chats"
```

---

### Task 3: Footer hints protocol + "move" terminology

**Files:**
- Modify: `src/cursor_chat_tool/tui/app.py` (Screen protocol, footer, on_reassign messages)
- Modify: `src/cursor_chat_tool/tui/screen_workspaces.py`, `screen_chats.py`, `screen_messages.py`, `dialogs.py`
- Test: `tests/test_tui_smoke.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tui_smoke.py`:

```python
def test_footer_hints_per_screen(minimal_db, workspace_storage_dir):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_chats import ChatsScreen
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    ws_screen = WorkspacesScreen(state)
    assert "[enter] open" in ws_screen.footer_hints()
    with storage.Storage.open_readonly(minimal_db) as s:
        ws = next(w for w in operations.list_workspaces(s, workspace_storage_dir)
                  if w.identifier.id == "ws-alpha")
    chats = ChatsScreen(state, ws)
    hints = chats.footer_hints()
    assert "[m] move" in hints
    assert "[space] select" in hints
    assert "[e] export" in hints


def test_move_key_m_triggers_reassign(minimal_db, workspace_storage_dir):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_chats import ChatsScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    with storage.Storage.open_readonly(minimal_db) as s:
        ws = next(w for w in operations.list_workspaces(s, workspace_storage_dir)
                  if w.identifier.id == "ws-alpha")
    calls: list[list[str]] = []
    screen = ChatsScreen(state, ws, on_reassign=lambda ids, src: calls.append(ids))
    kb = screen.get_key_bindings()
    keys = {tuple(b.keys) for b in kb.bindings}
    assert ("m",) in keys
    assert ("r",) in keys  # legacy alias kept
```

Note: this test changes `on_reassign` to a two-arg callback `(ids, source_workspace)` — that signature change is part of this task (needed by Task 6's pick-target overhaul).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tui_smoke.py -q`
Expected: FAIL — no `footer_hints`, no `m` binding.

- [ ] **Step 3: Implement**

`app.py` — extend the protocol and footer:

```python
@runtime_checkable
class Screen(Protocol):
    def title(self) -> str: ...
    def render(self) -> list[tuple[str, str]]: ...
    def get_key_bindings(self) -> KeyBindings: ...
    def footer_hints(self) -> str:
        """Key-hint line for the footer, e.g. '[enter] open  [s] sort'."""
        ...
```

Footer window in `_build_application`:

```python
    footer = Window(
        content=FormattedTextControl(
            lambda: [("class:footer", f" {nav.current.footer_hints()}  [?] help  [q] quit ")]
        ),
        height=1,
    )
```

Add `footer_hints` to every screen:

- `WorkspacesScreen`: `return "[enter] open  [s] sort  [↑/↓] move"` (Task 5 adds filter to this string)
- `ChatsScreen`: `return "[enter] open  [space] select  [a] all  [A] none  [m] move  [e] export  [esc] back"`
- `MessagesScreen`: `return "[e] export  [esc] back"` (Task 4 adds scroll keys)
- `PickTargetScreen`: `return "[enter] choose  [esc] cancel"`
- `ConfirmScreen`: `return "[y] yes  [n]/[esc] no"`
- `ResultScreen`: `return "[esc] close"`
- `ExportPathScreen`: `return "[enter] save  [esc] cancel"`
- `SchemaMismatchScreen`: `return "[q] quit"`

`screen_chats.py` — change the callback type to include the source workspace, bind `m` plus legacy `r`:

```python
        on_reassign: Callable[[list[str], Workspace], None] | None = None,
```

```python
        @kb.add("m")
        @kb.add("r")
        def _(event: Any) -> None:
            ids = self._ids_for_action()
            if self.on_reassign is not None and ids:
                self.on_reassign(ids, self.workspace)
```

`app.py` — update `on_reassign` signature and user-facing copy (full updated closure; the
`source_ws` parameter is stored for Task 6, unused for now is fine — name it and pass through):

```python
    def on_reassign(ids: list[str], source_ws: Any) -> None:
        if state.readonly:
            nav.push(dialogs.ResultScreen(state, ["Read-only mode: mutations disabled."]))
            return

        with storage.Storage.open_readonly(state.global_db) as s:
            from cursor_chat_tool import operations
            workspaces = operations.list_workspaces(
                s, state.workspace_storage, state.workspaces_config
            )

        chats_depth = len(nav.stack)

        def on_pick(target_ws: Any) -> None:
            nav.pop()

            def on_yes() -> None:
                backup_dir = Path.home() / ".cursor-chat-tool" / "backups"
                while len(nav.stack) > chats_depth:
                    nav.pop()
                try:
                    res = actions.perform_reassign(
                        state.global_db, backup_dir, ids,
                        target_ws.identifier.id, cursor_running_check=check,
                    )
                except storage.CursorRunning as e:
                    nav.push(dialogs.ResultScreen(state, [f"Move failed: {e}"]))
                    return
                nav.push(dialogs.ResultScreen(state, [
                    f"Moved {len(res.composer_ids)} chat(s) to {target_ws.display_name}.",
                    f"Backup: {res.backup_path}",
                ]))

            target_path = target_ws.identifier.uri or target_ws.identifier.id
            nav.push(dialogs.ConfirmScreen(
                state,
                f'Move {len(ids)} chat(s) to "{target_ws.display_name}" ({target_path})?\n'
                "A backup will be written.",
                on_yes=on_yes,
            ))

        nav.push(dialogs.PickTargetScreen(state, workspaces, on_pick=on_pick))
```

(`PickTargetScreen` gains source-awareness in Task 6; keep its current constructor here.)

- [ ] **Step 4: Run suite + types**

Run: `uv run pytest -q` and `uv run mypy` — expected: pass/clean.

- [ ] **Step 5: Commit**

```bash
git add src/cursor_chat_tool/tui tests/test_tui_smoke.py
git commit -m "feat(tui): per-screen footer hints; rename reassign to move with m key"
```

---

### Task 4: Help screen + scrolling

**Files:**
- Modify: `src/cursor_chat_tool/tui/dialogs.py` (add `HelpScreen`)
- Modify: `src/cursor_chat_tool/tui/app.py` (`?` global binding; focusable body control)
- Modify: `src/cursor_chat_tool/tui/screen_workspaces.py`, `screen_chats.py`, `screen_messages.py`, `dialogs.py` (SetCursorPosition + paging keys)
- Test: `tests/test_tui_smoke.py`

- [ ] **Step 1: Write failing tests**

```python
def test_help_screen_lists_keys(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui import dialogs
    from cursor_chat_tool.tui.app import AppState
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    help_screen = dialogs.HelpScreen(state)
    text = "".join(t for _, t in help_screen.render())
    for needle in ("move", "export", "space", "filter", "sort", "quit"):
        assert needle in text.lower(), needle


def test_question_mark_opens_help(minimal_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("?")
        inp.send_text("\x1b")  # close help
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput())
    assert rc == 0


def test_list_screens_emit_cursor_position(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    styles = [s for s, _ in screen.render()]
    assert "[SetCursorPosition]" in styles


def test_messages_screen_scroll_bindings(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_messages import MessagesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = MessagesScreen(state, "c-alpha-1")
    keys = {tuple(b.keys) for b in screen.get_key_bindings().bindings}
    for k in (("up",), ("down",), ("pageup",), ("pagedown",)):
        assert k in keys, k
    styles = [s for s, _ in screen.render()]
    assert "[SetCursorPosition]" in styles
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tui_smoke.py -q` — expected: new tests FAIL.

- [ ] **Step 3: Implement**

`dialogs.py` — add:

```python
_HELP_TEXT = """\
Global
  ?            open this help
  q            quit
  esc          back / cancel (clears an active filter first)
  ctrl-c       force quit

Workspaces (project list)
  up/down      move selection      pgup/pgdn    page
  enter        open workspace's chats
  s            cycle sort (last activity / chat count / name / health)
  /            filter by name or path (enter keeps it, esc clears)

Chats (within a workspace)
  up/down      move selection      pgup/pgdn    page
  enter        view messages
  space        select/deselect chat for bulk actions
  a / A        select all / clear selection
  m            move selected (or highlighted) chats to another workspace
  e            export selected (or highlighted) chats to markdown files

Messages (within a chat)
  up/down, pgup/pgdn, home/end   scroll
  e            export this chat

Moving chats writes a timestamped backup first; Cursor must be closed.
"""


class HelpScreen:
    """Static key-binding reference; Esc closes via the global binding."""

    def __init__(self, state: AppState) -> None:
        self.state = state

    def title(self) -> str:
        return "Help"

    def render(self) -> list[tuple[str, str]]:
        return [("class:row", _HELP_TEXT)]

    def footer_hints(self) -> str:
        return "[esc] close"

    def get_key_bindings(self) -> KeyBindings:
        return KeyBindings()
```

`app.py` — global `?` binding (after the existing ones, inside `_build_application` it needs
access to `state`; pass `state` is already a parameter):

```python
    @global_kb.add("?")
    def _(event: Any) -> None:
        from cursor_chat_tool.tui import dialogs
        if not isinstance(nav.current, dialogs.HelpScreen):
            nav.push(dialogs.HelpScreen(state))
```

Scrolling — in `app.py`, make the body control report the cursor so the Window auto-scrolls:

```python
    body = Window(
        content=FormattedTextControl(lambda: nav.current.render(), focusable=True),
    )
```

In `screen_workspaces.py` and `screen_chats.py` `render()`, immediately before appending the
selected row's fragment, emit the cursor marker:

```python
            if i == self.cursor:
                fragments.append(("[SetCursorPosition]", ""))
```

Add paging bindings to both list screens (workspaces uses `self.visible`, chats uses `self.chats`):

```python
        @kb.add("pageup")
        def _(event: Any) -> None:
            self.cursor = max(0, self.cursor - 10)

        @kb.add("pagedown")
        def _(event: Any) -> None:
            self.cursor = min(len(self.visible) - 1, self.cursor + 10)

        @kb.add("home")
        def _(event: Any) -> None:
            self.cursor = 0

        @kb.add("end")
        def _(event: Any) -> None:
            self.cursor = len(self.visible) - 1
```

Also emit `[SetCursorPosition]` in `PickTargetScreen.render()` at its cursor row.

`screen_messages.py` — line-based scrolling. Build the line list once after load; track
`self.scroll_line`:

```python
    def __init__(self, ...):
        ...
        self.scroll_line: int = 0

    def _lines(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        if not self.chat.bubbles:
            return [("class:row", "  (no messages)\n")]
        for bubble in self.chat.bubbles:
            role = str(bubble.role)
            style = _ROLE_STYLE.get(role, "class:role-unknown")
            ts = bubble.created_at
            when = ts.strftime("%Y-%m-%d %H:%M") if ts else ""
            fragments.append((style, f"{role.upper()}  {when}".rstrip() + "\n"))
            for line in bubble.text.splitlines() or [""]:
                fragments.append(("class:row", "    " + line + "\n"))
            fragments.append(("class:row", "\n"))
        return fragments

    def render(self) -> list[tuple[str, str]]:
        lines = self._lines()
        self.scroll_line = max(0, min(self.scroll_line, len(lines) - 1))
        out: list[tuple[str, str]] = []
        for i, frag in enumerate(lines):
            if i == self.scroll_line:
                out.append(("[SetCursorPosition]", ""))
            out.append(frag)
        return out
```

Bindings (`up`, `down`, `pageup` −20, `pagedown` +20, `home` 0, `end` last line) adjusting
`self.scroll_line` with the same clamping. Update `footer_hints` to
`"[e] export  [↑/↓ pgup/pgdn] scroll  [esc] back"`.

Note: `MessagesScreen.render()` recomputes `_lines()` each frame; for very long chats cache it
(`self._line_cache: list[tuple[str, str]] | None = None`, invalidated never — chat data is
immutable for the screen's lifetime). Implement the cache.

- [ ] **Step 4: Run suite + types**

Run: `uv run pytest -q` and `uv run mypy` — expected: pass/clean.

- [ ] **Step 5: Commit**

```bash
git add src/cursor_chat_tool/tui tests/test_tui_smoke.py
git commit -m "feat(tui): help screen on '?', auto-scroll lists, scrollable messages, paging keys"
```

---

### Task 5: Filter mode (workspaces) + selection/sort indicators (chats)

**Files:**
- Create: `src/cursor_chat_tool/tui/filtering.py`
- Modify: `src/cursor_chat_tool/tui/app.py` (escape delegation)
- Modify: `src/cursor_chat_tool/tui/screen_workspaces.py`, `screen_chats.py`
- Test: `tests/test_tui_smoke.py`

- [ ] **Step 1: Write failing tests**

```python
def test_workspaces_filter_mode(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    total = len(screen.visible)
    assert total > 1
    screen.filter.active = True
    screen.filter.feed("alpha")
    assert screen.filter_text == "alpha"
    assert len(screen.visible) < total
    # esc clears the filter and is consumed
    assert screen.handle_escape() is True
    assert screen.filter_text == ""
    assert len(screen.visible) == total
    # second esc is not consumed (lets the app pop the screen)
    assert screen.handle_escape() is False


def test_workspaces_filter_via_keys(minimal_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("/alpha\r")  # filter to alpha, confirm
        inp.send_text("\x1b")       # clear filter
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput())
    assert rc == 0


def test_chats_select_all_and_clear(minimal_db, workspace_storage_dir):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_chats import ChatsScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    with storage.Storage.open_readonly(minimal_db) as s:
        ws = next(w for w in operations.list_workspaces(s, workspace_storage_dir)
                  if w.identifier.id == "ws-alpha")
    screen = ChatsScreen(state, ws)
    screen.select_all()
    assert len(screen.selected_ids) == len(screen.chats)
    text = "".join(t for _, t in screen.render())
    assert "selected" in text
    screen.clear_selection()
    assert not screen.selected_ids


def test_workspaces_header_shows_sort(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    text = "".join(t for _, t in screen.render())
    assert "last_activity" in text or "last activity" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tui_smoke.py -q` — expected: new tests FAIL.

- [ ] **Step 3: Implement**

Create `src/cursor_chat_tool/tui/filtering.py`:

```python
"""Reusable incremental text-filter state for list screens."""
from __future__ import annotations


class FilterState:
    """Tracks a live substring filter being typed by the user.

    Lifecycle: '/' sets active=True; printable keys feed(); enter deactivates
    (keeping the text); escape clears (handled by the owning screen via
    handle_escape).
    """

    def __init__(self) -> None:
        self.active: bool = False
        self.text: str = ""

    def feed(self, data: str) -> None:
        if data.isprintable():
            self.text += data

    def backspace(self) -> None:
        self.text = self.text[:-1]

    def clear(self) -> None:
        self.active = False
        self.text = ""

    def handle_escape(self) -> bool:
        """Clear the filter if set; return True when the escape was consumed."""
        if self.active or self.text:
            self.clear()
            return True
        return False

    def status(self) -> str:
        if self.active:
            return f"filter: {self.text}▌"
        if self.text:
            return f"filter: {self.text}"
        return ""
```

`app.py` — delegate escape to the screen when it wants it (replace the existing escape binding):

```python
    @global_kb.add("escape", eager=True)
    def _(event: Any) -> None:
        handler = getattr(nav.current, "handle_escape", None)
        if handler is not None and handler():
            return
        nav.pop()
```

**Critical:** prompt_toolkit prefers specific key bindings over `<any>` catch-alls, so while
the user is typing into a filter, the *global* `q` and `?` bindings would fire (quitting the
app mid-word). Gate them on a "screen is capturing text" check. In `_build_application`:

```python
    from prompt_toolkit.filters import Condition

    def _typing() -> bool:
        return bool(getattr(nav.current, "wants_text_input", lambda: False)())

    not_typing = Condition(lambda: not _typing())

    @global_kb.add("q", filter=not_typing)
    def _(event: Any) -> None:
        event.app.exit(result=0)

    @global_kb.add("?", filter=not_typing)
    def _(event: Any) -> None:
        ...  # (the Task 4 help binding, now gated)
```

Screens with a filter implement:

```python
    def wants_text_input(self) -> bool:
        return self.filter.active
```

(`WorkspacesScreen` here; `PickTargetScreen` in Task 6; `ExportPathScreen` returns `True`
unconditionally in Task 8.)

`screen_workspaces.py` — replace `filter_text` with the shared state (keep a compatibility
property), wire bindings, and show status. Key points:

```python
from cursor_chat_tool.tui.filtering import FilterState
```

```python
        self.filter = FilterState()

    @property
    def filter_text(self) -> str:
        return self.filter.text

    def handle_escape(self) -> bool:
        return self.filter.handle_escape()
```

In `visible`, use `self.filter.text` instead of `self.filter_text` (the property keeps external
readers working).

In `render()`, prepend a status line above the column header:

```python
        status = f"sorted by: {self.sort_key}"
        fstat = self.filter.status()
        if fstat:
            status += f"   {fstat} — {len(rows)}/{len(self.workspaces)} shown"
        fragments.append(("class:header", " " + status + "\n"))
```

Bindings — register the catch-all FIRST so explicit keys win, and guard everything on
`self.filter.active`:

```python
        from prompt_toolkit.filters import Condition

        in_filter = Condition(lambda: self.filter.active)
        not_in_filter = Condition(lambda: not self.filter.active)

        @kb.add("<any>", filter=in_filter)
        def _(event: Any) -> None:
            if event.data:
                self.filter.feed(event.data)
                self.cursor = 0

        @kb.add("backspace", filter=in_filter)
        def _(event: Any) -> None:
            self.filter.backspace()

        @kb.add("enter", filter=in_filter)
        def _(event: Any) -> None:
            self.filter.active = False

        @kb.add("/", filter=not_in_filter)
        def _(event: Any) -> None:
            self.filter.active = True
```

Gate the existing `s` and `enter` bindings with `filter=not_in_filter` (up/down can stay
unguarded — arrows aren't printable so `<any>` ignores them, and moving while filtering is fine).

`footer_hints()` becomes dynamic:

```python
    def footer_hints(self) -> str:
        if self.filter.active:
            return "type to filter  [enter] done  [esc] clear"
        return "[enter] open  [s] sort  [/] filter  [↑/↓] move"
```

`screen_chats.py` — selection helpers + indicator + keys:

```python
    def select_all(self) -> None:
        self.selected_ids = {c.composer_id for c in self.chats}

    def clear_selection(self) -> None:
        self.selected_ids = set()
```

In `render()`, prepend before the column header when relevant:

```python
        if self.selected_ids:
            fragments.append(
                ("class:header", f" {len(self.selected_ids)} selected\n")
            )
```

Bindings:

```python
        @kb.add("a")
        def _(event: Any) -> None:
            self.select_all()

        @kb.add("A")
        def _(event: Any) -> None:
            self.clear_selection()
```

- [ ] **Step 4: Run suite + types**

Run: `uv run pytest -q` and `uv run mypy` — expected: pass/clean.

- [ ] **Step 5: Commit**

```bash
git add src/cursor_chat_tool/tui tests/test_tui_smoke.py
git commit -m "feat(tui): live '/' filter on workspaces, select-all/clear and indicators on chats"
```

---

### Task 6: PickTargetScreen overhaul (path-based identification)

**Files:**
- Modify: `src/cursor_chat_tool/tui/dialogs.py` (`PickTargetScreen`)
- Modify: `src/cursor_chat_tool/tui/app.py` (pass source workspace + chat count)
- Test: `tests/test_tui_smoke.py`

- [ ] **Step 1: Write failing tests**

```python
def _mk_pick(minimal_db, workspace_storage_dir, n_chats=2):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui import dialogs
    from cursor_chat_tool.tui.app import AppState
    state = AppState(readonly=False, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    with storage.Storage.open_readonly(minimal_db) as s:
        wslist = operations.list_workspaces(s, workspace_storage_dir)
    source = next(w for w in wslist if w.identifier.id == "ws-alpha")
    picked: list = []
    screen = dialogs.PickTargetScreen(
        state, wslist, on_pick=picked.append,
        source=source, chat_count=n_chats,
    )
    return screen, wslist, source, picked


def test_pick_target_shows_paths_and_source(minimal_db, workspace_storage_dir):
    screen, wslist, source, _ = _mk_pick(minimal_db, workspace_storage_dir)
    text = "".join(t for _, t in screen.render())
    # identifies targets by path like the workspaces screen
    with_uri = next(w for w in wslist if w.identifier.uri and w.identifier.id != "ws-alpha")
    assert (w := with_uri.identifier.uri) and w[-20:] in text
    # header explains the move
    assert "Move 2 chat(s)" in text
    assert source.display_name in text
    # the source row is marked
    assert "(current)" in text


def test_pick_target_skips_source_on_enter(minimal_db, workspace_storage_dir):
    screen, wslist, source, picked = _mk_pick(minimal_db, workspace_storage_dir)
    # point the cursor at the source row, enter must be a no-op
    from prompt_toolkit.keys import Keys
    rows = screen.visible
    screen.cursor = next(i for i, w in enumerate(rows)
                         if w.identifier.id == source.identifier.id)
    # NB: "enter" registers as Keys.ControlM, not the literal string "enter"
    for b in screen.get_key_bindings().bindings:
        if tuple(b.keys) == (Keys.ControlM,):
            b.handler(None)  # type: ignore[arg-type]
    assert picked == []


def test_pick_target_filter(minimal_db, workspace_storage_dir):
    screen, wslist, _, _ = _mk_pick(minimal_db, workspace_storage_dir)
    total = len(screen.visible)
    screen.filter.active = True
    screen.filter.feed("beta")
    assert 0 < len(screen.visible) < total
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tui_smoke.py -q` — expected: new tests FAIL (constructor lacks
`source`/`chat_count`, no `visible`, no `filter`).

- [ ] **Step 3: Implement**

Rewrite `PickTargetScreen` in `dialogs.py`:

```python
from cursor_chat_tool.tui.filtering import FilterState

_PT_NAME_WIDTH = 28


class PickTargetScreen:
    """Pick a move target. Identifies workspaces by name + path + activity,
    mirroring the workspaces screen, so ambiguous names are distinguishable."""

    def __init__(
        self,
        state: AppState,
        workspaces: list[Workspace],
        on_pick: Callable[[Workspace], None],
        source: Workspace | None = None,
        chat_count: int = 1,
    ) -> None:
        self.state = state
        self.workspaces = workspaces
        self.on_pick = on_pick
        self.source = source
        self.chat_count = chat_count
        self.cursor: int = 0
        self.filter = FilterState()

    @property
    def visible(self) -> list[Workspace]:
        items = self.workspaces
        needle = self.filter.text.lower()
        if needle:
            items = [
                w for w in items
                if needle in w.display_name.lower()
                or needle in (w.identifier.uri or "").lower()
            ]
        return items

    def _is_source(self, w: Workspace) -> bool:
        return self.source is not None and w.identifier.id == self.source.identifier.id

    def title(self) -> str:
        return "Move to"

    def render(self) -> list[tuple[str, str]]:
        rows = self.visible
        if rows and self.cursor >= len(rows):
            self.cursor = len(rows) - 1
        if self.cursor < 0:
            self.cursor = 0

        src = f' from "{self.source.display_name}"' if self.source else ""
        fragments: list[tuple[str, str]] = [
            ("class:header", f"Move {self.chat_count} chat(s){src} to:\n")
        ]
        fstat = self.filter.status()
        if fstat:
            fragments.append(
                ("class:header",
                 f" {fstat} — {len(rows)}/{len(self.workspaces)} shown\n")
            )
        header = f"   {'NAME':<{_PT_NAME_WIDTH}}  {'CHATS':>5}  {'LAST ACTIVITY':<16}  PATH"
        fragments.append(("class:header", header + "\n"))

        if not rows:
            fragments.append(("class:row", "  (no matching workspaces)\n"))
            return fragments

        for i, w in enumerate(rows):
            marker = "> " if i == self.cursor else "  "
            name = w.display_name
            if self._is_source(w):
                name += " (current)"
            if len(name) > _PT_NAME_WIDTH:
                name = name[: _PT_NAME_WIDTH - 1] + "…"
            last = w.last_chat_at.strftime("%Y-%m-%d %H:%M") if w.last_chat_at else "-"
            uri = w.identifier.uri or f"[{w.identifier.id}]"
            if len(uri) > 60:
                uri = "…" + uri[-59:]
            line = (
                f"{marker}{name:<{_PT_NAME_WIDTH}}  {w.chat_count:>5}  {last:<16}  {uri}"
            )
            if i == self.cursor:
                fragments.append(("[SetCursorPosition]", ""))
            cls = "class:row-selected" if i == self.cursor else (
                "class:row-dim" if self._is_source(w) else "class:row"
            )
            fragments.append((cls, line + "\n"))
        return fragments

    def footer_hints(self) -> str:
        if self.filter.active:
            return "type to filter  [enter] done  [esc] clear"
        return "[enter] choose  [/] filter  [esc] cancel"

    def handle_escape(self) -> bool:
        return self.filter.handle_escape()

    def wants_text_input(self) -> bool:
        return self.filter.active

    def get_key_bindings(self) -> KeyBindings:
        from prompt_toolkit.filters import Condition

        kb = KeyBindings()
        in_filter = Condition(lambda: self.filter.active)
        not_in_filter = Condition(lambda: not self.filter.active)

        @kb.add("<any>", filter=in_filter)
        def _(event: Any) -> None:
            if event.data:
                self.filter.feed(event.data)
                self.cursor = 0

        @kb.add("backspace", filter=in_filter)
        def _(event: Any) -> None:
            self.filter.backspace()

        @kb.add("enter", filter=in_filter)
        def _(event: Any) -> None:
            self.filter.active = False

        @kb.add("/", filter=not_in_filter)
        def _(event: Any) -> None:
            self.filter.active = True

        @kb.add("up")
        def _(event: Any) -> None:
            if self.cursor > 0:
                self.cursor -= 1

        @kb.add("down")
        def _(event: Any) -> None:
            if self.cursor < len(self.visible) - 1:
                self.cursor += 1

        @kb.add("enter", filter=not_in_filter)
        def _(event: Any) -> None:
            rows = self.visible
            if 0 <= self.cursor < len(rows) and not self._is_source(rows[self.cursor]):
                self.on_pick(rows[self.cursor])

        return kb
```

Add the dim style to `_STYLE` in `app.py`: `"row-dim": "#666666"`.

In `app.py` `on_reassign`, pass the new arguments:

```python
        nav.push(dialogs.PickTargetScreen(
            state, workspaces, on_pick=on_pick,
            source=source_ws, chat_count=len(ids),
        ))
```

Top-of-file imports in `dialogs.py` need `Workspace` at runtime now (it was TYPE_CHECKING-only);
move it to a real import.

- [ ] **Step 4: Run suite + types**

Run: `uv run pytest -q` and `uv run mypy` — expected: pass/clean.

- [ ] **Step 5: Commit**

```bash
git add src/cursor_chat_tool/tui tests/test_tui_smoke.py
git commit -m "feat(tui): pick-target shows paths/activity, marks source, supports filtering"
```

---

### Task 7: Async loading with spinner

**Files:**
- Create: `src/cursor_chat_tool/tui/loading.py`
- Modify: `src/cursor_chat_tool/tui/app.py` (AppState.sync_load, run_tui param, refresh_interval)
- Modify: `src/cursor_chat_tool/tui/screen_workspaces.py`, `screen_chats.py`, `screen_messages.py`
- Test: `tests/test_tui_smoke.py`

- [ ] **Step 1: Write failing tests**

```python
def test_screens_load_sync_without_event_loop(minimal_db, workspace_storage_dir):
    """Direct construction outside an app must still load immediately."""
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    assert screen.workspaces  # loaded synchronously
    assert screen.loading is False


def test_loading_render_shows_spinner(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    screen.loading = True
    text = "".join(t for _, t in screen.render())
    assert "Loading" in text


def test_load_error_renders_error(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    screen.error = "boom"
    text = "".join(t for _, t in screen.render())
    assert "boom" in text


def test_run_tui_sync_load_flag(minimal_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("\r\r\x1b\x1bq")  # drill to messages and back, deterministic
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput(), sync_load=True)
    assert rc == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tui_smoke.py -q` — expected: FAIL (`loading` attribute missing,
`sync_load` unknown kwarg).

- [ ] **Step 3: Implement**

Create `src/cursor_chat_tool/tui/loading.py`:

```python
"""Background data loading for TUI screens with a spinner fallback."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner_frame() -> str:
    return _SPINNER[int(time.monotonic() * 10) % len(_SPINNER)]


def start_load(
    sync: bool,
    load_fn: Callable[[], T],
    on_done: Callable[[T], None],
    on_error: Callable[[str], None],
) -> None:
    """Run load_fn and deliver the result.

    Synchronous when sync is true or no asyncio loop is running (unit tests,
    pre-app construction); otherwise runs in a thread-pool executor and
    invalidates the app on completion so the spinner is replaced.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if sync or loop is None:
        try:
            on_done(load_fn())
        except Exception as e:  # surface, never crash the app loop
            on_error(str(e))
        return

    from prompt_toolkit.application import get_app

    app = get_app()

    async def task() -> None:
        try:
            result = await asyncio.get_running_loop().run_in_executor(None, load_fn)
        except Exception as e:
            on_error(str(e))
        else:
            on_done(result)
        finally:
            app.invalidate()

    app.create_background_task(task())
```

`app.py`:

```python
@dataclass
class AppState:
    readonly: bool
    global_db: Path
    workspace_storage: Path
    workspaces_config: Path | None
    sync_load: bool = False
```

`run_tui` gains `sync_load: bool = False`, passes it into `AppState`, and the Application gets
`refresh_interval=0.1`:

```python
    return Application(
        layout=layout,
        key_bindings=key_bindings,
        style=_STYLE,
        full_screen=True,
        refresh_interval=0.1,
        input=inp,
        output=output,
    )
```

Each data screen follows the same pattern — shown for `WorkspacesScreen`; apply the analogous
change to `ChatsScreen` (rows attr `chats`) and `MessagesScreen` (loads `self.chat`; while
loading, `title()` falls back to `chat_name or composer_id` and `render()` guards on
`self.chat is None`):

```python
from cursor_chat_tool.tui.loading import spinner_frame, start_load
```

```python
    def __init__(self, state: AppState, on_open=...) -> None:
        self.state = state
        self.on_open = on_open
        self.cursor = 0
        self.filter = FilterState()
        self.sort_key = "last_activity"
        self.workspaces: list[Workspace] = []
        self.loading: bool = True
        self.error: str | None = None
        start_load(state.sync_load, self._load, self._on_loaded, self._on_error)

    def _on_loaded(self, rows: list[Workspace]) -> None:
        self.workspaces = rows
        self.loading = False

    def _on_error(self, msg: str) -> None:
        self.error = msg
        self.loading = False
```

At the top of each `render()`:

```python
        if self.error:
            return [("class:row", f"  Error: {self.error}\n")]
        if self.loading:
            return [("class:row", f"  {spinner_frame()} Loading…\n")]
```

All key handlers already no-op on empty row lists; verify each handler guards
`len(rows)` (they do via existing bounds checks — `_ids_for_action` returns `[]`,
`enter` checks `0 <= cursor < len(rows)`).

Pipe-input tests in `tests/test_tui_smoke.py` that drive multi-step flows
(`test_tui_drill_into_workspace_and_back`, `test_tui_drill_to_messages_and_back`,
`test_tui_reassign_flow_no_crash`, `test_tui_export_flow_no_crash`,
`test_workspaces_filter_via_keys`, `test_question_mark_opens_help`) must now pass
`sync_load=True` to `run_tui` for determinism. Update them.

- [ ] **Step 4: Run suite + types**

Run: `uv run pytest -q` and `uv run mypy` — expected: pass/clean.

- [ ] **Step 5: Commit**

```bash
git add src/cursor_chat_tool/tui tests/test_tui_smoke.py
git commit -m "feat(tui): background loading with animated spinner; sync_load for tests"
```

---

### Task 8: Editable export path

**Files:**
- Modify: `src/cursor_chat_tool/tui/dialogs.py` (`ExportPathScreen`)
- Test: `tests/test_tui_smoke.py`

- [ ] **Step 1: Write failing test**

```python
def test_export_path_is_editable(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui import dialogs
    from cursor_chat_tool.tui.app import AppState
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    submitted: list[str] = []
    screen = dialogs.ExportPathScreen(state, default_dir="C:/exports",
                                      on_submit=submitted.append)
    from prompt_toolkit.keys import Keys
    screen.feed("2")   # append a char
    screen.backspace()
    screen.feed("x")
    # NB: "enter" registers as Keys.ControlM, not the literal string "enter"
    for b in screen.get_key_bindings().bindings:
        if tuple(b.keys) == (Keys.ControlM,):
            b.handler(None)  # type: ignore[arg-type]
    assert submitted == ["C:/exportsx"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tui_smoke.py::test_export_path_is_editable -q` — expected: FAIL.

- [ ] **Step 3: Implement**

Replace `ExportPathScreen` (drop the unused `Buffer`):

```python
class ExportPathScreen:
    """Editable output directory; ``enter`` submits, Esc cancels."""

    def __init__(
        self,
        state: AppState,
        default_dir: str,
        on_submit: Callable[[str], None],
    ) -> None:
        self.state = state
        self.text = default_dir
        self.on_submit = on_submit

    def feed(self, data: str) -> None:
        if data.isprintable():
            self.text += data

    def backspace(self) -> None:
        self.text = self.text[:-1]

    def title(self) -> str:
        return "Export"

    def render(self) -> list[tuple[str, str]]:
        return [
            ("class:header", "Export to directory:\n\n"),
            ("class:row", "  " + self.text),
            ("class:row-selected", " "),
            ("class:row", "\n"),
        ]

    def footer_hints(self) -> str:
        return "type to edit  [enter] save  [esc] cancel"

    def wants_text_input(self) -> bool:
        return True  # gates the global q/? bindings (see Task 5)

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("<any>")
        def _(event: Any) -> None:
            if event.data:
                self.feed(event.data)

        @kb.add("backspace")
        def _(event: Any) -> None:
            self.backspace()

        @kb.add("enter")
        def _(event: Any) -> None:
            self.on_submit(self.text)

        return kb
```

(The existing `test_tui_export_flow_no_crash` still passes because `enter` submits
`self.text` which defaults to `default_dir`.)

- [ ] **Step 4: Run suite + types**

Run: `uv run pytest -q` and `uv run mypy` — expected: pass/clean.

- [ ] **Step 5: Commit**

```bash
git add src/cursor_chat_tool/tui/dialogs.py tests/test_tui_smoke.py
git commit -m "feat(tui): editable export directory"
```

---

### Task 9: Docs + final QA

**Files:**
- Modify: `README.md` (key bindings section)
- Verify: lint, types, full suite

- [ ] **Step 1: Update README**

Add/replace a "Keys" section documenting: global (`?`, `q`, `esc`, `ctrl-c`), workspaces
(`enter`, `s`, `/`, paging), chats (`enter`, `space`, `a`/`A`, `m` move, `e` export), messages
(scrolling, `e`), and a short "Moving chats" paragraph (pick target by path, confirm, backups,
Cursor must be closed). Mirror the HelpScreen text.

- [ ] **Step 2: Full verification**

```bash
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

Expected: all clean. Fix anything that isn't.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document key bindings and move flow"
```
