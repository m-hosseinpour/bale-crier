# bale-crier

One server-side bot that pushes into a single Bale chat everything the owner needs told: hard
alerts about external state (the disk filling up, a watched page changing, and similar), notes
drawn from his own lists and sent as they are once a day at 07:07 (an LLM expansion is available
behind an off-by-default switch), and an AI-news digest three times a day, picked and written in
Persian.

Bale is the only channel. The bot sends and never receives — no webhook, no long polling.

**Status:** milestones 1 (the path end to end), 3 (the owner's lists), 4 (the news digest), 5 (the
disk watcher) and 6 (the changedetection watcher) are built and tested. Milestone 2, the AvalAI
credit watcher, was removed on 2026-11-26. Since 2026-11-28 the note run sends each note as written;
the model rewording is opt-in behind `CRIER_NOTE_REWORD`.

The design and the reasons behind it are in `docs/specs/2026-10-17-bale-crier-design.md`; one plan
per milestone lives in `docs/plans/`.

## Setup

`uv` and Python 3.11 or newer are needed.

```sh
uv sync
cp .env.example .env
```

Then fill in `.env`. Two settings have no default and a run refuses to start without them:

| variable | meaning |
| --- | --- |
| `CRIER_BALE_BOT_TOKEN` | the token of `@bale_crier_bot` |
| `CRIER_BALE_CHAT_ID` | the destination chat |

Every other setting has a default; `.env.example` lists them all. A misconfigured run prints one
Persian sentence naming the variable and exits, rather than raising a stack trace.

## Run

One run:

```sh
uv run python -m bale_crier
```

A run asks every producer for bulletins, sends each one to Bale, and appends one line per bulletin
to the history — whatever the outcome, so a failed send is still on record. That line carries the
sender's own reason when the send failed (`error`), and the run's summary names each reason on
stderr, so a refusal is never a bare count. The exit code is zero when nothing failed. The watcher memory is written only when every send landed, so a failed send
costs a repeat next run rather than the change it was carrying.

Every completed run also appends one line to the **run log** (`CRIER_RUNS_PATH`, default
`data/runs.jsonl`; capped at `CRIER_RUNS_MAX_LINES`, default 1000). That line says when the run
happened (`ts`), what `--only` asked for (`only`, `null` for the ordinary note run), which producers
were actually built (`producers`), how many messages went and failed (`sent`, `failed`), and the
sender's reasons (`errors`). It is written even when the run sent nothing and even when no producer
could be built, so a missing line means the run never finished — not that it had nothing to say. A
run that raises writes no line. The run log is deliberately separate from the history: the history
is what the owner read, the run log is what the process did, and neither is derived from the other.

```json
{"ts":"2026-11-10T02:05:12.123456Z","only":["disk"],"producers":["disk"],"sent":0,"failed":0,"errors":[]}
```

`CRIER_SMOKE=1` replaces the producers with the smoke producer, which sends one fixed test bulletin.
It is how the path is proved after a deploy, and it is never registered by default.

`--only NAME` narrows a run to one producer, and may be repeated. The disk and changedetection
watchers and the news digest each own a timer of their own, so the ordinary run leaves all three
out; the watchers' timers run them alone with `--only disk` and `--only changedetection`, and the
news timer runs the digest alone with `--only news`. The disk watcher needs no key and no network,
so it is always registered. The changedetection watcher needs its API key, and without one it is
not registered at all. The digest needs an LLM key; without one `--only news` says so in Persian and
sends nothing.

The note producer is the note run's own work and is always registered: by default it sends the
note's own text, so it needs no model key. A model key is needed by the digest, and by the note
run only when `CRIER_NOTE_REWORD` is on; with the switch on and no key, the run says so in Persian
on stderr and sends the note as it is. With no `lists/` directory the run says so on stderr rather
than passing the gap off as a quiet day.

Tests:

```sh
uv run pytest
```

## The notes

The note run sends one note from the owner's own lists. A list is one Markdown file in `lists/`
(gitignored; `lists.example/` shows the format), and a note is a `## id` heading plus the body under
it:

```markdown
## reading-1
هر روز یک صفحه کتاب بخوان
```

A note's identity is `(list name, heading id)`, so fixing a typo in the body does not look like a new
note and does not risk re-sending it.

Which note goes is the **cycle**: the one whose last send is oldest goes first, and a note that has
never gone goes before any that has. So every note is reached before any repeats, and the spacing a
note gets follows from the size of its list. There is deliberately no separate "do not repeat within
N days" floor: with the notes ordered by last send, such a floor can only ever return the note the
cycle had already picked.

The note goes out as it is written: the body under the heading is the message. **The LLM expansion
is off by default** (owner's ruling, 2026-11-28); set `CRIER_NOTE_REWORD=1` to have the model reword
the note into fresh Persian through `CRIER_OPEN_AI_MODEL`, as two short sentences under 200
characters explaining the note's point and why it matters, with the wordings it already arrived in
supplied so the model can avoid them. The explanation is plain and clear: no simile, metaphor or
poetic phrasing, and it says the point rather than reporting what "the note says" (2026-11-12). The
model may not invent a number, statistic, quote or event, and it gives no practical tip about how to
apply the note — the owner found those tips useless (2026-11-05). The history stores what was
actually sent: the note's text, or the expansion when it ran. With the switch on, a failed call does
not cost the note: the bulletin then carries the note's own text followed by one line saying the
expansion did not happen, and the history records that.

A model call gets `CRIER_OPEN_AI_TIMEOUT` (default 600 seconds, ten minutes), not the 30-second
`CRIER_HTTP_TIMEOUT`: it is a reasoning model reached through a router, and a slow route can take
minutes to answer, so a shorter allowance would silently turn every reworded note and every digest
into its fallback.

`--only note` runs the note producer alone.

## The disk watcher

The watcher reads the free space on the filesystem at `CRIER_DISK_PATH` (default `/`; the whole
machine is one mount here) and speaks when it falls below `CRIER_DISK_THRESHOLD_GIB` (default 2 GiB
— the setting and the bulletin use the same unit).

The alert is a threshold with a latch: below the threshold while the latch is armed, one alert
goes and the latch is set; at or above it the latch re-arms. On top of that, space that stays below
the threshold gets a reminder at most once every
`CRIER_DISK_REMINDER_HOURS` hours (default 24) — a disk nobody cleans up does not fix itself, so
one crossing alert alone would scroll away and be forgotten. The reminder says the disk is still
low rather than pretending it just crossed.

A read that fails is its own bulletin, at most once per reminder window, and it says the reading
failed — **"I cannot tell" is never announced as "the disk is full"**. It leaves the latch exactly
as it found it.

The latch is the watcher's own memory, in `CRIER_WATCHERS_STATE_PATH` under the name `disk` —
deliberately separate from the history, which records what the owner read.

It runs hourly, on its own timer, `bale-crier-disk.timer`, with `--only disk`. Checking often costs
nothing: the latch and the reminder window, not the check, decide when a message goes.

## The changedetection watcher

`changedetection.io` on this machine watches a handful of pages and knows when one of them changes.
This watcher reads that knowledge out of its API — on the loopback, `CRIER_CHANGEDETECTION_URL`
(default `http://127.0.0.1:5005`), with `CRIER_CHANGEDETECTION_API_KEY` from its own settings — and
turns it into one Persian message naming the pages that changed and the lines that changed in them.

It asks rather than being told, because changedetection's own notifications go through Apprise and
the Apprise it ships with has no Bale plugin. The alternative — a webhook into a receiving server of
our own — would give the bot an inbound door it deliberately does not have.

The state is one number per watch: the `last_changed` this bot has already reported. A watch whose
number has moved past that speaks once; the run then records the new numbers of the pages its
message carried, so the next run is quiet about those. The very first run records every number and says nothing — everything under watch has changed
at some point in the past, and none of it is news — and a watch added later is recorded the same way,
silently. A number that moves *backwards* (history cleared in changedetection) is a reset, not a
change, so it is recorded without a word.

One bulletin per run, not one per page: the pages are checked together, and a run rarely finds more
than one. Each page is a block — its title, how long ago the change was seen, and the page's address
as plain text on the line below the title (a page with no title is just its address; the owner asked
for plain addresses rather than Markdown links, 2026-11-05) — then the changed lines in patch style:
`+` for what appeared, `-` for what went away, and both when a line was
rewritten. A block carries at most ten changed lines — up to five from each side, borrowing the rest
when one side is short — plus a line counting the remainder, so a rewritten page does not show only
what vanished. The whole text stays inside one Bale
message; a page whose block does not fit is left for the next run, and the message's last line says
so. A page whose diff cannot be read is still reported, with one line saying the text could not be
read, because `last_changed` already proved the change; a page with a single snapshot has nothing to
diff and says only that.

A failed read of the API is a bulletin of its own, at most once every
`CRIER_CHANGEDETECTION_UNKNOWN_ALERT_HOURS` hours (default 24), and it says the reading failed —
**"I cannot tell" is never announced as "nothing changed"**. It leaves the numbers exactly as it
found them, so a change it could not see still speaks on the next run that can — except on the very
first run, where there were no numbers yet and the next successful run takes the silent baseline.

Once the message has landed, the watcher also clears the page's unread dot in changedetection —
the one thing this bot writes anywhere but Bale. It does that by sending `last_viewed` back
through the same API, after the send succeeded, and only for the pages the message carried: a
page left for the next message keeps its dot, and a failed send keeps every dot. This changes
what the dot means, deliberately — it no longer says "I have not opened this diff in the UI",
it says "Bale has not told me about this change yet".

It runs every three hours at half past (00:30, 03:30, … 21:30), on
`bale-crier-changedetection.timer` with `--only changedetection`. Three hours is how often
changedetection itself fetches a page here (its global `time_between_check`); the half hour puts
the read just after that fetch instead of somewhere in the middle of its cycle. changedetection has
no global clock — each watch is fetched three hours after its own last fetch — so its pages were
aligned to the top of the hour once, by forcing a recheck of every active watch. If they drift over
the months, re-align them the same way and the half hour is honest again.

## The news digest

The digest arrives as messages of at most five AI-news stories each, and often it does not arrive at
all: only news the owner would call genuinely valuable gets through. It reads a Google News RSS
search — `CRIER_NEWS_FEED_URL`, whose default is the owner's query — and parses it into stories. It
then drops what the owner does not want to read before the model ever sees it.

**The hard filter** drops a story whose title contains one of `CRIER_NEWS_BLOCKLIST`'s words,
case-insensitive and on word boundaries; when the setting is empty the built-in default is used:
`funding, raises, valuation, lawsuit, ban, regulation, layoffs, earnings, iPhone, iOS, Android,
gaming, laptop, laptops, GPU, driver, drivers, DLSS, Fitbit, Sims, Chrome, Netflix` — the first
eight are news types the owner does not want, the rest are consumer-device words, because an earlier
query also matched phone, gaming and driver releases. **The seen set** then drops the stories the
digest already carried. It is the producer's own memory, in `CRIER_WATCHERS_STATE_PATH` under the
name `news`, holding the guids the digest carried, newest last and capped at 500 — deliberately
separate from the history, which records what the owner read.

What survives goes to the model newest first, capped at 60 candidates. **It is a bar, not a ranking:**
the prompt names the four things worth sending — a new AI model (especially a frontier or open-weight
one), a leap in capability, an event whose impact goes past one company or device, and a serious
warning from a credible body — and tells the model to drop everything else: product and feature news,
minor versions, funding, commercial deals, earnings, lists, how-tos, rumours, and anything confined to
one company or device. It picks at most `CRIER_NEWS_MAX_ITEMS` (default 10, though a strict run
usually carries two or three, and often none) and writes one short Persian line for each, answering
with indices the code maps back to the real title, source and link — so a model that invents a link is
impossible rather than merely unlikely. When nothing clears the bar it answers `0|` alone and the run
sends nothing; that quiet run is a real answer, not a failure, and it marks nothing seen, so a story
can still be picked later if it grows into the day's big news. Each message is a fixed Persian
header, then its stories numbered with Persian digits as their Persian line, then
`منبع: [<source>](<link>)`. Bale formats every message as Markdown, so the address hides behind the
source name rather than filling the line with three hundred characters of Google News redirect; a
story with no source shows the label «لینک خبر» instead. The address itself is still in the text —
which is what the 4096-character count sees — and it is a Google News redirect, never the publisher's
URL: the server never resolves it, the owner's browser does when he taps it.

**The stories go out in groups of `CRIER_NEWS_BATCH_SIZE`** (default 5), each message restarting its
numbering at ۱, so ten stories arrive as two messages of five. The split is not only the owner's
preference: Bale's `sendMessage` takes 1 to 4096 characters and refuses the whole message beyond it,
and ten stories with their Google News links reach 4300 to 5100 characters — which is how five
digests were lost between 22 and 29 October 2026, each one recorded in `history.jsonl` as `ok: false`
and never seen in the chat, while every send that landed was under 4000. A group that would cross
4000 characters therefore closes early and the rest goes in the next message; only a story that alone
crosses the limit ships uncut, because cutting it would break the link.

Two failures speak, and a quiet day does not. A feed read that fails is retried once after three
seconds, because Google News throttles or drops the connection now and then; if both reads fail, one
short Persian line names the short error code and says plainly that this was a failed read, not a
quiet day — "I cannot tell" stays "I cannot tell", and a quiet run is silent. A model that fails, or
an answer that does not parse, sends the raw English headlines of the newest `CRIER_NEWS_MAX_ITEMS`
survivors with their sources and links, in the same groups, each message carrying the Persian line
that names the failure and the call's code. A feed
that was read with nothing left sends nothing: a day without news is not a failure.

The digest owns a timer of its own, `bale-crier-news.timer`, three times a day at 09:07, 15:07 and
21:07, so the note run leaves it out and the two cannot race over one seen set. `--only news` runs
it alone. The seven-minute offset keeps its model call from landing with the other project's :00
news run.

## Structure

```
bale_crier/
  config.py      settings from the environment, CRIER_ prefix
  models.py      Bulletin, SendResult, RunReport, RunRecord, HistoryRecord, Note, Story, Watch
  bale.py        the sender — the only place that talks to Bale, and the one that knows its Markdown
  history.py     append-only JSONL with a size cap
  runs.py        the run log: one append-only line per completed run
  jsonl.py       the crash-safe append and trim both stores share
  memory.py      a watcher's own state, across runs
  persian.py     numbers written with Persian digits, for the texts that count
  changedetection.py  the changedetection.io API: the watch list and one watch's diff
  llm.py         the AvalAI chat call, reduced to the text or a short error
  producers.py   the Producer protocol and the smoke producer
  run.py         one run: gather, send, record
  cli.py         the entry point
  watchers/      one module per watcher: disk.py, changedetection.py
  notes/         the owner's lists: reading them, choosing a note, the opt-in rewording
  news/          the AI-news digest: the feed, the selection, the producer
deploy/user/     the systemd units
lists/           the owner's content (gitignored)
lists.example/   the list format, committed
data/            the history, the run log and the watcher memory (gitignored)
tests/           pytest
```

## Deploy

Four `Type=oneshot` user services, each with a timer of its own. Install them into the user manager:

```sh
cp deploy/user/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now bale-crier.timer bale-crier-disk.timer bale-crier-changedetection.timer bale-crier-news.timer
```

There are four timers. `bale-crier.timer` runs the note bulletins (everything but the disk watcher,
the changedetection watcher and the news digest); `bale-crier-disk.timer` runs the disk check hourly
with `--only disk`, `bale-crier-changedetection.timer` runs the changedetection check every three
hours with `--only changedetection`, and `bale-crier-news.timer` runs the digest three times a day with
`--only news`. Each owns a timer of its own so it cannot race over the note run's latch, watermarks
or seen set. Enabling the disk watcher, the changedetection watcher and the digest is not optional —
without their timers nothing ever checks the disk or changedetection, and nothing sends the digest.

Enable the **timers**, not the services — each service is a oneshot with no `[Install]` section, so
enabling it alone does nothing. Run `sudo loginctl enable-linger $USER` once, or the user manager
(and the timers with it) is torn down when the last session ends.

The run reads `.env` from the unit's `WorkingDirectory`, so the token, the chat id and
`CRIER_OPEN_AI_API_KEY` live in `/home/mahdi/workspace/bale-crier/.env`. The model key is only for
the digest and, when `CRIER_NOTE_REWORD` is on, the note rewording; a missing one leaves the digest
off and only costs the note its rewording. `WorkingDirectory` also fixes where the relative
`lists_dir`, `history_path` and `watchers_state_path` point. The two units that can call the
model — `bale-crier.service` (only with `CRIER_NOTE_REWORD`) and `bale-crier-news.service` — set
`TimeoutStartSec=900`, above systemd's 90-second default, so a run is not killed while it waits out
a feed fetch, a model call and a send in turn. Keep it above `CRIER_OPEN_AI_TIMEOUT` plus the
`CRIER_HTTP_TIMEOUT` allowances if you raise them.

The times are literal `OnCalendar` lines in the unit files — 07:07 in `bale-crier.timer` (once a
day, one note per run, seven minutes after the other project's 07:00 news run); `hourly` with a
two-minute spread in `bale-crier-disk.timer`; `*-*-* 00/3:30:00` with a two-minute spread in
`bale-crier-changedetection.timer`; and 09:07, 15:07 and 21:07 with a two-minute spread in
`bale-crier-news.timer` (three times a day, each about seven minutes after the other project's
:00 run).
systemd expands no environment variable in a unit file, so a schedule setting would silently never
fire. To change a time, edit the unit, copy it again and run `systemctl --user daemon-reload`.

Check them:

```sh
systemctl --user list-timers bale-crier.timer bale-crier-disk.timer bale-crier-changedetection.timer bale-crier-news.timer
journalctl --user -u bale-crier.service
journalctl --user -u bale-crier-disk.service
journalctl --user -u bale-crier-changedetection.service
journalctl --user -u bale-crier-news.service
```

Before the timer is enabled, prove the path by hand with one test bulletin:

```sh
CRIER_SMOKE=1 uv run python -m bale_crier
```

And prove the disk watcher by hand. With more than 2 GiB free it sends nothing; to see the latch
work, raise `CRIER_DISK_THRESHOLD_GIB` above the current free space, run once and watch one alert
arrive, then run again and watch the latch hold — and the 24-hour reminder window keep it quiet.

```sh
uv run python -m bale_crier --only disk
```

And prove the changedetection watcher by hand. The first run records every watch's `last_changed` and
sends nothing; a run after a page has changed sends one message naming it and the lines that changed.
To force one without waiting for a page to change, lower one number in `data/watchers.json` under
`changedetection.seen` and run again:

```sh
uv run python -m bale_crier --only changedetection
```

And prove the digest by hand. One run sends one digest and records the stories it carried in the
seen set, so a second run in the same minute carries *different* stories — the ones the first run
left behind. Remove the `news` key from `data/watchers.json` between the two runs and the second
run sends the same stories again, which is what shows the seen set is doing the work.

```sh
uv run python -m bale_crier --only news
```

