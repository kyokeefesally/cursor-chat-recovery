"""prompt_toolkit Application with a navigation stack and breadcrumb.

Architecture: screens implement the :class:`Screen` protocol. A :class:`NavStack`
holds the active screens; the top screen is always the one rendered. The
``Application`` body reads ``nav.current.render()`` and its key bindings are the
merge of a global ``KeyBindings`` and ``DynamicKeyBindings`` that read
``nav.current.get_key_bindings()`` so the active screen's keys swap in
automatically when the stack changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import (
    DynamicKeyBindings,
    KeyBindings,
    merge_key_bindings,
)
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from cursor_chat_tool import paths


@dataclass
class AppState:
    readonly: bool
    global_db: Path
    workspace_storage: Path
    workspaces_config: Path | None


@runtime_checkable
class Screen(Protocol):
    """A single TUI screen pushed onto the navigation stack."""

    def title(self) -> str:
        """Breadcrumb segment for this screen."""
        ...

    def render(self) -> list[tuple[str, str]]:
        """Formatted-text fragments for the body."""
        ...

    def get_key_bindings(self) -> KeyBindings:
        """Screen-specific key bindings."""
        ...


class NavStack:
    """Holds the stack of screens; the top is the active screen."""

    def __init__(self, root: Screen) -> None:
        self.stack: list[Screen] = [root]

    @property
    def current(self) -> Screen:
        return self.stack[-1]

    def push(self, screen: Screen) -> None:
        self.stack.append(screen)

    def pop(self) -> Screen | None:
        if len(self.stack) > 1:
            return self.stack.pop()
        return None


_STYLE = Style.from_dict({
    "breadcrumb": "bg:#222222 #ffffff bold",
    "footer": "bg:#222222 #aaaaaa",
    "header": "bold",
    "row": "",
    "row-selected": "reverse",
    "role-user": "bold #5fafff",
    "role-assistant": "bold #5fd75f",
    "role-system": "bold #aaaaaa",
    "role-tool": "bold #d7af5f",
    "role-unknown": "bold",
})


def _build_application(
    state: AppState,
    nav: NavStack,
    inp: Any = None,
    output: Any = None,
) -> Application[int]:
    def breadcrumb_text() -> list[tuple[str, str]]:
        ro = " [READ-ONLY]" if state.readonly else ""
        crumb = " › ".join(s.title() for s in nav.stack)
        return [("class:breadcrumb", crumb + ro)]

    breadcrumb_window = Window(
        content=FormattedTextControl(breadcrumb_text), height=1
    )
    body = Window(content=FormattedTextControl(lambda: nav.current.render()))
    footer = Window(
        content=FormattedTextControl(
            lambda: [("class:footer", " [q] quit  [esc] back  [↑/↓] move  [s] sort ")]
        ),
        height=1,
    )
    layout = Layout(HSplit([breadcrumb_window, body, footer]))

    global_kb = KeyBindings()

    @global_kb.add("q")
    def _(event: Any) -> None:
        event.app.exit(result=0)

    @global_kb.add("c-c")
    def _(event: Any) -> None:
        event.app.exit(result=130)

    @global_kb.add("escape", eager=True)
    def _(event: Any) -> None:
        nav.pop()

    key_bindings = merge_key_bindings([
        global_kb,
        DynamicKeyBindings(lambda: nav.current.get_key_bindings()),
    ])

    return Application(
        layout=layout,
        key_bindings=key_bindings,
        style=_STYLE,
        full_screen=True,
        input=inp,
        output=output,
    )


def run_tui(
    readonly: bool = False,
    global_db: Path | None = None,
    workspace_storage: Path | None = None,
    workspaces_config: Path | None = None,
    input: Any = None,  # noqa: A002
    output: Any = None,
) -> int:
    if global_db is None or workspace_storage is None:
        loc = paths.locate_cursor_dirs()
        global_db = global_db or loc.global_storage_db
        workspace_storage = workspace_storage or loc.workspace_storage_dir
        workspaces_config = workspaces_config or loc.workspaces_dir

    state = AppState(
        readonly=readonly,
        global_db=Path(global_db),
        workspace_storage=Path(workspace_storage),
        workspaces_config=Path(workspaces_config) if workspaces_config else None,
    )

    # Imported here to avoid a circular import (screen modules import from app).
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen

    def open_chat(chat_header: Any) -> None:
        # Lazy import to avoid a circular import (screen imports from app).
        from cursor_chat_tool.tui.screen_messages import MessagesScreen

        nav.push(
            MessagesScreen(state, chat_header.composer_id, chat_header.name)
        )

    def open_workspace(workspace: Any) -> None:
        # Lazy import to avoid a circular import (screen imports from app).
        from cursor_chat_tool.tui.screen_chats import ChatsScreen

        nav.push(ChatsScreen(state, workspace, on_open=open_chat))

    nav = NavStack(WorkspacesScreen(state, on_open=open_workspace))
    app = _build_application(state, nav, inp=input, output=output)
    result = app.run()
    return result if isinstance(result, int) else 0
