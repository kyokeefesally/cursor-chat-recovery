# iMessage assistant

Read and summarize a specific iMessage conversation over a chosen time window.

Built for the case where you're behind on a busy group thread and want something you
can read in two minutes that leaves you as informed as reading all 400 messages —
speaker-attributed, chronologically ordered, and honest about what's still unsettled.

```
/summarize-chat Sierra Trip since 3w profile backpacking-trip
```

**macOS only.** The Messages database lives on your Mac; iOS doesn't expose it.

---

## What it does

- **Any conversation, any window.** Pick a chat by name, participant, or id; set the
  window as `14d`, `36h`, `3w`, `2026-07-01`, or `all`.
- **Speaker-aware.** Every message is attributed to a named person, in group chats and
  1:1s alike. Phone numbers resolve through your roster, then macOS Contacts.
- **Chronological.** The summary tracks how things changed over time, not just where
  they landed — including people who changed their minds.
- **Complete.** Tapbacks folded into the messages they react to, inline replies linked
  to their parent, edited and unsent messages flagged, attachments noted, and group
  events (adds, removals, renames) preserved.
- **Honest.** Distinguishes proposed from decided, flags unanswered questions, and says
  "unclear" instead of guessing.

## Setup

Full walkthrough: **[docs/SETUP-MACOS.md](docs/SETUP-MACOS.md)**. In short:

1. Clone on your Mac.
2. Grant **Full Disk Access** to your terminal app, then fully quit and reopen it.
3. `python3 scripts/imessage_query.py doctor`
4. `cp config/roster.example.json config/roster.json` and fill in names.

No dependencies — standard library only.

## Use

In Claude Code, from the repo directory:

| Command | Purpose |
|---|---|
| `/imessage-doctor` | Check access and setup |
| `/list-chats [term]` | Find a conversation |
| `/summarize-chat <chat> since <window> [profile <name>]` | Summarize |

Examples:

```
/summarize-chat Sierra Trip since 3w profile backpacking-trip
/summarize-chat Alex since 14d
/list-chats trip
```

The CLI works standalone too:

```bash
python3 scripts/imessage_query.py list --search trip
python3 scripts/imessage_query.py export --chat 47 --since 2w
python3 scripts/imessage_query.py export --chat 47 --since all --format stats
```

## How it fits together

```
chat.db  →  scripts/imessage_query.py  →  transcript  →  Claude  →  summary
                                                          ↑
                            .claude/skills/imessage-summary/SKILL.md
                            profiles/<type>.md
```

The script does no summarizing — it produces a clean, deterministic transcript. All
judgment lives in the spec, which is plain markdown you can edit when a summary isn't
shaped the way you want.

| Path | What it is |
|---|---|
| `scripts/imessage_query.py` | The reader. `doctor`, `list`, `export`, `stats`. |
| `.claude/skills/imessage-summary/SKILL.md` | The summary contract — structure, rules, length targets. |
| `profiles/` | Per-conversation-type lenses. Add your own. |
| `.claude/commands/` | The slash commands. |
| `config/roster.json` | Handle → name map. Gitignored. |
| `tests/` | 38 tests against a synthetic database. No Mac needed. |

## Tuning the output

If a summary isn't right, edit the markdown rather than the code:

- **Wrong sections or emphasis** → `.claude/skills/imessage-summary/SKILL.md`, §4.
- **Too long or too short** → same file, §5.
- **Missing something specific to a chat type** → add or edit a file in `profiles/`.

To add a profile, copy `profiles/general.md`, list what to track and how the output
should change, then pass `profile <filename>` to the command.

## Privacy

Everything runs locally against your own database, read-only via a temp snapshot that
is deleted on exit. Nothing is uploaded anywhere; message content only leaves your
machine if you paste a summary somewhere.

`config/roster.json`, `summaries/`, and any exported transcript are gitignored, so
phone numbers and message content stay out of git. Keep it that way — this repo is
private, but a private repo is still a copy of your friends' messages.

## Tests

```bash
python3 -m pytest tests/ -q
```

`tests/make_fixture.py` builds a synthetic `chat.db` mirroring the real Messages
schema, so the reader is testable without a Mac or real message data.

## Limits

- macOS only, and requires Full Disk Access.
- Reads what Messages has synced locally. Very old messages offloaded to iCloud may
  not be present; check `doctor`'s message count against what you expect.
- Attachments are noted by filename and type; images aren't analyzed.
- Very large windows are exported in slices — see the spec, §1.
