# Prompt Search & Usage Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 25-entry recent-prompts `<select>` with a searchable list that highlights matches in context, and rank the default list by a new usage counter.

**Architecture:** `services/prompt_store.py` gains a `use_count` column (added to the live 85-row DB by a guarded `ALTER TABLE`), a `Row` NamedTuple carrying pre-computed highlight segments, and a `search()` that scans the whole table in Python — the table is under a megabyte, so no FTS5. A new `GET /prompts` route renders one shared partial that both the first page paint and every htmx keystroke request use, so there is a single code path for rendering the list instead of the current two that must agree with each other.

**Tech Stack:** Python 3 stdlib (`sqlite3`, `re`), Flask, Jinja2, htmx 2.0.4 (CDN), Tailwind (CDN), pytest, Selenium + headless Firefox.

**Spec:** `docs/superpowers/specs/2026-08-13-prompt-search-design.md`

## Global Constraints

- Two spaces for indentation. Never tabs.
- Round brackets around sub-expressions in conditions: `if ((a + b) > c)`, not `if (a + b > c)`.
- Curly braces on every `if`/`else` branch in JavaScript, including single-line ones.
- No new dependencies. Everything here is stdlib, or already in `requirements.txt`.
- `_MAX_LEN = 2000` and the strip-then-truncate behaviour in `add()` are unchanged.
- Snippet window: 60 characters before the first match, 140 after. No query: first 200 characters.
- Search result cap: 50.
- Pinned favourites: 3.
- `min_use_count` default: **1** — not 3. After migration every row sits at 1, so a higher default would render an empty list on day one.
- Never put user text through `|safe`. Highlighting is done by looping `(chunk, is_match)` pairs so Jinja autoescapes every chunk.
- Run tests with `source venv/bin/activate` first. Fast loop: `pytest -m "not browser" -q`. Full: `pytest -q`.
- Baseline before starting: **145 tests pass.**

---

## File Structure

| File | Responsibility |
|---|---|
| `services/prompt_store.py` | *Modify.* Schema + migration, `add()`, `recent()`, `top()`, `search()`, `_segments()`. All persistence and all matching logic. No Flask imports — stays directly unit-testable. |
| `config.py` | *Modify.* One new `Config` field, `prompt_min_use_count`. |
| `settings.toml`, `settings.example.toml` | *Modify.* New `[prompts]` section. |
| `translations.py` | *Modify.* Five new keys in `en` and `de`. |
| `templates/partials/prompt_results.html` | *Create.* The entire picker list: pinned block, result rows, edge states. Rendered by both `/` and `/prompts`. |
| `templates/index.html` | *Modify.* Picker moves out of the `<form>`, becomes a search input plus a results container. The ~40-line select-sync script is replaced by ~20 lines. |
| `app.py` | *Modify.* New `GET /prompts` route and a shared context helper. |
| `tests/test_prompt_store.py` | *Modify.* Existing assertions updated to `Row`; new tests for migration, counting, matching, snippets. |
| `tests/test_routes.py` | *Modify.* Existing `<select>` assertions move to the partial; new route tests. |
| `tests/test_dropdown_browser.py` | *Modify.* Eleven select-driven tests ported to the button list. |

Five tasks. Each ends green and committable.

---

## Task 1: Usage counter, migration, and the Row shape

Reshapes the store's return type and adds the counter. Nothing user-visible changes yet — `index.html` still renders a `<select>`, so this task must keep the existing template working by passing `Row` objects whose `.text` the template reads.

**Files:**
- Modify: `services/prompt_store.py`
- Modify: `app.py` (one line in `index()`)
- Modify: `templates/index.html:31-33` (option loop reads `p.text`)
- Test: `tests/test_prompt_store.py`, `tests/test_routes.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Row(NamedTuple)` with fields `text: str`, `use_count: int`, `segments: list[tuple[str, bool]]`
  - `add(text: str) -> None` (unchanged signature)
  - `recent(n: int = 25, min_count: int = 1) -> list[Row]`
  - `top(n: int = 3) -> list[Row]`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompt_store.py`:

```python
import sqlite3

from services import prompt_store


def test_legacy_two_column_db_gains_use_count_and_keeps_rows():
    """The live prompts.db predates use_count. CREATE TABLE IF NOT EXISTS is a
    no-op against it, so an explicit ALTER is the only thing that migrates it."""
    conn = sqlite3.connect(prompt_store._DB_PATH)
    conn.execute(
        "CREATE TABLE prompts (text TEXT PRIMARY KEY, used_at REAL NOT NULL)"
    )
    conn.execute("INSERT INTO prompts VALUES ('an old prompt', 1000.0)")
    conn.commit()
    conn.close()

    rows = prompt_store.recent()

    assert [row.text for row in rows] == ["an old prompt"]
    assert rows[0].use_count == 1


def test_readd_increments_use_count():
    prompt_store.add("a repeated prompt")
    prompt_store.add("a repeated prompt")
    prompt_store.add("a repeated prompt")

    rows = prompt_store.recent()

    assert len(rows) == 1
    assert rows[0].use_count == 3


def test_recent_honours_min_count():
    prompt_store.add("used once")
    prompt_store.add("used twice")
    prompt_store.add("used twice")

    assert [row.text for row in prompt_store.recent(min_count=2)] == ["used twice"]


def test_top_returns_most_used_first():
    prompt_store.add("rare")
    for _ in range(3):
        prompt_store.add("common")
    for _ in range(2):
        prompt_store.add("middling")

    assert [row.text for row in prompt_store.top(2)] == ["common", "middling"]


def test_top_is_empty_when_nothing_has_been_reused():
    """A table of all-ones has no favourites. Showing three arbitrary rows
    under a 'favourites' heading would be a lie."""
    prompt_store.add("one")
    prompt_store.add("two")

    assert prompt_store.top() == []
```

Then update the six existing tests in the same file to the `Row` shape:

```python
def test_add_then_recent_returns_prompt():
    prompt_store.add("a sunset over water")
    assert [r.text for r in prompt_store.recent()] == ["a sunset over water"]


def test_readd_moves_to_front_without_duplicating():
    prompt_store.add("first")
    prompt_store.add("second")
    prompt_store.add("first")
    assert [r.text for r in prompt_store.recent()] == ["first", "second"]


def test_recent_is_newest_first_and_capped():
    for i in range(30):
        prompt_store.add(f"prompt {i}")
    result = prompt_store.recent(25)
    assert len(result) == 25
    assert result[0].text == "prompt 29"
    assert result[-1].text == "prompt 5"


def test_blank_prompts_are_ignored():
    prompt_store.add("")
    prompt_store.add("   ")
    assert prompt_store.recent() == []


def test_prompt_is_stripped_before_storing():
    prompt_store.add("  padded  ")
    assert [r.text for r in prompt_store.recent()] == ["padded"]


def test_long_prompt_is_truncated():
    prompt_store.add("x" * 5000)
    assert len(prompt_store.recent()[0].text) == prompt_store._MAX_LEN
```

`test_recent_on_empty_db_returns_empty_list` is unchanged — `[] == []` holds either way.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source venv/bin/activate && pytest tests/test_prompt_store.py -q
```

Expected: the five new tests fail with `AttributeError: 'str' object has no attribute 'text'` (or `TypeError` on the `min_count`/`top` calls), and the six rewritten ones fail the same way.

- [ ] **Step 3: Implement the store changes**

In `services/prompt_store.py`, add the import and the `Row` type at the top:

```python
import sqlite3
import threading
from contextlib import contextmanager
from time import time
from typing import NamedTuple


class Row(NamedTuple):
    """One prompt as the templates want it.

    `segments` is the snippet split into (chunk, is_match) pairs. The template
    wraps the matching chunks in <mark> and Jinja autoescapes every chunk, so
    no user text ever needs |safe.
    """
    text: str
    use_count: int
    segments: list[tuple[str, bool]]
```

Replace the body of `_db()` between the `with _lock:` and the `yield`:

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

Update the `_db()` docstring — it currently claims there is no migration path:

```python
    """Connect-per-call. Sidesteps sqlite3's thread-affinity rule entirely.

    CREATE TABLE IF NOT EXISTS covers a fresh database; it is a no-op against
    an existing one, so a schema change needs its own guarded ALTER below.
    The PRAGMA is an in-memory schema read, cheap enough to run per call.
    """
```

Update the upsert in `add()`:

```python
        conn.execute(
            "INSERT INTO prompts (text, used_at, use_count) VALUES (?, ?, 1) "
            "ON CONFLICT(text) DO UPDATE SET "
            "  used_at   = excluded.used_at,"
            "  use_count = use_count + 1",
            (text, time()),
        )
```

Replace `recent()` and add `top()`:

```python
def recent(n: int = 25, min_count: int = 1) -> list[Row]:
    """The n most recently used prompts, newest first.

    min_count trims the default list only; search deliberately ignores it,
    because the prompt you search for is usually the one you used once.
    """
    with _db() as conn:
        rows = conn.execute(
            "SELECT text, use_count FROM prompts "
            "WHERE use_count >= ? ORDER BY used_at DESC LIMIT ?",
            (min_count, n),
        ).fetchall()
    return [Row(text, use_count, _segments(text, [])) for text, use_count in rows]


def top(n: int = 3) -> list[Row]:
    """The n most-used prompts, for pinning above the recent list.

    use_count > 1 keeps a never-reused table from producing three arbitrary
    'favourites'.
    """
    with _db() as conn:
        rows = conn.execute(
            "SELECT text, use_count FROM prompts "
            "WHERE use_count > 1 ORDER BY use_count DESC, used_at DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [Row(text, use_count, _segments(text, [])) for text, use_count in rows]
```

Add a placeholder `_segments` — Task 2 replaces it with the real one:

```python
_SNIPPET_BEFORE = 60
_SNIPPET_AFTER = 140


def _segments(text: str, patterns: list) -> list[tuple[str, bool]]:
    """Split text into (chunk, is_match) pairs for the template to render."""
    window = text[:(_SNIPPET_BEFORE + _SNIPPET_AFTER)]
    out = [(window, False)]
    if (len(text) > len(window)):
        out.append(("…", False))
    return out
```

- [ ] **Step 4: Keep the existing template and route working**

`templates/index.html:31-33` currently reads the bare string. Change the loop body to read `.text`:

```jinja
        {% for p in prompts %}
        <option value="{{ p.text }}">{{ p.text[:40] | replace('\n', ' ') }}{% if p.text | length > 40 %}…{% endif %}</option>
        {% endfor %}
```

In `app.py`, `index()` keeps passing `prompts=prompt_store.recent(25)` — the signature is unchanged. No edit needed there yet.

Fix the two assertions in `tests/test_routes.py` that compare strings against the now-`Row` list. At `:355`:

```python
    assert "a lighthouse at dusk" in [r.text for r in prompt_store.recent()]
```

and at `:370`:

```python
    assert "rejected but memorable" in [r.text for r in prompt_store.recent()]
```

These fail silently rather than loudly — `"str" in [Row(...)]` is `False`, not a `TypeError` — so they are easy to miss.

- [ ] **Step 5: Run the full suite**

```bash
source venv/bin/activate && pytest -q
```

Expected: 150 passed (145 baseline + 5 new). If browser tests skip for lack of network, that is fine — note the skip count.

- [ ] **Step 6: Commit**

```bash
git add services/prompt_store.py templates/index.html tests/test_prompt_store.py tests/test_routes.py
git commit -m "feat: count prompt reuse and return prompts as Row objects"
```

---

## Task 2: Search and snippet highlighting

Pure store-layer work. Still nothing user-visible.

**Files:**
- Modify: `services/prompt_store.py`
- Test: `tests/test_prompt_store.py`

**Interfaces:**
- Consumes: `Row`, `_db()`, `_SNIPPET_BEFORE`, `_SNIPPET_AFTER` from Task 1.
- Produces:
  - `search(query: str, limit: int = 50) -> tuple[list[Row], bool, int]` — rows (at most `limit`), `regex_error`, total matches
  - `_compile(query: str) -> tuple[list | None, bool]` — patterns (`None` for an empty or invalid query), `regex_error`
  - `_segments(text: str, patterns: list) -> list[tuple[str, bool]]` — real implementation replacing Task 1's placeholder

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompt_store.py`:

```python
def test_keyword_search_is_order_independent():
    prompt_store.add("a red bikini on a beach")
    prompt_store.add("a blue dress in a field")

    for query in ("red bikini", "bikini red"):
        rows, regex_error, total = prompt_store.search(query)
        assert [r.text for r in rows] == ["a red bikini on a beach"]
        assert regex_error is False
        assert total == 1


def test_keyword_search_is_case_insensitive_including_umlauts():
    """The specific reason matching is not done in SQL: SQLite's LIKE and
    lower() are ASCII-only, so 'Größe' would not be found by 'größe'."""
    prompt_store.add("Die Größe des Bildes")

    rows, _, _ = prompt_store.search("größe")

    assert [r.text for r in rows] == ["Die Größe des Bildes"]


def test_sql_wildcards_in_a_query_are_literal():
    """The other reason: with LIKE, '%' and '_' would match anything."""
    prompt_store.add("50% off everything")
    prompt_store.add("nothing relevant here")

    rows, _, _ = prompt_store.search("%")

    assert [r.text for r in rows] == ["50% off everything"]


def test_slash_delimited_query_is_a_regex():
    prompt_store.add("a bathing suit")
    prompt_store.add("a winter coat")

    rows, regex_error, _ = prompt_store.search("/bikini|bathing/")

    assert [r.text for r in rows] == ["a bathing suit"]
    assert regex_error is False


def test_invalid_regex_reports_an_error_instead_of_raising():
    prompt_store.add("anything")

    rows, regex_error, total = prompt_store.search("/foo(/")

    assert rows == []
    assert regex_error is True
    assert total == 0


def test_half_typed_slash_is_a_keyword_not_a_broken_regex():
    """Typing '/foo' on the way to '/foo/' must not flash an error."""
    prompt_store.add("the /foo directory")
    prompt_store.add("unrelated")

    for query in ("/foo", "//"):
        rows, regex_error, _ = prompt_store.search(query)
        assert regex_error is False, f"{query!r} should be a keyword"

    rows, _, _ = prompt_store.search("/foo")
    assert [r.text for r in rows] == ["the /foo directory"]


def test_empty_query_matches_nothing_rather_than_everything():
    """all([]) is True, so a missing guard would return the whole table."""
    prompt_store.add("something")

    assert prompt_store.search("") == ([], False, 0)
    assert prompt_store.search("   ") == ([], False, 0)


def test_search_ignores_min_use_count():
    """A prompt used once is exactly what search exists to find."""
    prompt_store.add("used exactly once")

    rows, _, _ = prompt_store.search("exactly")

    assert [r.text for r in rows] == ["used exactly once"]


def test_search_caps_rows_but_reports_the_true_total():
    for i in range(10):
        prompt_store.add(f"candidate number {i}")

    rows, _, total = prompt_store.search("candidate", limit=3)

    assert len(rows) == 3
    assert total == 10


def test_snippet_is_centred_on_a_late_match():
    text = ("x" * 800) + "NEEDLE" + ("y" * 200)
    prompt_store.add(text)

    rows, _, _ = prompt_store.search("needle")
    segments = rows[0].segments

    assert ("NEEDLE", True) in segments
    assert segments[0] == ("…", False), "text before the window must be elided"
    assert segments[-1] == ("…", False), "text after the window must be elided"

    body = "".join(chunk for chunk, _ in segments if (chunk != "…"))
    assert body == text[(800 - 60):(806 + 140)]


def test_every_match_in_the_window_is_marked_not_just_the_first():
    prompt_store.add("cat and cat and cat")

    rows, _, _ = prompt_store.search("cat")

    assert [chunk for chunk, is_match in rows[0].segments if is_match] == ["cat"] * 3


def test_anchored_regex_still_produces_highlighting():
    """Regression guard: spans must come from the full text, not the window.
    A window cut short of the end does not satisfy '$', so computing spans on
    the slice would match the row and then highlight nothing."""
    text = ("x" * 900) + " the end"
    prompt_store.add(text)

    rows, _, _ = prompt_store.search("/end$/")

    assert len(rows) == 1
    assert any(is_match for _, is_match in rows[0].segments), (
        "row matched but nothing was highlighted"
    )


def test_a_pattern_that_can_match_empty_produces_no_empty_marks():
    prompt_store.add("aaa bbb")

    rows, _, _ = prompt_store.search("/a*/")

    assert all((chunk != "") for chunk, _ in rows[0].segments)


def test_overlapping_terms_never_duplicate_text():
    prompt_store.add("a lighthouse at dusk")

    rows, _, _ = prompt_store.search("lighthouse light house")

    body = "".join(chunk for chunk, _ in rows[0].segments if (chunk != "…"))
    assert body == "a lighthouse at dusk"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source venv/bin/activate && pytest tests/test_prompt_store.py -q
```

Expected: 14 failures, `AttributeError: module 'services.prompt_store' has no attribute 'search'`.

- [ ] **Step 3: Implement `_compile`**

Add `import re` at the top of `services/prompt_store.py`, then:

```python
def _compile(query: str) -> tuple[list | None, bool]:
    """Turn a query into a list of patterns that must ALL match.

    Both modes compile to the same thing on purpose: the patterns are used
    for filtering AND for locating spans to highlight, so a single mechanism
    is the only way the two can never disagree. The obvious keyword shortcut
    -- `term in text.lower()` -- would disagree, because lowering can change
    length (`"İ".lower()` is two code points) and the offsets no longer map
    back onto the original text.

    Returns (patterns, regex_error). patterns is None when there is nothing
    to search for.
    """
    q = query.strip()
    if (not q):
        return (None, False)
    # Regex mode needs BOTH delimiters and a non-empty body. A half-typed
    # "/foo" is a keyword, so typing towards "/foo/" never flashes an error,
    # and "//" is a literal rather than an empty pattern matching everything.
    if ((len(q) >= 3) and q.startswith("/") and q.endswith("/")):
        try:
            return ([re.compile(q[1:-1], re.IGNORECASE)], False)
        except re.error:
            return (None, True)
    # re.escape keeps % and _ literal for free, and re.IGNORECASE is
    # Unicode-aware, so "größe" finds "Größe".
    return ([re.compile(re.escape(term), re.IGNORECASE) for term in q.split()], False)
```

- [ ] **Step 4: Implement `_segments`**

Replace Task 1's placeholder:

```python
def _segments(text: str, patterns: list) -> list[tuple[str, bool]]:
    """Split a snippet of text into (chunk, is_match) pairs.

    Spans are found over the FULL text, never over the window: '$' and
    lookbehind do not survive slicing, so a window-local search would match
    the row and then highlight nothing.
    """
    spans = []
    for rx in patterns:
        for match in rx.finditer(text):
            # Zero-length matches (/a*/, /^/) would render as empty <mark>s.
            if (match.end() > match.start()):
                spans.append((match.start(), match.end()))
    spans.sort()

    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if (merged and (start <= merged[-1][1])):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    if (merged):
        window_start = max(0, (merged[0][0] - _SNIPPET_BEFORE))
        window_end = min(len(text), (merged[0][1] + _SNIPPET_AFTER))
    else:
        window_start = 0
        window_end = min(len(text), (_SNIPPET_BEFORE + _SNIPPET_AFTER))

    out: list[tuple[str, bool]] = []
    if (window_start > 0):
        out.append(("…", False))

    cursor = window_start
    for start, end in merged:
        start = max(start, window_start)
        end = min(end, window_end)
        if (start >= end):
            continue
        if (start > cursor):
            out.append((text[cursor:start], False))
        out.append((text[start:end], True))
        cursor = end
    if (cursor < window_end):
        out.append((text[cursor:window_end], False))

    if (window_end < len(text)):
        out.append(("…", False))
    return out
```

- [ ] **Step 5: Implement `search`**

```python
def search(query: str, limit: int = 50) -> tuple[list[Row], bool, int]:
    """Prompts matching query, newest first.

    Returns (rows, regex_error, total). total counts every match, not just
    the ones returned, so the caller can say "showing 50 of 130" -- which is
    why the scan does not stop early at limit.

    Deliberately has no min_count parameter: search sees every prompt.

    Accepted risk: `re` cannot be interrupted, so a valid but catastrophic
    pattern like /(a+)+$/ can spin. Single-user tool on a trusted LAN; the
    only person who can type it is the one it would inconvenience.
    """
    patterns, regex_error = _compile(query)
    if (patterns is None):
        return ([], regex_error, 0)

    with _db() as conn:
        rows = conn.execute(
            "SELECT text, use_count FROM prompts ORDER BY used_at DESC"
        ).fetchall()

    out = []
    total = 0
    for text, use_count in rows:
        if (not all((rx.search(text)) for rx in patterns)):
            continue
        total += 1
        if (len(out) < limit):
            out.append(Row(text, use_count, _segments(text, patterns)))
    return (out, False, total)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
source venv/bin/activate && pytest tests/test_prompt_store.py -q
```

Expected: PASS. Then the full suite:

```bash
source venv/bin/activate && pytest -q
```

Expected: 164 passed (150 + 14 new).

- [ ] **Step 7: Commit**

```bash
git add services/prompt_store.py tests/test_prompt_store.py
git commit -m "feat: add keyword and regex search over stored prompts"
```

---

## Task 3: Config, the shared partial, and the /prompts route

Everything server-side. At the end of this task the picker renders from the partial and the search endpoint works — verifiable with `curl` — but `index.html` still shows the old `<select>`.

**Files:**
- Modify: `config.py`
- Modify: `settings.toml`, `settings.example.toml`
- Modify: `translations.py`
- Create: `templates/partials/prompt_results.html`
- Modify: `app.py`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `Row`, `recent(n, min_count)`, `top(n)`, `search(query, limit)` from Tasks 1–2.
- Produces:
  - `Config.prompt_min_use_count: int = 1`
  - `GET /prompts?q=<query>` → rendered `partials/prompt_results.html`
  - Partial context: `pinned: list[Row]`, `prompts: list[Row]`, `query: str`, `regex_error: bool`, `total: int`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_routes.py`:

```python
def test_prompts_endpoint_lists_recent_when_no_query(client):
    from services import prompt_store

    prompt_store.add("a previously used prompt")
    resp = client.get("/prompts")

    assert resp.status_code == 200
    assert b"a previously used prompt" in resp.data


def test_prompts_endpoint_filters_by_query(client):
    from services import prompt_store

    prompt_store.add("a red bikini")
    prompt_store.add("a blue coat")

    body = client.get("/prompts?q=bikini").data.decode()

    assert "a red bikini" in body
    assert "a blue coat" not in body


def test_prompts_endpoint_marks_the_match(client):
    from services import prompt_store

    prompt_store.add("a red bikini")

    body = client.get("/prompts?q=bikini").data.decode()

    assert "<mark" in body
    assert ">bikini</mark>" in body


def test_prompts_endpoint_reports_an_invalid_pattern_without_erroring(client):
    from services import prompt_store

    prompt_store.add("anything")
    resp = client.get("/prompts?q=/foo(/")

    assert resp.status_code == 200
    assert b"anything" not in resp.data


def test_blank_query_is_treated_as_no_query_not_as_no_matches(client):
    """htmx sends ?q=%20 for a lone space. A raw truthiness check would
    render 'no matches' for what the user sees as an empty box."""
    from services import prompt_store

    prompt_store.add("a previously used prompt")

    assert b"a previously used prompt" in client.get("/prompts?q=%20").data


def test_pinned_prompts_are_not_repeated_in_the_recent_list(client):
    from services import prompt_store

    prompt_store.add("a favourite")
    prompt_store.add("a favourite")
    prompt_store.add("a one-off")

    body = client.get("/prompts").data.decode()

    assert body.count("a favourite") == 1


def test_prompt_html_is_escaped_in_the_results(client):
    from services import prompt_store

    prompt_store.add('<script>alert("x")</script>')

    body = client.get("/prompts").data.decode()

    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body


def test_index_renders_the_results_partial_on_first_paint(client):
    from services import prompt_store

    prompt_store.add("a previously used prompt")
    body = client.get("/").data.decode()

    assert 'id="prompt-results"' in body
    assert "a previously used prompt" in body


def test_picker_is_absent_on_an_empty_database(client):
    body = client.get("/").data.decode()

    assert "data-prompt" not in body
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source venv/bin/activate && pytest tests/test_routes.py -q
```

Expected: 404s on `/prompts`, and assertion failures on the index tests.

- [ ] **Step 3: Add the config field**

In `config.py`, add to the `Config` dataclass **after `sd_model`** — it is the first field with a default, so it must come last:

```python
    sd_model: str                 # InvokeAI model name
    prompt_min_use_count: int = 1  # default-list cutoff; search ignores it
```

The default is load-bearing: ten places construct `Config(...)` by hand (`tests/conftest.py`, `tests/test_routes.py`, four each in `tests/test_image_gen.py` and `tests/test_video_gen.py`). A required field would `TypeError` in the `cfg` fixture before any new test could run.

In `from_settings()`, after `sd_model = ...`:

```python
            prompt_min_use_count = int(_get("prompts", "min_use_count", 1)),
```

Append to both `settings.toml` and `settings.example.toml`:

```toml
[prompts]
# Prompts used fewer than this many times are hidden from the default list.
# Search always sees every prompt regardless of this value. Every row starts
# at 1 after the use_count migration, so raise this only once counts have grown.
min_use_count = 1
```

- [ ] **Step 4: Add the translation keys**

In `translations.py`, add to the `en` dict:

```python
        "prompt_search": "Search prompts",
        "prompt_favourites": "Most used",
        "prompt_no_matches": "No prompts match.",
        "prompt_bad_regex": "Invalid regular expression.",
        "prompt_showing": "Showing {shown} of {total} matches.",
```

and to the `de` dict:

```python
        "prompt_search": "Prompts durchsuchen",
        "prompt_favourites": "Am häufigsten genutzt",
        "prompt_no_matches": "Keine passenden Prompts.",
        "prompt_bad_regex": "Ungültiger regulärer Ausdruck.",
        "prompt_showing": "Zeige {shown} von {total} Treffern.",
```

- [ ] **Step 5: Create the partial**

`templates/partials/prompt_results.html`:

```jinja
{#- The picker list. Rendered both by GET / (first paint) and GET /prompts
    (every keystroke), so there is exactly one way the list can look.

    Highlighting loops (chunk, is_match) pairs rather than interpolating a
    pre-built HTML string: Jinja autoescapes every chunk, so a prompt full of
    <script> renders as text and no |safe is needed anywhere. -#}

{%- macro prompt_row(row) -%}
<button type="button"
        data-prompt="{{ row.text }}"
        title="{{ row.text }}"
        class="w-full text-left flex gap-3 items-start px-3 py-2 rounded-lg
               hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-400">
  <span class="flex-1 text-sm text-gray-700 break-words">
    {%- for chunk, is_match in row.segments -%}
      {%- if is_match -%}<mark class="bg-yellow-200 rounded-sm">{{ chunk }}</mark>
      {%- else -%}{{ chunk }}{%- endif -%}
    {%- endfor -%}
  </span>
  <span class="text-xs text-gray-400 shrink-0 pt-0.5">&times;{{ row.use_count }}</span>
</button>
{%- endmacro -%}

{% if regex_error %}
  <p class="text-sm text-amber-700 px-3 py-2">{{ t.prompt_bad_regex }}</p>
{% elif (query and (not prompts)) %}
  <p class="text-sm text-gray-500 px-3 py-2">{{ t.prompt_no_matches }}</p>
{% else %}
  {% if pinned %}
    <p class="text-xs uppercase tracking-wide text-gray-400 px-3 pt-1">
      {{ t.prompt_favourites }}
    </p>
    <div class="divide-y divide-gray-100">
      {% for row in pinned %}{{ prompt_row(row) }}{% endfor %}
    </div>
    <hr class="my-1 border-gray-200">
  {% endif %}
  <div class="divide-y divide-gray-100">
    {% for row in prompts %}{{ prompt_row(row) }}{% endfor %}
  </div>
  {% if (prompts | length) < total %}
    <p class="text-xs text-gray-400 px-3 py-1">
      {{ t.prompt_showing.format(shown=(prompts | length), total=total) }}
    </p>
  {% endif %}
{% endif %}
```

An empty database with no query falls into the `else` branch with both lists empty, so the whole thing renders as blank markup — the picker collapses, matching today's hidden-wrapper behaviour.

- [ ] **Step 6: Add the route and the shared context helper**

In `app.py`, inside `create_app`, just above `index()`:

```python
    def _picker_context(query: str = ""):
        """Context for partials/prompt_results.html.

        Pinned rows also satisfy recent()'s WHERE clause, so they are filtered
        out here -- the store has no cross-query knowledge. This can leave 22
        rows instead of 25; that is fine, do not over-fetch to compensate.
        """
        if (query):
            rows, regex_error, total = prompt_store.search(query)
            return {"pinned": [], "prompts": rows, "query": query,
                    "regex_error": regex_error, "total": total}
        pinned = prompt_store.top(3)
        seen = {row.text for row in pinned}
        prompts = [row for row in prompt_store.recent(25, cfg.prompt_min_use_count)
                   if (row.text not in seen)]
        return {"pinned": pinned, "prompts": prompts, "query": "",
                "regex_error": False, "total": len(prompts)}
```

In `index()`, replace `prompts=prompt_store.recent(25),` with:

```python
            **_picker_context(),
```

And add the route after `index()`:

```python
    @app.get("/prompts")
    def prompts():
        # Strip here, not only inside search(): htmx sends ?q=%20 for a lone
        # space, which is truthy but means "no query".
        query = request.args.get("q", "").strip()
        return render_template("partials/prompt_results.html", t=t(),
                               **_picker_context(query))
```

- [ ] **Step 7: Keep the old select rendering**

`templates/index.html` still loops `prompts`, which is now a list of `Row` after Task 1 — it already reads `p.text`, so it keeps working. Add the results container so `test_index_renders_the_results_partial_on_first_paint` passes; Task 4 removes the select around it. Directly after the closing `</select>`:

```jinja
      <div id="prompt-results">
        {% include "partials/prompt_results.html" %}
      </div>
```

- [ ] **Step 8: Run the tests**

```bash
source venv/bin/activate && pytest -q
```

Expected: 173 passed (164 + 9 new). If `test_index_history_wrapper_visible_when_populated` or `test_index_history_wrapper_hidden_when_empty` now fail because the wrapper is no longer the only signal, leave them — Task 4 rewrites them. If they pass, leave them alone too.

- [ ] **Step 9: Commit**

```bash
git add config.py settings.toml settings.example.toml translations.py \
        templates/partials/prompt_results.html templates/index.html app.py \
        tests/test_routes.py
git commit -m "feat: add /prompts search endpoint and shared results partial"
```

---

## Task 4: Replace the dropdown with the search UI

**Files:**
- Modify: `templates/index.html:22-118`
- Modify: `tests/test_routes.py`

**Interfaces:**
- Consumes: `GET /prompts`, `partials/prompt_results.html`, `id="prompt-results"` from Task 3.
- Produces: `id="prompt-search"` (the input), `button[data-prompt]` (the rows) — both used by Task 5's browser tests.

- [ ] **Step 1: Update the route tests that assert on `<select>` markup**

In `tests/test_routes.py`, rewrite the wrapper tests against the new markup. Replace `test_index_history_wrapper_hidden_when_empty` and `test_index_history_wrapper_visible_when_populated` with:

```python
def test_index_shows_the_search_box(client):
    body = client.get("/").data.decode()

    assert 'id="prompt-search"' in body
    assert 'name="q"' in body


def test_index_lists_a_stored_prompt_as_a_button(client):
    from services import prompt_store

    prompt_store.add("a previously used prompt")
    body = client.get("/").data.decode()

    assert 'data-prompt="a previously used prompt"' in body
    assert "<select" not in body or 'id="prompt-history"' not in body
```

Five more tests in the file assert on `<select>` markup and must be rewritten against the partial. Named individually so none is quietly dropped:

- `test_index_shows_history_select_when_populated` (`:411`) → assert on `data-prompt` instead of `<option value=`.
- `test_index_trims_long_history_labels` (`:426`) → the 40-char label trim is gone; assert instead that a 1000-char prompt renders a snippet shorter than the full text while `data-prompt` still carries all 1000 characters.
- `test_index_escapes_history_entries` (`:440`) and `test_index_escapes_quote_in_history_entry` (`:449`) → keep the same hostile inputs, assert `&lt;script&gt;` and `&quot;` appear and the raw forms do not. These are the XSS guards; they matter more now that there is markup inside each row.
- `test_index_history_label_flattens_newlines` (`:457`) → newline flattening is now CSS, not string munging. Assert the `data-prompt` attribute round-trips `"line one\nline two"` intact.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source venv/bin/activate && pytest tests/test_routes.py -q
```

Expected: FAIL, `'id="prompt-search"' not in body`.

- [ ] **Step 3: Replace the picker markup**

In `templates/index.html`, cut the entire `<!-- Recent prompts -->` block (the `div#prompt-history-wrap` with its `<select>`, plus the `div#prompt-results` added in Task 3) out of the `<form>` and put it **above** the `<form ...>` opening tag, immediately after the Advanced-toggle div:

```jinja
  <!-- Prompt picker: outside the form on purpose. It is a picker, not form
       data -- left inside, the search term would be POSTed to /generate. -->
  <div>
    <label class="block text-sm font-medium text-gray-600 mb-1" for="prompt-search">
      {{ t.prompt_search }}
    </label>
    <input id="prompt-search" name="q" type="search"
           placeholder="{{ t.prompt_search }}"
           hx-get="/prompts"
           hx-trigger="keyup changed delay:250ms, search"
           hx-target="#prompt-results"
           class="w-full border border-gray-300 rounded-lg p-2 text-sm
                  focus:outline-none focus:ring-2 focus:ring-blue-400">
    <div id="prompt-results" class="mt-1 max-h-64 overflow-y-auto">
      {% include "partials/prompt_results.html" %}
    </div>
  </div>
```

`name="q"` is not decorative: htmx only sends an element's value when it has a `name`, so without it every request would arrive with an empty query and the search would silently do nothing. `type="search"` is what makes the `search` event in `hx-trigger` fire (the native clear button emits it).

- [ ] **Step 4: Replace the script**

Delete the entire existing `<script>` block that defines `label()`, the `change`/`blur` handlers and the select-sync `htmx:configRequest` handler (`templates/index.html`, the `(function() { ... })();` immediately after the prompt textarea). Replace it with:

```html
    <script>
      (function() {
        var results = document.getElementById('prompt-results');
        var search  = document.getElementById('prompt-search');
        var ta      = document.querySelector('textarea[name="prompt"]');

        // Delegated: htmx replaces the contents of #prompt-results on every
        // keystroke, so a listener bound to the buttons themselves would die
        // with the first swap.
        results.addEventListener('click', function(evt) {
          var btn = evt.target.closest('button[data-prompt]');
          if (!btn) {
            return;
          }
          ta.focus();
          ta.select();
          // execCommand is deprecated, but it is the only way to make a
          // programmatic edit undoable — measured in Firefox 140:
          // setRangeText leaves no undo entry, insertText does. Losing an
          // in-progress prompt to a stray pick should be recoverable.
          document.execCommand('insertText', false, btn.dataset.prompt);
        });

        // Keep the list current: the form submits via htmx, so the page never
        // reloads and the server-rendered list would go stale. Clearing first
        // is deliberate — refreshing with a stale query would render results
        // for that query, which need not contain the prompt just submitted.
        document.querySelector('form[hx-post]').addEventListener('htmx:configRequest', function() {
          search.value = '';
          htmx.trigger(search, 'search');
        });
      })();
    </script>
```

- [ ] **Step 5: Run the tests**

```bash
source venv/bin/activate && pytest -m "not browser" -q
```

Expected: PASS. Browser tests are expected to fail at this point — Task 5 ports them.

- [ ] **Step 6: Look at it in a browser**

```bash
source venv/bin/activate && python app.py
```

Open the app, confirm: the list renders on load, typing narrows it with matches highlighted, `/bikini|bathing/` works, `/foo(/` shows the invalid-pattern message, clicking a row fills the textarea, and Ctrl+Z restores what was there before.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html tests/test_routes.py
git commit -m "feat: replace the prompt dropdown with a search box and result list"
```

---

## Task 5: Port the browser tests

Eleven of the twelve Selenium tests target `#prompt-history`. `test_dummy_backend_renders_a_decodable_512x512_png` touches neither the select nor the wrapper and is left alone.

**Files:**
- Modify: `tests/test_dropdown_browser.py`

**Interfaces:**
- Consumes: `id="prompt-search"`, `id="prompt-results"`, `button[data-prompt]` from Task 4.
- Produces: nothing.

- [ ] **Step 1: Update the module docstring and helpers**

The file's opening docstring says "prompt-history dropdown". Change the first paragraph to:

```python
"""Browser tests for the prompt picker in templates/index.html.

The JS there has no other coverage: pytest alone cannot see the native undo
stack, delegated click handling across htmx swaps, or whether the list
refreshes after a submit. These drive a real headless Firefox against the
real app.
"""
```

Keep the rest of the docstring (selenium/geckodriver/Playwright notes) verbatim.

Replace the ID constants:

```python
_RESULTS_ID = "prompt-results"
_SEARCH_ID = "prompt-search"
```

Replace `_values` and `_labels`:

```python
def _values(driver):
    """The full prompt text of every rendered row."""
    rows = driver.find_elements(By.CSS_SELECTOR, f"#{_RESULTS_ID} button[data-prompt]")
    return [row.get_attribute("data-prompt") for row in rows]


def _search(driver, query):
    box = driver.find_element(By.ID, _SEARCH_ID)
    box.clear()
    box.send_keys(query)
    return box


def _pick(driver, text):
    driver.find_element(
        By.CSS_SELECTOR, f"#{_RESULTS_ID} button[data-prompt='{text}']"
    ).click()
```

`_pick` builds an attribute selector with a quoted string, so it cannot be used for prompts containing a single quote — the hostile-input test below picks by index instead.

Remove the now-unused `Select` import from the selenium imports. Leave `Keys` and `WebDriverWait` — both are still used.

- [ ] **Step 2: Port the tests**

Rewrite these five, which keep their intent exactly:

```python
def test_picker_is_empty_on_a_fresh_install(page):
    assert _values(page) == []


def test_list_appears_after_first_submit_without_a_reload(page):
    _submit(page, _LONG)

    assert _values(page) == [_LONG]
    assert _js_errors(page) == []


def test_second_prompt_goes_to_the_top(page):
    _submit(page, "an older prompt")
    _submit(page, _LONG)

    assert _values(page)[0] == _LONG


def test_resubmitting_moves_to_top_without_duplicating(page):
    _submit(page, "an older prompt")
    _submit(page, _LONG)
    _submit(page, "an older prompt")

    values = _values(page)
    assert values[0] == "an older prompt"
    assert values.count("an older prompt") == 1


def test_picking_fills_the_textarea_with_the_full_text_not_the_snippet(page):
    _submit(page, _LONG)
    _textarea(page).clear()

    _pick(page, _LONG)

    assert _textarea(page).get_attribute("value") == _LONG
    assert _js_errors(page) == []
```

The three freshness tests above are the only coverage of the new
clear-and-refresh path, which is the one genuinely new piece of JavaScript in
this feature. `_submit` already waits on `_values`, so it exercises the refresh
implicitly — if the `htmx.trigger` is wrong, `_submit` times out.

Keep `test_picking_moves_focus_to_the_textarea` but drop its second assertion about `selectedIndex` — a button has no sticky selection to reset:

```python
def test_picking_moves_focus_to_the_textarea(page):
    """ta.focus() is what puts the replacement on the native undo stack."""
    _submit(page, _LONG)
    _textarea(page).clear()

    _pick(page, _LONG)

    assert page.execute_script(
        "return document.activeElement === document.querySelector('textarea[name=prompt]')"
    )
```

Keep the undo test — this is the important one, and the reason `insertText` survives:

```python
def test_undo_after_picking_restores_typed_text(page):
    _submit(page, _LONG)
    field = _textarea(page)
    field.clear()
    field.send_keys("something I was in the middle of writing")

    _pick(page, _LONG)
    assert _textarea(page).get_attribute("value") == _LONG

    _textarea(page).send_keys(Keys.CONTROL, "z")

    assert _textarea(page).get_attribute("value") == "something I was in the middle of writing", (
        "insertText did not land on the native undo stack — picking a prompt "
        "destroys in-progress text irrecoverably"
    )
```

Port the hostile-input test, picking by position because the text contains a double quote:

```python
def test_quotes_and_angle_brackets_survive_a_round_trip(page):
    hostile = 'a " onmouseover="alert(1)" <script>x</script> prompt'
    _submit(page, hostile)
    _textarea(page).clear()

    page.find_element(By.CSS_SELECTOR, f"#{_RESULTS_ID} button[data-prompt]").click()

    assert _textarea(page).get_attribute("value") == hostile
    assert page.find_elements(By.CSS_SELECTOR, f"#{_RESULTS_ID} [onmouseover]") == []
    assert page.execute_script("return document.querySelectorAll('script').length") \
        == page.execute_script("return window.__scriptCount")
```

Port the multiline test — the snippet is flattened by CSS, not by JS, so it now
only needs to assert the value round-trips:

```python
def test_multiline_prompt_survives_a_round_trip(page):
    multiline = "line one\nline two"
    _submit(page, multiline)
    _textarea(page).clear()

    _pick(page, multiline)

    assert _textarea(page).get_attribute("value") == multiline
```

Add one new test for the feature itself:

```python
def test_typing_in_the_search_box_narrows_the_list(page):
    _submit(page, "a red bikini on a beach")
    _submit(page, "a blue coat in the snow")

    _search(page, "bikini")
    WebDriverWait(page, 5).until(lambda d: _values(d) == ["a red bikini on a beach"])

    assert _js_errors(page) == []
```

Delete these two outright — they test select-specific behaviour with no analogue on a button list. Both are named here so the deletion is a recorded decision, not an oversight:

- `test_selecting_the_same_entry_twice_still_fills` — a button has no `selectedIndex` to reset, so re-picking always works.
- `test_arrowing_a_closed_select_reaches_only_the_most_recent_entry` — there is no closed select to arrow through.

- [ ] **Step 3: Run the browser tests**

```bash
source venv/bin/activate && pytest tests/test_dropdown_browser.py -q
```

Expected: PASS, or a clean skip if headless Firefox or the htmx CDN is unavailable. A skip is not a pass — if they skip, say so explicitly rather than reporting the task as verified.

- [ ] **Step 4: Run the full suite**

```bash
source venv/bin/activate && pytest -q
```

Expected: all green, roughly 172 tests (173 from Task 3, minus the two deleted select tests, plus the new search test).

- [ ] **Step 5: Commit**

```bash
git add tests/test_dropdown_browser.py
git commit -m "test: port the browser tests from the select to the search list"
```

---

## Verification

After Task 5, before calling this done:

- [ ] `source venv/bin/activate && pytest -q` — all pass, and state the browser-test skip count if any skipped.
- [ ] `git status` — no stray files. `prompts.db` must be **unmodified**: the autouse `_isolated_cwd` fixture chdirs every test into `tmp_path`, so a modified `prompts.db` means test isolation broke.
- [ ] Open the real app against the real 85-row `prompts.db` and confirm the migration ran: every row shows `×1` and the favourites block is empty until something is reused.
- [ ] Search for a word you know is buried mid-prompt and confirm the snippet is centred on it, not the boilerplate prefix. This is the whole point of the feature.
