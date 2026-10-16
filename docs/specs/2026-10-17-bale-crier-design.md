# bale-crier — design

Settled with the owner on 2026-10-17. This document records the design and the
reasons behind it; `AGENTS.md` keeps the summary and points here.

## What it is

One server-side bot that pushes into a single Bale chat everything the owner
needs told. Two families of message, one channel:

- **alerts** about external state — the first one is AvalAI credit running out;
- **notes** drawn from the owner's own lists, reworded by an LLM so the same
  item does not arrive in the same words twice, and sometimes with a short
  motivational addition.

Lessons and news summaries come later. Nothing here is channel-agnostic: Bale is
the only channel, and alerts are Bale messages too.

## Vocabulary (settled 2026-10-17)

Five words, three layers. The names came out of what the sources actually hold,
not the other way round.

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
  models.py      Note, Bulletin, SendResult
  producers.py   the Producer protocol; a registry joins when a second producer does
  bale.py        the sender (sendMessage today; media later)
  history.py     append-only JSONL with a size cap
  llm.py         the AvalAI client (needed once notes land)
  run.py         one run: gather, send, record
  cli.py         the entry point
  watchers/      one module per watcher; avalai_credit.py is the first
  notes/         reading the lists, choosing a note, rewording it
deploy/user/bale-crier.service + .timer
lists/           the owner's content (gitignored)
data/history.jsonl
tests/
```

## Data model

- `Note` — `list_name`, `id`, `text`.
- `Bulletin` — `kind` (`alert` | `note`, more later), `text`, `note_id` optional.
- history line — `{ts, kind, list_name, note_id, text, ok}`.

## Choosing a note

Cycle plus a floor, both read from the history:

- **cycle** — the note whose last send is oldest goes first, so every note is
  reached before any repeats;
- **floor** — while any fresh note remains, a note sent within the last
  `CRIER_NOTE_FLOOR_DAYS` days does not go again. If every note is inside the
  floor, the oldest one goes anyway, so a small list cannot starve.

This scales itself: the rule needs no count of notes and no per-list tuning.

## Rewording (the LLM)

One call per bulletin — a failure costs one bulletin, and retrying it costs one
call. The model is configurable (`CRIER_OPEN_AI_MODEL`); the default is a cheap
one, reached through AvalAI's OpenAI-compatible endpoint at
`https://api.avalai.ir/v1`.

The prompt asks for: the note's meaning kept; a fresh Persian wording each time,
with the previous wordings of the same note supplied so the model can avoid
them; correct U+200C in every half-space word; and optionally one short
motivational sentence when it fits. Output is the message text alone — no
preamble, no quotes, no markdown scaffolding.

The reworded text, not the note's own text, is what the history stores: that is
the record of what the owner actually read.

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

Each run sends every alert that is due plus **one** note bulletin — with two or
three runs a day that is the owner's "several per day".

## Configuration

| variable | meaning |
| --- | --- |
| `CRIER_BALE_BOT_TOKEN` | the bot's token |
| `CRIER_BALE_CHAT_ID` | the destination chat |
| `CRIER_LISTS_DIR` | the content directory (default `lists`) |
| `CRIER_HISTORY_PATH` | the history file (default `data/history.jsonl`) |
| `CRIER_HISTORY_MAX_LINES` | the history cap |
| `CRIER_NOTE_FLOOR_DAYS` | the no-repeat floor |
| `CRIER_OPEN_AI_BASE_URL`, `CRIER_OPEN_AI_MODEL`, `CRIER_OPEN_AI_API_KEY` | the LLM |
| `CRIER_AVALAI_API_KEY` | what the credit watcher reads |

Settings go through `pydantic-settings`, which gives validation and the
`CRIER_` prefix in one place.

## The credit watcher

`GET https://api.avalai.ir/user/v1/credit` with `Authorization: Bearer <key>`
returns `remaining_irt` plus `credit_sources.packages[]`, with the numbers
arriving as strings.

The watcher inherits a rule the owner already set: **"I cannot tell" is never
announced as "the credit is gone"**. A failed read is a failure, not an empty
account. It reports the numbers and gives no buying advice and no "nearly out"
colour of its own.

## Milestones

1. **The path end to end.** Skeleton, config, the Bale sender, the history, one
   hardcoded bulletin, and the timer — a message that really lands in Bale.
2. **The first real bulletin.** The AvalAI credit watcher.
3. **The owner's lists.** Reading the lists, choosing a note, rewording it.

Each milestone carries its own pytest tests. Milestone 1 is not "done" until a
real message arrives in Bale.

## Testing

pytest, type hints throughout, `uv` for the environment — the stack
`bale-news-digest` runs.

Testable without the network: parsing a list into notes, the cycle-and-floor
choice given a synthetic history, the history cap, bulletin rendering, and the
sender's payload shape against a stub. The live Bale send is verified by hand,
once per milestone.

## Still open

- Which other watchers the owner wants, beyond AvalAI credit. Only that one is
  named so far.
- Whether a note's motivational addition should be bounded, and how.
- The exact fixed times and how many runs a day.
- Whether news summaries move here from `bale-news-digest`, or stay there and
  are consumed. Exactly one must win when that work starts.
