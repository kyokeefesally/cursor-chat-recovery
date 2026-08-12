---
name: imessage-summary
description: Read and summarize a specific iMessage conversation over a chosen time window. Use whenever the user asks what happened in a text thread or group chat, wants to catch up on a conversation, or names a chat and a period ("what's happened in the trip chat in the last 2 weeks", "summarize my texts with Alex since July"). macOS only.
---

# Summarizing an iMessage conversation

Produce a summary that is a **faithful substitute for reading the whole thread**. The
reader should finish it knowing everything that was decided, everything still open, who
said what, and in what order — without opening Messages.

## 1. Get the messages

Never guess at conversation contents. Always pull the transcript first.

```bash
# Find the conversation (do this if the user's name for it is not exact)
python3 scripts/imessage_query.py list --search "trip"

# Export the window
python3 scripts/imessage_query.py export --chat "Sierra Trip" --since 14d
```

`--since` accepts `14d`, `36h`, `3w`, `6m`, `2026-07-01`, or `all`. Map the user's
phrasing onto it: "last couple weeks" → `14d`, "since the start" → `all`, "since we
started planning" → ask, or use `all` and let the timeline show the start.

Add `--me` and `--roster` so names render properly (see `config/roster.json`).

**If the export is very large** (thousands of messages, or the tool warns about the
`--max-messages` cap), do not summarize a truncated transcript and present it as
complete. Instead, export in consecutive slices and summarize in two passes:

```bash
python3 scripts/imessage_query.py export --chat X --since 2026-06-01 --until 2026-06-15
python3 scripts/imessage_query.py export --chat X --since 2026-06-15 --until 2026-07-01
```

Summarize each slice, then merge — resolving contradictions in favor of the later
slice, and keeping the timeline continuous across the seam.

## 2. Read for these six things

Work through the transcript in order and track, per person:

1. **Decisions** — what is now settled, and the message that settled it.
2. **Reversals** — anything decided then changed. These matter more than the original.
3. **Commitments** — who said they'd do or bring something.
4. **Status** — for anything with participants: who's in, out, or undecided, and why.
5. **Open loops** — questions asked that nobody answered. Easy to miss; look for
   questions with no reply in the following messages.
6. **Color** — jokes, running bits, reactions, tone. Not noise; it's part of the thread.

## 3. Distinctions that must not blur

These are where summaries go wrong. Hold them precisely:

- **Proposed ≠ agreed.** "We could do Thursday" is not "we're going Thursday." Say
  "Alex floated Thursday; nobody confirmed" — not "the trip is Thursday."
- **Latest wins, but show the change.** If Erin was out on the 5th and in on the 7th,
  the status is **in**, and the timeline records the switch. Never report a superseded
  state as current.
- **One person ≠ the group.** Attribute. "Dev is driving" only if Dev said so.
- **Silence is not consent.** If a question got no answer, it belongs in Open loops.
- **Preserve exact values.** Dates, times, costs, mileage, meeting points, and counts
  are copied verbatim from the messages. Never round, infer, or reconcile them.
- **Absent ≠ false.** If the transcript does not say why someone dropped out, write
  "no reason given" — do not construct a plausible one.

## 4. Output shape

Use this structure. Drop any section that would be empty rather than padding it — but
never drop **Where things stand**, **Who's in** (for group plans), or **Timeline**.

```markdown
# <Chat name> — <window in plain language>
*<N> messages · <participants> · <first date> to <last date>*

## Where things stand
3–6 bullets. Current state only, as of the last message. No history here.

## At a glance
Only for chats with hard logistics. A short table of settled facts:
| Detail | Value | Settled by |

## Who's in
Only for group plans. One row per person, including the user:
| Person | Status | Detail | As of |
| Erin | ✅ In | work travel moved | Aug 7 |
| Ben | ❌ Out | sister's wedding same weekend | Aug 4 |
| Finn | ❓ Unclear | added to the chat, hasn't replied | — |

Status vocabulary: ✅ In · ❌ Out · 🕐 Conditional · ❓ Unclear.
"Conditional" needs the condition stated.

## Timeline
Chronological. Group by day, or by phase if the window is long. Each bullet is
attributed and carries what changed — not a message-by-message replay.

### Mon Aug 3 — dates and permit locked
- Alex set the dates (Aug 22–24) and got the Little Lakes Valley permit.
- Kyle confirmed the lake-basin route; Alex: "5 lakes in the first 3 miles."

## Open loops
Unanswered questions and undecided items. Name who raised each and when.

## Who owes what
- [ ] Alex — source a third bear canister (Cara offered one, Aug 5)
Only real commitments — someone volunteered or was asked directly.

## Banter & color
2–5 bullets. The running jokes and tone. Brief, but don't skip it.

## Shared links & files
Only if any were sent.
```

## 5. Length

Scale to the volume, and stay well under the cost of reading the thread:

| Messages in window | Target |
|---|---|
| under 50 | ~150 words |
| 50–200 | 250–400 words |
| 200–600 | 400–700 words |
| 600+ | 700–1,100 words, phase-grouped timeline |

Compression comes from **merging** ("the group went back and forth on food for two
days, landing on everyone-brings-their-own dinners") — never from dropping a decision,
a status change, or an open question. If it's approaching the ceiling, tighten the
timeline and the banter; keep the status table and open loops intact.

## 6. Quoting

Quote directly when the exact words carry information a paraphrase loses: a firm
commitment, a precise logistical detail, a memorable line. Keep quotes under ~15 words
and attribute them. Everything else is paraphrase.

## 7. Honesty

- If a handle never resolved to a name, say so — don't silently call them by a phone
  number in the prose without flagging that you don't know who it is.
- If the window cut off mid-discussion, note that the thread starts mid-conversation.
- If something is genuinely ambiguous, mark it "unclear" and quote the message. Do not
  resolve it by guessing.
- Report what the messages say, including unflattering or awkward content. This is the
  user's own conversation; sanitizing it makes the summary useless.

## Profiles

`profiles/` holds lenses for recurring conversation types — extra things to track and
sections to emphasize. Load the matching one alongside this spec:

- `profiles/backpacking-trip.md` — trip planning: roster, route, gear, logistics.
- `profiles/general.md` — the default when nothing more specific fits.
