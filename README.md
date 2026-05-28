# cursor-chat-tool

Interactive TUI to inventory, view, reassign, merge, and export Cursor AI chats.

## Why

Cursor identifies each workspace by a hash of its identifier URI. Reopening a project from a different path, or saving an Untitled multi-folder workspace as a `.code-workspace` file, mints a new workspace identity and detaches all prior chats from the sidebar. The conversations are still in `globalStorage/state.vscdb` keyed by `composerId` — they just need their `workspaceIdentifier` rewritten to point at the new workspace.

## Install

    uv tool install cursor-chat-tool
    # or
    pipx install cursor-chat-tool

## Use

    cursor-chat-tool                # interactive TUI
    cursor-chat-tool --readonly     # TUI with mutations disabled
    cursor-chat-tool --list         # workspaces table to stdout
    cursor-chat-tool --list --json
    cursor-chat-tool --export <COMPOSER_ID> --format markdown -o chat.md
    cursor-chat-tool --reassign <COMPOSER_IDS,COMMA,SEP> <TARGET_WS_ID> --yes
    cursor-chat-tool --merge <SRC_WS_ID> <TARGET_WS_ID> --yes

Close Cursor before any mutation. The tool refuses to write while Cursor is running.

## Safety

- Per-session full DB backup written next to `state.vscdb` on first mutation.
- Per-op headers backup under `~/.cursor-chat-tool/backups/`.
- Read-only mode auto-engages on schema mismatch or detected Cursor-running.
- Reassign is reversible: the per-op backup restores the prior `composer.composerHeaders`.

## Schema drift

When Cursor changes its schema, the tool detects the mismatch on startup and shows a copy-pastable prompt you can paste into a coding agent to adapt the tool. The agent prompt names the affected files and what to change.

## Development

    uv sync --dev
    uv run pytest
    uv run ruff check
    uv run mypy src/

## License

MIT
