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
