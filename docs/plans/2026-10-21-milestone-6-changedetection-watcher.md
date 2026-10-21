# Milestone 6 — the changedetection watcher

**Goal:** the bot tells the owner which pages changed, as one Persian message naming
the page and the lines that changed, checked every three hours against the
`changedetection.io` already running on this machine — and never mistakes "I could
not read it" for "nothing changed".

**Architecture:** one more watcher, built the way the credit and disk watchers are.
A client module talks to the API and reduces it to values; the watcher keeps one
watermark per watch in its own memory, decides what is new, and words one bulletin.
It runs on a timer of its own so the daily run cannot race over those watermarks.

**Spec:** `docs/specs/2026-10-17-bale-crier-design.md`, section "The changedetection
watcher".

## Decisions (owner, 2026-10-21)

- **Poll, do not push.** changedetection notifies through Apprise, and the Apprise
  it ships with has no Bale plugin (its telegram module is hardcoded to
  `api.telegram.org`), so a push would need a receiving server — an inbound door
  the design refuses. The watcher reads the local API instead.
- **Every three hours.** The owner chose the same interval changedetection itself
  checks a page with, rather than asking changedetection to fetch every page every
  hour. A change therefore arrives up to six hours after it happens, three on
  average, since the two three-hour clocks are independent.
- **One message per run**, all changed pages inside it, rather than one message per
  page.
- **The diff is shown, not summarized.** The changed lines are the message; there is
  no model call, because on a list page the diff already is the content and a
  summary would only add a wrong line or a delay.

## Files

| file | responsibility |
| --- | --- |
| `bale_crier/changedetection.py` | the API: the watch list, one watch's diff, the placemarkers as `+`/`-` lines, failures as values |
| `bale_crier/watchers/changedetection.py` | the watcher: watermarks, what counts as new, the bulletin text and its caps |
| `bale_crier/watchers/window.py` | the reminder-window rule the three watchers shared by copy before |
| `bale_crier/persian.py` | numbers written with Persian digits, now that two modules count |
| `bale_crier/models.py` | `Watch`, and `watch` added to the kinds `Bulletin` names |
| `bale_crier/config.py` | `changedetection_url`, `changedetection_api_key`, `changedetection_unknown_alert_hours` |
| `bale_crier/run.py`, `cli.py` | register the producer, name it in `--only`, warn when its key is missing |
| `deploy/user/bale-crier-changedetection.service`, `.timer` | the three-hourly check |
| `.env.example`, `README.md`, `AGENTS.md`, the spec | the settings, the fifth timer, the `watch` word |
| `tests/test_changedetection.py`, `tests/test_changedetection_watcher.py`, additions to `test_config.py` and `test_run.py` | the tests |

## Behavior to verify

- The first run ever records every watch's `last_changed` and sends nothing.
- A watch whose number moved past the recorded one speaks once, naming its address,
  how long ago the change was seen, and the changed lines as `+`/`-`.
- The same number again is silent, and a quiet run does not rewrite the memory file.
- Two changed pages in one run are one bulletin, oldest first, so no page waits
  behind one that changed after it.
- A watch seen for the first time later is recorded silently.
- A number that moved backwards (history cleared) is recorded silently.
- A failed read of the API is one bulletin saying the reading failed, at most once
  per `CRIER_CHANGEDETECTION_UNKNOWN_ALERT_HOURS`, and leaves the watermarks alone,
  so the change it could not see speaks on the next run that can.
- A page whose diff cannot be read is still reported, with one line saying so; a
  page with a single snapshot says the text is not there, which is not a failure.
- More than ten changed lines a page, a single runaway line, and six pages at once
  all stay inside one Bale message.
- The ten lines are shared between what went and what came (up to five each, the
  short side lending the rest), so a rewritten page does not show ten removals and
  no additions.
- A page whose block does not fit the message keeps its watermark, so the next run
  carries it and the message's "next message" line is true.
- A failed send leaves the watermark too: the run saves no watcher memory, so the
  change repeats rather than vanishing.
- The watermarks survive the process; a corrupt one costs a bulletin, not a crash.
- The daily run leaves the watcher out; `--only changedetection` selects it alone.
- Both texts are Persian, with a real U+200C.
- The timer is every three hours, literally in the unit file.

## Acceptance and what was checked

- `uv run pytest` green (361 tests, 57 of them new).
- `systemd-analyze verify` exits 0 for both units; `systemd-analyze calendar
  '*-*-* 00/3:00:00'` normalizes to 00, 03, … 21.
- The timer is installed and enabled in the user manager with a next elapse.
- By hand, against the real instance on port 5005 and the real chat: one run
  recorded six watches and said nothing, and a run with one number lowered sent one
  message naming `https://opencode.ai/zen/v1/models` with its two changed lines; the
  run after it was quiet, and the watermark was back at the real number.
- An independent review read the diff before it was committed. It found three things
  that were fixed: a page dropped by the message cap had its watermark advanced (it
  was lost, and the message promised a next time that never came), the first ten
  lines of a rewritten page were all removals, and a failed Bale send consumed the
  change for good. It also caught the spec's own vocabulary section still counting
  five words, and two plurals written without U+200C.
