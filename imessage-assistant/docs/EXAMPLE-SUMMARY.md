# Example output

Generated from the synthetic fixture in `tests/make_fixture.py` (a 7-person trip chat)
by running the transcript through `.claude/skills/imessage-summary/SKILL.md` with the
`backpacking-trip` profile. It shows the shape and the level of specificity to expect.

The source is only 19 messages, so this is shorter than a real summary — but every
section behaves the way it will on a real thread.

---

# Sierra Trip 🏔️ — last 3 weeks
*19 messages · Kyle, Alex, Ben, Cara, Dev, Erin, Finn · Aug 3 – Aug 11*

## Where things stand
- Trip is on: **Aug 22–24** in the Sierras, **Little Lakes Valley**. Alex has the permit.
- **Five confirmed** (Kyle, Alex, Cara, Dev, Erin). Ben is out; Finn hasn't said either way.
- Dev is driving and has posted a departure plan: **Friday 6am, Chevron on Main**.
- Bear canisters are covered — Alex has 2, Cara is lending a third.
- Two things don't add up yet: the departure day contradicts the trip dates, and the
  car seats fewer people than are going. Neither has been raised in the chat.

## At a glance
| Detail | Value | Settled by |
|---|---|---|
| Destination | Little Lakes Valley, Sierras | Alex, Aug 3 |
| Dates | Aug 22–24 | Alex, Aug 3 |
| Depart | Friday 6am — *conflicts with the dates, see Open loops* | Dev, Aug 11 |
| Meeting point | Chevron on Main | Dev, Aug 11 |
| Permit | Secured | Alex, Aug 3 |
| Transport | Dev's 4Runner, "room for 4 + packs" | Dev, Aug 4 |
| Nights out | — not settled | |
| Cost | — not discussed | |

## Who's in
| Person | Status | Detail | As of |
|---|---|---|---|
| Kyle | ✅ In | — | Aug 7 |
| Alex | ✅ In | organizing; holds the permit | Aug 3 |
| Cara | ✅ In | lending a bear canister | Aug 5 |
| Dev | ✅ In | driving | Aug 4 |
| Erin | ✅ In | was a maybe pending work travel; it moved | Aug 7 |
| Ben | ❌ Out | sister's wedding that weekend | Aug 4 |
| Finn | ❓ Unclear | posted an elevation profile, added to the chat Aug 6, never said in or out | — |

## Timeline

### Mon Aug 3 — dates, destination, and permit locked
- Alex set **Aug 22–24, Sierras**, and secured the **Little Lakes Valley** permit
  (Ben ❤️, Cara 👍).
- Kyle confirmed the route; Alex: *"5 lakes in the first 3 miles."*

### Tue Aug 4 — first drop-out, transport solved
- **Ben pulled out** — his sister's wedding is that weekend. Cara: *"noooo"*.
- **Dev offered to drive** — 4Runner, *"room for 4 + packs."*

### Wed Aug 5 — gear, and one maybe
- **Erin went to a maybe**, waiting on work travel to be confirmed.
- Finn shared an elevation profile (`elevation.jpg`).
- Kyle raised bear canisters. Alex has 2, needs a 3rd; **Cara offered hers**. Covered.

### Thu Aug 6 – Fri Aug 7 — roster settles
- Alex added Finn to the chat.
- **Erin confirmed** — work travel moved. *"I'm IN 🎒"*. Kyle: *"let's gooo"*.
- Alex renamed the chat to Sierra Trip 🏔️.

### Sat Aug 8 – Tue Aug 11 — departure logistics
- Ben, from the sidelines: *"jealous. take pics."*
- **Dev set the departure**: Friday 6am, meeting at the Chevron on Main.

## Open loops
- **Departure day contradicts the trip dates.** The trip is Aug 22–24 (Aug 22 is a
  Saturday), but Dev's plan is to leave Friday 6am. Either the group is leaving Aug 21
  or one of the two is wrong. Nobody has flagged it.
- **Not enough seats.** Dev's 4Runner has "room for 4 + packs" and five people are
  confirmed — six if Finn comes. No second car has been offered.
- **Finn's status.** Added Aug 6, active in the chat, never said whether he's coming.
- **Nights out, food, and cost** have not been discussed at all.

## Who owes what
- [ ] Cara — bring the spare bear canister for Alex (offered Aug 5)
- [ ] Alex — holds the permit
- [ ] Dev — driving; departure 6am Friday from the Chevron on Main
- [ ] Someone — sort out a second car, or confirm the 4Runner actually fits everyone

**Gear**
- Covered: bear canisters (Alex ×2, Cara ×1)
- Not discussed: tents, stove, water filter, first aid, satellite communicator

## Banter & color
- Cara's *"noooo"* at Ben's drop-out, and Ben staying in the chat to be jealous at
  everyone — *"jealous. take pics."*
- Alex is clearly running this trip: dates, permit, and the chat name all came from him.
- Real enthusiasm once Erin got in — *"I'm IN 🎒"* / *"let's gooo"*.

## Shared links & files
- `elevation.jpg` — elevation profile (Finn, Aug 5)

---

## What to notice

Things the summary does that a naive one wouldn't:

- **Catches the date/day contradiction** by checking the departure day against the
  stated dates, rather than restating both as if they agree.
- **Catches the seat shortfall** by counting confirmed people against stated car
  capacity — a problem the chat itself never noticed.
- **Reports Erin as in**, not as a maybe, while still recording the switch in the
  timeline. Latest state wins; the change is preserved.
- **Leaves Finn unclear** instead of inferring from his participation.
- **Says "not settled"** for nights and cost rather than omitting the rows, so gaps are
  visible.
- **Keeps the banter**, which is most of why the group chat exists.
