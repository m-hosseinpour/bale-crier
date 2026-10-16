# bale-crier

One server-side bot that pushes into a single Bale chat everything the owner needs told: hard
alerts about external state (AvalAI credit exhausted, and similar), and the reading he wants daily —
items drawn from his own lists of notes and reviews, reworded and varied by an LLM a few times a
day — with lessons and news summaries to be added later.

**Bale is the only channel, and the alerts are Bale messages too** (owner's correction, 2026-10-17):
by "notification" he never meant a second surface. Nothing here is channel-agnostic, so no
abstraction is owed to a channel that does not exist.

Status: the design is settled and written down in `docs/specs/2026-10-17-bale-crier-design.md`;
milestone 1 (the path end to end) is the next thing to build. This file keeps the summary — the
requirements, the names, and the shapes already verified elsewhere — and the spec holds the design
itself.

## The name (settled 2026-10-17)

The town crier: stands up on schedule and announces whatever the town needs to hear. It does not
care whether the news is bad (credit is gone) or educational (today's note), which is why the name
survives the app growing new message types.

| where | value |
| --- | --- |
| repo and directory | `bale-crier` |
| Python package | `bale_crier` |
| env var prefix | `CRIER_` |
| systemd unit | `bale-crier.service` |
| bot username | `@bale_crier_bot` |

Alternatives weighed and dropped: `bale-bulletin` (neutral but bland), `bale-owl` (warm, says
nothing about the app), `bale-steward` (weight on managing, while the app mostly sends),
`bale-pigeon` (carries an air of unreliability). Rejected outright: any name carrying `digest`,
`news` or `alert` — `bale-news-digest` already exists and this app will send news summaries too,
and two near-identical names make it impossible to remember later which repo did what — and
`bale-notifier` / `bale-alerts`, which drop half the app (the alert half only).

**Vocabulary — settled 2026-10-17.** Five words in three layers, adopted after the sources were
pinned down: `list` (one Markdown file of notes), `note` (one item inside a list), `bulletin` (any
single message sent: alert, note, lesson, news), `watcher` (something under observation, e.g.
AvalAI credit) and `schedule` (when it goes out). `note` and `bulletin` are two layers, not two
names for one thing — the LLM turns a note into a bulletin's text.

## Requirements, as the owner described them (2026-10-17)

- Runs on a server, unattended.
- Alerts on external state: AvalAI credit running out, "and other things".
- Later: lessons and news summaries, also into Bale.
- His own lists of notes and review items, sent daily, **several per day**, reworded and varied by
  an LLM so the same item does not arrive in the same words twice. "Varied" covers the *item* too,
  not only the wording: the same note must not come back too soon. The LLM may also add a short
  motivational touch, so the message lands better than a bare repetition of the note
  (owner's clarification, 2026-10-17).

## Already known, verified elsewhere — do not re-derive

These are measured shapes from adjacent work, not guesses. They are the reason the first milestone
is small.

**Sending to Bale.** `bale-news-digest` has a working sender
(`~/workspace/bale-news-digest/bale_bot_message_sender.py`): a `POST` to
`https://tapi.bale.ai/bot<TOKEN>/sendMessage` with `{"chat_id": ..., "text": ...}`, whose response
carries `ok`; media goes through `sendPhoto`/`sendVideo`/`sendAudio`/`sendDocument`, and Bale
downloads from a URL itself, so nothing is uploaded by us. `sendMediaGroup` takes at most 10 items
and rejects a single-item group. Reuse this rather than re-probing the API.

**AvalAI credit.** `GET https://api.avalai.ir/user/v1/credit` with `Authorization: Bearer <key>`
returns `remaining_irt` (main balance) plus `credit_sources.packages[]`, where `name`,
`template_id` (`d-…` daily, `w-…` weekly), `remaining_irt` and `amount_irt` arrive **as strings**.
`~/.config/opencode/scripts/avalai-credit.py --json` already parses this and is the cheaper
integration: it exits `0` when something is left, `2` when nothing is, `3` when it could not read
the answer. **`3` must never be announced as `2`** — "I cannot tell" is not "the credit is gone",
and the watcher inherits that rule. That script also reports and does not advise (owner's ruling of
2026-10-15); the bot must not reintroduce buying advice or a "nearly out" colour of its own.

**The LLM.** AvalAI is OpenAI-compatible at `https://api.avalai.ir/v1`; `bale-news-digest` reaches
it with `OPEN_AI_MODEL_NAME` / `OPEN_AI_BASE_URL` / `OPEN_AI_API_KEY` through
`open_ai_client_provider.py`. The key for a server comes from the environment — `avalai_key.py`'s
desktop-app lookup is a laptop concern and does not apply to a daemon.

**Deployment path exists.** `bale-news-digest` runs on **systemd user units** — a `.service` plus a
`.timer` for the scheduled run, and a separate webhook service — under
`~/workspace/bale-news-digest/deploy/user/`, with the webhook public on `bot.m-hosseinpour.ir`. So
both "run on a clock" and "let Bale reach the server" are solved territory; copy the shape rather
than inventing one.

## Decided (2026-10-17) — see the spec for the reasoning

| question | decision |
| --- | --- |
| Scheduling | systemd **user timer**, 2–3 fixed times a day, `RandomizedDelaySec`; no resident process |
| How the lists are stored | Markdown files, one per list, in a gitignored directory; a note is a heading id plus body |
| How "sent" is known | a separate append-only JSONL history with a size cap — never a flag in the content |
| What "varied" means | cycle (oldest-sent first) plus a day-count floor; the LLM rewords each note and may add a motivational line |
| Which LLM, how many calls | AvalAI's OpenAI-compatible endpoint, one call per bulletin, cheap model, configurable |
| Delivery path | neither polling nor webhook — the bot only sends |
| Stack | `uv`, pydantic v2 (with `pydantic-settings` for config), pytest, type hints |

## Still open

- Which "other things" the watchers cover. AvalAI credit is the only one named so far.
- Whether a note's motivational addition should be bounded, and how.
- The exact fixed times, and how many runs a day.

## One decision the naming exposed, to make when news work starts

`bale-news-digest` already sends news summaries to Bale, and `bale-crier` is meant to as well.
Exactly one of these must win when that work begins: the news summary moves into `bale-crier` and
the old repo is retired, or `bale-news-digest` stays and `bale-crier` consumes its output. A
half-decision leaves two things that can both post news, and no way to tell which one did.

## First milestone

The smallest thing that proves the whole path end to end: a scheduler plus one hard-coded bulletin
that actually lands in Bale. Then the AvalAI credit watcher as the first real bulletin, because its
external shape is already verified above. The note lists come after that, since they are the part
with the most undecided design. Milestone 1 is not "done" until a real message arrives in Bale.

## Conventions

- Code, comments and this file are English; every string that reaches the owner is Persian, and
  Persian half-spaces need a real U+200C — the generating model drops it otherwise.
- Commits: OpenCode as author and committer, the owner as `Co-authored-by`.
