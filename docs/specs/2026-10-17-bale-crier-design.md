# bale-crier — design

Settled with the owner on 2026-10-17. This document records the design and the
reasons behind it; `AGENTS.md` keeps the summary and points here.

## What it is

One server-side bot that pushes into a single Bale chat everything the owner
needs told. Three families of message, one channel:

- **alerts** about external state — AvalAI credit running out and free disk space
  falling below a threshold;
- **notes** drawn from the owner's own lists, expanded by an LLM into a few lines
  of Persian so the same item does not arrive in the same words twice and does
  not arrive as a one-line bullet. The expansion's tone may be warm and
  motivational; nothing is appended to it (settled 2026-10-17, expanded 2026-10-21);
- **news** — the day's AI trends, drawn from a web feed and written in Persian.
  It is a subsystem of its own, designed in
  `2026-10-17-news-digest-design.md` (settled 2026-10-17).

The owner's آموزش comes later. Nothing here is channel-agnostic: Bale is the
only channel, and alerts are Bale messages too.

## Vocabulary (settled 2026-10-17, extended since)

Seven words today, in three layers. Five came first: the names came out of what the
sources actually hold, not the other way round. The news digest added `story` in its
own design (`2026-10-17-news-digest-design.md`), and the changedetection watcher
added `watch` for one page on the other side of its API. `AGENTS.md` carries the same
table, one line each.

| word | what it is | who owns it |
| --- | --- | --- |
| `list` | one Markdown file of notes | the owner writes it, the app only reads |
| `note` | one item inside a list: a heading id plus body text | the owner |
| `bulletin` | one message that actually goes to Bale, of any kind | the app |
| `watcher` | something external under observation (AvalAI credit, free disk space, the pages changedetection.io watches) | the app |
| `watch` | one page under observation in changedetection.io, with its own `last_changed` | changedetection.io, read by the app |
| `story` | one entry in the news feed: a headline, its source and its link | the feed, read by the app |
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
  models.py      Note, Story, Watch, Bulletin, SendResult, RunReport, HistoryRecord, Package, CreditReport
  producers.py   the Producer protocol; a registry joins when a second producer does
  bale.py        the sender (sendMessage today; media later)
  history.py     append-only JSONL with a size cap
  memory.py      where a watcher keeps its own state across runs
  credit.py      the AvalAI credit endpoint, parsed into numbers
  persian.py     numbers written with Persian digits, for the texts that count
  llm.py         the AvalAI client, reduced to the text or a short error code
  run.py         one run: gather, send, record
  cli.py         the entry point
  changedetection.py  the changedetection.io API: the watch list, one watch's diff, the viewed mark
  watchers/      one module per watcher: avalai_credit.py, disk.py, changedetection.py
  notes/         reading the lists, choosing a note, rewording it
  news/          the AI-news digest: the feed, the selection, the producer
deploy/user/bale-crier.service + .timer          the daily bulletins
deploy/user/bale-crier-credit.service + .timer   the hourly credit check
deploy/user/bale-crier-disk.service + .timer     the hourly disk check
deploy/user/bale-crier-changedetection.service + .timer  the three-hourly changedetection check
deploy/user/bale-crier-news.service + .timer     the three-times-daily news digest
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
- `Watch` — `uuid`, `title`, `url`, `last_changed` (epoch seconds; 0 when the watch
  has never changed).
- `Bulletin` — `kind` (`smoke` | `alert` | `note` | `news` | `watch`), `text`,
  `note_id` optional, `list_name` optional (which list a note came from).
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

The prompt asks for: the note's meaning kept, then **expanded** into two short
Persian sentences, under 200 characters — why the note is worth acting on, and how to
do it today, with an explanation, analogy or example free to be added, but no
number, statistic, quote or event invented; a fresh wording each time, with the
previous wordings of the same note supplied so the model can avoid them; correct
U+200C in every half-space word, taught with worked examples (`می‌شود`,
`تجربه‌ها`, `بیشتر`) because the bare rule still let one real bulletin go out
with `میآید`; and a warm, motivational tone inside the
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
roughly 400 to 500 characters. **Halved on 2026-10-27** (owner's ruling): that
much read as too long in the chat. Two sentences alone did not do it — a live
call cut to "two sentences" still came back at 427 characters, because the model
only packed the same length into fewer periods — so the instruction now also caps
the whole text at 200 characters. Two more live calls through the same model
answered at 174 and 180 characters, two sentences each.

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
producer has no timer of its own — with two runs a day (08:00 and 20:00, the
owner's choice on 2026-10-27, down from three) that is "twice a day". The credit
watcher, the disk watcher, the
changedetection watcher and the news digest each have a timer of their own, so
they are not part of those runs.

There are therefore five timers: `bale-crier.timer` for the daily bulletins,
`bale-crier-credit.timer`, hourly, which runs the same program narrowed with
`--only credit`, `bale-crier-disk.timer`, hourly, which runs it with `--only disk`,
`bale-crier-changedetection.timer`, every three hours, which runs it with
`--only changedetection`, and `bale-crier-news.timer`, three times a day at
09:00, 15:00 and 21:00, which runs it with
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
| `CRIER_CREDIT_EXPIRY_WARNING_HOURS` | how long before a weekly package lapses the owner hears of it (default 24, at least above 0) |
| `CRIER_DISK_PATH` | the filesystem the disk watcher reads (default `/`) |
| `CRIER_DISK_THRESHOLD_GIB` | the free-space threshold in GiB (default 2) |
| `CRIER_DISK_REMINDER_HOURS` | how often a still-low disk may remind the owner (default 24) |
| `CRIER_NEWS_FEED_URL` | the news digest's Google News RSS URL (default: the owner's query) |
| `CRIER_NEWS_MAX_ITEMS` | the most stories in one digest (default 10, at least 1) |
| `CRIER_NEWS_BLOCKLIST` | comma-separated filter words; empty means the built-in default |
| `CRIER_CHANGEDETECTION_URL` | where changedetection.io listens (default `http://127.0.0.1:5005`, the loopback) |
| `CRIER_CHANGEDETECTION_API_KEY` | the key from changedetection's own settings; without it the watcher is not registered |
| `CRIER_CHANGEDETECTION_UNKNOWN_ALERT_HOURS` | how often an unreadable changedetection may speak (default 24) |

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

**A weekly package about to lapse is its own bulletin** (owner's request,
2026-10-27). The same read already carries each package's `end_date`, so this
costs no second call: a weekly package that still holds money and whose end date
is inside `CRIER_CREDIT_EXPIRY_WARNING_HOURS` (default 24) speaks once, naming the
package, the time left and the money left in it. The announcement is remembered
per package by name and end date, because the check runs hourly and a package
inside its window would otherwise be announced every hour; the entry is pruned
once the package has lapsed, so the next weekly package warns again. Two things
are deliberately silent: a weekly package with nothing left in it (an empty pot
lapsing is not news), and every daily package (its whole life is a day, so a
day's warning would be on from the moment it was bought). Like the threshold
bulletin, this one states what is left and when it goes, and advises nothing.

A package whose `remaining_irt` cannot be read is still announced: the end date
was read even when the money was not, and the amount is replaced by one line
saying the balance could not be read — a failed number is never a zero. And as
with every latch here, the memory is written only when every send in the run
landed, so a failed send repeats the notice on the next run rather than losing
it.

**It runs hourly, on its own timer.** A threshold crossed at 09:00 should not
wait for the afternoon. Checking often costs nothing, because the latch — not the
check — is what keeps a repeated look from becoming a repeated message. A
producer that owns a timer of its own says so (`own_timer`), and the daily run
leaves it out so the two timers cannot race over the same latch.

## The disk watcher

Settled with the owner on 2026-10-21. The number it watches is the free space on
one filesystem — `/` by default (`CRIER_DISK_PATH`), which on this machine is the
whole disk: `/proc/mounts` showed one ext4 root and no separate `/home`, so
pointing it anywhere else would report the same numbers. The threshold is
`CRIER_DISK_THRESHOLD_GIB`, 2 by default: the setting and the bulletin use the
same unit, so no message shows one number and means another.

**The alert is a threshold with a latch and a reminder.** Below the threshold
while the latch is armed → one alert and the latch is set; at or above it → the
latch re-arms. That alone would send nothing more while the disk stays low, and a
disk nobody cleans up does not fix itself, so while space remains below the
threshold the watcher may repeat at most once every `CRIER_DISK_REMINDER_HOURS`
hours (24 by default). The reminder says the disk is *still* low rather than
reusing the crossing wording, so the owner can tell a new crossing from a repeat.

The owner chose the latch-plus-daily-reminder over a plain latch and over a
message on every check (2026-10-21), and hourly checks over three fixed times:
checking often costs nothing because the latch and the window, not the check,
decide when a message goes.

**A failed read is its own bulletin**, at most once per reminder window, and it
says the reading failed — "I cannot tell" is never announced as "the disk is
full". It leaves the latch exactly as it found it, so a crossing it could not see
still speaks once the reading works again. The state lives in the watcher memory
under the name `disk`, with `armed` and `last_alert`.

It runs hourly on `bale-crier-disk.timer` with `--only disk`, for the same reason
the credit watcher does: a producer that owns a timer keeps the daily run from
racing over its latch.

## The changedetection watcher

Settled with the owner on 2026-10-21. The thing under observation is not a number
this project reads itself: `changedetection.io` on the same machine watches a
handful of pages (model-list endpoints, a news site) and already knows when one of
them changes. The bot's job is only to turn that knowledge into a Bale message.

**It asks; it is not told.** changedetection can push a notification through
Apprise, and the Apprise it ships with has no Bale plugin — its telegram module is
hardcoded to `api.telegram.org` — so the push path would need a receiving server of
our own. That would give the bot an inbound door, which the design refuses ("the
bot sends and never receives"). The watcher therefore polls the local API on the
loopback (`CRIER_CHANGEDETECTION_URL`, `http://127.0.0.1:5005`) with
`x-api-key`, so Caddy and the public hostname are not on the path: a public outage
cannot silence the watch, and there is no second way into Bale.

**The state is one watermark per watch.** `GET /api/v1/watch` returns, per watch,
`last_changed` — the epoch second of the last change changedetection detected. The
watcher keeps the number it has already reported, under the name
`changedetection` in `CRIER_WATCHERS_STATE_PATH`, and speaks when a watch's number
moves past it. Three cases are deliberately silent, each because the alternative
would be a message about something that is not news:

- **the first run ever**: everything under watch changed at some point in the
  past, so every number is recorded and nothing is said;
- **a watch seen for the first time later**: a page added yesterday may carry a
  change from before it was added;
- **a number that moves backwards**: clearing a watch's history resets
  `last_changed`, which is a reset and not a change.

**One bulletin per run, not one per page** (owner's choice, 2026-10-21). The pages
are checked together and a run rarely finds more than one, so the message lists
whatever changed — oldest first, so no page can wait behind one that changed
after it, each with its address, how long ago the change was seen, and the
changed lines from
`GET /api/v1/watch/<uuid>/difference/previous/latest?changesOnly=true&no_markup=true`,
which is the API's own per-snapshot diff. The API's segment placemarkers become
patch-style `+` and `-` lines, and the ten lines a page are shared between the two
directions — up to five each, one side lending the rest when it is short: changedetection renders a rewritten page as all of its old lines and
then all of its new ones, so a plain "first ten" cut would show ten things vanishing
and never their replacements. The whole text stays below Bale's 4096-character
limit; a page whose block does not fit keeps its watermark, so the next run carries
it, which is what the message's last line promises. A page whose diff cannot be read
is still reported, with one line saying the text could not be read: `last_changed`
already proved the change, so losing the detail must not lose the message. The diff
is the API's snapshot diff, so a watch's own `ignore_text` rules are not applied to
it.

**The unread dot goes out after the message lands** (owner's request, 2026-10-25).
changedetection keeps a per-watch flag — its unread dot — for a change the operator has
not opened in the UI: `has_unviewed` is "a newer snapshot than `last_viewed`", and the
API's own rule is that a `last_viewed` above the newest snapshot marks a watch viewed
(`PUT /api/v1/watch/<uuid>`, a partial body the API merges). Once a message has landed,
the watcher writes that for the pages the message carried — through a hook the run loop
calls after the sends (`Producer.sent`), so a failed send leaves every dot on. Pages left
over for the next message keep theirs: they have not been told yet. This is the one write
the bot makes anywhere but Bale, and it redefines the dot: from "not opened in the UI" to
"Bale has not told me yet". A mark that fails is not retried and adds no line to the
message — a dot left on is the safe direction, and the message itself already went.

**The watermark only advances when the message landed.** The run saves no watcher
memory after a failed send (`run.py`), so a Bale outage repeats a change on the next
run instead of losing it — the same safe direction the memory store already took for
a crash between produce and send.

**A failed read is its own bulletin**, at most once every
`CRIER_CHANGEDETECTION_UNKNOWN_ALERT_HOURS` hours (24 by default), and it says the
reading failed — "I cannot tell" is never announced as "nothing changed". The
watermarks are left exactly as they were found, so a change the failure could not
see still speaks on the next run that can; a first read that fails has no numbers to
leave, and the first-run rule then takes the baseline silently.

**It runs every three hours at half past**, on `bale-crier-changedetection.timer`
with `--only changedetection`. Three hours is the owner's choice (2026-10-21): it is
also the interval changedetection itself fetches a page with here (its global
`time_between_check`), so reading the API more often would cost a request and tell
the owner nothing sooner.

The half hour is the owner's second ruling (2026-10-21): read just after
changedetection's fetch, not somewhere in the middle of its cycle. changedetection
has no global check clock — each watch keeps its own phase, three hours from its own
last fetch — so "half past" only means "half an hour after the fetch" once those
phases are aligned, which was done once by forcing a recheck of every active watch at
18:00. The delivery delay is then what the change itself costs: up to three hours
until the next fetch plus half an hour, so up to three and a half hours (about two on
average), where the two independent clocks it replaces could leave a change waiting
six.

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
5. **The disk watcher.** Free space on the machine's one filesystem under a
   threshold, with a latch and a daily reminder, and a timer of its own.
   **Built 2026-10-21.**
6. **The changedetection watcher.** One bulletin naming the pages
   `changedetection.io` saw change, read from its local API every three hours with
   a watermark per watch. **Built 2026-10-21.**

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

- Which other watchers the owner wants, beyond AvalAI credit, free disk space and
  the pages changedetection.io watches.
- The daily times are 08:00 and 20:00 — twice a day, as the owner chose on
  2026-10-27, down from the three-times default; the hourly credit check needs no
  confirmation.
- **Settled 2026-10-17:** news summaries do not move here from `bale-news-digest`. That project
  keeps its own news; the news digest is a new, different thing — the day's AI trends from a web
  feed — and has its own design (`2026-10-17-news-digest-design.md`).
