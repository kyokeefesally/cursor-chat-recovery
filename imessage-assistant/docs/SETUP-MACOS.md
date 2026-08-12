# macOS setup

Everything in this repo other than the actual reading of messages works anywhere. This
page covers the steps that must happen on the Mac.

Total time: about five minutes, and the only fiddly part is step 2.

---

## 1. Clone the repo on your Mac

```bash
git clone https://github.com/kyokeefesally/imessage-assistant.git
cd imessage-assistant
```

Python 3.9+ is required; macOS ships with a suitable version. There are no required
dependencies — the reader uses only the standard library.

## 2. Grant Full Disk Access

This is the step that blocks people. macOS protects `~/Library/Messages/chat.db` under
TCC, so a terminal cannot read it until you explicitly allow it — even as your own
user, even with `sudo`.

1. **System Settings → Privacy & Security → Full Disk Access**
2. Click **+**
3. Add the app that runs Claude Code:
   - Terminal → `/Applications/Utilities/Terminal.app`
   - iTerm2 → `/Applications/iTerm.app`
   - VS Code → `/Applications/Visual Studio Code.app`
   - Claude Desktop → `/Applications/Claude.app`
4. Make sure the toggle is **on**.
5. **Quit that app completely (⌘Q) and reopen it.**

Step 5 is not optional. TCC permissions are evaluated when a process starts, so a
running terminal keeps its old, denied state. Opening a new tab or window is not
enough — the whole application has to restart.

If you run Claude Code inside VS Code's integrated terminal, VS Code is the app that
needs access, not Terminal.

## 3. Verify

```bash
python3 scripts/imessage_query.py doctor
```

Expected:

```
Platform: darwin
Database: /Users/you/Library/Messages/chat.db
OK    Exists (2143.7 MB)
OK    Readable (Full Disk Access is granted)
OK    412,983 messages across 1,204 conversations
OK    Most recent message: 2026-08-12T09:14:22-07:00
```

If you get `permission denied`, step 2 didn't take. The usual cause is not restarting
the app, or adding the wrong app.

## 4. Find your conversation

```bash
python3 scripts/imessage_query.py list --limit 30
```

Look for the trip group chat. Note its bracketed id (e.g. `[47]`) — using the id is
more reliable than the name for chats with emoji or no name at all.

## 5. Build the roster

The Messages database stores phone numbers and Apple IDs, not names. The reader will
fall back to macOS Contacts automatically, but a roster gives better results: it wins
over Contacts, so you get "Ben" rather than "Ben Marsh (Work)", and it covers people
who aren't in your contacts at all.

```bash
cp config/roster.example.json config/roster.json
```

Then fill it in using the handles from step 4. `roster.json` is gitignored — real
numbers never get committed.

```json
{
  "me": "Kyle",
  "people": [
    { "name": "Alex", "handles": ["+15551234567"] },
    { "name": "Ben",  "handles": ["+15559876543", "ben@icloud.com"] }
  ]
}
```

Phone numbers match on their last 10 digits, so formatting doesn't matter. List every
handle a person uses — people text from a number and an Apple ID interchangeably, and
an unlisted one shows up as a separate unnamed participant.

Re-run `doctor` to confirm the roster loaded, then:

```bash
python3 scripts/imessage_query.py export --chat 47 --since 7d | head -40
```

Any remaining raw phone numbers in the output are handles you still need to add.

## 6. Summarize

In Claude Code, from the repo directory:

```
/summarize-chat Sierra Trip since 3w profile backpacking-trip
```

---

## Troubleshooting

**`permission denied` even after granting access**
Confirm the *exact* app is listed and toggled on, then fully quit and reopen it.
`ls ~/Library/Messages/chat.db` from the same terminal is a quick independent check —
if that fails, the terminal still lacks access.

**Recent messages are missing**
The reader copies the `-wal` and `-shm` sidecar files along with the database, which
normally handles this. If messages from the last few minutes are still missing, quit
Messages.app and re-run — that forces a checkpoint.

**Everyone shows as a phone number**
No roster and no Contacts match. See step 5.

**Some messages appear blank or missing**
Recent macOS versions store message bodies in `attributedBody` rather than `text`. The
reader decodes it with a built-in parser. For unusual formatting (heavily styled text,
some link previews) an exact decoder helps:

```bash
pip3 install pytypedstream
```

It's detected automatically if present.

**`database is locked`**
Shouldn't happen — the reader works on a snapshot copy. If it does, quit Messages.app
and retry.

**Group chat has no name**
Unnamed groups list as their participants. Use the numeric id from `list` instead.
