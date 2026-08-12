# Launch primer

Paste the block below into a fresh Claude Code session **running locally on your Mac**.

Before you paste it, get the code onto the Mac. The project currently lives on a branch
of another repo, because the GitHub App in the cloud session couldn't create new
repositories.

```bash
# 1. Create the private repo (one click): https://github.com/new
#    Name: imessage-assistant · Private · do NOT initialize with a README

# 2. Extract this project into it
git clone --branch claude/imessage-assistant-repo-vj32pq \
    https://github.com/kyokeefesally/cursor-chat-recovery.git /tmp/extract
mkdir -p ~/code/imessage-assistant
cp -R /tmp/extract/imessage-assistant/. ~/code/imessage-assistant/
cd ~/code/imessage-assistant

git init -b main
git add -A
git commit -m "Add iMessage assistant"
git remote add origin https://github.com/kyokeefesally/imessage-assistant.git
git push -u origin main

# 3. Start Claude Code here
claude
```

Then paste everything below the line.

---

I'm on my Mac, in the `imessage-assistant` repo. This project reads a specific iMessage
conversation over a time window and summarizes it. It was built in a previous cloud
session and has never been run against a real Messages database — you're doing the
first real run.

Read `README.md`, `.claude/skills/imessage-summary/SKILL.md`, and
`profiles/backpacking-trip.md` first so you know how it's meant to work.

Then walk me through setup, stopping whenever you need something from me:

1. Run `python3 scripts/imessage_query.py doctor`. If Full Disk Access isn't granted,
   tell me exactly which app to add and remind me I have to fully quit and reopen it —
   don't continue until `doctor` passes.

2. Run `python3 scripts/imessage_query.py list --search trip` to find my backpacking
   group chat. It's a group with 6 other people. If several conversations match, show
   me the candidates and let me pick.

3. Build the roster. Show me the participant handles from that chat, and ask me who
   each phone number or email belongs to. Write the answers to `config/roster.json`
   (copy the shape from `config/roster.example.json`, set `"me": "Kyle"`). Then re-run
   `doctor` to confirm it loaded, and re-run the chat listing so I can check every
   participant now shows a real name.

4. Export the conversation and summarize it, using the `backpacking-trip` profile:

   ```
   /summarize-chat <chat> since <window> profile backpacking-trip
   ```

   Ask me how far back to go before you run it. If the export warns that messages were
   dropped at the cap, slice the window by date and do it in two passes rather than
   summarizing a truncated transcript.

For the summary itself, what I care about most:

- Who's going, who's not, and **why** they're not — with dates for anyone who changed
  their mind.
- Where we're going, and whether that changed at any point.
- All the trip logistics: dates, departure, meeting point, permits, transport, gear,
  food, cost.
- The banter. It's most of the chat and I don't want it stripped out.
- Chronological — I want to see how things developed, not just where they landed.

It should be a genuine substitute for reading every message. Comprehensive, but tight
enough that reading it beats scrolling the thread. Attribute everything to whoever
actually said it, don't present anything proposed as decided, and flag what's still
open instead of smoothing over it.

`docs/EXAMPLE-SUMMARY.md` shows the target format, generated from test data.

Two things to check as you go:

- Nothing in `config/roster.json` or `summaries/` should ever get committed — both are
  gitignored, and I want it kept that way.
- If any handle doesn't resolve to a name, tell me rather than quietly using a phone
  number in the summary.

Also: I'd separately installed the iMessage plugin from
https://claude.com/plugins/imessage. This project doesn't depend on it — it reads
`chat.db` directly. If the plugin is installed and gives you a cleaner path to the same
data, use it, but compare its output against
`python3 scripts/imessage_query.py export` before trusting it, and tell me which one
you used.
