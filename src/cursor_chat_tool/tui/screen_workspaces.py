"""Workspaces screen: lists workspaces with cursor, filter, and sort."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings

from cursor_chat_tool import operations
from cursor_chat_tool.model import Workspace
from cursor_chat_tool.storage import Storage
from cursor_chat_tool.tui.app import AppState
from cursor_chat_tool.tui.filtering import FilterState

_SORT_KEYS = ("last_activity", "chat_count", "name", "health")


class WorkspacesScreen:
    """Root screen listing all workspaces."""

    def __init__(
        self,
        state: AppState,
        on_open: Callable[[Workspace], None] | None = None,
    ) -> None:
        self.state = state
        self.on_open = on_open
        self.cursor: int = 0
        self.filter = FilterState()
        self.sort_key: str = "last_activity"
        self.workspaces: list[Workspace] = self._load()

    def _load(self) -> list[Workspace]:
        with Storage.open_readonly(self.state.global_db) as storage_:
            return operations.list_workspaces(
                storage_,
                self.state.workspace_storage,
                self.state.workspaces_config,
            )

    @property
    def filter_text(self) -> str:
        return self.filter.text

    def handle_escape(self) -> bool:
        return self.filter.handle_escape()

    def wants_text_input(self) -> bool:
        return self.filter.active

    # -- data view --------------------------------------------------------

    @property
    def visible(self) -> list[Workspace]:
        items = self.workspaces
        if self.filter_text:
            needle = self.filter_text.lower()
            items = [
                w
                for w in items
                if needle in w.display_name.lower()
                or (w.identifier.uri or "").lower().find(needle) >= 0
            ]

        def sort_key(w: Workspace) -> Any:
            if self.sort_key == "chat_count":
                return (-w.chat_count, w.display_name.lower())
            if self.sort_key == "name":
                return w.display_name.lower()
            if self.sort_key == "health":
                return (w.health, w.display_name.lower())
            # last_activity (default): most recent first, None last
            ts = w.last_chat_at
            return (ts is None, -(ts.timestamp() if ts else 0.0))

        return sorted(items, key=sort_key)

    # -- Screen protocol --------------------------------------------------

    def title(self) -> str:
        return "Workspaces"

    def footer_hints(self) -> str:
        if self.filter.active:
            return "type to filter  [enter] done  [esc] clear"
        return "[enter] open  [s] sort  [/] filter  [↑/↓] move"

    def render(self) -> list[tuple[str, str]]:
        rows = self.visible
        if rows and self.cursor >= len(rows):
            self.cursor = len(rows) - 1
        if self.cursor < 0:
            self.cursor = 0

        fragments: list[tuple[str, str]] = []

        status = f"sorted by: {self.sort_key}"
        fstat = self.filter.status()
        if fstat:
            status += f"   {fstat} — {len(rows)}/{len(self.workspaces)} shown"
        fragments.append(("class:header", " " + status + "\n"))

        header = f"   {'HEALTH':<14} {'CHATS':>6}  {'LAST ACTIVITY':<16}  NAME"
        fragments.append(("class:header", header + "\n"))
        fragments.append(("class:header", "  " + "─" * (len(header) + 20) + "\n"))

        if not rows:
            fragments.append(("class:row", "  (no workspaces)\n"))
            return fragments

        for i, w in enumerate(rows):
            marker = "> " if i == self.cursor else "  "
            last = (
                w.last_chat_at.strftime("%Y-%m-%d %H:%M")
                if w.last_chat_at
                else "-"
            )
            uri = w.identifier.uri or ""
            if len(uri) > 50:
                uri = "…" + uri[-49:]
            line = (
                f"{marker}{w.health:<14} {w.chat_count:>6}  "
                f"{last:<16}  {w.display_name}  {uri}"
            )
            cls = "class:row-selected" if i == self.cursor else "class:row"
            if i == self.cursor:
                fragments.append(("[SetCursorPosition]", ""))
            fragments.append((cls, line + "\n"))

        return fragments

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        in_filter = Condition(lambda: self.filter.active)
        not_in_filter = Condition(lambda: not self.filter.active)

        @kb.add("up")
        def _(event: Any) -> None:
            if self.cursor > 0:
                self.cursor -= 1

        @kb.add("down")
        def _(event: Any) -> None:
            if self.cursor < len(self.visible) - 1:
                self.cursor += 1

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

        @kb.add("s", filter=not_in_filter)
        def _(event: Any) -> None:
            idx = _SORT_KEYS.index(self.sort_key)
            self.sort_key = _SORT_KEYS[(idx + 1) % len(_SORT_KEYS)]
            self.cursor = 0

        @kb.add("enter", filter=not_in_filter)
        def _(event: Any) -> None:
            rows = self.visible
            if self.on_open is not None and 0 <= self.cursor < len(rows):
                self.on_open(rows[self.cursor])

        @kb.add("/", filter=not_in_filter)
        def _(event: Any) -> None:
            self.filter.active = True

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

        return kb
