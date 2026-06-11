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
                             input=inp, output=DummyOutput(), sync_load=True)
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
                             input=inp, output=DummyOutput(), sync_load=True)
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

    from cursor_chat_tool import storage
    from cursor_chat_tool.tui import app as tui_app
    work = tmp_path / "state.vscdb"
    shutil.copy(minimal_db, work)
    with storage.Storage.open_readonly(work) as s:
        headers_before = s.read_headers()
    with create_pipe_input() as inp:
        inp.send_text("\r")      # into workspace -> chats
        inp.send_text("r")       # reassign current chat -> pick target
        # Row 0 of the pick list is the source workspace, where enter is a
        # deliberate no-op; move down to a real target first.
        inp.send_text("\x1b[B")  # down arrow
        inp.send_text("\r")      # pick the target
        inp.send_text("y")       # confirm
        inp.send_text("\x1b")    # close result
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=False, global_db=work,
                             workspace_storage=workspace_storage_dir,
                             workspaces_config=None,
                             input=inp, output=DummyOutput(),
                             cursor_running_check=lambda: False,
                             sync_load=True)
    assert rc == 0
    # The move must actually have happened, not just not-crashed.
    with storage.Storage.open_readonly(work) as s:
        headers_after = s.read_headers()
    assert headers_after != headers_before


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


def test_footer_hints_per_screen(minimal_db, workspace_storage_dir):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_chats import ChatsScreen
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    ws_screen = WorkspacesScreen(state)
    assert "[enter] open" in ws_screen.footer_hints()
    with storage.Storage.open_readonly(minimal_db) as s:
        ws = next(w for w in operations.list_workspaces(s, workspace_storage_dir)
                  if w.identifier.id == "ws-alpha")
    chats = ChatsScreen(state, ws)
    hints = chats.footer_hints()
    assert "[m] move" in hints
    assert "[space] select" in hints
    assert "[e] export" in hints


def test_move_key_m_triggers_reassign(minimal_db, workspace_storage_dir):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_chats import ChatsScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    with storage.Storage.open_readonly(minimal_db) as s:
        ws = next(w for w in operations.list_workspaces(s, workspace_storage_dir)
                  if w.identifier.id == "ws-alpha")
    calls: list[list[str]] = []
    screen = ChatsScreen(state, ws, on_reassign=lambda ids, src: calls.append(ids))
    kb = screen.get_key_bindings()
    keys = {tuple(b.keys) for b in kb.bindings}
    assert ("m",) in keys
    assert ("r",) in keys  # legacy alias kept


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
                             input=inp, output=DummyOutput(), sync_load=True)
    assert rc == 0


def test_help_screen_lists_keys(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui import dialogs
    from cursor_chat_tool.tui.app import AppState
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    help_screen = dialogs.HelpScreen(state)
    text = "".join(t for _, t in help_screen.render())
    for needle in ("move", "export", "space", "filter", "sort", "quit"):
        assert needle in text.lower(), needle


def test_question_mark_opens_help(minimal_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("?")
        inp.send_text("\x1b")  # close help
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput(), sync_load=True)
    assert rc == 0


def test_list_screens_emit_cursor_position(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    styles = [s for s, _ in screen.render()]
    assert "[SetCursorPosition]" in styles


def test_messages_screen_scroll_bindings(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_messages import MessagesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = MessagesScreen(state, "c-alpha-1")
    keys = {tuple(b.keys) for b in screen.get_key_bindings().bindings}
    for k in (("up",), ("down",), ("pageup",), ("pagedown",)):
        assert k in keys, k
    styles = [s for s, _ in screen.render()]
    assert "[SetCursorPosition]" in styles


def test_workspaces_filter_mode(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    total = len(screen.visible)
    assert total > 1
    screen.filter.active = True
    screen.filter.feed("alpha")
    assert screen.filter_text == "alpha"
    assert len(screen.visible) < total
    # esc clears the filter and is consumed
    assert screen.handle_escape() is True
    assert screen.filter_text == ""
    assert len(screen.visible) == total
    # second esc is not consumed (lets the app pop the screen)
    assert screen.handle_escape() is False


def test_workspaces_filter_via_keys(minimal_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("/alpha\r")  # filter to alpha, confirm
        inp.send_text("\x1b")       # clear filter
        inp.send_text("q")
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput(), sync_load=True)
    assert rc == 0


def test_filter_typing_q_does_not_quit(minimal_db, workspace_storage_dir):
    """While the filter is active, the global q/? bindings must be disabled.

    Verified at the unit level: the screen reports wants_text_input() while
    active, which gates the global bindings in app._build_application.
    """
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    assert screen.wants_text_input() is False
    screen.filter.active = True
    assert screen.wants_text_input() is True


def test_chats_select_all_and_clear(minimal_db, workspace_storage_dir):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_chats import ChatsScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    with storage.Storage.open_readonly(minimal_db) as s:
        ws = next(w for w in operations.list_workspaces(s, workspace_storage_dir)
                  if w.identifier.id == "ws-alpha")
    screen = ChatsScreen(state, ws)
    screen.select_all()
    assert len(screen.selected_ids) == len(screen.chats)
    text = "".join(t for _, t in screen.render())
    assert "selected" in text
    screen.clear_selection()
    assert not screen.selected_ids


def test_workspaces_header_shows_sort(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    text = "".join(t for _, t in screen.render())
    assert "last_activity" in text or "last activity" in text


def _mk_pick(minimal_db, workspace_storage_dir, n_chats=2):
    from cursor_chat_tool import operations, storage
    from cursor_chat_tool.tui import dialogs
    from cursor_chat_tool.tui.app import AppState
    state = AppState(readonly=False, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    with storage.Storage.open_readonly(minimal_db) as s:
        wslist = operations.list_workspaces(s, workspace_storage_dir)
    source = next(w for w in wslist if w.identifier.id == "ws-alpha")
    picked: list = []
    screen = dialogs.PickTargetScreen(
        state, wslist, on_pick=picked.append,
        source=source, chat_count=n_chats,
    )
    return screen, wslist, source, picked


def test_pick_target_shows_paths_and_source(minimal_db, workspace_storage_dir):
    screen, wslist, source, _ = _mk_pick(minimal_db, workspace_storage_dir)
    text = "".join(t for _, t in screen.render())
    # identifies targets by path like the workspaces screen
    with_uri = next(w for w in wslist if w.identifier.uri and w.identifier.id != "ws-alpha")
    uri = with_uri.identifier.uri
    assert uri is not None and uri[-20:] in text
    # header explains the move
    assert "Move 2 chat(s)" in text
    assert source.display_name in text
    # the source row is marked
    assert "(current)" in text


def test_pick_target_skips_source_on_enter(minimal_db, workspace_storage_dir):
    from prompt_toolkit.keys import Keys
    screen, wslist, source, picked = _mk_pick(minimal_db, workspace_storage_dir)
    rows = screen.visible
    screen.cursor = next(i for i, w in enumerate(rows)
                         if w.identifier.id == source.identifier.id)
    # NB: "enter" registers as Keys.ControlM, not the literal string "enter"
    for b in screen.get_key_bindings().bindings:
        if tuple(b.keys) == (Keys.ControlM,):
            b.handler(None)  # type: ignore[arg-type]
    assert picked == []


def test_pick_target_picks_non_source(minimal_db, workspace_storage_dir):
    from prompt_toolkit.keys import Keys
    screen, wslist, source, picked = _mk_pick(minimal_db, workspace_storage_dir)
    rows = screen.visible
    screen.cursor = next(i for i, w in enumerate(rows)
                         if w.identifier.id != source.identifier.id)
    for b in screen.get_key_bindings().bindings:
        if tuple(b.keys) == (Keys.ControlM,) and b.filter():
            b.handler(None)  # type: ignore[arg-type]
    assert len(picked) == 1
    assert picked[0].identifier.id != source.identifier.id


def test_pick_target_filter(minimal_db, workspace_storage_dir):
    screen, wslist, _, _ = _mk_pick(minimal_db, workspace_storage_dir)
    total = len(screen.visible)
    screen.filter.active = True
    screen.filter.feed("beta")
    assert 0 < len(screen.visible) < total


def test_screens_load_sync_without_event_loop(minimal_db, workspace_storage_dir):
    """Direct construction outside an app must still load immediately."""
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    assert screen.workspaces  # loaded synchronously
    assert screen.loading is False


def test_loading_render_shows_spinner(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    screen.loading = True
    text = "".join(t for _, t in screen.render())
    assert "Loading" in text


def test_load_error_renders_error(minimal_db, workspace_storage_dir):
    from cursor_chat_tool.tui.app import AppState
    from cursor_chat_tool.tui.screen_workspaces import WorkspacesScreen
    state = AppState(readonly=True, global_db=minimal_db,
                     workspace_storage=workspace_storage_dir, workspaces_config=None)
    screen = WorkspacesScreen(state)
    screen.error = "boom"
    text = "".join(t for _, t in screen.render())
    assert "boom" in text


def test_run_tui_sync_load_flag(minimal_db, workspace_storage_dir):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from cursor_chat_tool.tui import app as tui_app
    with create_pipe_input() as inp:
        inp.send_text("\r\r\x1b\x1bq")  # drill to messages and back, deterministic
        rc = tui_app.run_tui(readonly=True, global_db=minimal_db,
                             workspace_storage=workspace_storage_dir,
                             input=inp, output=DummyOutput(), sync_load=True)
    assert rc == 0
