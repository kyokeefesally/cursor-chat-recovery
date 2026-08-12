---
description: Check that iMessage access is set up correctly on this Mac
allowed-tools: Bash(python3 scripts/imessage_query.py:*), Read, Edit, Write
---

Verify this machine can read the Messages database.

Run:

```bash
python3 scripts/imessage_query.py doctor
```

Interpret the output for the user:

- **Not macOS** — the Messages database only exists on a Mac. Nothing to fix here;
  they need to continue on their Mac.
- **Permission denied / not readable** — Full Disk Access is missing. Walk them
  through: System Settings → Privacy & Security → Full Disk Access → `+` → add the
  app running Claude Code (Terminal, iTerm, VS Code, or Claude Desktop) → toggle on →
  **quit that app completely and reopen it**. The restart is required; the permission
  does not take effect in a running process.
- **No roster** — offer to create `config/roster.json` from
  `config/roster.example.json`. Then run
  `python3 scripts/imessage_query.py list` and use the participant handles shown there
  to fill it in, asking the user which name goes with which number.
- **Everything OK** — report the message and conversation counts, and suggest
  `/list-chats` as the next step.
