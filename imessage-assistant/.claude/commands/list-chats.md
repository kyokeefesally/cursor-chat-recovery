---
description: List iMessage conversations, most recently active first
argument-hint: [search term]
allowed-tools: Bash(python3 scripts/imessage_query.py:*)
---

List the user's iMessage conversations so they can pick one to summarize.

Search term (may be empty): `$ARGUMENTS`

Run:

```bash
python3 scripts/imessage_query.py list --limit 40 --search "$ARGUMENTS"
```

Omit `--search` entirely if no term was given.

Present the results as a compact table: chat name, group or 1:1, participant count,
message count, and last activity. Note that any conversation can be summarized with
`/summarize-chat <name> since <window>`.

If participants show as raw phone numbers, point out that adding them to
`config/roster.json` will make summaries use real names.
