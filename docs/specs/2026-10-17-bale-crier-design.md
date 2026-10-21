# bale-crier — design

Settled with the owner on 2026-10-17. This document records the design and the
reasons behind it; `AGENTS.md` keeps the summary and points here.

## What it is

One server-side bot that pushes into a single Bale chat everything the owner
needs told. Three families of message, one channel:

- **alerts** about external state — the first one is AvalAI credit running out;
- **notes** drawn from the owner's own lists, expanded by an LLM into a few lines
  of Persian so the same item does not arrive in the same words twice and does
  not arrive as a one-line bullet. The expansion's tone may be warm and
  motivational; nothing is appended to it (settled 2026-10-17, expanded 2026-10-21);
- **news** — the day's AI trends, drawn from a web feed and written in Persian.
  It is a subsystem of its own, designed in
  `2026-10-17-news-digest-design.md` (settled 2026-10-17).

The owner's آموزش comes later. Nothing here is channel-agnostic: Bale is the
only channel, and alerts are Bale messages too.

## Vocabulary (settled 2026-10-17)

Five words, three layers. The names came out of what the sources actually hold,
not the other way round. The news digest adds a sixth, `story`, in its own design
(`2026-10-17-news-digest-design.md`).

| word | what it is | who owns it |
| --- | --- | --- |
| `list` | one Markdown file of notes | the owner writes it, the app only reads |
| `note` | one item inside a list: a heading id plus body text | the owner |
| `bulletin` | one message that actually goes to Bale, of any kind | the app |
| `watcher` | something external under observation (AvalAI credit) | the app |
| `schedule` | when a run happens | the OS timer |

`note` and `bulletin` are two layers, not two names for one thing. The LLM takes
a `note` and produces the text of a `bulletin`. That is why the history records
two different facts: which note went, and what text was sent.

Alternatives weighed and dropped: naming the note and the bulletin the same word
(would hide the reword step), and dropping `list` as "just a directory" (the
list name is the owner's own label for a group of notes, and it is half of a
note's identity).

## Sources and storage

Two stores, deliberately separate. Mixing them would mean every send dirties the
file the owner hand-edits.

**Content — the owner's, not committed.** A directory of Markdown files, one
file per list. Every note is a small heading carrying its id, followed by the
body:

```markdown
## reading-1
هر روز یک صفحه کتاب بخوان
```

A note's identity is `(list name, heading id)`. The heading is what makes the
identity survive an edit to the text: fixing a typo does not turn the note into
a new one, and does not risk re-sending it.

The live directory is `lists/` and is gitignored. A committed `lists.example/`
holds the same shape so a newcomer can see the format without the owner's
content leaving the machine. The path is `CRIER_LISTS_DIR`.

**History — the app's.** An append-only JSONL file: one line per sent bulletin.
Append-only means no partial rewrite and no schema migration; a size cap trims it
to the last N lines when it grows past the limit, so it cannot fill the disk.
Path and cap are `CRIER_HISTORY_PATH` and `CRIER_HISTORY_MAX_LINES`.

A line carries: `ts`, `kind`, `list_name`, `note_id`, `text`, `ok`. The last-sent time
per note is read straight out of this file — there is no separate "sent" flag in
the content.

## Architecture

One **run** is one wake-up. Every run does the same three things:

1. ask every registered **producer** what bulletins it has right now;
2. send each bulletin to Bale;
3. append one history line per bulletin.

A `watcher` is one kind of producer (it inspects external state); the note-list
reader is another. Adding a new kind of message later means writing a producer
and registering it — not editing the run loop, the sender, or the history.

```
bale_crier/
  config.py      settings from the environment, CRIER_ prefix
  models.py      Note, Story, Bulletin, SendResult, RunReport, HistoryRecord, Package, CreditReport
  producers.py   the Producer protocol; a registry joins when a second producer does
  bale.py        the sender (sendMessage today; media later)
  history.py     append-only JSONL with a size cap
  memory.py      where a watcher keeps its own state across runs
  credit.py      the AvalAI credit endpoint, parsed into numbers
  llm.py         the AvalAI client, reduced to the text or a short error code
  run.py         one run: gather, send, record
  cli.py         the entry point
  watchers/      one module per watcher; avalai_credit.py is the first
  notes/         reading the lists, choosing a note, rewording it
  news/          the AI-news digest: the feed, the selection, the producer
deploy/user/bale-crier.service + .timer          the daily bulletins
deploy/user/bale-crier-credit.service + .timer   the hourly credit check
deploy/user/bale-crier-news.service + .timer     the daily news digest
lists/           the owner's content (gitignored)
lists.example/   the list format, committed
data/history.jsonl
data/watchers.json
tests/
```

## Data model

- `Note` — `list_name`, `id`, `text`.
- `Story` — `title`, `source`, `link`, `guid`, `published` (timezone-aware UTC when the
  feed gave a date, `None` when it did not).
- `Bulletin` — `kind` (`smoke` | `alert` | `note` | `news`), `text`, `note_id` optional,
  `list_name` optional (which list a note came from).
- history line — `{ts, kind, list_name, note_id, text, ok}`.
- watcher memory — one JSON object per producer name, in
  `CRIER_WATCHERS_STATE_PATH`. Its contents are the producer's own business; the
  store only loads, hands out and saves it.

## Choosing a note

The cycle, read from the history: the note whose last send is oldest goes first,
and a note that has never gone is the oldest send of all. Every note is therefore
reached before any repeats, and the spacing a note gets follows from the size of
its list — no count of notes and no per-list tuning.

**The repeat floor was dropped** (owner's ruling, 2026-10-17, after measuring it).
The first design had a second rule on top of the cycle: while any note outside the
floor remained, a note sent within the last `CRIER_NOTE_FLOOR_DAYS` days would not
go again, and if every note was inside the floor the oldest went anyway. With the
notes ordered by last send, the notes outside such a floor are always a *prefix*
of that ordering, so the oldest note is outside the floor exactly when any note
is — the filter hands back the note the cycle already picked — and when every note
is inside the floor the fallback hands back that same note. A version with the
filter deleted passes the same tests, which is what a rule that changes no answer
looks like. `CRIER_NOTE_FLOOR_DAYS` went with it.

## Rewording (the LLM)

One call per bulletin — a failure costs one bulletin, and retrying it costs one
call. The model is configurable (`CRIER_OPEN_AI_MODEL`); the default is a cheap
one, reached through AvalAI's OpenAI-compatible endpoint at
`https://api.avalai.ir/v1`.

The prompt asks for: the note's meaning kept, then **expanded** into one paragraph
of three or four Persian sentences — why the note is worth acting on, and how to
do it today, with an explanation, analogy or example free to be added, but no
number, statistic, quote or event invented; a fresh wording each time, with the
previous wordings of the same note supplied so the model can avoid them; correct
U+200C in every half-space word; and a warm, motivational tone inside the
expansion, since nothing may be appended to it. Output is the message text alone
— no preamble, no quotes, no markdown scaffolding, no line break.

**The note is expanded, not merely reworded** (owner's ruling, 2026-10-21). One
short line read as a bullet on a list rather than as a reminder worth receiving,
so the bulletin is now a few lines: the earlier prompt's "add no claim of your
own" and "keep it short" both pulled the answer back down to a single sentence
and are gone. What stays is that nothing is *fabricated* — the freedom is in
explaining and applying the note, not in asserting facts about the world — and
that the extra lines live inside the rewording rather than after it, so the
"nothing appended" ruling still holds. Verified on 2026-10-21 with three real
calls through `CRIER_OPEN_AI_MODEL`: three to four sentences, no line breaks,
roughly 400 to 500 characters.

The reworded text, not the note's own text, is what the history stores: that is
the record of what the owner actually read.

**Two rulings from the owner (2026-10-17).** There is **no separate motivational
sentence**: the warm tone lives inside the rewording, so nothing is appended to it
and there is no addition to bound — still true after the expansion of 2026-10-21,
which grew the rewording's body rather than hanging lines off it. And **a failed
call is not a lost note**: the bulletin then carries the note's own text followed
by one short Persian line saying the rewording did not happen, with the call's
short error code in parentheses. That bulletin is a real send — the history records
it, and it moves the note through the cycle — because the history is the record of
what the owner actually read. The fallback stays the note's own single line: a
short fallback is the price of a failed call, not the shape of a good bulletin.

## Bale delivery

A `POST` to `https://tapi.bale.ai/bot<TOKEN>/sendMessage` with
`{"chat_id": ..., "text": ...}`, whose response carries `ok`. This is the shape
`bale-news-digest` already verified; nothing is re-probed. Media methods
(`sendPhoto`, `sendMediaGroup`, and the rest) have known shapes and land when a
bulletin first needs one.

No webhook and no long polling: the bot only sends. Receiving is only needed if
it must take commands or acknowledgements, which it does not.

## Scheduling

A `Type=oneshot` systemd **user** service plus a timer, the shape
`bale-news-digest` already runs. Two or three `OnCalendar` entries a day at fixed
times, with `RandomizedDelaySec` for a little spread. A timer survives a restart
with nothing lost, and needs no resident process.

The times are written **literally in `deploy/user/bale-crier.timer`**, not read
from the environment. systemd does not expand environment variables in a unit
file — only its own `%` specifiers — so a `CRIER_SCHEDULE_TIMES` would simply not
work. Checked on 2026-10-17 on systemd 255: a timer whose `OnCalendar` was
`$CRIER_PROBE_TIME` never activated, and the literal string failed to parse as a
calendar spec. Changing the times means editing the unit and running
`systemctl --user daemon-reload`; the unit's own comments say so.

Each run of `bale-crier.timer` sends **one** note bulletin, plus any alert whose
producer has no timer of its own — with two or three runs a day that is the
owner's "several per day". The credit watcher and the news digest each have a
timer of their own, so they are not part of those runs.

There are therefore three timers: `bale-crier.timer` for the daily bulletins,
`bale-crier-credit.timer`, hourly, which runs the same program narrowed with
`--only credit`, and `bale-crier-news.timer`, daily, which runs it with
`--only news` for the AI-news digest.

## Configuration

| variable | meaning |
| --- | --- |
| `CRIER_BALE_BOT_TOKEN` | the bot's token |
| `CRIER_BALE_CHAT_ID` | the destination chat |
| `CRIER_LISTS_DIR` | the content directory (default `lists`) |
| `CRIER_HISTORY_PATH` | the history file (default `data/history.jsonl`) |
| `CRIER_HISTORY_MAX_LINES` | the history cap |
| `CRIER_OPEN_AI_BASE_URL`, `CRIER_OPEN_AI_MODEL`, `CRIER_OPEN_AI_API_KEY` | the LLM (`CRIER_OPEN_AI_API_KEY` inherits `CRIER_AVALAI_API_KEY` when empty) |
| `CRIER_OPEN_AI_TIMEOUT` | how long a model call may take (default 120; the model is a reasoning model and needs tens of seconds, where `CRIER_HTTP_TIMEOUT` is a Bale-sized allowance) |
| `CRIER_AVALAI_API_KEY` | what the credit watcher reads |
| `CRIER_CREDIT_THRESHOLD_IRT` | the credit threshold (default 50,000) |
| `CRIER_WATCHERS_STATE_PATH` | where a watcher keeps its own memory (default `data/watchers.json`) |
| `CRIER_CREDIT_UNKNOWN_ALERT_HOURS` | how often an unreadable credit may speak (default 24) |
| `CRIER_NEWS_FEED_URL` | the news digest's Google News RSS URL (default: the owner's query) |
| `CRIER_NEWS_MAX_ITEMS` | the most stories in one digest (default 10, at least 1) |
| `CRIER_NEWS_BLOCKLIST` | comma-separated filter words; empty means the built-in default |

Settings go through `pydantic-settings`, which gives validation and the
`CRIER_` prefix in one place.

## The credit watcher

`GET https://api.avalai.ir/user/v1/credit` with `Authorization: Bearer <key>`
returns `remaining_irt` (the main balance) plus `credit_sources.packages[]`, with
the numbers arriving as strings. The project calls it directly rather than
shelling out to `~/.config/opencode/scripts/avalai-credit.py` (owner's ruling,
2026-10-17): that directory is agent tooling on a laptop, and a server daemon
should not depend on it. Only a fraction of what that script does is needed here.

**The number the threshold watches** is whatever is paying right now: the active
tier's spendable balance — daily first, then weekly, then unclassified — or the
main balance when no package is live. A package is spendable when its remaining
is above zero and its end date has not passed. Summing a tier is deliberate: two
daily packages can coexist when a new one is bought before the old one drains,
and the provider's order of consumption between them is not documented.

**The alert is a threshold with a latch** (owner's ruling, 2026-10-17), not a
"reached zero" event:

- below `CRIER_CREDIT_THRESHOLD_IRT` while the latch is armed → one alert, and
  the latch is set;
- at or above the threshold → the latch re-arms.

So the alert fires once per crossing. Buying a package lifts the balance back
over the threshold and re-arms the latch, so the next crossing alerts again. It
also means the very first run on an already-low balance speaks immediately.

The latch has to outlive the process, so a watcher keeps a small blob of its own
in `CRIER_WATCHERS_STATE_PATH`. That is deliberately **not** the history: the
history records what the owner read, and nothing else.

**A failed read is its own bulletin**, at most once every
`CRIER_CREDIT_UNKNOWN_ALERT_HOURS` hours, and it says what happened: the credit
could not be read, which is not the same as the credit being gone. The owner's
rule stands — "I cannot tell" is never announced as "the credit is gone". Staying
silent was the alternative and was rejected: a watcher that breaks and says
nothing is a watcher nobody notices is broken.

The bulletin reports the numbers, with no buying advice and no "nearly out"
colour of its own. The threshold is the owner's, not the bot's.

**It runs hourly, on its own timer.** A threshold crossed at 09:00 should not
wait for the afternoon. Checking often costs nothing, because the latch — not the
check — is what keeps a repeated look from becoming a repeated message. A
producer that owns a timer of its own says so (`own_timer`), and the daily run
leaves it out so the two timers cannot race over the same latch.

## Milestones

1. **The path end to end.** Skeleton, config, the Bale sender, the history, one
   hardcoded bulletin, and the timer — a message that really lands in Bale.
2. **The first real bulletin.** The AvalAI credit watcher: the endpoint parsed
   into numbers, the threshold and its latch, the watcher memory that lets the
   latch outlive a run, and a timer of its own.
3. **The owner's lists.** Reading the lists, choosing a note, rewording it.
4. **The news digest.** The day's AI trends from a Google News feed: the fetch and
   parse, the hard filter and the seen set, the model's selection, and a timer of
   its own. Designed in `2026-10-17-news-digest-design.md`. **Built 2026-10-17.**

Each milestone carries its own pytest tests. Milestone 1 is not "done" until a
real message arrives in Bale.

## Testing

pytest, type hints throughout, `uv` for the environment — the stack
`bale-news-digest` runs.

Testable without the network: parsing a list into notes, the cycle's choice given
a synthetic history, the history cap, bulletin rendering, the rewording prompt
and its fallback, and the sender's payload shape against a stub. The live Bale
send is verified by hand, once per milestone.

## Still open

- Which other watchers the owner wants, beyond AvalAI credit. Only that one is
  named so far.
- The daily times are 08:00, 14:00 and 20:00 as a default the owner has not
  confirmed; the hourly credit check needs no confirmation.
- **Settled 2026-10-17:** news summaries do not move here from `bale-news-digest`. That project
  keeps its own news; the news digest is a new, different thing — the day's AI trends from a web
  feed — and has its own design (`2026-10-17-news-digest-design.md`).
