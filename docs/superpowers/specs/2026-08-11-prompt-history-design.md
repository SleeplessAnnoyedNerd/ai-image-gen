# Prompt History Dropdown — Design

**Date:** 2026-08-11
**Status:** Approved

## Goal

Let the user re-select one of their 25 most recently used prompts from a dropdown
above the prompt textarea, instead of retyping or copy-pasting.

All prompts ever submitted are stored server-side in SQLite. The dropdown shows
the 25 most recent, labels trimmed to 40 characters.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Storage | Server-side SQLite (`sqlite3`, stdlib) | App binds `0.0.0.0`, so phone and desktop share one history. `localStorage` would fragment it per browser. |
| Recording trigger | On submit, not on success | One line in `/generate` instead of threading through three job workers. A failed prompt is usually the one you want to retry. |
| Dedup / LRU | `text` is `PRIMARY KEY`; re-submit bumps `used_at` | The schema *is* the LRU. No id column, no dedup code. |
| Retention | Keep all rows forever, display 25 | A few thousand rows of text is nothing. No pruning job. |
| Selection behaviour | Replace textarea content | Appending risks accidental concatenation. |
| Freshness after htmx submit | Client-side prepend | Page never reloads. ~6 lines in the `htmx:configRequest` handler that already exists. No endpoint, no OOB partial. |
| DB path | Hardcoded `prompts.db` in project root | Consistent with the existing relative `.cache/` and `logs/` dirs. |
| Length cap | Truncate to 2000 chars in `add()` | App is LAN-exposed with an unbounded textarea; without a cap, one POST loop fills the disk. |

## Components

### `services/prompt_store.py` (new)

Stdlib only. Public surface is two functions.

```python
_DB_PATH  = "prompts.db"   # module-level so tests can monkeypatch it
_MAX_LEN  = 2000           # trust boundary: cap what a LAN client can store
_lock     = threading.Lock()

@contextmanager
def _db():
    # with _lock:
    #   sqlite3.connect(_DB_PATH)
    #   CREATE TABLE IF NOT EXISTS prompts (text TEXT PRIMARY KEY, used_at REAL NOT NULL)
    #   try: yield conn; conn.commit()
    #   finally: conn.close()

def add(text: str) -> None:
    # text = text.strip()[:_MAX_LEN]; return early if empty
    # INSERT INTO prompts (text, used_at) VALUES (?, ?)
    #   ON CONFLICT(text) DO UPDATE SET used_at = excluded.used_at

def recent(n: int = 25) -> list[str]:
    # SELECT text FROM prompts ORDER BY used_at DESC LIMIT ?
```

Notes:

- **Connect-per-call.** Sidesteps SQLite's thread-affinity rule entirely — no
  `check_same_thread=False`, no connection pool. `CREATE TABLE IF NOT EXISTS`
  runs inline on every connect, so there is no init step to call from `app.py`.
  At a handful of calls per minute the cost is irrelevant.
- **`_lock`.** Redundant with SQLite's own locking in the common case, but one
  line of insurance against `database is locked` when two submits race. It wraps
  the whole `_db()` body, connect through close.
- **Connection is closed in `finally`.** `with sqlite3.connect(...)` commits but
  does *not* close, so the context manager handles both explicitly.
- **`_MAX_LEN`.** The app binds `0.0.0.0` and the textarea is unbounded, so
  without a cap one POST loop from anywhere on the LAN fills the disk. Truncating
  (rather than rejecting) keeps long prompts present in history, just clipped.
  Server-side because that is the trust boundary; the matching `maxlength` on the
  textarea is UX, not enforcement.

### `app.py` (2 lines changed)

- `index()` passes `prompts=prompt_store.recent(25)` to the template.
- `/generate` calls `prompt_store.add(prompt)` after reading the form field and
  **before** the backend validation that can `abort(400)` — so a prompt is
  recorded even if the request is later rejected.

### `templates/index.html`

A `<select>` directly above the prompt textarea, wrapped in `{% if prompts %}`
so it is absent on a fresh install.

- First option is an empty-valued placeholder (`— recent prompts —`).
- Labels trimmed server-side: `{{ p[:40] | replace('\n', ' ') }}`, with a
  trailing `…` when `p | length > 40`. The full text lives in the option's
  `value`, so nothing is lost. Jinja autoescaping covers both the `value`
  attribute and the label text — no manual escaping needed.
- `change`: if the value is non-empty, copy it into the textarea. A separate
  `blur` listener resets the select back to the placeholder once focus leaves,
  so picking the same entry twice still works.
  - The reset **must not** live in the `change` handler. A focused-but-closed
    `<select>` fires `change` on every arrow-key press, so an immediate reset
    snaps the index back to 0 each time and makes entries 2-25 unreachable by
    keyboard. Caught in review; ruled by the repo owner on 2026-08-11.
- `maxlength="2000"` on the textarea, matching `prompt_store._MAX_LEN`.
- Client-side prepend hooks the **existing** `htmx:configRequest` listener in
  this file: on submit, remove any option whose value equals the prompt, insert
  a fresh option at index 1 (just after the placeholder), and trim the list back
  to 26 options.
  - **Guard first:** the select is absent until the first prompt is stored, so
    the handler must bail on a `null` lookup or it throws on the very submit
    that creates the history.
  - It also bails when `ta.value.trim()` is empty, matching `add()`'s no-op on
    whitespace-only input.
  - `ponytail:` if the server then rejects the request with `abort(400)`, the
    dropdown shows an entry that was never stored. Self-corrects on reload.
    Add an OOB refresh only if that ever actually bites.

### `translations.py`

One new key, `prompt_history`, in both `en` and `de`.

### `.gitignore`

Add `prompts.db`.

## Testing

**`tests/test_prompt_store.py` (new)** — monkeypatch `_DB_PATH` to a `tmp_path`
file:

- `add()` then `recent()` returns the prompt.
- Re-adding an existing prompt moves it to the front and does **not** duplicate it.
- `recent(n)` caps the result length and returns newest-first order.
- `add("")` and `add("   ")` are no-ops.
- A prompt longer than `_MAX_LEN` is stored truncated to `_MAX_LEN`.

**`tests/test_routes.py` (1 test added)** — POST a prompt to `/generate`, then
GET `/` and assert the prompt appears in the returned HTML.

## Out of Scope

Not built, each a small add later if wanted:

- Delete / clear-history UI
- Search or filter over history
- A settings.toml key for the DB path
- A retention cap or pruning job
- Per-language or per-backend scoping of history
- htmx out-of-band refresh of the dropdown
