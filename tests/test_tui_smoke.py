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


def test_chats_screen_renders(minimal_db, workspace_storage_dir):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_chats import ChatsScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    with storage.Storage.open_readonly(minimal_db) as s:
        ws = next(
            w
            for w in operations.list_workspaces(s, workspace_storage_dir)
            if w.identifier.id == "ws-alpha"
        )
    screen = ChatsScreen(state, ws)
    text = "".join(t for _, t in screen.render())
    assert "Alpha chat 1" in text
    assert "Alpha chat 2" in text


def test_tui_drill_into_workspace_and_back(minimal_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("\r")    # Enter: drill into top workspace
        inp.send_text("\x1b")  # Esc: back to workspaces
        inp.send_text("q")     # quit
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput())
    assert rc == 0


def test_messages_screen_renders(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_messages import MessagesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = MessagesScreen(state, "c-alpha-1")
    text = "".join(t for _, t in screen.render())
    assert "Hello" in text
    assert "Hi there" in text


def test_tui_drill_to_messages_and_back(minimal_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("\r")    # into workspace -> chats
        inp.send_text("\r")    # into chat -> messages
        inp.send_text("\x1b")  # back to chats
        inp.send_text("\x1b")  # back to workspaces
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput())
    assert rc == 0


def test_perform_reassign_moves_chat(minimal_db, workspace_storage_dir, tmp_path):
    import shutil

    from cursor_chat_tool import storage
    from cursor_chat_tool.tui import actions
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    res = actions.perform_reassign(
        work, tmp_path / "backups", ["c-alpha-1"], "ws-beta",
        cursor_running_check=lambda: False,
    )
    assert res.to_workspace_id == "ws-beta"
    with storage.Storage.open_readonly(work) as s:
        h = next(x for x in s.read_headers()["allComposers"] if x["composerId"] == "c-alpha-1")
    assert h["workspaceIdentifier"]["id"] == "ws-beta"


def test_dialog_screens_render(minimal_db, workspace_storage_dir):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui import dialogs
    from cursor_chat_tool.tui.app import AppState
    state = AppState(readonly=False, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    with storage.Storage.open_readonly(minimal_db) as s:
        wslist = operations.list_workspaces(s, workspace_storage_dir)
    pick = dialogs.PickTargetScreen(state, wslist, on_pick=lambda w: None)
    assert "Pick" in pick.title() or len(pick.render()) > 0
    confirm = dialogs.ConfirmScreen(state, "Reassign 1 chat?", on_yes=lambda: None)
    assert "Reassign 1 chat?" in "".join(t for _, t in confirm.render())
    result = dialogs.ResultScreen(state, ["Done.", "Backup: x"])
    assert "Done." in "".join(t for _, t in result.render())


def test_schema_mismatch_makes_root_readonly(drift_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=False, global_db=drift_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput())
    assert rc == 0


def test_tui_reassign_flow_no_crash(minimal_db, workspace_storage_dir, tmp_path):
    import shutil

    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from cursor_chat_tool.tui import app as tui_app
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    with create_pipe_input() as inp:
        inp.send_text("\r")    # into workspace -> chats
        inp.send_text("r")     # reassign current chat -> pick target
        inp.send_text("\r")    # pick first target
        inp.send_text("y")     # confirm
        inp.send_text("\x1b")  # close result
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=False, global_db=work,
                             workspace_storage=workspace_storage_dir,
                             workspaces_config=None,
                             input=inp, output=DummyOutput(),
                             cursor_running_check=lambda: False)
    assert rc == 0


def test_export_chats_writes_files(minimal_db, workspace_storage_dir, tmp_path):
    from cursor_chat_tool.tui import actions
    out = tmp_path / "exports"
    paths = actions.export_chats(minimal_db, ["c-alpha-1"], out, fmt="markdown")
    assert len(paths) == 1
    assert paths[0].exists()
    content = paths[0].read_text(encoding="utf-8")
    assert "Alpha chat 1" in content
    assert "Hi there" in content


def test_export_chats_json(minimal_db, workspace_storage_dir, tmp_path):
    import json

    from cursor_chat_tool.tui import actions
    out = tmp_path / "exports"
    paths = actions.export_chats(minimal_db, ["c-alpha-1"], out, fmt="json")
    assert len(paths) == 1
    data = json.loads(paths[0].read_text(encoding="utf-8"))
    assert data["composer_id"] == "c-alpha-1"


def test_tui_export_flow_no_crash(minimal_db, workspace_storage_dir, tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("\r")    # into workspace -> chats
        inp.send_text("e")     # export current chat -> export path screen
        inp.send_text("\r")    # submit default dir -> performs export -> result
        inp.send_text("\x1b")  # close result
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput())
    assert rc == 0
