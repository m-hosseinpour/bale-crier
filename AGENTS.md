# bale-crier

One server-side bot that pushes into a single Bale chat everything the owner needs told: hard
alerts about external state (AvalAI credit exhausted, and similar), and notes drawn from his own
lists, reworded and varied by an LLM a few times a day. Lessons and news summaries come later.

Bale is the only channel, and the alerts are Bale messages too. Nothing here is channel-agnostic,
so no abstraction is owed to a channel that does not exist.

**Status:** milestones 1–3 are done — the path end to end, the AvalAI credit watcher, and the
owner's lists (reading them, choosing a note, rewording it). Both timers are enabled and running;
the daily one sends one note per run, so until the owner puts his own content in `lists/` it says
the directory is missing and sends none.

**Where the reasoning lives:** `docs/specs/2026-10-17-bale-crier-design.md` holds the design and why
it is that way; `docs/plans/` holds one plan per milestone. This file holds only what a session must
know before touching the code.

## The names

| where | value |
| --- | --- |
| repo and directory | `bale-crier` |
| Python package | `bale_crier` |
| env var prefix | `CRIER_` |
| systemd unit | `bale-crier.service` |
| bot username | `@bale_crier_bot` |

## Vocabulary

Five words, settled. Use them for modules, classes and settings; do not invent a sixth for the same
thing.

| word | what it is |
| --- | --- |
| `list` | one Markdown file of notes |
| `note` | one item in a list: a `## id` heading plus the body under it |
| `bulletin` | one message that actually goes to Bale, of any kind |
| `watcher` | something external under observation (AvalAI credit) |
| `schedule` | when a run happens |

`note` and `bulletin` are two layers, not two names for one thing: the LLM turns a note into a
bulletin's text, and the history records both facts separately.

## Commands

| what | how |
| --- | --- |
| install | `uv sync` |
| test | `uv run pytest` |
| one run | `uv run python -m bale_crier` |
| deploy | copy `deploy/user/*` to `~/.config/systemd/user/`, then `systemctl --user daemon-reload && systemctl --user enable --now bale-crier.timer bale-crier-credit.timer` |

Linger must be on — `sudo loginctl enable-linger $USER` — or the user timer is torn down with the
last session.

## Layout

```
bale_crier/     the package: config, models, the Bale sender, history, producers, the run loop
bale_crier/watchers/   one module per watcher (external state)
bale_crier/notes/      reading the lists, choosing a note, rewording it
deploy/user/    the systemd units
lists/          the owner's content (gitignored)
lists.example/  the list format, committed
data/           the history (gitignored)
tests/          pytest
```

## Conventions

- Code, comments and docs are English. Every string that reaches the owner is Persian.
- Persian half-spaces need a real U+200C. It goes in `می`/`نمی`, the plural `ها`, `تر`/`ترین` and
  the prefix `بی` (`بی‌پاسخ`) — but **not** in the prefix `نا`, which is written connected
  (`ناموفق`, `نامعتبر`, `نامناسب`). The generating model drops the character otherwise.
- Commits: OpenCode as author and committer, the owner as `Co-authored-by`.

## Rules a session must not break

- **The owner's content never enters git.** `lists/` is gitignored; only `lists.example/` is
  committed.
- **"I cannot tell" is never "it is gone".** A failed AvalAI credit read is a failure, not an empty
  account, and the bot must not add buying advice or a "nearly out" colour of its own.
- **Bale is reached from one module only** — `bale_crier/bale.py`. A second path to the API is a bug.
- **History is append-only.** No read-modify-write of the whole file, so a crash cannot lose what was
  already recorded.
- **The bot sends and never receives.** No webhook, no long polling.
- **Schedule times are literal in the timer unit.** systemd does not expand environment variables in
  a unit file, so a `CRIER_SCHEDULE_TIMES` would silently never fire.
