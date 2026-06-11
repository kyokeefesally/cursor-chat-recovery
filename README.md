# cursor-chat-tool

Interactive TUI to inventory, view, reassign, merge, and export Cursor AI chats.

## Why

Cursor identifies each workspace by a hash of its identifier URI. Reopening a project from a different path, or saving an Untitled multi-folder workspace as a `.code-workspace` file, mints a new workspace identity and detaches all prior chats from the sidebar. The conversations are still in `globalStorage/state.vscdb` keyed by `composerId` — they just need their `workspaceIdentifier` rewritten to point at the new workspace.

## Install

Not published to PyPI — install from a local checkout of this repo:

    git clone <repo-url> cursor-chat-tool
    cd cursor-chat-tool
    uv tool install .        # installs the `cursor-chat-tool` executable to ~/.local/bin
    # or, with pipx:
    pipx install .

To run without installing (from the repo dir): `uv run cursor-chat-tool`.
After `uv tool install`, ensure `~/.local/bin` is on your PATH (run `uv tool update-shell` once if needed).

## Use

    cursor-chat-tool                # interactive TUI
    cursor-chat-tool --readonly     # TUI with mutations disabled
    cursor-chat-tool --list         # workspaces table to stdout
    cursor-chat-tool --list --json
    cursor-chat-tool --export <COMPOSER_ID> --format markdown -o chat.md
    cursor-chat-tool --reassign <COMPOSER_IDS,COMMA,SEP> <TARGET_WS_ID> --yes
    cursor-chat-tool --merge <SRC_WS_ID> <TARGET_WS_ID> --yes

Close Cursor before any mutation. The tool refuses to write while Cursor is running.

## Keys

### Global

| Key | Action |
|-----|--------|
| `?` | Open help screen |
| `q` | Quit |
| `esc` | Back / cancel (clears an active filter first) |
| `ctrl-c` | Force quit |

### Workspaces (project list)

| Key | Action |
|-----|--------|
| `up` / `down` | Move selection |
| `pgup` / `pgdn` | Page up / down |
| `home` / `end` | Jump to first / last |
| `enter` | Open workspace's chats |
| `s` | Cycle sort order (last activity → chat count → name → health) |
| `/` | Filter by name or path (`enter` keeps filter, `esc` clears) |

### Chats (within a workspace)

| Key | Action |
|-----|--------|
| `up` / `down` | Move selection |
| `pgup` / `pgdn` | Page up / down |
| `enter` | View messages |
| `space` | Select / deselect chat for bulk actions |
| `a` | Select all chats |
| `A` | Deselect all chats |
| `m` | Move selected (or highlighted) chats to another workspace (`r` is a legacy alias) |
| `e` | Export selected (or highlighted) chats to Markdown files |

### Messages (within a chat)

| Key | Action |
|-----|--------|
| `up` / `down`, `pgup` / `pgdn`, `home` / `end` | Scroll |
| `e` | Export this chat |

### Moving chats

Press `m` on the chats screen to open the move-target picker. Workspaces are
identified by name, path, chat count, and last activity so ambiguous short
names are distinguishable. Type `/` to filter the list; the current workspace
is marked and cannot be selected as a target. After you confirm, a timestamped
backup is written to `~/.cursor-chat-tool/backups/` before any data is
touched. Cursor must be closed before the move is attempted; the tool refuses
to write while Cursor is running.

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
