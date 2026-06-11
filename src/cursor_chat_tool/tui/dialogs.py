"""Dialog screens (pick-target, confirm, result, schema-mismatch).

These implement the Screen protocol from :mod:`cursor_chat_tool.tui.app` so they
can be pushed onto the navigation stack like any other screen. Escape pops the
stack via the global binding, which doubles as "cancel".
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from prompt_toolkit.key_binding import KeyBindings

if TYPE_CHECKING:
    from cursor_chat_tool.model import Workspace
    from cursor_chat_tool.tui.app import AppState


class PickTargetScreen:
    """Lists workspaces; ``enter`` invokes ``on_pick`` with the selection."""

    def __init__(
        self,
        state: AppState,
        workspaces: list[Workspace],
        on_pick: Callable[[Workspace], None],
    ) -> None:
        self.state = state
        self.workspaces = workspaces
        self.on_pick = on_pick
        self.cursor: int = 0

    def title(self) -> str:
        return "Pick target"

    def footer_hints(self) -> str:
        return "[enter] choose  [esc] cancel"

    def render(self) -> list[tuple[str, str]]:
        rows = self.workspaces
        if rows and self.cursor >= len(rows):
            self.cursor = len(rows) - 1
        if self.cursor < 0:
            self.cursor = 0

        fragments: list[tuple[str, str]] = [
            ("class:header", "Select a target workspace:\n\n")
        ]
        if not rows:
            fragments.append(("class:row", "  (no workspaces)\n"))
            return fragments
        for i, w in enumerate(rows):
            marker = "> " if i == self.cursor else "  "
            line = f"{marker}{w.display_name}  ({w.identifier.id})"
            cls = "class:row-selected" if i == self.cursor else "class:row"
            fragments.append((cls, line + "\n"))
        return fragments

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _(event: Any) -> None:
            if self.cursor > 0:
                self.cursor -= 1

        @kb.add("down")
        def _(event: Any) -> None:
            if self.cursor < len(self.workspaces) - 1:
                self.cursor += 1

        @kb.add("enter")
        def _(event: Any) -> None:
            if 0 <= self.cursor < len(self.workspaces):
                self.on_pick(self.workspaces[self.cursor])

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
            from cursor_chat_tool.tui.app import get_nav

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
    """Confirms an output directory; ``enter`` submits, Esc cancels.

    For v1 the path is not live-editable: ``enter`` submits ``default_dir``.
    """

    def __init__(
        self,
        state: AppState,
        default_dir: str,
        on_submit: Callable[[str], None],
    ) -> None:
        from prompt_toolkit.buffer import Buffer

        self.state = state
        self.default_dir = default_dir
        self.on_submit = on_submit
        self.buffer = Buffer()
        self.buffer.text = default_dir

    def title(self) -> str:
        return "Export"

    def footer_hints(self) -> str:
        return "[enter] save  [esc] cancel"

    def render(self) -> list[tuple[str, str]]:
        return [
            (
                "class:header",
                "Export to directory (Enter to save, Esc to cancel):\n\n",
            ),
            ("class:row", "  " + self.buffer.text + "\n"),
        ]

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("enter")
        def _(event: Any) -> None:
            self.on_submit(self.default_dir)

        return kb


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
