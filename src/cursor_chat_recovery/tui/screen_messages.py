"""Messages screen: renders a single chat's conversation bubbles."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prompt_toolkit.key_binding import KeyBindings

from cursor_chat_recovery import operations
from cursor_chat_recovery.model import ChatDetail
from cursor_chat_recovery.storage import Storage
from cursor_chat_recovery.tui.app import AppState
from cursor_chat_recovery.tui.loading import spinner_frame, start_load

_ROLE_STYLE = {
    "user": "class:role-user",
    "assistant": "class:role-assistant",
    "system": "class:role-system",
    "tool": "class:role-tool",
}


class MessagesScreen:
    """Screen rendering the bubbles of a single chat conversation."""

    # Chat text reads better soft-wrapped; the app body window honors this.
    wrap_lines = True

    def __init__(
        self,
        state: AppState,
        composer_id: str,
        chat_name: str | None = None,
        on_export: Callable[[list[str]], None] | None = None,
    ) -> None:
        self.state = state
        self.composer_id = composer_id
        self.chat_name = chat_name
        self.on_export = on_export
        self.chat: ChatDetail | None = None
        self.loading: bool = True
        self.error: str | None = None
        self.scroll_line: int = 0
        self._line_cache: list[tuple[str, str]] | None = None
        start_load(state.sync_load, self._load_chat, self._on_loaded, self._on_error)

    def _load_chat(self) -> ChatDetail:
        with Storage.open_readonly(self.state.global_db) as s:
            return operations.load_chat(s, self.composer_id)

    def _on_loaded(self, chat: ChatDetail) -> None:
        self.chat = chat
        self.loading = False

    def _on_error(self, msg: str) -> None:
        self.error = msg
        self.loading = False

    # -- Screen protocol --------------------------------------------------

    def title(self) -> str:
        if self.chat_name:
            return self.chat_name
        if self.chat is not None and self.chat.header.name:
            return self.chat.header.name
        return self.composer_id

    def footer_hints(self) -> str:
        return "[e] export  [↑/↓ pgup/pgdn] scroll  [esc] back"

    def _lines(self) -> list[tuple[str, str]]:
        if self.chat is None:
            return [("class:row", "  (no messages)\n")]
        if self._line_cache is not None:
            return self._line_cache
        fragments: list[tuple[str, str]] = []
        if not self.chat.bubbles:
            fragments = [("class:row", "  (no messages)\n")]
        else:
            for bubble in self.chat.bubbles:
                role = str(bubble.role)
                style = _ROLE_STYLE.get(role, "class:role-unknown")
                ts = bubble.created_at
                when = ts.strftime("%Y-%m-%d %H:%M") if ts else ""
                fragments.append((style, f"{role.upper()}  {when}".rstrip() + "\n"))
                for line in bubble.text.splitlines() or [""]:
                    fragments.append(("class:row", "    " + line + "\n"))
                fragments.append(("class:row", "\n"))
        self._line_cache = fragments
        return fragments

    def render(self) -> list[tuple[str, str]]:
        if self.error:
            return [("class:row", f"  Error: {self.error}\n")]
        if self.loading:
            return [("class:row", f"  {spinner_frame()} Loading…\n")]
        lines = self._lines()
        self.scroll_line = max(0, min(self.scroll_line, len(lines) - 1))
        out: list[tuple[str, str]] = []
        for i, frag in enumerate(lines):
            if i == self.scroll_line:
                out.append(("[SetCursorPosition]", ""))
            out.append(frag)
        return out

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _(event: Any) -> None:
            self.scroll_line = max(0, self.scroll_line - 1)

        @kb.add("down")
        def _(event: Any) -> None:
            self.scroll_line = min(len(self._lines()) - 1, self.scroll_line + 1)

        @kb.add("pageup")
        def _(event: Any) -> None:
            self.scroll_line = max(0, self.scroll_line - 20)

        @kb.add("pagedown")
        def _(event: Any) -> None:
            self.scroll_line = min(len(self._lines()) - 1, self.scroll_line + 20)

        @kb.add("home")
        def _(event: Any) -> None:
            self.scroll_line = 0

        @kb.add("end")
        def _(event: Any) -> None:
            self.scroll_line = len(self._lines()) - 1

        @kb.add("e")
        def _(event: Any) -> None:
            if self.on_export is not None:
                self.on_export([self.composer_id])

        return kb
