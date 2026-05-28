"""prompt_toolkit Application with screen stack and breadcrumb."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
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
    breadcrumb: list[str] = field(default_factory=lambda: ["Workspaces"])


_STYLE = Style.from_dict({
    "breadcrumb": "bg:#222222 #ffffff bold",
    "footer": "bg:#222222 #aaaaaa",
})


def _build_application(
    state: AppState,
    inp: Any = None,
    output: Any = None,
) -> Application[int]:
    def breadcrumb_text() -> list[tuple[str, str]]:
        ro = " [READ-ONLY]" if state.readonly else ""
        return [("class:breadcrumb", " › ".join(state.breadcrumb) + ro)]

    breadcrumb_window = Window(
        content=FormattedTextControl(breadcrumb_text), height=1
    )
    body = Window(content=FormattedTextControl(lambda: [("", "Press q to quit.")]))
    footer = Window(
        content=FormattedTextControl(lambda: [("class:footer", " [q] quit ")]), height=1
    )
    layout = Layout(HSplit([breadcrumb_window, body, footer]))

    kb = KeyBindings()

    @kb.add("q")
    def _(event: Any) -> None:
        event.app.exit(result=0)

    @kb.add("c-c")
    def _(event: Any) -> None:
        event.app.exit(result=130)

    return Application(
        layout=layout,
        key_bindings=kb,
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
    app = _build_application(state, inp=input, output=output)
    result = app.run()
    return result if isinstance(result, int) else 0
