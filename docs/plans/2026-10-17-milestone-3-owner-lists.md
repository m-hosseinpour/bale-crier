# Milestone 3 — the owner's lists

**Goal:** the daily run reads the owner's own Markdown lists, picks the note that is
due by the cycle, rewrites it in fresh Persian through the LLM, and
sends that as the bulletin — so the same item never arrives in the same words twice.

**Architecture:** the notes package is four small modules behind one producer. One
reads the list directory into `Note` objects, one chooses a note from the history's
last-send times, one builds the prompt and the fallback text, and one is the
`NoteProducer` the run loop already knows how to ask. The LLM itself is a transport
module of its own (`llm.py`), so the prompt lives with the notes and the HTTP lives
apart from it.

**Tech Stack:** unchanged — Python ≥ 3.11 (the venv is a uv-managed 3.14.7), `uv`,
pydantic v2 + `pydantic-settings`, `requests`, pytest, type hints. No new dependency:
the LLM call is one `requests.post`, exactly like the Bale sender and the credit read.

**Spec:** `docs/specs/2026-10-17-bale-crier-design.md`, sections "Sources and storage",
"Choosing a note", "Rewording (the LLM)" and "Configuration".

**Status:** complete, 2026-10-17 — the amendments at the end of this plan record what
implementation changed.

## Global Constraints

- Every setting comes from the environment with the `CRIER_` prefix.
- Code, comments and docs are English; every string that reaches the owner is Persian,
  with a real U+200C in every half-space word. **The prefix `نا` is written connected**
  (`ناموفق`, `نامعتبر`); `می`, `ها`, `تر`/`ترین` and `بی` take the half-space.
- **A note's identity is `(list name, heading id)`** — the heading is what survives an
  edit to the text, so fixing a typo must not re-send the note.
- **The history stores the reworded text, not the note's own text** — it is the record
  of what the owner actually read.
- **A failed reword still sends a bulletin** (owner's ruling, 2026-10-17): the note's
  own text, followed by one short Persian line saying the rewording did not happen this
  time. That bulletin is a real send: it is recorded in the history and it moves the
  note through the cycle.
- **No separate motivational sentence** (owner's ruling, 2026-10-17). The tone of the
  rewording itself may be warm and motivational; there is no appended extra sentence and
  therefore no bound to place on one. The spec's open question closes here.
- **`CRIER_OPEN_AI_API_KEY` inherits `CRIER_AVALAI_API_KEY`** when it is unset or empty
  (owner's ruling, 2026-10-17): both are the same provider, and a second copy of one key
  is friction with no gain. An explicit `CRIER_OPEN_AI_API_KEY` always wins.
- The bot reports and does not advise: no buying suggestion, no "nearly out" wording, in
  any bulletin including a reworded note.
- The history stays "what the owner read". Nothing in this milestone writes a history
  line for a bulletin that was not sent.
- `bale_crier/bale.py` stays the only module that talks to Bale.
- The notes are the owner's: `lists/` is gitignored, and no test and no run writes into it.
- Defaults unchanged: `lists` dir, LLM base `https://api.avalai.ir/v1`, model
  `deepseek-v4-flash`, HTTP timeout 30s.
- **The repeat floor is dropped** (owner's ruling, 2026-10-17, after the finding below).
  `CRIER_NOTE_FLOOR_DAYS` and `Settings.note_floor_days` are removed, and the choice is the
  cycle alone. See the amendment at the end of this plan for why the floor could not do
  anything.

### Verified external facts (probed live, 2026-10-17)

- `POST https://api.avalai.ir/v1/chat/completions` with
  `Authorization: Bearer <key>` and an OpenAI-shaped JSON body of `model` plus
  `messages` (each `{"role": ..., "content": ...}`) answers `200`.
- The message text is at **`choices[0].message.content`**, a plain string. The same
  object also carries `reasoning_content`, which is not the message and must not be sent
  to the owner.
- An error answers with an HTTP status and a body of
  `{"error": {"message": ..., "type": ..., "code": ...}}`.
- `deepseek-v4-flash` is served by this account (checked against the 368-entry model
  list) and answers correctly, with correct U+200C in its Persian output.
- `temperature` is accepted (tried at `0.0` and `1.2`, both `200`). The client does not
  send it: the model varies its wording across calls without it, and a field nothing
  needs is a field that can break.

## Acceptance Criteria

The milestone is done when all of these hold:

1. `uv run pytest` is green.
2. `CRIER_LISTS_DIR=lists.example uv run python -m bale_crier --only note` puts a real
   reworded Persian note in the owner's Bale chat, and `data/history.jsonl` gains a line
   with `kind:"note"`, `ok:true`, the chosen `list_name` and `note_id`, and a `text`
   equal to what was actually sent.
3. The **next** run sends a *different* note from the same directory — the cycle, read
   straight off the history's `note_id` sequence.
4. With the LLM key deliberately wrong, one run sends the note's own text followed by the
   failure line, and that text — not a reworded one — is what the history records.
5. The plain daily run (`uv run python -m bale_crier`, no `--only`) sends exactly one note
   bulletin and no credit alert.
6. With `lists/` absent, a run sends nothing and prints the Persian line naming the
   missing directory; with no LLM key, it prints the Persian line naming the key. Neither
   is a traceback and neither is silence.

Criterion 3 is the one that matters by hand: it is the only check that the cycle reads
the history the previous run wrote.

## Prerequisite the owner must supply

His own content in `lists/` — one or more Markdown files in the settled format. Nothing
else is new: the LLM key is inherited from `CRIER_AVALAI_API_KEY`, which is already set.
The live checks may point `CRIER_LISTS_DIR` at the committed `lists.example/` instead, so
that the path is proved without his content leaving the machine.

## Files

| file | responsibility |
| --- | --- |
| `bale_crier/llm.py` | the AvalAI chat call, reduced to text or a short error code |
| `bale_crier/notes/__init__.py` | package marker |
| `bale_crier/notes/lists.py` | a list file, parsed into notes |
| `bale_crier/notes/choose.py` | the cycle, given last-send times |
| `bale_crier/notes/reword.py` | the prompt, and the text when the reword fails |
| `bale_crier/notes/producer.py` | `NoteProducer`: read, choose, reword, one bulletin |
| `bale_crier/models.py` | add `Note`; add `list_name` to `Bulletin` |
| `bale_crier/history.py` | `last_sent_map`, `previous_texts`; `_as_utc` becomes public |
| `bale_crier/config.py` | the LLM key inherits the AvalAI key; `note_floor_days` is removed |
| `bale_crier/run.py` | register the note producer; carry `list_name` into the history |
| `bale_crier/cli.py` | `--only note`, and the two Persian lines for a gap that would otherwise be silent |
| `lists.example/habits.md` | a second example list, so the cycle is visible in the examples |
| `.env.example`, `README.md` | the inherited key, the notes section, the structure |
| `AGENTS.md`, `docs/specs/2026-10-17-bale-crier-design.md`, `docs/plans/2026-10-17-milestone-1-path-end-to-end.md` | the claims this milestone makes stale |
| `tests/test_llm.py`, `tests/test_notes_lists.py`, `tests/test_notes_choose.py`, `tests/test_notes_reword.py`, `tests/test_notes_producer.py`, and additions to `test_history.py`, `test_config.py`, `test_run.py` | the tests |

## Tasks

### Task 1: The LLM call

**Files:**
- Create: `bale_crier/llm.py`, `tests/test_llm.py`

**Interfaces:**
- `LlmRead` — `typing.NamedTuple`: `text: str | None`, `error: str`. `text` is `None`
  exactly when the call failed, and `error` is then a short code-like string, never
  empty: `"HTTP 401"`, `"transport error"`, `"unparsable response"`,
  `"empty completion"`. On success `error` is `""`.
- `complete(messages: list[dict[str, str]], *, key: str, model: str, base_url: str = "https://api.avalai.ir/v1", timeout: int = 30) -> LlmRead`
- `CHAT_PATH = "/chat/completions"` — the one place the path is written.
- `Llm` — `Callable[..., LlmRead]`, the alias a caller stubs in tests.

**Behavior to verify:**
- The request is a `POST` to `https://api.avalai.ir/v1/chat/completions` carrying
  `Authorization: Bearer <key>` and a body with the model and the messages as given,
  passed as JSON through `requests`' own `json=` argument (which is what sets the
  content type), and the configured timeout (assert against a stubbed `requests.post`).
- A body of `{"choices": [{"message": {"content": "سلام"}}]}` gives `text == "سلام"` and
  an empty error.
- Content padded with whitespace comes back stripped.
- A `choices[0].message` whose `content` is empty or whitespace-only gives `text is None`
  and an error — never an empty bulletin.
- A non-200 with an error body gives `text is None` and an error carrying the status.
- A non-200 with a body that is not JSON gives `text is None` and an error carrying the
  status, and raises nothing.
- A transport exception gives `text is None` and a non-empty error, and raises nothing.
- A 200 whose body is not JSON, is not an object, has no `choices`, or has an empty
  `choices` list, each gives `text is None` and a non-empty error.
- `content` that is not a string (a list, a number) gives `text is None` and an error.
- Every failure path above returns rather than raises: the caller is a run that must
  still record what happened.

**Notes:**
- `reasoning_content` is present on this provider and is **not** the message. Reading the
  wrong field would put the model's private reasoning into the owner's chat, so the
  field is read by name and a test pins that `reasoning_content` alone yields the
  empty-completion error.
- The error is a short code, not the provider's English prose: it is embedded in a
  Persian bulletin (Task 4), and a paragraph of English support text does not belong
  there.
- The client never reads the settings itself; the caller passes key, model and base URL,
  so the module can be tested without an environment.

### Task 2: Reading the lists

**Files:**
- Create: `bale_crier/notes/__init__.py`, `bale_crier/notes/lists.py`,
  `tests/test_notes_lists.py`
- Modify: `bale_crier/models.py` (add `Note`)

**Interfaces:**
- `Note` — pydantic model: `list_name: str`, `id: str`, `text: str`.
- `read_notes(directory: Path) -> list[Note]`

**Behavior to verify:**
- One file with two notes gives two notes, in file order, with the right ids and bodies
  and `list_name` equal to the file's stem.
- A body spanning several lines and blank lines keeps its text, with only the leading and
  trailing whitespace removed.
- A line that is a heading of another level (`#`, `###`) stays inside the body and does
  not start a note; a `#` title before the first note is ignored.
- A note whose body is empty is skipped — there is nothing to reword.
- A duplicate id inside one file keeps the first and drops the later ones, so the
  `(list, id)` identity stays one note.
- Two files give both lists, ordered by file name, and the same id in two files is two
  distinct notes.
- A file that is not `.md` is ignored.
- A missing directory, or a path that is not a directory, gives `[]` and raises nothing.
- A file that cannot be decoded as UTF-8 is skipped, and the other files still give their
  notes.

**Notes:**
- The heading rule is deliberately loose: any line beginning with exactly `##` and a
  space starts a note, and the id is the rest of the line. A stricter rule that rejected a
  two-word id would silently fold that note's text into the previous one — losing the
  owner's note without a word, which is the failure this format exists to avoid.
- Only the first token matters for the heading level, so `###` and `#` are body text.
- The parse is pure: it reads and returns, and writes nothing.

### Task 3: Choosing the note

**Files:**
- Create: `bale_crier/notes/choose.py`, `tests/test_notes_choose.py`
- Modify: `bale_crier/history.py` (`last_sent_map`, `previous_texts`; `_as_utc` → `as_utc`)

**Interfaces:**
- `last_sent_map(*, path: Path) -> dict[tuple[str, str], datetime]` — newest successful
  `note` timestamp per `(list_name, note_id)`. A missing file gives `{}`. **Replaces
  `last_sent_at`**, which asked the same question one note at a time and would re-read the
  whole history once per note.
- `previous_texts(*, path: Path, note_id: str, list_name: str, limit: int) -> list[str]`
  — the newest `limit` texts of the successful `note` records for that note, oldest
  first, so the prompt can say "do not repeat these". A missing file gives `[]`.
- `as_utc(ts: datetime) -> datetime` — the existing naive-means-UTC rule, now public,
  because the chooser applies the same rule to `now` as the history applies to a record.
- `choose_note(notes: Sequence[Note], *, last_sent: Mapping[tuple[str, str], datetime]) -> Note | None`

**Behavior to verify:**
- A note that has never been sent is chosen over one that has.
- Among sent notes, the one whose last send is oldest is chosen.
- Two notes that have never been sent give the first in input order, so a repeated run on
  unchanged input is not flaky.
- An empty `notes` gives `None`.
- A note that appears in `last_sent` under a different list is not treated as sent.
- `last_sent_map` ignores records that failed, records of another kind, and records of
  another note; it gives the newest timestamp when a note went twice.
- `previous_texts` returns the newest `limit` texts, oldest first, ignoring failures and
  other notes, and gives `[]` for a note that never went.

**Notes:**
- **There is no floor.** The plan first carried the spec's cycle-plus-floor, and the
  implementation showed the floor could not change the answer: with the cycle ordering
  notes by last send, the notes outside the floor are always a prefix of that ordering, so
  the oldest note is outside the floor exactly when any note is, and the "every note is
  inside the floor" fallback then picks that same oldest note. A test cannot see it either —
  a version with the filter deleted passes the same cases. The owner's ruling is to drop it
  rather than keep a setting and a filter that do nothing; the dated amendment at the end of
  this plan records the finding, and Task 6 sweeps `CRIER_NOTE_FLOOR_DAYS` out of the spec,
  the milestone-1 plan, `.env.example` and the README.
- The map replaces the per-note lookup because the chooser asks about every note at once;
  the history file is read once per question, not once per note. Milestone 1's plan named
  `last_sent_at` as the interface milestone 3 would consume — the dated amendment at the
  end of that plan records the change.
- Both helpers read the history and write nothing.

### Task 4: Rewording, and what goes out when it fails

**Files:**
- Create: `bale_crier/notes/reword.py`, `tests/test_notes_reword.py`

**Interfaces:**
- `build_messages(note: Note, previous: Sequence[str]) -> list[dict[str, str]]` — the
  system instruction plus the user turn, ready for `complete`.
- `fallback_text(note: Note, error: str) -> str` — the note's own text, then one short
  Persian line saying the rewording did not happen this time, carrying the error code in
  parentheses when there is one.
- `reword(note: Note, previous: Sequence[str], *, settings: Settings, complete: Llm = llm.complete) -> str`
  — always returns text: the model's rewording, or `fallback_text` when the call failed.
- `PREVIOUS_LIMIT = 3` — how many earlier wordings the prompt is given.

**Behavior to verify:**
- The prompt carries the note's own text.
- Each supplied previous wording appears in the prompt, so the model can avoid it; with
  none supplied the messages are still built and sent.
- `reword` with a stub that returns text gives exactly that text.
- `reword` with a stub that returns a failure gives the note's own text, verbatim, as the
  first thing in the returned string.
- The fallback text names the failure and carries the error code when one is given.
- The fallback text contains at least one Persian character and at least one U+200C.
- Neither the fallback text nor the prompt's instruction contains buying advice — assert
  on a small list of forbidden Persian words (`بخر`, `خرید`, `توصیه`) rather than
  trusting the eye.

**Notes:**
- The prompt's requirements, which the implementer writes out in Persian: keep the note's
  meaning and add no claim of its own; write fresh wording and avoid the supplied earlier
  wordings; a warm, motivational tone is welcome **inside** the rewording, and nothing is
  appended to it; correct U+200C in every half-space word, with `نا` written connected;
  answer with the message text alone — no preamble, no quotes, no markdown, no heading;
  keep it short.
- The fallback is the owner's ruling: a missing reword must not cost him the note. It also
  keeps the cycle honest, because the bulletin that goes out is the one the history
  records.
- The instruction tells the model nothing about the credit watcher, the threshold or the
  app: the notes are the owner's content and the bot adds no advice of its own.

### Task 5: The producer, and the wiring

**Files:**
- Create: `bale_crier/notes/producer.py`, `tests/test_notes_producer.py`
- Modify: `bale_crier/models.py` (`Bulletin.list_name`), `bale_crier/config.py`,
  `bale_crier/run.py`, `bale_crier/cli.py`, `lists.example/habits.md`,
  `tests/test_config.py`, `tests/test_run.py`

**Interfaces:**
- `Bulletin` gains `list_name: str | None = None`; the credit watcher and the smoke
  producer leave it `None`.
- `NoteProducer(settings: Settings, *, complete: Llm = llm.complete)` — `name = "note"`,
  `own_timer = False`, `produce(now: datetime) -> list[Bulletin]` returning zero or one
  bulletin, `kind="note"`, with `note_id` and `list_name` set from the chosen note.
- `Settings.note_floor_days` is removed, along with `CRIER_NOTE_FLOOR_DAYS` in
  `.env.example`, the spec's configuration table and the README. `Settings.open_ai_api_key` is filled from `avalai_api_key` when unset or empty; an
  explicit value is never overwritten. A `model_validator` does it once, so every caller
  reads one field.
- `build_producers` registers the note producer when `settings.open_ai_api_key` is set.
  It is not gated on the list directory existing: the directory is the producer's business
  at produce time, and the CLI reports a missing one.
- `build_producers` with `smoke` true and no `--only` returns the smoke producer alone —
  the deploy check stays one fixed message, as the README has claimed since milestone 1.
- `run_once` carries `bulletin.list_name` into the history record.
- `KNOWN_PRODUCERS` gains `"note"`, so `--only note` is accepted.
- `cli.main` prints a Persian line to stderr when the note producer cannot work: no LLM
  key, and a `lists_dir` that is not a directory. Each line is printed when the run would
  have asked the note producer — so not under `--only credit`.

**Behavior to verify:**
- With no lists directory, `produce` returns `[]` and raises nothing.
- With one note and a stub LLM returning text, `produce` gives exactly one bulletin with
  `kind == "note"`, the note's `id` and `list_name`, and the stub's text.
- The stub LLM is handed the note's own text, and the earlier wordings the history holds
  for that note — at most `PREVIOUS_LIMIT` of them, which the producer passes as the
  history lookup's `limit`.
- With a failing stub LLM, the bulletin carries the note's own text plus the failure line,
  and is still a bulletin — the run must not fall silent.
- After a successful send is recorded in the history, the next `produce` chooses the other
  note.
- `name == "note"` and `own_timer is False`.
- Without `--only`, the produced set contains `"note"` and not `"credit"`; `--only note`
  selects it alone; `--only nope` still raises `ValueError`.
- With `CRIER_SMOKE=1` and no `--only`, the produced set is `["smoke"]` alone.
- A note run writes a history line carrying `list_name` and `note_id` and the text that
  was sent.
- `Settings(avalai_api_key="k")` leaves `open_ai_api_key == "k"`; with both set the
  explicit one wins; with neither it is `None`.
- `main` with no LLM key prints a Persian stderr line naming `CRIER_OPEN_AI_API_KEY` and
  exits without a traceback; with no `lists` directory it prints the Persian line naming
  the directory.

**Notes:**
- `own_timer` stays false: the notes are the daily run's own work, and the spec's
  scheduling section has `bale-crier.timer` sending one note per run.
- The two stderr lines exist because a missing key or a missing directory would otherwise
  be a silent gap — the same reasoning milestone 2 applied to the credit watcher's key.
  A single list file that cannot be decoded is skipped without a bulletin: the file is on
  the owner's own disk where he can see it, unlike the remote credit the watcher reports.
- `lists.example/habits.md` carries two short notes, so the example directory has enough
  notes for the cycle to be visible in a live check.

### Task 6: The documents, and the live check

**Files:**
- Modify: `README.md`, `.env.example`, `AGENTS.md`,
  `docs/specs/2026-10-17-bale-crier-design.md`,
  `docs/plans/2026-10-17-milestone-1-path-end-to-end.md`

**Behavior to verify:**
- `README.md` documents the list format, the cycle, the inherited LLM key,
  the failure line, `--only note`, and that `lists/` is the owner's to create; its Status
  line no longer says milestone 3 is next; its structure block no longer says `notes/` and
  `llm.py` "arrive with milestone 3".
- `.env.example` says `CRIER_OPEN_AI_API_KEY` is inherited from `CRIER_AVALAI_API_KEY`
  when left empty.
- `AGENTS.md`'s status line no longer calls milestone 3 "next".
- The spec's "Still open" no longer lists the motivational addition as open, and the
  "Rewording (the LLM)" section records the two rulings of 2026-10-17 — the tone lives in
  the rewording, and a failed reword sends the note's own text with one line.
- The spec's "Choosing a note" section describes the cycle alone, with a dated line saying
  the floor was dropped and why; its configuration table and the README no longer list
  `CRIER_NOTE_FLOOR_DAYS`, and `.env.example` no longer carries it.
- Milestone 1's plan carries a dated amendment saying `last_sent_at` became
  `last_sent_map` in milestone 3, so its "Milestone 3 consumes this" claim is not read as
  the current interface.
- No file still describes the note producer as unbuilt.

**Notes:**
- This is the sweep the project's rules require: a document describing the state before a
  change is worse than none, because the next session reads it first and acts on it.
- The live checks are the Acceptance Criteria, run by hand: a real note in Bale, then a
  second run showing the cycle, then a run with a broken key showing the failure line.

## Amendments during implementation

Dated 2026-10-17, so a later reader sees the plan's current state rather than the state it
was written in.

- **The repeat floor is gone, and the choice is the cycle alone.** This plan first carried
  the spec's cycle-plus-floor. Implemented, the floor provably cannot change the answer:
  with the notes ordered by last send, the notes outside the floor are a prefix of that
  ordering, so the oldest note is outside the floor exactly when any note is — the filter
  returns that same oldest note — and when every note is inside the floor the spec's own
  fallback returns it too. Deleting the filter passes the same tests, which is how the
  finding surfaced. The owner ruled to drop `CRIER_NOTE_FLOOR_DAYS` and
  `Settings.note_floor_days` rather than keep a knob that turns nothing; Task 6 sweeps both
  out of the spec, the milestone-1 plan, `.env.example` and the README. The observable
  behaviour is unchanged, so nothing else in this plan moved — except that dropping the floor
  also removed `choose_note`'s `now` parameter, which existed only for the floor comparison;
  the function is now a pure function of the notes and the last-send map. That correction is
  recorded here because the first version of this amendment claimed nothing else moved.
- **`llm.py` reports a 200 whose `message` is missing or is not an object as
  `"unparsable response"`,** reserving `"empty completion"` for a message object whose
  `content` is unusable. The brief left that case open; the split keeps the error honest —
  there is no completion to call empty when the message itself is absent.
- **A list file's first `## id` with an empty body does not claim the id.** `read_notes`
  registers an id only when it actually appends a note, so a later heading with the same id
  and a body still counts. The tested rule ("the first wins") is unchanged for notes that
  have bodies.
- **`reword` does not wrap the call in `try/except`.** A first version caught every
  exception and returned the fallback, to honour "never raises" even against a caller that
  breaks its contract. That is a second safety net under a client whose whole design is
  "a failure is a value, never an exception", and it masked a real bug during this
  milestone: a stub missing `status_code` turned an `AttributeError` into a plausible
  fallback bulletin instead of a traceback. The contract holds by composition now, and the
  docstring says so.
- **`بازنویسی` is written without U+200C.** One implementation wrote it half-spaced; the
  letter before the break is `ز`, which does not join forward, so the parts cannot merge and
  the character is not owed. Measured on Persian Wikipedia the same way `ناموفق` was:
  2,616 occurrences connected, 0 half-spaced. The fallback's second clause reads
  `متن اصلی یادداشت فرستاده می‌شود`, which keeps a genuine half-space word in a string that
  is all-Persian and shown to the owner.
- **The independent review found eight things, and all eight are closed** (2026-10-17):
  - the CLI warned about notes on a `CRIER_SMOKE=1` run, which asks no producer for notes —
    a false alarm on the very deploy check the warning exists for. It is now gated on the
    note producer actually being in the run, and a smoke case pins it;
  - this plan still required the removed floor in Task 5 and still named `choose_note`'s
    `now` (above);
  - the spec still described the motivational addition in two places, and still called the
    choice "cycle-and-floor" in its Testing section; its data model also lacked
    `Bulletin.list_name`, and it called `llm.py` future work;
  - `PREVIOUS_LIMIT` was not pinned: the test held one earlier wording, so a `limit` of 1
    would have passed. It now records four and asserts the oldest is absent;
  - "which records count as a sent note" was written twice in `history.py`; it is one
    helper now, so the two queries cannot drift;
  - `previous_texts`' `limit < 1` guard had no test, and neither had the empty-body id
    rule. Both do.
- **Not changed from the review:** `previous_texts` reads by timestamp rather than file
  order. Append-only makes the two agree, and the timestamp is the one that is guaranteed.

## Amendment after the milestone (2026-10-21)

- **The note is expanded into a few lines, not reworded into one.** The owner's ruling:
  a single short sentence arrived like a bullet from a list, not like a reminder worth
  reading. The prompt now asks for one paragraph of three or four sentences — why the item
  is worth acting on and how to do it today — and drops both "add no claim of your own" and
  "keep it short", which together were what held the answer at one line. Fabricating a
  number, statistic, quote or event is forbidden instead: the freedom is in explaining and
  applying the note. Everything else in Task 4 stands, including the fallback, which stays
  the note's own single line because a short fallback is the price of a failed call.
  `docs/specs/2026-10-17-bale-crier-design.md` carries the reasoning; the README was swept
  with it.
