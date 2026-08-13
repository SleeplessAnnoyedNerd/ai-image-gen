# Prompt Search & Usage Ranking — Design

**Date:** 2026-08-13
**Status:** Approved

## Goal

The prompt history dropdown (`2026-08-11-prompt-history-design.md`) shipped as a
`<select>` of the 25 most recent prompts, labels trimmed to 40 characters. Two
problems showed up in real use:

1. **Search is missing.** LRU only surfaces what you used last. The prompt you
   actually grope for is the one you used once, months ago, and half-remember.
2. **The labels are useless.** The live DB holds 85 prompts averaging 411
   characters, and many share the same long boilerplate prefix
   (`"Use the uploaded reference image as the primary identity reference…"`).
   At 40 characters they are indistinguishable from one another.

This design replaces the `<select>` with a search box over a result list that
shows a snippet centred on the match, and adds a usage counter that pins
frequently-used prompts to the top of the default list.

## Non-goals

- **No FTS5.** Expected scale is low thousands of rows at ~400 chars — under a
  megabyte. A full scan in Python is sub-millisecond and avoids a virtual-table
  migration.
- **No pruning job.** Rows are still kept forever.
- **No fuzzy / stemming / ranking-by-relevance.** Substring and regex only.
- **`_DB_PATH` stays hardcoded.** `settings.toml` documents `[paths].data_dir`
  as covering `prompts.db`, but `prompt_store` uses a relative
  `"prompts.db"` instead. With the default `data_dir = "."` the two coincide.
  Pre-existing inconsistency, out of scope here.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Search location | Python, not SQL | Sidesteps `LIKE` escaping (`%`/`_` in a user query are wildcards) and SQLite's ASCII-only `LIKE`/`lower()`, which breaks case-insensitive matching on umlauts. Python's `str.lower()` is Unicode-aware. Makes regex nearly free. |
| Query syntax | Whitespace-split, all terms must match; `/…/` means regex | Order-independent AND is what "multiple keywords" means in practice. The slash convention costs zero UI. |
| Invalid regex | Empty result + inline hint | Never a 500 from a half-typed pattern. |
| Usage counter | `use_count` column, bumped in the existing `ON CONFLICT` | One clause, no second table. |
| What the counter drives | Default list only — **never** search | Excluding low-count prompts from search would defeat the feature: the one-off prompt is exactly what search is for. |
| Counting trigger | On generate (`add()`), not on picking from the list | Picking a prompt and then editing it into something else shouldn't inflate the original's score. |
| Default list order | Top 3 most-used pinned above, then recency | Favourites stay reachable without pushing "what I just ran" down the page. |
| Search result order | `used_at DESC` | Same instinct as the default list. `use_count` is displayed but does not reorder. |
| Snippet highlighting | Return `(text, is_match)` segments, mark in the template | Jinja autoescapes each segment, so no `|safe` ever touches user data. Building pre-highlighted HTML in Python would need manual escaping — that is where XSS bugs live. |
| Migration | `PRAGMA table_info` guard + `ALTER TABLE` | `CREATE TABLE IF NOT EXISTS` is a no-op against the existing 85-row table. |
| `min_use_count` default | `1`, not `3` | After migration every row sits at 1. A default of 3 gives an empty list on day one and keeps it empty until each prompt has been re-run three times. |
| Config plumbing | Read in `config.py`, passed into `recent()` as an argument | Keeps `prompt_store` dependency-free and directly unit-testable. |

## Components

### `services/prompt_store.py` (modified)

**Schema.** Inside the existing `_db()` context manager, after the current
`CREATE TABLE IF NOT EXISTS`:

```python
conn.execute(
    "CREATE TABLE IF NOT EXISTS prompts ("
    "  text TEXT PRIMARY KEY,"
    "  used_at REAL NOT NULL,"
    "  use_count INTEGER NOT NULL DEFAULT 1"
    ")"
)
cols = {row[1] for row in conn.execute("PRAGMA table_info(prompts)")}
if ("use_count" not in cols):
    conn.execute(
        "ALTER TABLE prompts ADD COLUMN use_count INTEGER NOT NULL DEFAULT 1"
    )
```

`CREATE TABLE` covers fresh databases; the guarded `ALTER` covers the existing
one. Existing rows start at `use_count = 1`. The `PRAGMA` runs per connection —
it is an in-memory schema read, not worth caching.

The `_db()` docstring currently states there is no migration path. Update it:
there is now exactly one, and the pattern for the next column is the same.

**`add(text)`** — one clause added to the existing upsert:

```sql
INSERT INTO prompts (text, used_at, use_count) VALUES (?, ?, 1)
ON CONFLICT(text) DO UPDATE SET
  used_at   = excluded.used_at,
  use_count = use_count + 1
```

Truncation to `_MAX_LEN` and the empty-string guard are unchanged.

**`recent(n=25, min_count=1) -> list[Row]`**

```sql
SELECT text, use_count FROM prompts
WHERE use_count >= ? ORDER BY used_at DESC LIMIT ?
```

**`top(n=3) -> list[Row]`**

```sql
SELECT text, use_count FROM prompts
WHERE use_count > 1 ORDER BY use_count DESC, used_at DESC LIMIT ?
```

The `use_count > 1` guard means a table of all-1s yields no favourites, so the
pinned block stays empty rather than showing three arbitrary rows.

**`search(query, limit=50) -> tuple[list[Row], bool, int]`**

Returns the matching rows (at most `limit`), a `regex_error` flag, and the
total number of matches found — the last so the partial can render
"showing 50 of N". Counting the full match set means the scan does not stop
early at `limit`; at the expected scale that is a full-table scan either way.

```python
q = query.strip()
if ((len(q) >= 2) and q.startswith("/") and q.endswith("/")):
    try:
        rx = re.compile(q[1:-1], re.IGNORECASE)
    except re.error:
        return ([], True)
    matches = lambda text: bool(rx.search(text))
else:
    terms = q.lower().split()
    matches = lambda text: all((term in text.lower()) for term in terms)
```

Then `SELECT text, use_count FROM prompts ORDER BY used_at DESC`, filter with
`matches`, count every hit but keep only the first `limit`. `min_count` is not
a parameter here — search sees everything, by design.

An empty query returns `([], False, 0)`; the caller uses `recent()`/`top()`
instead.

**Row shape.** A `NamedTuple` (`text: str`, `use_count: int`,
`segments: list[tuple[str, bool]]`) rather than a bare tuple, so the template
reads as `row.use_count` and adding a field later does not break unpacking.

**Snippet builder** — module-private `_segments(text, matches_spans)`:

- Window: 60 characters before the first match, 140 after — clamped to the
  string bounds, with `…` prepended/appended where the text was cut.
- Every term occurrence inside the window is marked, not just the first.
- No query (default list): first 200 characters, single unmarked segment, `…`
  if truncated.
- Output is a list of `(substring, is_match)` pairs covering the window
  contiguously — concatenating the substrings reproduces the window exactly.

For regex mode the spans come from `rx.finditer` over the window; for keyword
mode from a case-insensitive scan for each term. Overlapping spans are merged
so a character is never emitted twice.

### `config.py` (modified)

New field on `Config`:

```python
prompt_min_use_count: int  # default-list cutoff; search ignores it
```

populated with `int(_get("prompts", "min_use_count", 1))`.

### `settings.toml` / `settings.example.toml`

```toml
[prompts]
# Prompts used fewer than this many times are hidden from the default list.
# Search always sees every prompt regardless of this value.
min_use_count = 1
```

### `app.py` (modified)

`index()` stops passing `prompts=` and instead renders the shared partial's
context: `pinned=prompt_store.top(3)` and
`prompts=prompt_store.recent(25, cfg.prompt_min_use_count)`, with pinned texts
excluded from the recent list so nothing appears twice.

New route:

```python
@app.get("/prompts")
def prompts():
    q = request.args.get("q", "")
    ...
    return render_template("partials/prompt_results.html", ...)
```

- Empty `q` → same pinned + recent context as first paint.
- Non-empty `q` → `search()` results, `pinned` empty, `regex_error` forwarded.
- When results hit the cap, pass `total` so the partial can render
  "showing 50 of N".

`prompt_store.add(prompt)` in `/generate` is unchanged.

### `templates/partials/prompt_results.html` (new)

Renders, in order: the pinned block (only when non-empty and no query), the
result rows, and one of three empty/edge states — "no matches", "invalid
pattern", or "showing 50 of N".

Each row is a `<button type="button">` carrying the full prompt in `title` and
`data-prompt`, with the snippet rendered as:

```jinja
{% for chunk, is_match in row.segments %}{% if is_match %}<mark>{{ chunk }}</mark>{% else %}{{ chunk }}{% endif %}{% endfor %}
```

and `×{{ row.use_count }}` right-aligned.

### `templates/index.html` (modified)

The prompt-history block **moves outside the `<form>`**. It is a picker, not
form data; left inside, the search term would be POSTed to `/generate` as a
stray field.

It becomes a search `<input id="prompt-search">` with:

```html
hx-get="/prompts"
hx-trigger="keyup changed delay:250ms, search"
hx-target="#prompt-results"
```

followed by `<div id="prompt-results">` containing the server-rendered partial
for first paint.

The existing ~40-line client-side select-sync script is **deleted**. Clicking a
result row sets the textarea value from `data-prompt` and focuses it (one
delegated listener on `#prompt-results`, so it survives htmx swaps). After a
generation, `htmx.trigger('#prompt-search', 'search')` refreshes the list
through the same endpoint — less JavaScript than today, and one code path for
rendering the list instead of two.

`translations.py` gains keys for the search placeholder, the empty state, the
invalid-pattern hint and the truncation notice, in both `en` and `de`.

## Testing

TDD: each test is written and seen to fail before the code that satisfies it.

### `tests/test_prompt_store.py`

- A DB created with the **old** two-column schema gains `use_count` on next
  open, existing rows preserved and defaulted to 1.
- `add()` twice on the same text → one row, `use_count == 2`.
- Keyword search is order-independent (`"red bikini"` and `"bikini red"` match
  the same row) and case-insensitive.
- Case-insensitive match on a non-ASCII prompt (`"Größe"` found by `"größe"`) —
  the specific reason SQL `lower()` is not used.
- `%` and `_` in a query are literal, not wildcards.
- `/regex/` matches; an unbalanced pattern returns `regex_error = True` without
  raising.
- A prompt with `use_count = 1` is absent from `recent(min_count=3)` but present
  in `search()` results.
- `top()` returns an empty list when every row has `use_count == 1`.
- Snippet centres on the match: a match at character 800 of a 1000-char prompt
  produces a window containing it, leading `…`, and segments whose
  concatenation equals the window.
- All term occurrences within the window are marked, not just the first.
- `search()` honours `limit`.

### `tests/test_routes.py`

- `GET /prompts` with no query renders pinned + recent; pinned texts do not
  repeat in the recent list.
- `GET /prompts?q=…` renders matching rows and marks the match.
- `GET /prompts` with an unbalanced regex renders the invalid-pattern hint,
  HTTP 200.
- A stored prompt containing `<script>alert("x")</script>` renders escaped in
  the results partial (the existing `<select>` XSS tests move here).
- The index page renders the results partial on first paint.

Existing tests referencing the `<select>` markup are updated, not deleted.
