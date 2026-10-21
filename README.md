# bale-crier

One server-side bot that pushes into a single Bale chat everything the owner needs told: hard
alerts about external state (AvalAI credit running out, the disk filling up, and similar), notes
drawn from his own lists, expanded and varied by an LLM into a few Persian lines a few times a day,
and a daily digest of AI news, picked and written in Persian.

Bale is the only channel. The bot sends and never receives — no webhook, no long polling.

**Status:** milestones 1 (the path end to end), 2 (the AvalAI credit watcher), 3 (the owner's
lists), 4 (the news digest), 5 (the disk watcher) and 6 (the changedetection watcher) are built and
tested.

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
to the history — whatever the outcome, so a failed send is still on record. The exit code is zero
when nothing failed. The watcher memory is written only when every send landed, so a failed send
costs a repeat next run rather than the change it was carrying.

`CRIER_SMOKE=1` replaces the producers with the smoke producer, which sends one fixed test bulletin.
It is how the path is proved after a deploy, and it is never registered by default.

`--only NAME` narrows a run to one producer, and may be repeated. The credit, disk and
changedetection watchers and the news digest each own a timer of their own, so the ordinary run
leaves all four out; the watchers' timers run them alone with `--only credit`, `--only disk` and
`--only changedetection`, and the daily news timer runs the digest alone with `--only news`. The
credit watcher is not registered at all unless `CRIER_AVALAI_API_KEY` is set — a run under
`--only credit` without it says so in Persian and sends nothing. The disk watcher needs no key and
no network, so it is always registered. The changedetection watcher needs its API key, and without
one it is not registered at all. The digest, like the note producer, needs an LLM key; without one
`--only news` says so in Persian and sends nothing.

The note producer is the daily run's own work, and is registered only when an LLM key exists. With
no key, or with no `lists/` directory, the run says so in Persian on stderr rather than passing the
gap off as a quiet day.

Tests:

```sh
uv run pytest
```

## The notes

The daily run sends one note from the owner's own lists. A list is one Markdown file in `lists/`
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

The note is expanded before it is sent — fresh Persian through `CRIER_OPEN_AI_MODEL`, as one
paragraph of three or four sentences saying why the note is worth acting on and how to do it today,
with the wordings it already arrived in supplied so the model can avoid them. The model may explain,
compare or give an example, but it may not invent a number, statistic, quote or event: the extra
lines are application, not new facts. The history stores the expanded text, because that is what the
owner actually read. A failed call does not cost the note: the bulletin then carries the note's own
text followed by one line saying the expansion did not happen, and the history records that.

A model call gets `CRIER_OPEN_AI_TIMEOUT` (default 120 seconds), not the 30-second
`CRIER_HTTP_TIMEOUT`: it is a reasoning model and takes tens of seconds to answer, so a shorter
allowance would silently turn every note and every digest into its fallback.

`--only note` runs the note producer alone.

## The credit watcher

The watcher reads `https://api.avalai.ir/user/v1/credit` and watches whatever is paying right now:
the active tier's spendable balance (daily first, then weekly, then unclassified), or the main
balance when no package is live.

The alert is a **threshold with a latch**, not a "reached zero" event. Below
`CRIER_CREDIT_THRESHOLD_IRT` while the latch is armed, it sends one alert and sets the latch; at or
above the threshold the latch re-arms. So the alert fires once per crossing, and buying a package
that lifts the balance back over the threshold makes the next crossing speak again. The latch lives
in `CRIER_WATCHERS_STATE_PATH` (default `data/watchers.json`) so it outlives the process.

A read that fails is its own bulletin, at most once every `CRIER_CREDIT_UNKNOWN_ALERT_HOURS` hours,
and it says the reading failed — **"I cannot tell" is never announced as "the credit is gone"**. The
bulletin reports the numbers and nothing else: no buying advice, and no "nearly out" colour of its
own. The threshold is the owner's, not the bot's.

The latch is the watcher's own memory, deliberately separate from the history: the history records
what the owner read, and nothing else.

## The disk watcher

The watcher reads the free space on the filesystem at `CRIER_DISK_PATH` (default `/`; the whole
machine is one mount here) and speaks when it falls below `CRIER_DISK_THRESHOLD_GIB` (default 2 GiB
— the setting and the bulletin use the same unit).

The alert is a threshold with a latch, like the credit watcher's: below the threshold while the
latch is armed, one alert goes and the latch is set; at or above it the latch re-arms. On top of
that, space that stays below the threshold gets a reminder at most once every
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
than one. Each page is a block — its address, how long ago the change was seen, then the changed
lines in patch style: `+` for what appeared, `-` for what went away, and both when a line was
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

It runs every three hours at half past (00:30, 03:30, … 21:30), on
`bale-crier-changedetection.timer` with `--only changedetection`. Three hours is how often
changedetection itself fetches a page here (its global `time_between_check`); the half hour puts
the read just after that fetch instead of somewhere in the middle of its cycle. changedetection has
no global clock — each watch is fetched three hours after its own last fetch — so its pages were
aligned to the top of the hour once, by forcing a recheck of every active watch. If they drift over
the months, re-align them the same way and the half hour is honest again.

## The news digest

The digest is one message a day carrying a handful of AI-news stories. It reads a Google News RSS
search — `CRIER_NEWS_FEED_URL`, whose default is the owner's query — and parses it into stories. It
then drops what the owner does not want to read before the model ever sees it.

**The hard filter** drops a story whose title contains one of `CRIER_NEWS_BLOCKLIST`'s words,
case-insensitive and on word boundaries; when the setting is empty the built-in default is used:
`funding, raises, valuation, lawsuit, ban, regulation, layoffs, earnings, iPhone, iOS, Android,
gaming, laptop, laptops, GPU, driver, drivers, DLSS, Fitbit, Sims, Chrome, Netflix` — the first
eight are news types the owner does not want, the rest are consumer-device words, because the
feed's phrasing also matches phone, gaming and driver releases. **The seen set** then
drops the stories the digest already carried. It is the producer's own memory, in
`CRIER_WATCHERS_STATE_PATH` under the name `news`, holding the guids the digest carried, newest
last and capped at 500 — deliberately separate from the history, which records what the owner read.

What survives goes to the model newest first, capped at 60 candidates; it picks at most
`CRIER_NEWS_MAX_ITEMS` (default 10) and writes one short Persian line for each, answering with
indices the code maps back to the real title, source and link — so a model that invents a link is
impossible rather than merely unlikely. The message is a fixed Persian header, then each story
numbered with Persian digits as its Persian line, then `منبع: <source> — <link>`. The link is a
Google News redirect, never the publisher's URL; the server never resolves it — the owner's browser
does when he taps it.

Two failures speak, and a quiet day does not. A feed that cannot be read sends one short Persian
line naming the short error code, and never claims there was no news — "I cannot tell" stays
"I cannot tell". A model that fails, or an answer that does not parse, sends the raw English
headlines of the newest `CRIER_NEWS_MAX_ITEMS` survivors with their sources and links, plus one
Persian line naming the failure and the call's code. A feed that was read with nothing left sends
nothing: a day without news is not a failure.

The digest owns a timer of its own, `bale-crier-news.timer`, daily at 09:00, so the daily note run
leaves it out and the two cannot race over one seen set. `--only news` runs it alone.

## Structure

```
bale_crier/
  config.py      settings from the environment, CRIER_ prefix
  models.py      Bulletin, SendResult, RunReport, HistoryRecord, Package, CreditReport, Note, Story, Watch
  bale.py        the sender — the only place that talks to Bale
  history.py     append-only JSONL with a size cap
  memory.py      a watcher's own state, across runs
  credit.py      the AvalAI credit endpoint, parsed into numbers
  persian.py     numbers written with Persian digits, for the texts that count
  changedetection.py  the changedetection.io API: the watch list and one watch's diff
  llm.py         the AvalAI chat call, reduced to the text or a short error
  producers.py   the Producer protocol and the smoke producer
  run.py         one run: gather, send, record
  cli.py         the entry point
  watchers/      one module per watcher: avalai_credit.py, disk.py, changedetection.py
  notes/         the owner's lists: reading them, choosing a note, rewording it
  news/          the AI-news digest: the feed, the selection, the producer
deploy/user/     the systemd units
lists/           the owner's content (gitignored)
lists.example/   the list format, committed
data/            the history and the watcher memory (gitignored)
tests/           pytest
```

## Deploy

Five `Type=oneshot` user services, each with a timer of its own. Install them into the user manager:

```sh
cp deploy/user/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now bale-crier.timer bale-crier-credit.timer bale-crier-disk.timer bale-crier-changedetection.timer bale-crier-news.timer
```

There are five timers. `bale-crier.timer` runs the daily bulletins (everything but the credit
watcher, the disk watcher, the changedetection watcher and the news digest); `bale-crier-credit.timer`
runs the credit check hourly with `--only credit`, `bale-crier-disk.timer` runs the disk check hourly
with `--only disk`, `bale-crier-changedetection.timer` runs the changedetection check every three
hours with `--only changedetection`, and `bale-crier-news.timer` runs the digest daily with
`--only news`. Each owns a timer of its own so it cannot race over the daily run's latch, watermarks
or seen set. Enabling the credit watcher, the disk watcher, the changedetection watcher and the
digest is not optional — without their timers nothing ever checks the credit, the disk or
changedetection, and nothing sends the digest.

Enable the **timers**, not the services — each service is a oneshot with no `[Install]` section, so
enabling it alone does nothing. Run `sudo loginctl enable-linger $USER` once, or the user manager
(and the timers with it) is torn down when the last session ends.

The run reads `.env` from the unit's `WorkingDirectory`, so the token, the chat id and
`CRIER_AVALAI_API_KEY` live in `/home/mahdi/workspace/bale-crier/.env`. `CRIER_OPEN_AI_API_KEY` is
left empty there and inherits that same key, so the rewording works without a second copy of it.
`WorkingDirectory` also fixes where the relative `lists_dir`, `history_path` and
`watchers_state_path` point. The two units that call the model — `bale-crier.service` and
`bale-crier-news.service` — set `TimeoutStartSec=300`, above systemd's 90-second default, so a run
is not killed while it waits out a feed fetch, a model call and a send in turn. Keep it above
`CRIER_OPEN_AI_TIMEOUT` plus the `CRIER_HTTP_TIMEOUT` allowances if you raise them.

The times are literal `OnCalendar` lines in the unit files — 08:00, 14:00 and 20:00 with a ten-minute
randomized delay in `bale-crier.timer`; `hourly` with a two-minute spread in `bale-crier-credit.timer`
and in `bale-crier-disk.timer`; `*-*-* 00/3:30:00` with a two-minute spread in
`bale-crier-changedetection.timer`; and 09:00 with a ten-minute delay in `bale-crier-news.timer`.
systemd expands no environment variable in a unit file, so a schedule setting would silently never
fire. To change a time, edit the unit, copy it again and run `systemctl --user daemon-reload`.

Check them:

```sh
systemctl --user list-timers bale-crier.timer bale-crier-credit.timer bale-crier-disk.timer bale-crier-changedetection.timer bale-crier-news.timer
journalctl --user -u bale-crier.service
journalctl --user -u bale-crier-credit.service
journalctl --user -u bale-crier-disk.service
journalctl --user -u bale-crier-changedetection.service
journalctl --user -u bale-crier-news.service
```

Before the timer is enabled, prove the path by hand with one test bulletin:

```sh
CRIER_SMOKE=1 uv run python -m bale_crier
```

And prove the credit watcher by hand. With the balance above the threshold it sends nothing; to see
the latch work, raise `CRIER_CREDIT_THRESHOLD_IRT` above the current balance, run once and watch one
alert arrive, then run again and watch the latch hold.

```sh
uv run python -m bale_crier --only credit
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

