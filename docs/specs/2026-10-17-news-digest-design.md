# bale-crier — the news digest (design)

Settled with the owner on 2026-10-17. This is the second design document. The first,
`2026-10-17-bale-crier-design.md`, covers the path end to end, the credit watcher and the
owner's lists; it points here for this subsystem.

## What it is

One message a day carrying a handful of AI-news stories: drawn from a Google News query,
selected and written in Persian by the LLM. The owner asked for it on 2026-10-17 — the news he
wants is AI trends, daily.

It is a **producer**, like the credit watcher and the note producer, so the run loop, the Bale
sender and the history are untouched.

It is **not** the news of `bale-news-digest`: that project reads Bale channels. This one reads a
web feed, which is a new capability in this repo. The owner ruled that nothing moves between the
two projects.

## Vocabulary

One new word, settled with the owner on 2026-10-17.

| word | what it is |
| --- | --- |
| `story` | one entry in the feed: a headline, its source and its link |

A `story` is not a `note`: a note is the owner's own text in `lists/`, a story is someone else's
headline. The message that carries the chosen stories is a `bulletin` — the word the project
already has, and the digest is one of them.

## The source

A Google News search, `https://news.google.com/rss/search?q=…`, whose query the owner owns and may
tighten whenever he likes. The default is the query he gave on 2026-10-17:

```
"new features" OR "now available" OR "update" OR "version" AI (tool OR model) -investment -funding -startup -stocks when:1d
```

Measured on 2026-10-17, so a later reader does not have to probe again:

- **The HTML search page is not fetchable from a server.** `https://news.google.com/search?q=…`
  answers `302` to `google.com/sorry` — Google's bot check. Scraping it is a dead end.
- **The RSS form works.** The same query on `/rss/search` answers `200`,
  `application/xml; charset=utf-8`, and carried **53 items** for one day — a figure that moves
  day to day with the news, so nothing depends on it. Each item has `title` (with the source
  name appended after `" - "`), `link`, `guid`, `pubDate` and `source`.
- **The item link is a Google redirect**, not the publisher's URL, and `requests` cannot resolve
  it: the page is a JavaScript shell, and a probe of Google's `batchexecute` endpoint came back
  with a null result. A real browser does resolve it — headless Chromium reached
  `https://tech-insider.org/codex-cli-0-163-ai-coding-agents-2026/` from the link. So the link
  works for the owner tapping it in Bale, which is all that is needed; the server never resolves
  it.
- **The feed is noisy and repeats itself.** The 53 items included a California legislative update
  and a Netflix story, and four different outlets carried the same DeepSeek release.

## One run, step by step

1. Fetch `CRIER_NEWS_FEED_URL` with `requests`, the project's `http_timeout`, and parse the XML
   with the standard library's `ElementTree`. A transport error, a non-200 or unparsable XML is a
   **feed failure** (below).
2. Turn each item into a `story`: `title`, `source`, `link`, `guid`, `published`. The title carries
   the source appended to it (`" - The Straits Times"`, sometimes `" - https://tech-insider.org/"`);
   it is stripped using that item's own `<source>`. A `<source>` that is a URL is shown by its
   hostname.
3. Drop the stories whose title matches the **hard filter**.
4. Drop the stories whose guid is already in the **seen set**.
5. If nothing is left, the run sends nothing: a day without news is not a failure.
6. Hand the survivors, newest first, to the LLM, capped at `CANDIDATE_LIMIT` (60). Each survivor is
   given to it as a number, its title and its source. It chooses the most important and writes one
   short Persian line for each.
7. Render one bulletin: a short Persian header, then each story as its Persian line, its source
   name and its Google News link.
8. Add the chosen stories' guids to the seen set.

## The hard filter and the model

Both, in that order — the owner's ruling of 2026-10-17.

**The hard filter** is a list of words; a story whose title contains one of them is dropped before
the model ever sees it. Matching is case-insensitive and on word boundaries, so `ban` does not fire
on `urban`. The list is the owner's: it comes from `CRIER_NEWS_BLOCKLIST` (comma-separated), and
when that is empty the built-in default is used —
`funding, raises, valuation, lawsuit, ban, regulation, layoffs, earnings, iPhone, iOS, Android,
gaming, laptop, laptops, GPU, driver, drivers, DLSS, Fitbit, Sims, Chrome, Netflix`. The first
eight are news types the owner does not want; the rest are consumer-device words, added after
measuring three days of feeds, where the phrasing `new features`/`now available`/`update` pulled
in phone, gaming and driver releases. Matching is whole-word, so the plural forms that the titles
used are listed too. A domain blocklist was
considered and dropped: the owner chose words only.

**The model** then reads the survivors and returns the digest. One call per bulletin, the project's
rule. It is told to keep each headline's meaning with no claim of its own added, to write fresh
Persian with a correct U+200C in every half-space word, to put the most important first, to choose
at most `CRIER_NEWS_MAX_ITEMS` (default 10), and to carry one story per event — which is the only
place the four outlets carrying one DeepSeek release are collapsed, since the seen set works by guid
and those are four guids.

**The model answers with indices, not links.** Each answer line is `<index>|<Persian sentence>`,
where `<index>` is the story's number in the list it was given. The code maps the index back to the
real title, source and link, so a model that invents a link is impossible rather than merely
unlikely. Parsing splits each line on its **first** `|`, so a `|` inside the Persian sentence is
harmless. An index out of range, a line that does not parse, or an answer with no usable line at all
is a **model failure** (below). The order of the answer is the order of the message, and the code
truncates it to `CRIER_NEWS_MAX_ITEMS` however many lines the model returned.

## What goes out

```
چند خبر تازه از دنیای هوش مصنوعی:

۱. <the model's Persian line>
منبع: The Straits Times — https://news.google.com/rss/articles/…

۲. …
```

Numbered with Persian digits, one blank line between stories. The header is one fixed Persian
sentence, a constant: no date and no count (owner's ruling, 2026-10-17).

## Failure behaviour

The owner's ruling of 2026-10-17. The second row is a deliberate exception to the project's rule
that every string reaching the owner is Persian.

| what happened | what goes to Bale |
| --- | --- |
| the feed could not be read | one short Persian bulletin saying so, naming the short error code |
| the model failed, or its answer did not parse | the raw headlines of the newest `CRIER_NEWS_MAX_ITEMS` survivors, in English, each with its source and link, plus one Persian line saying the rewording did not happen and the call's short error code |
| the feed was read but no story survived | nothing |

A failed read is never announced as "there was no news": *"I cannot tell" stays "I cannot tell"*,
the rule the credit watcher already follows. The digest runs three times a day, so a broken feed speaks at
most three times a day and needs no throttle of its own — the window the credit watcher has exists because
that watcher runs hourly.

## The seen set

The producer's own memory, in `CRIER_WATCHERS_STATE_PATH` under the name `news` — the store the
credit watcher's latch already uses. It holds the guids of the stories the digest carried, newest
last, capped at `SEEN_LIMIT` (500) so it cannot grow without bound.

It is deliberately not the history: the history records the text the owner read, and this is
bookkeeping about the feed. It is written by `produce`, and `run_once` saves the memory after the
sends — so a crash between the two costs a re-send, the safe direction, and a failed Bale send still
counts the story as seen. That last one costs nothing in practice: the feed's `when:1d` window means
a story that is not sent today has fallen out of the feed by tomorrow anyway.

## Scheduling

Its own timer, the credit watcher's shape: `bale-crier-news.service` — a `Type=oneshot` user
service running `--only news` — and `bale-crier-news.timer`, three times a day (09:00, 15:00
and 21:00, the owner's choice on 2026-10-29) at fixed times with a small `RandomizedDelaySec`. The producer sets `own_timer = True`, so the daily note run leaves it out and
the two cannot race over one seen set.

## Configuration

| variable | meaning |
| --- | --- |
| `CRIER_NEWS_FEED_URL` | the Google News RSS URL (default: the owner's query) |
| `CRIER_NEWS_MAX_ITEMS` | the most stories in one digest (default 10, at least 1) |
| `CRIER_NEWS_BLOCKLIST` | comma-separated filter words; empty means the built-in default |

The digest needs the LLM, so `CRIER_OPEN_AI_API_KEY` — or `CRIER_AVALAI_API_KEY`, which it inherits
— must be set. Without a key the producer is not registered, exactly as the note producer is not,
and the CLI says so in Persian. A *failing* call is the raw-headline case above; a *missing* key is
not, so the digest does not quietly start arriving in English every day.

A model call is allowed `CRIER_OPEN_AI_TIMEOUT` (default 120 seconds) rather than the project's
30-second `http_timeout`. Measured on 2026-10-17, this model takes **30 to 50 seconds** to answer
the digest prompt — with five candidates as well as with fifty-four, so the latency is the model's
own, not the prompt's size. At the HTTP timeout every call would be cut off and the digest would
arrive in English every day, which is the one outcome the failure rules exist to avoid.

## Where it sits in the code

```
bale_crier/news/feed.py       the Google News RSS fetch and parse, into Story objects
bale_crier/news/select.py     the hard filter, the seen set, the prompt, the answer's parse, the message text
bale_crier/news/producer.py   NewsProducer
bale_crier/models.py          + Story
deploy/user/bale-crier-news.service + .timer
tests/                        the digest's pytest
```

`run.py` gains the producer's registration and its name; `cli.py` gains it to `--only`'s choices and
to the missing-key warning. Nothing else on the existing path changes.

## Testing

pytest, all offline. A real feed response is saved as a fixture — the 54-item reply actually saved
at `tests/fixtures/news_feed.xml`, captured live on 2026-10-17 — so the parser is tested against
the real shape rather than one invented for the test.
Covered: parsing into stories (title, source, link, guid, published), the title's source suffix and
a URL-shaped source, the word-boundary filter, the seen-set filter and its cap, the candidate cap
and the newest-first order, the prompt, the index-and-sentence answer's parse including a bad index
and an unparsable line, the rendered message, both failure bulletins, the producer's wiring, and the
`--only news` CLI path. The live Bale send is verified by hand once, like every milestone.

## Still open

- The digest shipped once a day at 09:00; on 2026-10-29 the owner made it three times a day, at
  09:00, 15:00 and 21:00.
- The query is the owner's to tighten. The default is the one given on 2026-10-17; the first digests
  will show whether the filter words need adding.
- The feed is parsed with the standard library's `ElementTree`, which is not hardened against
  hostile XML. The feed is one known host, so nothing is done about it now; if the URL ever becomes
  free-form, it becomes a real concern.
