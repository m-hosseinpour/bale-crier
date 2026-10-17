# Milestone 1 — the path end to end

**Goal:** a scheduled run that really lands a message in Bale, with the history
recording it — the whole path proved, and nothing else.

**Architecture:** one run gathers bulletins from producers, sends each through a
single small Bale sender, and appends one history line per bulletin. Milestone 1
has exactly one producer, a smoke producer behind `CRIER_SMOKE`, so the path can
be proved without spamming the owner before real bulletins exist.

**Tech Stack:** Python ≥ 3.11 (the machine has 3.12.3), `uv` 0.12.4, pydantic v2
with `pydantic-settings`, `requests`, pytest, type hints.

**Spec:** `docs/specs/2026-10-17-bale-crier-design.md`

**Status:** complete, 2026-10-17. All five acceptance criteria were met — including a real message in
the owner's Bale chat, which he confirmed. See "Amendments during implementation" at the end for
what changed after this plan was written.

## Global Constraints

- Every setting is read from the environment with the `CRIER_` prefix.
- Bale: `POST https://tapi.bale.ai/bot<TOKEN>/sendMessage`, JSON body
  `{"chat_id": ..., "text": ...}`, and the response JSON carries `ok`. Verified in
  `~/workspace/bale-news-digest/bale_bot_message_sender.py`; do not re-probe.
- Code, comments and docs are English; **every string that reaches the owner is
  Persian, with a real U+200C in every half-space word.**
- The sender never raises on a bad response — it returns a failed `SendResult`,
  and the run records the failure. A failed send must not take the process down
  before the history line is written.
- Content lives in `lists/` (gitignored) and history in `data/history.jsonl`
  (gitignored). `lists.example/` is committed.
- No webhook and no polling anywhere.
- Defaults: history cap 5000 lines, note floor 30 days, HTTP timeout 30s,
  LLM base `https://api.avalai.ir/v1`.

## Acceptance Criteria

The milestone is done when all of these hold:

1. `uv run pytest` is green.
2. With a real `CRIER_BALE_BOT_TOKEN` and `CRIER_BALE_CHAT_ID` set,
   `CRIER_SMOKE=1 uv run python -m bale_crier` puts a real message in the owner's
   Bale chat, and `data/history.jsonl` gains a line with `"ok": true`.
3. `systemd-analyze verify deploy/user/bale-crier.service` and
   `systemd-analyze verify deploy/user/bale-crier.timer` both exit 0.
4. `systemd-analyze calendar` accepts every `OnCalendar` line in the timer.
5. The timer is enabled in the user manager and shows a next elapse.

## Prerequisite the owner must supply

A Bale bot token and the destination chat id for `@bale_crier_bot`. Nothing in
this milestone can be accepted without them; tasks 1–5 are testable without, task
6's live check is not.

## Files

| file | responsibility |
| --- | --- |
| `pyproject.toml` | project metadata, dependencies, pytest config |
| `.gitignore` | `.venv`, caches, `.env`, `lists/`, `data/` |
| `.env.example` | every `CRIER_` variable with a placeholder value |
| `README.md` | what it is, setup, run, structure, deploy |
| `bale_crier/__init__.py` | package marker |
| `bale_crier/config.py` | `Settings` and `load_settings()` |
| `bale_crier/models.py` | `Bulletin`, `SendResult`, `RunReport`, `HistoryRecord` |
| `bale_crier/bale.py` | `send_message()` — the only place that talks to Bale |
| `bale_crier/history.py` | append-only JSONL, read, cap |
| `bale_crier/producers.py` | the `Producer` protocol and `SmokeProducer` |
| `bale_crier/run.py` | `build_producers()`, `run_once()` |
| `bale_crier/cli.py` | argument parsing, wiring, exit code |
| `bale_crier/__main__.py` | `python -m bale_crier` entry point |
| `deploy/user/bale-crier.service` | `Type=oneshot` run |
| `deploy/user/bale-crier.timer` | 2–3 fixed `OnCalendar` times |
| `lists.example/reading.md` | the list format, committed |
| `tests/test_config.py`, `test_bale.py`, `test_history.py`, `test_producers.py`, `test_run.py` | the tests |

`Note`, `notes/`, `llm.py` and `watchers/` are **not** in this milestone; they
belong to milestones 2 and 3.

## Tasks

### Task 1: Skeleton, settings, README

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`,
  `bale_crier/__init__.py`, `bale_crier/config.py`,
  `bale_crier/models.py`, `lists.example/reading.md`, `tests/test_config.py`

**Interfaces:**
- `Settings` — a `pydantic_settings.BaseSettings` subclass, `env_prefix="CRIER_"`,
  reading `.env`, with fields: `bale_bot_token: str`, `bale_chat_id: int`,
  `lists_dir: Path = Path("lists")`, `history_path: Path = Path("data/history.jsonl")`,
  `history_max_lines: int = 5000`, `note_floor_days: int = 30` (removed in milestone 3 — see the
  amendments at the end of this plan),
  `http_timeout: int = 30`, `smoke: bool = False`,
  `open_ai_base_url: str = "https://api.avalai.ir/v1"`,
  `open_ai_model: str = "deepseek-v4-flash"`, `open_ai_api_key: str | None = None`,
  `avalai_api_key: str | None = None`.
- `ConfigError(Exception)` — raised in place of pydantic's `ValidationError`, so a
  misconfiguration reads as Persian prose rather than a stack trace.
- `load_settings() -> Settings` — reads the environment and `.env`, and raises
  `ConfigError` naming the missing or invalid variable.
- `models.py` — created here, and each later task adds the shapes it owns:
  `SendResult` (Task 2), `HistoryRecord` (Task 3), `Bulletin` (Task 4),
  `RunReport` (Task 5). The shapes are given in those tasks. Every one of them
  edits this single file, so those tasks are not parallel-safe.

**Behavior to verify:**
- `CRIER_BALE_CHAT_ID=123` reaches `Settings.bale_chat_id` as the int `123`.
- An unset `CRIER_BALE_BOT_TOKEN` makes `load_settings()` raise `ConfigError`
  whose message names `CRIER_BALE_BOT_TOKEN` and is Persian.
- `CRIER_BALE_CHAT_ID=abc` raises `ConfigError` naming `CRIER_BALE_CHAT_ID`.
- With nothing set but the two required variables, every default in the interface
  list above is what the spec says.

**Notes:**
- The two required fields are required: without them nothing can be sent, and a
  daemon that silently does nothing is worse than one that refuses to start.
- `lists.example/reading.md` carries one note in the settled format — a `## id`
  heading and a Persian body — so the format is visible without the owner's
  content leaving the machine.

### Task 2: The Bale sender

**Files:**
- Create: `bale_crier/bale.py`, `tests/test_bale.py`
- Modify: `bale_crier/models.py` (add `SendResult`)

**Interfaces:**
- `SendResult` — pydantic model: `ok: bool`, `error: str | None = None`.
- `send_message(text: str, *, token: str, chat_id: int, base_url: str = "https://tapi.bale.ai", timeout: int = 30) -> SendResult`
- Module constant `SEND_MESSAGE_PATH = "/bot{token}/sendMessage"` or an equivalent
  single place where the URL is built, so tests can assert the URL without
  duplicating the format string.

**Behavior to verify:**
- The outgoing request is a `POST` to
  `https://tapi.bale.ai/bot<TOKEN>/sendMessage` carrying exactly
  `{"chat_id": <chat_id>, "text": <text>}` as JSON (assert against a stubbed
  `requests.post`).
- A response body `{"ok": true, "result": {...}}` yields `SendResult(ok=True, error=None)`.
- A response body `{"ok": false, "description": "..."}` yields `ok=False` with the
  description in `error`, and raises nothing.
- A `requests` transport exception yields `ok=False` with an error, and raises
  nothing.
- A non-JSON response body yields `ok=False` with an error, and raises nothing.

**Notes:**
- This is the only module that talks to Bale. Milestone 2 and 3 must not add a
  second path to the API.
- The only response field verified in the sibling project is `ok`. Nothing here
  may depend on the shape of `result`; if a later milestone needs a message id,
  verify that shape against a real response first.
- `ok: false` is a real outcome, not an exception: Bale rejects a bad chat id this
  way, and the run has to record it. `error` carries `description` when the body
  has it and falls back to a short repr of the body when it does not, so an
  unexpected failure is still readable.

### Task 3: History

**Files:**
- Create: `bale_crier/history.py`, `tests/test_history.py`
- Modify: `bale_crier/models.py` (add `HistoryRecord`)

**Interfaces:**
- `HistoryRecord` — pydantic model: `ts: datetime`, `kind: str`, `text: str`,
  `list_name: str | None = None`, `note_id: str | None = None`, `ok: bool`.
- `append(record: HistoryRecord, *, path: Path, max_lines: int) -> None`
- `read_all(*, path: Path) -> list[HistoryRecord]`
- `last_sent_at(*, note_id: str, list_name: str, path: Path) -> datetime | None`
  (became `last_sent_map` in milestone 3 — see the amendments at the end of this plan)
  — the newest `ts` among the successful `note` records for that note; `None` when
  it has never gone. Milestone 3 consumes this; milestone 1 only needs it to
  exist and be tested.

**Behavior to verify:**
- `append` creates the parent directory and the file when neither exists.
- Two appends put exactly two lines in the file, each one parseable JSON object.
- `read_all` on a missing path returns an empty list and does not raise.
- A file whose last line is truncated (a crash mid-write) yields the intact
  records and skips the broken one, raising nothing.
- With `max_lines=3`, appending a fourth record leaves the three newest in file
  order, oldest dropped.
- `ts` survives the round trip as an aware UTC datetime.
- `last_sent_at` returns `None` for a note that never went, the newest `ts` when
  it went twice, and ignores records whose `ok` is false.

**Notes:**
- Append-only is the point: no read-modify-write of the whole file, so a crash
  cannot lose the records already written.
- The cap is enforced on append, and it rewrites the file only when the count is
  over — the one case where the file is not purely appended to.
- Store `ts` as UTC ISO-8601 so the file stays readable by eye.

### Task 4: Producers and the smoke bulletin

**Files:**
- Create: `bale_crier/producers.py`, `tests/test_producers.py`
- Modify: `bale_crier/models.py` (add `Bulletin`)

**Interfaces:**
- `Bulletin` — pydantic model: `kind: str`, `text: str`, `note_id: str | None = None`.
  Documented kinds so far: `"smoke"` (this milestone), `"alert"` and `"note"`
  (milestones 2 and 3).
- `Producer` — a `typing.Protocol` with `name: str` and
  `produce(now: datetime) -> list[Bulletin]`.
- `SmokeProducer` — `name = "smoke"`, `produce(now)` returns exactly one
  `Bulletin` with `kind="smoke"` and a fixed Persian text saying it is a test
  bulletin from the crier, so a reader knows the path is alive.

**Behavior to verify:**
- `SmokeProducer().produce(now)` returns exactly one bulletin, `kind == "smoke"`,
  `note_id is None`.
- Its `text` is non-empty and contains at least one Persian character.
- Two calls with the same `now` return equal bulletins — the producer is
  deterministic, so a repeated test run is not flaky.

**Notes:**
- The smoke producer is gated behind `CRIER_SMOKE` by `build_producers` in Task 5,
  never registered by default: an unconditional smoke bulletin would hit the
  owner's chat two or three times a day until milestone 2.
- It stays after milestone 1 as the deploy check the acceptance criteria use. When
  milestone 2 adds the watcher, `build_producers` grows a second entry — that is
  the whole seam.

### Task 5: The run loop and the CLI

**Files:**
- Create: `bale_crier/run.py`, `bale_crier/cli.py`, `bale_crier/__main__.py`,
  `tests/test_run.py`
- Modify: `README.md` (run instructions)

**Interfaces:**
- `build_producers(settings: Settings) -> list[Producer]` — returns
  `[SmokeProducer()]` when `settings.smoke` is true, otherwise `[]`.
- `RunReport` — pydantic model: `sent: int`, `failed: int`, `producers: list[str]`.
- `Sender = Callable[..., SendResult]`
- `run_once(settings: Settings, *, now: datetime, send: Sender = send_message) -> RunReport`
  — gathers from every producer, sends each bulletin, appends one history line per
  bulletin whatever the outcome, and returns the counts.
- `main(argv: list[str] | None = None) -> int` — parses arguments, calls
  `load_settings()`, calls `run_once`, prints a short Persian summary, and returns
  the exit code.
- `__main__.py` calls `sys.exit(main())`.

**Behavior to verify:**
- `smoke=False` with a stubbed sender: nothing is sent, the history file is not
  created, and the report is `sent=0, failed=0, producers=[]`.
- `smoke=True` with a stubbed sender returning `ok=True`: exactly one send call,
  one history line with `ok=True` and `kind="smoke"`, report `sent=1, failed=0`.
- `smoke=True` with a stubbed sender returning `ok=False`: one history line with
  `ok=False`, report `sent=0, failed=1`, and `main` returns a non-zero exit code.
- A `ConfigError` from `load_settings()` makes `main` return a non-zero code and
  print the Persian message rather than a traceback.
- `main(["--help"])` returns 0.

**Notes:**
- The history line is written for a failed send too — a silent failure is the one
  outcome the owner cannot debug later.
- `run_once` takes `now` rather than calling the clock itself, so tests are not
  time-dependent.

### Task 6: systemd units and the live check

**Files:**
- Create: `deploy/user/bale-crier.service`, `deploy/user/bale-crier.timer`
- Modify: `README.md` (a deploy section: install, enable, where the times live)

**Interfaces:**
- `bale-crier.service` — `Type=oneshot`, `WorkingDirectory=/home/mahdi/workspace/bale-crier/`,
  `ExecStart=/home/mahdi/workspace/bale-crier/.venv/bin/python -m bale_crier`,
  `Environment=PYTHONUNBUFFERED=1`, no `[Install]` section.
- `bale-crier.timer` — `[Timer]` with two or three literal `OnCalendar=` lines at
  fixed times, `Persistent=true`, `RandomizedDelaySec=10m`; `[Install]`
  `WantedBy=timers.target`.
- Both units carry the install notes the sibling units carry: install to
  `~/.config/systemd/user/`, `daemon-reload`, enable the **timer** not the
  service, and `sudo loginctl enable-linger $USER` or the timer dies with the
  session.

**Behavior to verify:**
- `systemd-analyze verify` exits 0 for both files.
- `systemd-analyze calendar` accepts every `OnCalendar` line.
- After install, `systemctl --user list-timers bale-crier.timer` shows a next
  elapse.

**Notes:**
- The times are literal in the file. systemd does not expand environment
  variables in a unit file — measured on 2026-10-17, systemd 255: a timer whose
  `OnCalendar` was `$CRIER_PROBE_TIME` never activated. Do not reintroduce a
  `CRIER_SCHEDULE_TIMES`.
- The live check needs the owner's token and chat id; it is the acceptance
  criterion, not a unit test.
- `WorkingDirectory` matters: the default `lists_dir` and `history_path` are
  relative, and a run started elsewhere would write its history in the wrong
  place.

## Amendments during implementation

Dated 2026-10-17, so a later reader sees the plan's current state rather than the
state it was written in.

- **`message_id` is not in `SendResult`** (dropped while planning, before the
  build). Nothing used it, and the shape of Bale's `result` was never verified —
  only `ok` was.
- **A fragment at the end of the history is now closed off before the next
  append.** Found in review, and a real bug rather than a test gap: a run killed
  mid-write leaves a line with no newline, so the next record was appended onto
  it and both were lost on read. The documented "one broken line" recovery was
  costing two records. `append` now writes a newline first when the file does not
  end with one.
- **`history_max_lines`, `note_floor_days` and `http_timeout` carry lower
  bounds** (`ge=1`, `ge=0`, `ge=1`). Each silently does damage at zero, and a cap
  of zero emptied the history.
- **The cap trim writes to a neighbour file and renames it**, rather than
  truncating the history in place — the one write that could otherwise lose
  everything. Atomicity itself is not observable to a unit test; the check that
  no neighbour file is left behind is.
- **`main(["--help"])` returns 0** by catching `argparse`'s `SystemExit`, which
  the plan's wording did not anticipate. A bad flag therefore returns 2 rather
  than propagating.
- **The venv resolved to a uv-managed CPython 3.14.7**, not the machine's 3.12.3
  — the same interpreter the sibling `bale-news-digest` venv uses. The
  `requires-python` floor stays `>=3.11`.
- **The `.env` reaches a systemd run through `WorkingDirectory`**, not through
  `EnvironmentFile=`. pydantic-settings reads `.env` relative to the working
  directory, which the unit sets. The unit's comments and the README say so.
- **Two interfaces this plan named were replaced in milestone 3** (2026-10-17).
  `history.last_sent_at(*, note_id, list_name, path)` asked about one note at a time, while the note
  chooser asks about every note at once, so it became `history.last_sent_map(*, path)`; the old name
  is gone rather than kept beside it. And `Settings.note_floor_days` was removed: the "do not repeat
  within N days" floor it fed could never change the note the cycle picked, so the owner dropped it
  rather than keep a knob that turns nothing. Both are in
  `docs/plans/2026-10-17-milestone-3-owner-lists.md`.

One claim from the review was checked and **rejected**: it asked for a U+200C in
`نامعتبر` and `ناموفق`. The prefix `نا` is written connected, unlike `بی`. Two
independent sources say so — an editorial site that half-spaces `می`/`ها`/`بی`
consistently, and the raw text of Persian Wikipedia, where `ناموفق` appears 32
times connected and 0 times half-spaced. Adding the character would have been the
error.
