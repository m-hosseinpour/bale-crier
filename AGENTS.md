# bale-crier

One server-side bot that pushes into a single Bale chat everything the owner needs told: hard
alerts about external state (AvalAI credit exhausted, and similar), notes drawn from his own
lists, expanded by an LLM into a couple of Persian sentences (not one) and varied twice a day, and a
daily digest of AI news, picked and written in Persian. Lessons come later.

Bale is the only channel, and the alerts are Bale messages too. Nothing here is channel-agnostic,
so no abstraction is owed to a channel that does not exist.

**Status:** milestones 1–6 are built — the path end to end, the AvalAI credit watcher, the owner's
lists (reading them, choosing a note, rewording it), the news digest (the Google News feed, the hard
filter and the seen set, the model's selection), the disk watcher (free space below a threshold,
hourly, with a latch and a daily reminder), and the changedetection watcher (the pages
changedetection.io watches, every three hours, one message naming what changed). All five timers are
enabled and scheduled. The daily one sends one note per run from `lists/`.

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

Seven words, settled. Use them for modules, classes and settings; do not invent an eighth for the
same thing.

| word | what it is |
| --- | --- |
| `list` | one Markdown file of notes |
| `note` | one item in a list: a `## id` heading plus the body under it |
| `bulletin` | one message that actually goes to Bale, of any kind |
| `watcher` | something external under observation (AvalAI credit, free disk space, the pages changedetection.io watches) |
| `watch` | one page under observation in changedetection.io, with its own `last_changed` |
| `story` | one entry in the news feed: a headline, its source and its link (not a `note`) |
| `schedule` | when a run happens |

`note` and `bulletin` are two layers, not two names for one thing: the LLM turns a note into a
bulletin's text, and the history records both facts separately.

## Commands

| what | how |
| --- | --- |
| install | `uv sync` |
| test | `uv run pytest` |
| one run | `uv run python -m bale_crier` |
| deploy | copy `deploy/user/*` to `~/.config/systemd/user/`, then `systemctl --user daemon-reload && systemctl --user enable --now bale-crier.timer bale-crier-credit.timer bale-crier-disk.timer bale-crier-changedetection.timer bale-crier-news.timer` |

Linger must be on — `sudo loginctl enable-linger $USER` — or the user timer is torn down with the
last session.

## Layout

```
bale_crier/     the package: config, models, the Bale sender, history, producers, the run loop
bale_crier/watchers/   one module per watcher (external state)
bale_crier/notes/      reading the lists, choosing a note, rewording it
bale_crier/news/       the AI-news digest: the feed, the selection, the producer
bale_crier/changedetection.py  the changedetection.io API: the watch list and one watch's diff
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
- **Every commit is pushed as soon as it is made** — `git push origin main`. One command covers both
  remotes (forgejo and GitHub), and a commit that only exists locally is not delivered work.

## Rules a session must not break

- **The owner's content never enters git.** `lists/` is gitignored; only `lists.example/` is
  committed.
- **"I cannot tell" is never "it is gone".** A failed AvalAI credit read is a failure, not an empty
  account, and the bot must not add buying advice or a "nearly out" colour of its own.
- **Bale is reached from one module only** — `bale_crier/bale.py`. A second path to the API is a bug.
- **History is append-only.** No read-modify-write of the whole file, so a crash cannot lose what was
  already recorded.
- **The bot sends and never receives.** No webhook, no long polling.
- **One watcher writes back, and only after a landing send.** The changedetection watcher marks
  the pages its message carried as viewed; the mark goes only for those pages, only when the
  bulletin landed, and a failed mark is left alone.
- **Schedule times are literal in the timer unit.** systemd does not expand environment variables in
  a unit file, so a `CRIER_SCHEDULE_TIMES` would silently never fire.
