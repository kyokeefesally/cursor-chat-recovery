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
