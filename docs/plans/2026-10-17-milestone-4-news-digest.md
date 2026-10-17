# Milestone 4 — the news digest

**Goal:** once a day, the bot reads a Google News feed, drops what the owner does not want to
read, hands the rest to the LLM to pick the most important and write one short Persian line
for each, and sends that as one bulletin — on a timer of its own.

**Architecture:** `news/` is three small modules behind one producer. `feed.py` fetches the
Google News RSS and parses it into `Story` objects; `select.py` holds everything that turns
stories into a message — the hard filter, the seen set, the newest-first order, the prompt,
the answer's parse and the message text; `producer.py` is the `NewsProducer` the run loop
already knows how to ask, keeping its seen set in the watcher memory the credit watcher
already uses. Nothing on the existing path changes: the run loop, the sender and the history
are untouched.

**Tech Stack:** unchanged — Python ≥ 3.11 (the venv is a uv-managed 3.14.7), `uv`, pydantic v2
+ `pydantic-settings`, `requests`, pytest, type hints. No new dependency: the fetch is one
`requests.get`, the parse is the standard library's `xml.etree.ElementTree`, and the LLM call
is the `llm.py` that milestone 3 already built.

**Spec:** `docs/specs/2026-10-17-news-digest-design.md` (the digest's own design, settled
2026-10-17). The main design's "Milestones" section names this as milestone 4.

**Status:** built, 2026-10-17 — the four tasks are done and `uv run pytest` is green; the live
checks in the Acceptance Criteria are run by hand.

## Global Constraints

- Every setting comes from the environment with the `CRIER_` prefix.
- Code, comments and docs are English; every string that reaches the owner is Persian, with a
  real U+200C in every half-space word. **The prefix `نا` is written connected**
  (`ناموفق`, `نامعتبر`); `می`, `ها`, `تر`/`ترین` and `بی` take the half-space.
- **A failed feed read is never "there was no news"** — the rule the credit watcher already
  follows. A feed that cannot be read speaks; a feed that was read with nothing left in it
  says nothing.
- **Bale is reached from `bale_crier/bale.py` only.**
- **The history stays "what the owner read"**, and nothing else. The seen set is the
  producer's own memory in `CRIER_WATCHERS_STATE_PATH`, never a history line.
- **The seen set lives under the name `news`** in that file, holding the guids of the stories
  the digest carried, newest last, capped at `SEEN_LIMIT` (500).
- **One LLM call per bulletin.**
- **The model answers with indices, never links**, so a model that invents a link is
  impossible rather than merely unlikely; the code maps an index back to the real story.
- **An out-of-range index, a line that does not parse, or an answer with no usable line at all
  is a model failure** → the raw-headline bulletin. This is the spec's sentence read
  literally: any such line fails the whole answer rather than being dropped.
- **The producer owns its timer** (`own_timer = True`), so the daily note run leaves it out and
  the two cannot race over one seen set.
- The bot reports and does not advise: no buying suggestion, no "nearly out" colour, in any
  bulletin. Asserted on a forbidden word list rather than trusted to the eye.
- Defaults: the feed URL is the owner's query (written out in Task 1), `CRIER_NEWS_MAX_ITEMS` is 5,
  `CRIER_NEWS_BLOCKLIST` empty means the built-in default. `CANDIDATE_LIMIT` is 60,
  `SEEN_LIMIT` is 500, HTTP timeout 30s.

### Verified external facts (probed live, 2026-10-17)

- `GET https://news.google.com/rss/search?q=<the owner's query>` answers **`302`** to a
  locale-normalised form (the same URL plus `&hl=en-US&gl=US&ceid=US:en`), which `requests`
  follows by default to a **`200 application/xml; charset=utf-8`**. Verified with the
  project's own `requests` and its default user agent: 200, 71,885 bytes, **54 items**. The
  spec measured 53 earlier the same day; the count moves with the news, so nothing may depend
  on it.
- The document is `<rss><channel>` with `<item>` children carrying `title`, `link`,
  `guid` (attribute `isPermaLink="false"`), `pubDate` and `source` (an element whose text is
  the outlet's name and whose `url` attribute is its home page).
- **Every one of the 54 titles ends with `" - " + the item's own `<source>` text`** (measured:
  0 exceptions), so the suffix strip uses that text, not the hostname.
- **Two of the 54 carry a URL as their `<source>` text** (`https://tech-insider.org/`,
  `https://streamlinefeed.co.ke/`), which is why a URL-shaped source is shown by its hostname.
- `<item><link>` is a Google redirect (`https://news.google.com/rss/articles/…`), never the
  publisher's URL. The server never resolves it — that is only the owner tapping it in Bale.
- A day's feed is noisy and repeats itself: today's reply carries a California legislative
  item, and one release covered by several outlets under different guids.
- **The 54-item reply is saved verbatim as `tests/fixtures/news_feed.xml`**, so the parser is
  tested against the real shape rather than one invented for the test.

## Acceptance Criteria

The milestone is done when all of these hold:

1. `uv run pytest` is green.
2. `uv run python -m bale_crier --only news` puts one real Persian digest in the owner's Bale
   chat, and `data/history.jsonl` gains a line with `kind:"news"`, `ok:true`, and a `text`
   equal to what was actually sent.
3. The **very next** `--only news` run sends nothing, because every story it carried is in the
   seen set and the feed's `when:1d` window has not refilled it. With `data/watchers.json`
   deleted between the two runs, the second run sends the same stories again — which is what
   shows the seen set, and not the feed, is what made the difference.
4. With `CRIER_NEWS_FEED_URL` pointed at an unreachable URL, one run sends one short Persian
   bulletin naming the short error code, and it does not say there was no news.
5. With a deliberately wrong LLM key, one run sends the raw English headlines of the newest
   `CRIER_NEWS_MAX_ITEMS` survivors, each with its source and link, plus the Persian line
   naming the failure and its code.
6. `systemd-analyze verify` exits 0 for the two new units, and the news timer shows a next
   elapse once enabled.
7. The daily run (`uv run python -m bale_crier`, no `--only`) still sends exactly one note and
   no digest.

Criterion 3 is the one that matters by hand: it is the only check that the seen set — the
digest's only memory — works against the real feed.

## Prerequisite the owner must supply

Nothing new. The LLM key is inherited from `CRIER_AVALAI_API_KEY`, which is already set, and
the feed is public and needs no key. Tightening `CRIER_NEWS_FEED_URL` and
`CRIER_NEWS_BLOCKLIST` is the owner's to do later, once the first digests show what gets
through.

## Files

| file | responsibility |
| --- | --- |
| `bale_crier/news/__init__.py` | package marker |
| `bale_crier/news/feed.py` | the Google News RSS fetch and parse, into `Story` objects |
| `bale_crier/news/select.py` | the hard filter, the seen set, the order, the prompt, the answer's parse, the message text |
| `bale_crier/news/producer.py` | `NewsProducer`: fetch, filter, ask, render, one bulletin |
| `bale_crier/models.py` | add `Story` |
| `bale_crier/config.py` | the three news settings |
| `bale_crier/run.py` | register the news producer; `KNOWN_PRODUCERS` gains `news` |
| `bale_crier/cli.py` | `news` in `--only`'s choices, and the missing-key line |
| `deploy/user/bale-crier-news.service`, `deploy/user/bale-crier-news.timer` | the daily digest |
| `tests/fixtures/news_feed.xml` | the real 54-item feed reply, verbatim |
| `tests/test_news_feed.py`, `tests/test_news_select.py`, `tests/test_news_producer.py`, and additions to `tests/test_config.py`, `tests/test_run.py` | the tests |
| `.env.example`, `README.md`, `AGENTS.md`, `docs/specs/2026-10-17-bale-crier-design.md`, `docs/specs/2026-10-17-news-digest-design.md` | the claims this milestone makes stale |

## Tasks

### Task 1: The feed, parsed into stories

**Files:**
- Create: `bale_crier/news/__init__.py`, `bale_crier/news/feed.py`, `tests/test_news_feed.py`
- Modify: `bale_crier/models.py` (add `Story`)
- Use as-is: `tests/fixtures/news_feed.xml` (already captured)

**Interfaces:**
- `Story` — pydantic model: `title: str`, `source: str`, `link: str`, `guid: str`,
  `published: datetime | None`. `published` is always timezone-aware UTC when it is present.
- `FeedRead` — `typing.NamedTuple`: `stories: list[Story] | None`, `error: str`. `stories` is
  `None` exactly when the read failed; `error` is then a short code-like string and never
  empty (`"transport error"`, `"HTTP 403"`, `"unparsable feed"`). On success `error` is `""`.
- `FeedReader` — `Callable[..., FeedRead]`, the alias a caller stubs in tests.
- `DEFAULT_QUERY: str` — the owner's query of 2026-10-17, verbatim and human-readable, and the one
  place it is written in the code:
  `"new features" OR "now available" OR "update" OR "version" AI (tool OR model) -investment -funding -startup -stocks when:1d`
- `DEFAULT_FEED_URL: str` — `https://news.google.com/rss/search?q=` + `quote(DEFAULT_QUERY)`,
  the one place the feed's URL shape is written.
- `fetch_feed(*, url: str, timeout: int = 30) -> FeedRead`
- `parse_feed(document: bytes | str) -> list[Story]` — the pure parse. It **raises `ValueError`**
  when the document is not a readable feed; a readable feed with no items gives `[]`.

**Behavior to verify:**
- `parse_feed` on the real fixture gives 54 stories, each with a non-empty `title`, `link` and
  `guid`.
- The first item's `title` has its `" - <source>"` suffix stripped and `source` is the outlet's
  name.
- An item whose `<source>` text is a URL gives `source` as the bare hostname
  (`tech-insider.org` — no scheme, no path, no trailing slash), and the title still loses its
  suffix.
- `published` is parsed from `pubDate` into a timezone-aware UTC datetime.
- An item whose `pubDate` cannot be parsed gives `published is None` and is still a story.
- An item with no `<guid>` uses its `link` as the `guid`.
- An item with no `title`, and an item with no `link`, are skipped; the other items still
  parse.
- A title that does not end with `" - " + source` is left whole.
- An item with no `<source>` element gives `source == ""` and keeps its title whole.
- A readable `<rss><channel>` with no items gives `[]`.
- A document that is not XML raises `ValueError`.
- An XML document whose root is not `<rss>` (an HTML page, say) raises `ValueError` — a 200
  that is not the feed must not read as a quiet day.
- An `<rss>` with no `<channel>` raises `ValueError`.
- `fetch_feed` with a stubbed `requests.get` answering 200 with the fixture bytes gives the
  same 54 stories, and passes the given URL and timeout through to `requests.get`.
- `fetch_feed` with a non-200 gives `stories is None` and an error carrying the status.
- `fetch_feed` with a 200 whose body is not a readable feed gives `stories is None` and a
  non-empty error.
- `fetch_feed` with a transport exception gives `stories is None` and a non-empty error, and
  raises nothing.
- `DEFAULT_FEED_URL` starts with `https://news.google.com/rss/search?q=` and its decoded `q`
  equals `DEFAULT_QUERY`.

**Notes:**
- The parse reads no settings and touches no network; only `fetch_feed` does.
- `pubDate` is read with `email.utils.parsedate_to_datetime`, not `datetime.fromisoformat`: the
  feed's `"Sat, 17 Oct 2026 09:43:16 GMT"` is RFC 822 and `fromisoformat` cannot read it.
- `fetch_feed` is the boundary and returns a value; `parse_feed` is a pure function and raises,
  because a caller that cannot tell "unreadable" from "empty" is the bug this whole shape
  exists to prevent. `xml.etree.ElementTree.ParseError` is a `SyntaxError` and **not** a
  `ValueError`, so `parse_feed` must catch it and re-raise its own `ValueError` — otherwise the
  "a 200 that is not a feed" case escapes as an unhandled exception.
- The tests locate the fixture as `Path(__file__).parent / "fixtures" / "news_feed.xml"`: every
  test module in this project `chdir`s into a tmp directory, so a path relative to the working
  directory would not resolve.
- The suffix strip uses the item's own `<source>` text verbatim, because that is what Google
  appends; the *displayed* source is the hostname when that text is a URL. Two different
  strings on purpose.
- `published` is normalised to UTC through `history.as_utc`, the same rule the rest of the
  project applies to a naive timestamp.
- Nothing resolves the Google redirect link. The story carries it as it came, and the owner's
  browser resolves it.

### Task 2: Selection, the prompt, and the message

**Files:**
- Create: `bale_crier/news/select.py`, `tests/test_news_select.py`

**Interfaces:**
- `DEFAULT_BLOCKLIST: tuple[str, ...]` = `("funding", "raises", "valuation", "lawsuit", "ban",
  "regulation", "layoffs", "earnings")`.
- `blocklist_words(raw: str) -> tuple[str, ...]` — the setting split on commas, trimmed, empty
  entries dropped; when nothing is left, `DEFAULT_BLOCKLIST`.
- `blocked(title: str, words: Sequence[str]) -> bool` — case-insensitive, on word boundaries.
- `newest_first(stories: Sequence[Story]) -> list[Story]` — by `published` descending, a story
  with no `published` last, equal dates keeping input order.
- `SEEN_LIMIT = 500`, `CANDIDATE_LIMIT = 60`.
- `seen_guids(state: Mapping[str, object]) -> list[str]` — the memory blob's `"seen"` list,
  oldest first; anything that is not a list of strings reads as empty.
- `remember(seen: Sequence[str], guids: Iterable[str]) -> list[str]` — the guids appended,
  capped at the newest `SEEN_LIMIT`.
- `Chosen` — `typing.NamedTuple`: `line: str`, `story: Story`.
- `build_messages(stories: Sequence[Story], *, max_items: int) -> list[dict[str, str]]`
- `parse_answer(text: str, stories: Sequence[Story], *, max_items: int) -> list[Chosen] | None`
  — `None` is a model failure.
- `HEADER: str` = `"چند خبر تازه از دنیای هوش مصنوعی:"`
- `digest_text(chosen: Sequence[Chosen]) -> str`
- `raw_text(stories: Sequence[Story], error: str) -> str`
- `feed_failure_text(error: str) -> str`

**Behavior to verify:**
- `blocked` is case-insensitive (`Funding` is blocked), matches on word boundaries (`ban` does
  not fire on `urban`, `raises` not on `praises`), and does not fire on a word it was not
  given.
- `blocklist_words("")` and `blocklist_words(" , ")` give `DEFAULT_BLOCKLIST`;
  `blocklist_words("ban, funding")` gives `("ban", "funding")`.
- `newest_first` orders by `published` descending, puts a story with no `published` last, and
  keeps input order for equal dates.
- `seen_guids` on `{}`, on a blob whose `"seen"` is not a list, and on a list holding a
  non-string, gives `[]` / only the strings; on a real blob it gives the guids oldest first.
- `remember` appends, and past `SEEN_LIMIT` keeps the newest 500: the oldest is gone and the
  newest is last.
- `build_messages` numbers the candidates from 1, carries each title and its source, states the
  answer format `<index>|<Persian sentence>`, and states the cap `max_items`.
- `parse_answer` maps `"2|متن دوم"` to the second story with the line `متن دوم`, and the
  message's order is the answer's order.
- A `|` inside the Persian line survives, because each line splits on its **first** `|`.
- An index out of range gives `None`.
- A line with no `|` gives `None`.
- An answer of blank lines only gives `None`.
- A repeated index gives that story once, first occurrence winning.
- More usable lines than `max_items` are truncated to `max_items`, keeping the answer's order.
- `digest_text` begins with `HEADER`, numbers the items with Persian digits, gives each item
  its Persian line, its source and its link, and separates items with one blank line.
- `digest_text` on a story whose `source` is empty renders the item without a `منبع:` prefix.
- `raw_text` carries each English title with its source and link and ends with one Persian line
  naming the error code; the text holds at least one Persian character and at least one U+200C.
- `feed_failure_text` names the code, says the read failed, holds at least one Persian
  character and one U+200C, and makes no claim that there was no news — assert a positive
  sentence *and* a forbidden list (`خبری نبود`, `خبری نیست`, `هیچ خبری`).
- No message text carries buying advice — assert on `بخر`, `خرید`, `توصیه`.

**Notes:**
- The prompt's requirements, which the implementer writes out in Persian: keep each headline's
  meaning and add no claim of the model's own; write fresh Persian with a correct U+200C in
  every half-space word and `نا` written connected; put the most important first; choose at
  most `max_items`; carry **one story per event** (this is the only place the several outlets
  covering one release are collapsed, since the seen set works by guid); answer with lines of
  exactly `<index>|<sentence>`, one per line, the index being the story's number in the list it
  was given, and nothing else — no preamble, no heading, no markdown, no quotes.
- **A repeated index is collapsed, first occurrence winning.** The spec does not name this
  case; recorded here as a dated ruling so the next reader sees it. A repeated index is
  unambiguously a slip — the prompt asks for one story per event — and the same story twice is
  noise the owner did not ask for. It is not a model failure: the answer is usable, and the
  spec's failure list names only an out-of-range index, an unparsable line, and no usable line.
- **The spec's failure list is read literally**: one bad line fails the whole answer rather
  than being dropped. That is the one place the digest prefers the English fallback over a
  partial digest, so it is called out here; if the owner would rather keep the good lines, this
  is the rule to change.
- The message text lives here rather than in the producer for the same reason the note's
  fallback lives in `reword.py`: the producer orchestrates, the module that shapes the content
  owns its words.
- `HEADER` is a constant with no date and no count (the owner's ruling, 2026-10-17).
- Persian digits come from translating the ASCII digits, so no number in a message is ever
  rendered in Latin digits.

### Task 3: The producer and the wiring

**Files:**
- Create: `bale_crier/news/producer.py`, `tests/test_news_producer.py`
- Modify: `bale_crier/config.py`, `bale_crier/run.py`, `bale_crier/cli.py`,
  `tests/test_config.py`, `tests/test_run.py`

**Interfaces:**
- `NewsProducer(settings: Settings, memory: WatcherMemory, *, complete: Llm = llm.complete,
  read: FeedReader = fetch_feed)` — `name = "news"`, `own_timer = True`,
  `produce(now: datetime) -> list[Bulletin]` returning zero or one bulletin with
  `kind="news"`, `note_id` and `list_name` left `None`.
- The memory blob it owns is `{"seen": [guid, …]}`, written through `memory.set("news", …)`.
- `produce` calls `read` with `url=settings.news_feed_url` and `timeout=settings.http_timeout`,
  and `complete` with `key=settings.open_ai_api_key`, `model=settings.open_ai_model`,
  `base_url=settings.open_ai_base_url` and `timeout=settings.http_timeout` — the same shape the
  note producer already uses.
- `Settings` gains `news_feed_url: str = DEFAULT_FEED_URL`,
  `news_max_items: int = Field(default=5, ge=1)`, `news_blocklist: str = ""`. The default is
  imported from `news/feed.py`, so the feed's URL shape has one home; `feed.py` imports no
  settings, so there is no cycle — **as long as `bale_crier/news/__init__.py` stays a bare
  marker**: a convenience re-export of `NewsProducer` there would make `config` → `news.feed`
  pull the producer in and create one.
- `build_producers` registers the news producer when `settings.open_ai_api_key` is set, exactly
  as the note producer is gated. It is not gated on the feed being reachable: the fetch is the
  producer's business at produce time.
- `KNOWN_PRODUCERS` gains `"news"`, so `--only news` is accepted.
- `cli.main` prints one Persian line to stderr when `--only news` was asked for and there is no
  LLM key, in the shape the note producer's line already has.

**Behavior to verify:**
- A failed feed read gives exactly one bulletin, whose text is the Persian failure line naming
  the code, and the model is never called.
- A feed whose every story is blocked gives no bulletin, no model call and no memory write.
- A feed whose every story is already in the seen set gives no bulletin and no model call.
- The candidates handed to the model are newest first and capped at `CANDIDATE_LIMIT`.
- The feed is read with the configured `news_feed_url` and `http_timeout`, and the model is
  called with the configured model, base URL and timeout — asserted against the stubs, so a
  configured timeout cannot be silently ignored in favour of the default.
- With a stub model answering `"1|متن یک"`, the bulletin's text is the digest of the first
  candidate carrying that line, and `kind == "news"`.
- A failed model call gives one bulletin carrying the English headlines of the newest
  `max_items` survivors and the Persian failure line with the call's code.
- An unparsable answer gives the same raw-headline bulletin, with the code `unparsable answer`.
- After a digest, the memory holds the guids that were carried, and a second `produce` on the
  same feed gives no bulletin.
- A story whose guid is already in the memory never reaches the model.
- The stories the failure bulletin carried are marked seen too.
- A feed-failure run and a no-survivors run write nothing to the memory file.
- `name == "news"` and `own_timer is True`.
- Without `--only`, the produced set is `["note"]` and not `"news"`; `--only news` selects the
  digest alone; the daily run's set is otherwise unchanged.
- Without an LLM key, no news producer is registered even under `--only news`.
- A news run writes one history line with `kind == "news"`, `ok is True`, and the text that was
  sent.
- `Settings(open_ai_api_key="k")` carries `news_max_items == 5`,
  `news_feed_url == DEFAULT_FEED_URL` and `news_blocklist == ""`.
- The three settings take their values from `CRIER_NEWS_FEED_URL`, `CRIER_NEWS_MAX_ITEMS` and
  `CRIER_NEWS_BLOCKLIST`.
- `CRIER_NEWS_MAX_ITEMS=0` is refused with a Persian `ConfigError` naming the variable.
- `main(["--only", "news"])` with no LLM key prints a Persian stderr line naming
  `CRIER_OPEN_AI_API_KEY`, exits 0, and raises no traceback.
- `main(["--only", "news"])` with a key prints no note warning about `lists`.

**Notes:**
- The producer holds the memory the way the credit watcher does and lets the run loop save it.
  A crash between the two costs a re-send, the safe direction; a failed Bale send still counts
  the story as seen, which costs nothing in practice because the feed's `when:1d` window means
  a story not sent today has fallen out of the feed by tomorrow.
- The feed-failure bulletin is a bulletin like any other and goes into the history: it is what
  the owner read.
- The `--only news` key warning is gated exactly as the credit watcher's is. Without `--only`
  the news producer is not part of the run at all, so a warning there would be a false alarm on
  a run that never asked for a digest.
- `produce` takes `now` for the `Producer` protocol's sake and does not need it: the seen set is
  keyed by guid, not by time. Say so in the docstring rather than dropping the parameter.
- `raw_text` adds no cap of its own: the producer slices the newest `max_items` survivors before
  calling it, because the cap is the settings' business and `raw_text` only renders what it is
  given.

### Task 4: The timer, the settings the owner sees, and the documents

**Files:**
- Create: `deploy/user/bale-crier-news.service`, `deploy/user/bale-crier-news.timer`
- Modify: `.env.example`, `README.md`, `AGENTS.md`,
  `docs/specs/2026-10-17-bale-crier-design.md`,
  `docs/specs/2026-10-17-news-digest-design.md`

**Behavior to verify:**
- `systemd-analyze verify` exits 0 for both new units.
- `bale-crier-news.service` is a `Type=oneshot` with the same `WorkingDirectory`, runs
  `--only news`, and has no `[Install]` section.
- `bale-crier-news.timer` is `OnCalendar=09:00` with `Persistent=true` and a
  `RandomizedDelaySec`, and installs under `timers.target`.
- `.env.example` lists `CRIER_NEWS_FEED_URL`, `CRIER_NEWS_MAX_ITEMS` and
  `CRIER_NEWS_BLOCKLIST`, and says the blocklist falls back to the built-in default when empty.
- `README.md`: the status line says milestone 4 is built; a "The news digest" section describes
  the feed, the hard filter, the seen set, both failure messages, `--only news` and the third
  timer; the structure block lists `news/` and `Story`; the deploy section names three timers.
- `AGENTS.md`: the status line no longer says news summaries come later; the vocabulary table
  gains `story`; the layout block lists `news/`; the deploy command enables the news timer.
- The design spec's "Milestones" marks milestone 4 as built, with a dated line; its `news/` line
  matches the modules as built; its Configuration table lists the three news settings; and its
  Data model list names `Story`.
- The news spec's "Still open" records 09:00 as the time that shipped and that the owner has not
  confirmed it, and its "Where it sits in the code" line names the message text's home.
- The news spec's Testing section says the fixture is the reply actually saved — 54 items — and
  names `tests/fixtures/news_feed.xml`. Its "The source" section's 53-item figure stays as the
  dated measurement it is, with a line saying the count moves day to day.
- No file still describes the digest as unbuilt.

**Notes:**
- The times are literal in the unit file, as everywhere in this project: systemd expands no
  environment variable in a unit, so a schedule setting would silently never fire.
- `RandomizedDelaySec=10m` matches the daily unit's spread; a daily timer has room for it.
- This is the sweep the project's rules require: a document describing the state before a change
  is worse than none, because the next session reads it first and acts on it.
- The live checks are the Acceptance Criteria, run by hand, and criterion 3 is the one to run:
  one digest arrives, then a second run in the same minute sends nothing.

## Amendments during implementation

Dated 2026-10-17, so a later reader sees the plan's current state rather than the state it was
written in.

- **An empty `CRIER_NEWS_FEED_URL` means the owner's query, not an empty URL.** Pydantic-settings
  reads a shipped `CRIER_NEWS_FEED_URL=` as `""` and does not fall back to the field default, so
  `.env.example` could not list the setting the way it lists every other one without breaking
  every fetch. A `model_validator` now fills the default when the value is blank — the same
  ruling the project already applies to an empty `CRIER_OPEN_AI_API_KEY` and to the empty
  blocklist — and `.env.example` ships the line empty and active, with a test pinning it.
- **`digest_text` keeps the link when a story's source is empty.** The first implementation
  dropped the whole `منبع:` line, which also dropped the link — the owner's only way to reach
  the story. It now renders the bare link instead. Google always sends a `<source>`, so this
  only shows on a shape change, which is exactly when losing the link would matter most.
- **The plan's "a second `produce` on the same feed gives no bulletin" holds only for a
  one-story feed.** With more than one survivor the second run legitimately offers the story the
  first run did not carry. The test uses a one-story feed for that case; the multi-story seen
  behaviour is covered by the failure-bulletin case, which marks its stories seen.
- **The note and news producers share one `open_ai_api_key` gate in `build_producers`**, rather
  than two identical `if` blocks back to back. No behaviour change; recorded because the plan
  described the news registration as its own condition.
- **The `--only news` CLI test needs one HTTP stub answering both shapes.** Bale and the LLM both
  post through `requests`, so the stub body carries `{"ok": …}` and `{"choices": …}` together.
  The plan did not mention it, and a stub answering only one shape fails for a reason that has
  nothing to do with the digest.
- **Milestone 3's plan still said `**Status:** not started.`** It is a present-tense claim about
  a milestone the project's own status line already called done, so it now reads `complete,
  2026-10-17`. The milestone 1–3 plans are otherwise left as the records of their own moment.

