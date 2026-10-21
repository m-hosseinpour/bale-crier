# Milestone 5 — the disk watcher

**Goal:** the bot tells the owner when the machine's free disk space falls below
2 GiB — once on the crossing, then a reminder at most once a day while it stays
low — and never mistakes "I could not read it" for "the disk is full".

**Architecture:** one more watcher, built the way the credit watcher is: a reader
turns a local reading into a number, the watcher turns the number into a bulletin
with a latch and a reminder window kept in its own memory file, and it runs hourly
on a timer of its own so the daily run cannot race over that latch.

**Spec:** `docs/specs/2026-10-17-bale-crier-design.md`, section "The disk watcher".

## Decisions (owner, 2026-10-21)

- **Which filesystem:** `/`. `/proc/mounts` showed one ext4 root and no separate
  `/home`, so every path that matters — the repo, `data/`, `lists/` — is on the
  same mount. It is still configurable (`CRIER_DISK_PATH`) rather than hardcoded.
- **Threshold:** 2 GiB, set in GiB (`CRIER_DISK_THRESHOLD_GIB`): the setting and
  the bulletin show the same number in the same unit.
- **Repetition:** crossing alert, then a reminder at most every 24 hours
  (`CRIER_DISK_REMINDER_HOURS`) while space stays low. A disk nobody cleans up
  does not fix itself, so a single crossing alert would scroll away.
- **Schedule:** hourly, like the credit watcher, on its own timer. Checking often
  costs nothing because the latch and the window decide when a message goes.

## Files

| file | responsibility |
| --- | --- |
| `bale_crier/watchers/disk.py` | the watcher: free space, latch, reminder, bulletin texts |
| `bale_crier/config.py` | `disk_path`, `disk_threshold_gib`, `disk_reminder_hours` |
| `bale_crier/run.py`, `cli.py` | register the producer, name it in `--only` |
| `deploy/user/bale-crier-disk.service`, `.timer` | the hourly check |
| `.env.example`, `README.md`, `AGENTS.md` | the settings and the fourth timer |
| `tests/test_disk_watcher.py`, additions to `test_config.py` and `test_run.py` | the tests |

## Behavior to verify

- Above the threshold with the latch armed → no bulletin, latch stays armed.
- Exactly at the threshold is not below it: quiet, latch stays armed.
- First crossing → one `alert` bulletin naming the free space and the threshold,
  latch set.
- Still below → quiet until `CRIER_DISK_REMINDER_HOURS` has passed; then one
  reminder whose wording says the disk is *still* low.
- Back above the threshold re-arms the latch, so the next crossing speaks again.
- A failed read → one bulletin saying the reading failed, at most once per
  reminder window, never claiming the disk is full; the latch is left untouched.
- The state survives the process (`data/watchers.json`, name `disk`, `armed` and
  an aware UTC `last_alert`); a corrupt or naive timestamp costs an extra
  bulletin, not a crash.
- The daily run leaves the watcher out; `--only disk` selects it alone.
- All three texts are Persian, with a real U+200C.

## Acceptance and what was checked

- `uv run pytest` green (304 tests).
- `systemd-analyze verify` exits 0 for both units.
- The timer is installed and enabled in the user manager with a next elapse.
- By hand, with the real chat: 4.5 GiB free and the 2 GiB default → a run sends
  nothing; with the threshold raised above the free space (6,000,000,000 bytes at
  the time, before the setting became GiB) → one alert really arrived, the second
  run was quiet (the latch), and a run at the default re-armed the latch because
  the space is above 2 GiB.
