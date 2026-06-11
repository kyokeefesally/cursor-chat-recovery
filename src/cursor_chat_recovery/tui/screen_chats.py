"""Chats screen: lists a workspace's chats with cursor and multi-select."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prompt_toolkit.key_binding import KeyBindings

from cursor_chat_recovery import operations
from cursor_chat_recovery.model import ChatHeader, Workspace
from cursor_chat_recovery.storage import Storage
from cursor_chat_recovery.tui.app import AppState
from cursor_chat_recovery.tui.loading import spinner_frame, start_load

_NAME_WIDTH = 40


class ChatsScreen:
    """Screen listing the chats belonging to a single workspace."""

    def __init__(
        self,
        state: AppState,
        workspace: Workspace,
        on_open: Callable[[ChatHeader], None] | None = None,
        on_reassign: Callable[[list[str], Workspace], None] | None = None,
        on_export: Callable[[list[str]], None] | None = None,
    ) -> None:
        self.state = state
        self.workspace = workspace
        self.on_open = on_open
        self.on_reassign = on_reassign
        self.on_export = on_export
        self.cursor: int = 0
        self.selected_ids: set[str] = set()
        self.chats: list[ChatHeader] = []
        self.loading: bool = True
        self.error: str | None = None
        start_load(state.sync_load, self._load, self._on_loaded, self._on_error)

    def _load(self) -> list[ChatHeader]:
        with Storage.open_readonly(self.state.global_db) as storage_:
            return operations.list_chats(storage_, self.workspace.identifier.id)

    def _on_loaded(self, rows: list[ChatHeader]) -> None:
        self.chats = rows
        self.loading = False

    def _on_error(self, msg: str) -> None:
        self.error = msg
        self.loading = False

    def reload(self) -> None:
        """Re-fetch rows (e.g. after chats were moved away from this workspace)."""
        self.selected_ids = set()
        self.loading = True
        self.error = None
        start_load(self.state.sync_load, self._load, self._on_loaded, self._on_error)

    # -- Screen protocol --------------------------------------------------

    def title(self) -> str:
        return self.workspace.display_name

    def render(self) -> list[tuple[str, str]]:
        if self.error:
            return [("class:row", f"  Error: {self.error}\n")]
        if self.loading:
            return [("class:row", f"  {spinner_frame()} Loading…\n")]
        rows = self.chats
        if rows and self.cursor >= len(rows):
            self.cursor = len(rows) - 1
        if self.cursor < 0:
            self.cursor = 0

        fragments: list[tuple[str, str]] = []
        if self.selected_ids:
            fragments.append(("class:header", f" {len(self.selected_ids)} selected\n"))
        header = f"   {'DATE':<16}  {'NAME':<{_NAME_WIDTH}}  MSGS"
        fragments.append(("class:header", header + "\n"))
        fragments.append(("class:header", "  " + "─" * (len(header) + 4) + "\n"))

        if not rows:
            fragments.append(("class:row", "  (no chats)\n"))
            return fragments

        for i, c in enumerate(rows):
            marker = "> " if i == self.cursor else "  "
            mark = "•" if c.composer_id in self.selected_ids else " "
            ts = c.last_updated_at or c.created_at
            date = ts.strftime("%Y-%m-%d %H:%M") if ts else "-"
            name = c.name or "(unnamed)"
            if len(name) > _NAME_WIDTH:
                name = name[: _NAME_WIDTH - 1] + "…"
            count = c.bubble_count_hint or 0
            line = f"{marker}{mark} {date:<16}  {name:<{_NAME_WIDTH}}  {count:>4}"
            cls = "class:row-selected" if i == self.cursor else "class:row"
            if i == self.cursor:
                fragments.append(("[SetCursorPosition]", ""))
            fragments.append((cls, line + "\n"))

        return fragments

    def select_all(self) -> None:
        self.selected_ids = {c.composer_id for c in self.chats}

    def clear_selection(self) -> None:
        self.selected_ids = set()

    def footer_hints(self) -> str:
        return "[enter] open  [space] select  [a] all  [A] none  [m] move  [e] export  [esc] back"

    def _ids_for_action(self) -> list[str]:
        if self.selected_ids:
            return sorted(self.selected_ids)
        if 0 <= self.cursor < len(self.chats):
            return [self.chats[self.cursor].composer_id]
        return []

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _(event: Any) -> None:
            if self.cursor > 0:
                self.cursor -= 1

        @kb.add("down")
        def _(event: Any) -> None:
            if self.cursor < len(self.chats) - 1:
                self.cursor += 1

        @kb.add("pageup")
        def _(event: Any) -> None:
            self.cursor = max(0, self.cursor - 10)

        @kb.add("pagedown")
        def _(event: Any) -> None:
            self.cursor = min(len(self.chats) - 1, self.cursor + 10)

        @kb.add("home")
        def _(event: Any) -> None:
            self.cursor = 0

        @kb.add("end")
        def _(event: Any) -> None:
            self.cursor = len(self.chats) - 1

        @kb.add("space")
        def _(event: Any) -> None:
            if 0 <= self.cursor < len(self.chats):
                cid = self.chats[self.cursor].composer_id
                if cid in self.selected_ids:
                    self.selected_ids.discard(cid)
                else:
                    self.selected_ids.add(cid)

        @kb.add("enter")
        def _(event: Any) -> None:
            if self.on_open is not None and 0 <= self.cursor < len(self.chats):
                self.on_open(self.chats[self.cursor])

        @kb.add("m")
        @kb.add("r")
        def _(event: Any) -> None:
            ids = self._ids_for_action()
            if self.on_reassign is not None and ids:
                self.on_reassign(ids, self.workspace)

        @kb.add("e")
        def _(event: Any) -> None:
            ids = self._ids_for_action()
            if self.on_export is not None and ids:
                self.on_export(ids)

        @kb.add("a")
        def _(event: Any) -> None:
            self.select_all()

        @kb.add("A")
        def _(event: Any) -> None:
            self.clear_selection()

        return kb
