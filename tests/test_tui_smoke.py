from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cursor_chat_tool.tui import app as tui_app


def test_tui_quits_on_q(minimal_db, workspace_storage_dir):
    with create_pipe_input() as inp:
        inp.send_text("q")
        rc = tui_app.run_tui(
            readonly=True,
            global_db=minimal_db,
            workspace_storage=workspace_storage_dir,
            input=inp,
            output=DummyOutput(),
        )
    assert rc == 0


def test_tui_renders_workspaces_then_quits(minimal_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from cursor_chat_tool.tui import app as tui_app
    from cursor_chat_tool.tui.app import AppState, NavStack  # noqa: F401
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen

    # Unit-level: the screen loads and renders real workspace rows
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    fragments = screen.render()
    text = "".join(t for _, t in fragments)
    # display_name derived from uri file:///tmp/alpha -> "alpha"
    assert "ws-alpha" in text or "alpha" in text

    # Integration: arrow down then quit doesn't crash
    with create_pipe_input() as inp:
        inp.send_text("j")   # if j not bound, ignored
        inp.send_text("\x1b[B")  # down arrow
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput())
    assert rc == 0
