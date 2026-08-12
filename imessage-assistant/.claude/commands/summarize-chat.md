---
description: Summarize an iMessage conversation over a time window
argument-hint: <chat name> [since <14d|3w|2026-07-01|all>] [profile <name>]
allowed-tools: Bash(python3 scripts/imessage_query.py:*), Read, Glob, Write
---

Summarize an iMessage conversation.

Request: `$ARGUMENTS`

Follow this exactly:

1. **Parse the request** into a chat selector, a time window, and (optionally) a
   profile. Default the window to `14d` if none is given. Infer the profile from the
   conversation's subject if not specified.

2. **Read the spec** at `.claude/skills/imessage-summary/SKILL.md`, plus the matching
   file in `profiles/` (`profiles/general.md` if nothing fits better).

3. **Locate the conversation.** If the selector isn't an exact chat name, run:
   ```bash
   python3 scripts/imessage_query.py list --search "<selector>"
   ```
   If several conversations match and it's genuinely ambiguous, ask which one rather
   than picking. If one is clearly right, proceed.

4. **Export the transcript**, reading `config/roster.json` for the `me` name:
   ```bash
   python3 scripts/imessage_query.py --me "<name from roster>" \
       export --chat "<chat>" --since "<window>"
   ```
   If the command reports unresolved handles, mention them in your final answer so the
   user can add them to the roster.

   If it warns that messages were dropped at the `--max-messages` cap, re-export in
   date slices with `--since`/`--until` and summarize in two passes, per the spec.

5. **Write the summary** following the output shape in the spec. Print it in the
   response. Only write it to `summaries/` if the user asked for a file — that
   directory is gitignored, because it would otherwise put private message content
   into a git repo.

6. **Close with** the message count, the actual date range covered, and anything you
   flagged as unclear.

Do not summarize from memory or assumption at any point — every claim traces to a
message in the exported transcript.
