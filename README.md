# bale-crier

One server-side bot that pushes into a single Bale chat everything the owner needs told: hard
alerts about external state (AvalAI credit running out, and similar), and notes drawn from his own
lists, reworded and varied by an LLM a few times a day.

Bale is the only channel. The bot sends and never receives — no webhook, no long polling.

**Status:** milestone 1, the path end to end — built, tested, and running on a timer. The AvalAI
credit watcher and the owner's lists are milestones 2 and 3.

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

Tests:

```sh
uv run pytest
```

## Structure

```
bale_crier/
  config.py      settings from the environment, CRIER_ prefix
  models.py      Bulletin, SendResult, RunReport, HistoryRecord
  bale.py        the sender — the only place that talks to Bale
  history.py     append-only JSONL with a size cap
  producers.py   the Producer protocol and the smoke producer
  run.py         one run: gather, send, record
  cli.py         the entry point
deploy/user/     the systemd units
lists/           the owner's content (gitignored)
lists.example/   the list format, committed
data/            the history (gitignored)
tests/           pytest
```

`watchers/`, `notes/` and `llm.py` arrive with milestones 2 and 3.

## Deploy

A `Type=oneshot` user service and a timer. Install them into the user manager:

```sh
cp deploy/user/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now bale-crier.timer
```

Enable the **timer**, not the service — the service is a oneshot with no `[Install]` section, so
enabling it alone does nothing. Run `sudo loginctl enable-linger $USER` once, or the user manager
(and the timer with it) is torn down when the last session ends.

The run reads `.env` from the unit's `WorkingDirectory`, so the token and the chat id live in
`/home/mahdi/workspace/bale-crier/.env`. `WorkingDirectory` also fixes where the relative
`lists_dir` and `history_path` point.

The times are literal `OnCalendar` lines in `deploy/user/bale-crier.timer` — 08:00, 14:00 and
20:00, each with a ten-minute randomized delay. systemd expands no environment variable in a unit
file, so a schedule setting would silently never fire. To change a time, edit the unit, copy it
again and run `systemctl --user daemon-reload`.

Check it:

```sh
systemctl --user list-timers bale-crier.timer
journalctl --user -u bale-crier.service
```

Before the timer is enabled, prove the path by hand with one test bulletin:

```sh
CRIER_SMOKE=1 uv run python -m bale_crier
```

