"""Dialog screens (pick-target, confirm, result, schema-mismatch).

These implement the Screen protocol from :mod:`cursor_chat_recovery.tui.app` so they
can be pushed onto the navigation stack like any other screen. Escape pops the
stack via the global binding, which doubles as "cancel".
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from prompt_toolkit.key_binding import KeyBindings

from cursor_chat_recovery.tui.filtering import FilterState

if TYPE_CHECKING:
    from cursor_chat_recovery.model import Workspace
    from cursor_chat_recovery.tui.app import AppState


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

        @kb.add("enter", filter=not_in_filter)
        def _(event: Any) -> None:
            rows = self.visible
            if 0 <= self.cursor < len(rows) and not self._is_source(rows[self.cursor]):
                self.on_pick(rows[self.cursor])

        return kb


class ConfirmScreen:
    """Shows ``message``; ``y`` invokes ``on_yes``, ``n``/Esc cancels."""

    def __init__(
        self,
        state: AppState,
        message: str,
        on_yes: Callable[[], None],
    ) -> None:
        self.state = state
        self.message = message
        self.on_yes = on_yes

    def title(self) -> str:
        return "Confirm"

    def footer_hints(self) -> str:
        return "[y] yes  [n]/[esc] no"

    def render(self) -> list[tuple[str, str]]:
        return [
            ("class:row", self.message + "\n\n"),
            ("class:footer", "[y] yes  [n]/[Esc] no"),
        ]

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("y")
        def _(event: Any) -> None:
            self.on_yes()

        @kb.add("n")
        def _(event: Any) -> None:
            from cursor_chat_recovery.tui.app import get_nav

            nav = get_nav()
            if nav is not None:
                nav.pop()

        return kb


class ResultScreen:
    """Shows result/error ``lines``; Esc closes via the global binding."""

    def __init__(self, state: AppState, lines: list[str]) -> None:
        self.state = state
        self.lines = lines

    def title(self) -> str:
        return "Result"

    def footer_hints(self) -> str:
        return "[esc] close"

    def render(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = [
            ("class:row", line + "\n") for line in self.lines
        ]
        fragments.append(("class:footer", "\n[Esc] close"))
        return fragments

    def get_key_bindings(self) -> KeyBindings:
        return KeyBindings()


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
            ("class:row-selected", " "),  # block cursor
            ("class:row", "\n"),
        ]

    def footer_hints(self) -> str:
        return "type to edit  [enter] save  [esc] cancel"

    def wants_text_input(self) -> bool:
        return True  # disables the global q/? bindings while this screen is up

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


class SchemaMismatchScreen:
    """Root screen shown when the DB schema does not match; ``q`` quits."""

    def __init__(self, state: AppState, agent_prompt: str) -> None:
        self.state = state
        self.agent_prompt = agent_prompt

    def title(self) -> str:
        return "Schema mismatch"

    def footer_hints(self) -> str:
        return "[q] quit"

    def render(self) -> list[tuple[str, str]]:
        return [
            ("class:row", self.agent_prompt + "\n"),
            ("class:footer", "\n[q] quit"),
        ]

    def get_key_bindings(self) -> KeyBindings:
        return KeyBindings()
