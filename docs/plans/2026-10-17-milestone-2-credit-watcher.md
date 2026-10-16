# Milestone 2 — the AvalAI credit watcher

**Goal:** a real alert, not a hardcoded one — the bot tells the owner when his
AvalAI credit crosses a threshold he set, once per crossing, and never mistakes
"I could not read it" for "it is gone".

**Architecture:** a small client turns the credit endpoint into numbers; a
watcher turns those numbers into a bulletin, using a latch it keeps in its own
memory file; and the run loop gains a way to select producers, so the watcher can
run hourly on a timer of its own.

**Tech Stack:** unchanged — Python ≥ 3.11 (the venv is a uv-managed 3.14.7),
`uv`, pydantic v2 + `pydantic-settings`, `requests`, pytest, type hints.

**Spec:** `docs/specs/2026-10-17-bale-crier-design.md`, sections "The credit
watcher", "Scheduling" and "Configuration".

## Global Constraints

- Every setting comes from the environment with the `CRIER_` prefix.
- Code, comments and docs are English; every string that reaches the owner is
  Persian, with a real U+200C in every half-space word. **The prefix `نا` is
  written connected** (`ناموفق`, `نامعتبر`); `می`, `ها`, `تر`/`ترین` and `بی` take
  the half-space.
- The credit endpoint: `GET https://api.avalai.ir/user/v1/credit` with
  `Authorization: Bearer <key>`. The numbers arrive **as strings** and must be
  parsed. Verified against a live response on 2026-10-17.
- **"I cannot tell" is never announced as "the credit is gone."** A read that
  fails, or a field that could not be parsed, produces a bulletin that says so —
  never an empty balance.
- The bot reports and does not advise: no buying suggestion, no "nearly out"
  wording. The threshold is the owner's, not the bot's.
- The history stays "what the owner read". A watcher's own memory is a separate
  file and never a history line.
- `bale_crier/bale.py` stays the only module that talks to Bale.
- Defaults: threshold 50,000 IRT, unknown-alert window 24 hours, state file
  `data/watchers.json`.

## Acceptance Criteria

The milestone is done when all of these hold:

1. `uv run pytest` is green.
2. `uv run python -m bale_crier --only credit` with the real key and the real
   balance sends **nothing** — the balance is above the threshold, so the quiet
   path is the correct outcome.
3. With the threshold temporarily raised above the current balance, one alert
   **really arrives in Bale**, `data/watchers.json` records the latch as set, and
   the very next run sends nothing.
4. With a bad key, one bulletin arrives that says the credit could not be read
   and does not say it is gone.
5. `systemd-analyze verify` exits 0 for the two new units, and the credit timer is
   enabled in the user manager with a next elapse.

Criterion 3 is the one that matters: it is the only check that the latch — the
subtle part — works against the real endpoint and the real chat.

## Prerequisite the owner must supply

A `CRIER_AVALAI_API_KEY` for the daemon. `avalai-credit.py` currently reads the
key from `~/.claude/settings.json`, which is a laptop concern; the daemon reads it
from `.env` like every other setting.

## Files

| file | responsibility |
| --- | --- |
| `bale_crier/credit.py` | the credit endpoint, parsed into numbers |
| `bale_crier/memory.py` | a watcher's own state, across runs |
| `bale_crier/watchers/__init__.py` | package marker |
| `bale_crier/watchers/avalai_credit.py` | the watcher: threshold, latch, bulletin text |
| `bale_crier/models.py` | add `Package`, `CreditReport` |
| `bale_crier/config.py` | three new settings |
| `bale_crier/producers.py` | `own_timer` on the protocol |
| `bale_crier/run.py` | memory wiring, producer selection |
| `bale_crier/cli.py` | `--only` |
| `deploy/user/bale-crier-credit.service`, `.timer` | the hourly check |
| `.env.example`, `README.md` | the new settings, the second timer |
| `tests/test_credit.py`, `test_memory.py`, `test_credit_watcher.py`, and additions to `test_run.py`, `test_config.py`, `test_producers.py` | the tests |

## Tasks

### Task 1: The credit endpoint, parsed

**Files:**
- Create: `bale_crier/credit.py`, `tests/test_credit.py`
- Modify: `bale_crier/models.py` (add `Package`, `CreditReport`)

**Interfaces:**
- `Package` — pydantic model: `tier: str` (`"daily"` | `"weekly"` | `"other"`),
  `name: str`, `remaining_irt: float | None`, `amount_irt: float | None`,
  `end_date: datetime | None`, `spendable: bool`.
- `CreditReport` — pydantic model: `main_balance_irt: float | None`,
  `packages: list[Package]`, `tier_remaining: dict[str, float]`,
  `active_tier: str | None`, `active_remaining_irt: float | None`.
- `CreditRead` — `typing.NamedTuple`: `report: CreditReport | None`, `error: str`.
- `tier_of(package: Mapping[str, object]) -> str` — `d-` prefix or «روزانه» in the
  name means daily; `w-` prefix or «هفتگی» means weekly; anything else is other.
- `fetch_report(*, key: str, timeout: int = 30, base_url: str = "https://api.avalai.ir") -> CreditRead`
- `CREDIT_PATH = "/user/v1/credit"` — the one place the path is written.

**Behavior to verify:**
- The request is a `GET` to `https://api.avalai.ir/user/v1/credit` carrying
  `Authorization: Bearer <key>` (assert against a stubbed `requests`).
- Numbers arriving as strings parse: `"439968.18"` becomes `439968.18`. The
  top-level `remaining_irt` arrives as a JSON number while the per-package
  `remaining_irt` and `amount_irt` arrive as strings; both forms must be accepted,
  so a change of form on either side is not a failure.
- `tier_of` maps `d-1`, `w-2`, `"وایب کُدر روزانه پایه"`, `"وایب کُدر هفتگی پایه"`
  and an unknown template to daily, weekly, daily, weekly and other.
- A package whose remaining is `0` is not spendable; one whose `end_date` has
  passed is not spendable; one with no `end_date` and a positive remaining is.
- `tier_remaining` sums only the spendable packages of that tier, so two live
  daily packages add up.
- `active_tier` is daily when the daily tier has a positive balance even if the
  weekly tier holds more; it is weekly when daily is empty; it is `None` when no
  tier is live.
- `active_remaining_irt` is the active tier's sum, and the main balance when no
  tier is live.
- A response with no readable `remaining_irt` and no live package gives
  `active_remaining_irt is None` — **not** `0`. This is the case the owner's rule
  is about.
- A transport failure, a non-JSON body, and a body that is not an object each give
  `report is None` with a non-empty `error`, and raise nothing.
- A package entry that is not an object is skipped rather than fatal.

**Notes:**
- The parsing rules mirror `~/.config/opencode/scripts/avalai-credit.py`, which is
  the verified reading of this endpoint. The script is not imported: the daemon
  must not depend on a file under `~/.config/opencode/`.
- Keep the shapes defensive. A provider response that changes shape must produce
  "could not read it", never a traceback and never a verdict built on a container
  that was not actually read.

### Task 2: A watcher's memory

**Files:**
- Create: `bale_crier/memory.py`, `tests/test_memory.py`

**Interfaces:**
- `WatcherMemory` — holds a mapping of producer name to a JSON object.
  - `WatcherMemory.load(path: Path) -> WatcherMemory`
  - `get(name: str) -> dict` — `{}` for a name that has never written.
  - `set(name: str, value: dict) -> None`
  - `save() -> None` — writes the file, creating the parent directory.
- `as_dict()` may exist for tests; it is not part of what a producer uses.

**Behavior to verify:**
- `get` on a name that never wrote returns `{}` and does not raise.
- `set` then `save` then `load` round-trips the value.
- A missing file loads as empty rather than raising.
- A file holding invalid JSON, or valid JSON that is not an object, loads as empty
  rather than raising — a corrupt memory must cost an extra alert, not a crash.
- `save` creates the parent directory when it does not exist.
- `save` leaves no `.tmp` neighbour behind, and the written file is the new
  content — it goes through a rename, not a truncate.
- `set` on one name does not disturb another name's value.

**Notes:**
- Atomicity matters here for the same reason it does in the history: a crash
  mid-write must not leave a half-written file that then reads as "no memory",
  which would re-alert.
- One writer per blob today, because a producer that owns a timer is the only one
  that runs it (Task 4). A lock is owed only when two watchers share a file and
  can run at once; say so in the module docstring rather than building it now.

### Task 3: The credit watcher

**Files:**
- Create: `bale_crier/watchers/__init__.py`,
  `bale_crier/watchers/avalai_credit.py`, `tests/test_credit_watcher.py`

**Interfaces:**
- `CreditWatcher(settings: Settings, memory: WatcherMemory, read: CreditReader = fetch_report)`
  where `CreditReader = Callable[..., CreditRead]`.
- `name = "credit"`, `own_timer = True`
- `produce(now: datetime) -> list[Bulletin]` — returns zero or one bulletin.
- **The value compared against the threshold is `CreditReport.active_remaining_irt`**,
  which is already "whatever is paying right now" (Task 1). `None` there is the
  failed-read path, not a zero balance.
- The memory blob this watcher owns is `{"armed": bool, "last_unknown_alert": str | None}`,
  holding an ISO-8601 UTC timestamp for the second.
- Bulletin `kind` is `"alert"`; `note_id` stays `None`.

**Behavior to verify:**
- A value at or above the threshold with the latch armed → no bulletin, and the
  latch stays armed.
- A value below the threshold with the latch armed → exactly one bulletin, and the
  latch is set.
- A value below the threshold with the latch already set → no bulletin.
- A value back at or above the threshold re-arms the latch, so a later crossing
  alerts again — the "he bought another package" case.
- The first run ever, with a value already below the threshold, alerts immediately.
- A failed read with no previous unknown alert → one bulletin.
- A failed read within `CRIER_CREDIT_UNKNOWN_ALERT_HOURS` of the last one → no
  bulletin; after the window → a bulletin.
- A failed read leaves the latch exactly as it was — a failed read must not
  consume the crossing.
- The threshold bulletin's text contains the remaining amount and the threshold,
  both formatted as numbers, and names the tier or the main balance.
- The unknown bulletin's text contains no claim that the credit is gone, and says
  the reading failed.
- Neither bulletin's text contains buying advice — assert on a small list of
  forbidden Persian words (`بخر`, `خرید`, `توصیه`) rather than trusting the eye.
- Both texts contain at least one Persian character and at least one U+200C.

**Notes:**
- The watcher writes the latch through `memory.set` and lets the run loop save it.
  A crash between the two re-alerts next run, which is the safe direction.
- `produce` takes `now` rather than reading the clock, so the unknown window is
  testable without waiting.
- The bulletin reports numbers only. Any wording that nudges the owner to buy is
  out of bounds, however helpful it reads.

### Task 4: Selecting producers, and the run loop

**Files:**
- Modify: `bale_crier/producers.py` (the `own_timer` attribute),
  `bale_crier/run.py`, `bale_crier/cli.py`, `bale_crier/config.py`,
  `tests/test_run.py`, `tests/test_config.py`, `tests/test_producers.py`

**Interfaces:**
- `Producer` gains `own_timer: bool = False` — a producer that runs on a timer of
  its own sets it, and the daily run leaves it out.
- `build_producers(settings: Settings, *, memory: WatcherMemory, only: Sequence[str] | None = None) -> list[Producer]`
  — `only` given means exactly those names, and an unknown name raises
  `ValueError`; otherwise every producer whose `own_timer` is false. The credit
  watcher is registered **only when `settings.avalai_api_key` is set**.
- `run_once(settings: Settings, *, now: datetime, send: Sender = send_message, only: Sequence[str] | None = None) -> RunReport`
  — loads the memory, builds the producers, sends, records, then saves the memory.
- `main(argv)` gains `--only NAME`, repeatable.
- New `Settings` fields: `credit_threshold_irt: float = Field(default=50_000, ge=0)`,
  `watchers_state_path: Path = Path("data/watchers.json")`,
  `credit_unknown_alert_hours: float = Field(default=24, gt=0)`.

**Behavior to verify:**
- Without `--only`, the credit watcher is not in the produced set, because it owns
  a timer; with `--only credit` it is the only one.
- `build_producers` with an unknown name raises `ValueError`.
- With `avalai_api_key` unset, no credit watcher is registered even under
  `--only credit`.
- A run that produces nothing still does not create the memory file.
- A run whose watcher sets the latch leaves it on disk afterwards.
- The three new settings take their values from `CRIER_CREDIT_THRESHOLD_IRT`,
  `CRIER_WATCHERS_STATE_PATH` and `CRIER_CREDIT_UNKNOWN_ALERT_HOURS`, and carry
  the stated defaults.
- `CRIER_CREDIT_UNKNOWN_ALERT_HOURS=0` is refused with a Persian `ConfigError`.

**Notes:**
- `own_timer` exists so the two timers cannot race over one latch: the hourly
  credit unit runs only the credit watcher, and the daily unit runs everything
  else. Without it, a daily run and an hourly run landing together could both read
  an armed latch and both alert.
- A missing key is not a crash and not a silent gap: the run reports in Persian
  that the credit watcher is off for want of a key.

### Task 5: The second timer, and the live check

**Files:**
- Create: `deploy/user/bale-crier-credit.service`, `deploy/user/bale-crier-credit.timer`
- Modify: `README.md`, `.env.example`

**Interfaces:**
- `bale-crier-credit.service` — `Type=oneshot`, the same `WorkingDirectory`,
  `ExecStart=…/.venv/bin/python -m bale_crier --only credit`, no `[Install]`.
- `bale-crier-credit.timer` — `OnCalendar=hourly`, `Persistent=true`,
  `RandomizedDelaySec=2m`, `[Install] WantedBy=timers.target`.
- Both carry the same install notes as the existing units.

**Behavior to verify:**
- `systemd-analyze verify` exits 0 for both files.
- `systemd-analyze calendar hourly` is accepted, and the timer shows a next elapse
  once installed.
- The two timers do not both run the credit watcher: the daily unit's own run
  reports the credit watcher as absent.

**Notes:**
- `RandomizedDelaySec=2m` rather than the daily unit's ten minutes: an hourly check
  has less room to spread into.
- The live checks in the Acceptance Criteria belong here, and criterion 3 is the
  one to run by hand: raise the threshold above the current balance, watch one
  message arrive, then run again and watch the latch hold.

## Amendments during implementation

Dated 2026-10-17, so a later reader sees the plan's current state rather than the
state it was written in.

- **`save()` writes only the names this run changed, merged into whatever is on
  disk at that moment.** Review found a real bug — and the one this milestone
  exists to prevent. The daily run registers no credit watcher, but it loaded and
  saved the whole memory file, so a re-arm the hourly run recorded in between was
  silently undone and the next crossing never spoke. Saving only this run's names,
  and re-reading the file first, closes it. Two runs writing the *same* name at
  once would still need a lock; one producer owns each name, so there is none.
- **A store built with `data=` marks nothing changed, so it writes nothing.**
  Three tests had seeded a file that way and were quietly not exercising what they
  claimed; they seed through `set` and `save` now.
- **`--only` is validated against the names that exist**, not against the
  producers this run can build, so `--only credit` without a key is an empty run
  rather than an error — and the CLI says so in Persian on stderr.
- **The unknown window is inclusive**: at exactly
  `CRIER_CREDIT_UNKNOWN_ALERT_HOURS` the window has passed and the watcher may
  speak. A test pins the boundary, which the first version left open.
- **The gone-claim guard is a blocklist plus a positive assertion.** A blocklist
  alone cannot be complete, and a mutation that *appended* a gone-claim to the
  unreadable-credit text slipped past the first version. The list is longer now,
  and the test also asserts the sentence that says the read failed.
- **`own_timer` has to be set explicitly on a producer that does not subclass the
  Protocol**, because a Protocol's attribute default is not inherited.
