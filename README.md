# bale-crier

One server-side bot that pushes into a single Bale chat everything the owner needs told: hard
alerts about external state (AvalAI credit running out, and similar), and notes drawn from his own
lists, reworded and varied by an LLM a few times a day.

Bale is the only channel. The bot sends and never receives — no webhook, no long polling.

**Status:** milestones 1 (the path end to end) and 2 (the AvalAI credit watcher) are built and
tested. The owner's lists are milestone 3.

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
when nothing failed.

`CRIER_SMOKE=1` replaces the producers with the smoke producer, which sends one fixed test bulletin.
It is how the path is proved after a deploy, and it is never registered by default.

`--only NAME` narrows a run to one producer, and may be repeated. The credit watcher owns a timer of
its own, so the ordinary run leaves it out; the hourly timer runs it alone with `--only credit`. The
credit watcher is not registered at all unless `CRIER_AVALAI_API_KEY` is set — a run under
`--only credit` without it says so in Persian and sends nothing.

Tests:

```sh
uv run pytest
```

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

## Structure

```
bale_crier/
  config.py      settings from the environment, CRIER_ prefix
  models.py      Bulletin, SendResult, RunReport, HistoryRecord, Package, CreditReport
  bale.py        the sender — the only place that talks to Bale
  history.py     append-only JSONL with a size cap
  memory.py      a watcher's own state, across runs
  credit.py      the AvalAI credit endpoint, parsed into numbers
  producers.py   the Producer protocol and the smoke producer
  run.py         one run: gather, send, record
  cli.py         the entry point
  watchers/      one module per watcher; avalai_credit.py is the first
deploy/user/     the systemd units
lists/           the owner's content (gitignored)
lists.example/   the list format, committed
data/            the history and the watcher memory (gitignored)
tests/           pytest
```

`notes/` and `llm.py` arrive with milestone 3.

## Deploy

A `Type=oneshot` user service and a timer. Install them into the user manager:

```sh
cp deploy/user/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now bale-crier.timer bale-crier-credit.timer
```

There are two timers. `bale-crier.timer` runs the daily bulletins (everything but the credit
watcher); `bale-crier-credit.timer` runs the credit check hourly with `--only credit`, on a timer of
its own so the two cannot race over one latch. Enabling the credit watcher is not optional — without
its timer nothing ever checks the credit.

Enable the **timers**, not the services — each service is a oneshot with no `[Install]` section, so
enabling it alone does nothing. Run `sudo loginctl enable-linger $USER` once, or the user manager
(and the timers with it) is torn down when the last session ends.

The run reads `.env` from the unit's `WorkingDirectory`, so the token, the chat id and
`CRIER_AVALAI_API_KEY` live in `/home/mahdi/workspace/bale-crier/.env`. `WorkingDirectory` also fixes
where the relative `lists_dir`, `history_path` and `watchers_state_path` point.

The times are literal `OnCalendar` lines in the unit files — 08:00, 14:00 and 20:00 with a ten-minute
randomized delay in `bale-crier.timer`, and `hourly` with a two-minute spread in
`bale-crier-credit.timer`. systemd expands no environment variable in a unit file, so a schedule
setting would silently never fire. To change a time, edit the unit, copy it again and run
`systemctl --user daemon-reload`.

Check them:

```sh
systemctl --user list-timers bale-crier.timer bale-crier-credit.timer
journalctl --user -u bale-crier.service
journalctl --user -u bale-crier-credit.service
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

