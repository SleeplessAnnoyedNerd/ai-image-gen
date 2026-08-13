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
- **`_DB_PATH` stays hardcoded.** `prompt_store` uses a relative
  `"prompts.db"` rather than resolving `[paths].data_dir`. It lands in the data
  dir anyway, because `app.py:20` chdirs into it at import time. The coupling is
  implicit and slightly fragile, but it works for every `data_dir` value, not
  just the default — and untangling it is not this design's job.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Search location | Python, not SQL | Sidesteps `LIKE` escaping (`%`/`_` in a user query are wildcards) and SQLite's ASCII-only `LIKE`/`lower()`, which breaks case-insensitive matching on umlauts. Python's `str.lower()` is Unicode-aware. Makes regex nearly free. |
| Query syntax | Whitespace-split, all terms must match; `/…/` means regex | Order-independent AND is what "multiple keywords" means in practice. The slash convention costs zero UI. |
| Matching primitive | `re` for both modes; keywords via `re.escape(term)` | One function for matching *and* for locating spans, so highlighting can never disagree with the filter. `str.lower()` would break both offset mapping and that agreement. |
| Invalid regex | Empty result + inline hint | Never a 500 from a half-typed pattern. |
| Catastrophic regex | Accepted, documented, not mitigated | `re` has no timeout. Single-user LAN tool; the only person who can hang it is the one typing. |
| Picking a prompt | `execCommand("insertText")`, as today | Preserves the native undo stack. Measured decision from the 2026-08-11 design; a plain `value =` assignment would silently regress it. |
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

Both modes compile to the *same* thing — a list of patterns, all of which must
match:

```python
q = query.strip()
if ((len(q) >= 3) and q.startswith("/") and q.endswith("/")):
    try:
        patterns = [re.compile(q[1:-1], re.IGNORECASE)]
    except re.error:
        return ([], True, 0)
else:
    patterns = [re.compile(re.escape(term), re.IGNORECASE) for term in q.split()]

matches = lambda text: all((rx.search(text)) for rx in patterns)
```

This unification matters for three reasons:

- **Keyword matching must not use `str.lower()`.** The obvious
  `term in text.lower()` disagrees with any offset computed on the lowercased
  copy, because lowering can change length (`"İ".lower()` is two code points),
  which would break the guarantee that snippet segments reproduce the source
  text exactly. `re.escape(term)` with `re.IGNORECASE` gives one function for
  both matching and span-finding, so they can never disagree.
- `re.escape` keeps `%` and `_` literal for free, same as before.
- The umlaut case still works: `re.IGNORECASE` matches `"Größe"` for `"größe"`.

**Delimiter rule.** Regex mode requires *both* a leading and a trailing slash,
and a non-empty body — hence `len(q) >= 3`. A half-typed `/foo` is treated as
the literal keyword `/foo`, which is the friendly behaviour while typing; `//`
is likewise a keyword, not an empty pattern that matches everything.
`regex_error` is therefore reachable only from a slash-delimited body that
fails to compile, such as `/foo(/`.

Then `SELECT text, use_count FROM prompts ORDER BY used_at DESC`, filter with
`matches`, count every hit but keep only the first `limit`. `min_count` is not
a parameter here — search sees everything, by design.

An empty query returns `([], False, 0)`; the caller uses `recent()`/`top()`
instead.

**Accepted risk: no regex timeout.** Python's `re` cannot be interrupted, so a
valid but catastrophic pattern (`/(a+)+$/`) against a 2000-character prompt can
spin far longer than a request should, and the endpoint fires on every typing
pause. This is accepted rather than mitigated, on the same grounds as the
existing `_MAX_LEN` cap reasoning: single-user tool on a trusted LAN, and the
only person who can type the pattern is the person it would inconvenience. A
thread-based timeout would be more machinery than the exposure justifies.
Noted here so the next reader knows it was considered, not missed.

**Row shape.** A `NamedTuple` (`text: str`, `use_count: int`,
`segments: list[tuple[str, bool]]`) rather than a bare tuple, so the template
reads as `row.use_count` and adding a field later does not break unpacking.

**Snippet builder** — module-private `_segments(text, patterns)`:

1. Collect spans by running `rx.finditer(text)` for every pattern **over the
   full text**, never over a window slice. Slicing first would break anchors
   and lookbehind: `/end$/` matches the full text but not a window cut short of
   the end, so the row would match and then render with nothing highlighted.
2. Drop zero-length spans (`/^/`, `/a*/` and friends match empty at every
   position; emitting them produces stray empty `<mark>` elements).
3. Sort and merge overlapping or touching spans, so a character is never
   emitted twice.
4. Window: 60 characters before the first surviving span, 140 after — clamped
   to the string bounds, with `…` prepended/appended where the text was cut.
5. Translate the merged full-text spans into window coordinates, clipping any
   that straddle an edge and discarding those entirely outside.
6. Emit a contiguous list of `(substring, is_match)` pairs covering the window.
   Concatenating the substrings reproduces the window exactly.

Every match inside the window is marked, not just the first. If there are no
spans at all (no query, or every span was zero-length), the window is the first
200 characters as a single unmarked segment, `…` if truncated.

### `config.py` (modified)

New field on `Config`, **with a default and placed last** in the dataclass:

```python
prompt_min_use_count: int = 1  # default-list cutoff; search ignores it
```

populated in `from_settings()` with `int(_get("prompts", "min_use_count", 1))`.

The default is not cosmetic: `tests/conftest.py` and
`tests/test_routes.py::test_index_shows_backend_select_with_multiple_backends`
both construct `Config(...)` by hand. A required field would break every route
test with a `TypeError` in the fixture before any new test could run. The field
genuinely has a sensible default everywhere, so giving it one is the honest fix
rather than editing two call sites.

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
`prompts=prompt_store.recent(25, cfg.prompt_min_use_count)`.

Pinned rows also satisfy `recent()`'s `WHERE`, so they must be filtered out in
the route — the store has no cross-query knowledge:

```python
seen = {row.text for row in pinned}
prompts = [row for row in prompts if (row.text not in seen)]
```

This can leave 22 rows instead of 25. That is fine and deliberate; do not
"fix" it by over-fetching.

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
result rows, and one of four empty/edge states:

| State | Rendering |
|---|---|
| Query set, no matches | "no matches" line |
| Query set, invalid regex | invalid-pattern hint |
| Query set, more matches than the cap | "showing 50 of N" line |
| No query, empty DB | nothing at all — the block collapses, preserving today's `test_index_history_wrapper_hidden_when_empty` behaviour |

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

It becomes a search input:

```html
<input id="prompt-search" name="q" type="search"
       hx-get="/prompts"
       hx-trigger="keyup changed delay:250ms, search"
       hx-target="#prompt-results">
```

followed by `<div id="prompt-results">` containing the server-rendered partial
for first paint.

`name="q"` is **required**, not decorative: htmx only includes an input's value
in the request when the element has a `name`, so without it every request would
arrive with an empty query and the feature would silently degrade to the
default list. `type="search"` is what makes the `search` event in `hx-trigger`
real (the native clear button fires it).

**Picking a row preserves the undo stack.** The delegated listener on
`#prompt-results` reuses the mechanism the current `change` handler uses, and
for the same measured reason recorded in `templates/index.html`: plain
`ta.value = …` destroys an in-progress prompt irrecoverably, and `setRangeText`
leaves no undo entry, while `insertText` does.

```javascript
ta.focus();
ta.select();
document.execCommand("insertText", false, btn.dataset.prompt);
```

A delegated listener survives htmx swapping the results list.

**Refresh after generation.** The existing ~40-line select-sync script is
**deleted**. In its place, the `htmx:configRequest` handler on the generate form
clears the search box and re-triggers the endpoint:

```javascript
search.value = "";
htmx.trigger(search, "search");
```

Clearing first is deliberate: refreshing while a stale query is still in the box
would render results for that old query, which need not contain the prompt just
generated. Net effect is less JavaScript than today, and one code path that
renders the list instead of two that must agree with each other.

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
- `/regex/` matches. `/foo(/` returns `regex_error = True` without raising.
  `/foo` (no closing slash) and `//` are treated as **keywords**, not as a
  regex, and never set `regex_error`.
- An anchored pattern matching near the end of a long prompt still produces
  marked segments — the regression guard for computing spans over the full text
  rather than the window.
- A pattern that can match empty (`/a*/`) produces no zero-length segments.
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
- An empty DB with no query renders no picker block at all (replaces
  `test_index_history_wrapper_hidden_when_empty`).

### `tests/test_dropdown_browser.py`

This file holds 12 Selenium tests written against `#prompt-history` and
`#prompt-history-wrap`. Every one of them breaks when the `<select>` is
removed, so the file is **ported, not deleted**:

- `test_undo_after_picking_restores_typed_text` is the important one and must
  keep passing unchanged in intent — it is the guard on the `insertText`
  decision above.
- Picking a row fills the textarea; a prompt containing quotes and one
  containing newlines round-trip correctly through `data-prompt`.
- The blur/`selectedIndex` reset tests have no analogue on a button list and
  are dropped — a button has no sticky selection to reset.
- Add one test that typing in the search box narrows the rendered list.

### Existing tests to update

`tests/test_prompt_store.py` currently asserts against plain strings
(`recent() == ["a sunset over water"]`, `len(recent()[0])`). With the `Row`
NamedTuple these become `[r.text for r in recent()]` and `len(recent()[0].text)`.
The `<select>`-markup assertions in `tests/test_routes.py` move to the results
partial. Nothing is deleted without a replacement.
