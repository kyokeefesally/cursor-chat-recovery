"""Messages screen: renders a single chat's conversation bubbles."""
from __future__ import annotations

from prompt_toolkit.key_binding import KeyBindings

from cursor_chat_tool import operations
from cursor_chat_tool.model import ChatDetail
from cursor_chat_tool.storage import Storage
from cursor_chat_tool.tui.app import AppState

_ROLE_STYLE = {
    "user": "class:role-user",
    "assistant": "class:role-assistant",
    "system": "class:role-system",
    "tool": "class:role-tool",
}


class MessagesScreen:
    """Screen rendering the bubbles of a single chat conversation."""

    def __init__(
        self,
        state: AppState,
        composer_id: str,
        chat_name: str | None = None,
    ) -> None:
        self.state = state
        self.composer_id = composer_id
        self.chat_name = chat_name
        with Storage.open_readonly(state.global_db) as s:
            self.chat: ChatDetail = operations.load_chat(s, composer_id)

    # -- Screen protocol --------------------------------------------------

    def title(self) -> str:
        return (
            self.chat_name
            or self.chat.header.name
            or self.chat.header.composer_id
        )

    def render(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        if not self.chat.bubbles:
            fragments.append(("class:row", "  (no messages)\n"))
            return fragments

        for bubble in self.chat.bubbles:
            role = str(bubble.role)
            style = _ROLE_STYLE.get(role, "class:role-unknown")
            ts = bubble.created_at
            when = ts.strftime("%Y-%m-%d %H:%M") if ts else ""
            header = f"{role.upper()}  {when}".rstrip()
            fragments.append((style, header + "\n"))
            for line in bubble.text.splitlines() or [""]:
                fragments.append(("class:row", "    " + line + "\n"))
            fragments.append(("class:row", "\n"))

        return fragments

    def get_key_bindings(self) -> KeyBindings:
        return KeyBindings()
