# Prompt History Dropdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user re-select one of their 25 most recently used prompts from a dropdown above the prompt textarea.

**Architecture:** A new stdlib-only `services/prompt_store.py` persists every submitted prompt to SQLite, keyed on the prompt text itself so the schema *is* the LRU. `app.py` records on submit and passes the 25 most recent to the index template. A server-rendered `<select>` fills the textarea on change; a small JS block keeps that select current after htmx submits, since the page never reloads.

**Tech Stack:** Python 3.14, Flask, Jinja2, htmx 2.x, `sqlite3` (stdlib), pytest.

**Spec:** `docs/superpowers/specs/2026-08-11-prompt-history-design.md`

## Global Constraints

- **Indentation: 4 spaces.** This deviates from the user's global 2-space preference. All 582 lines of existing Python in this repo are 4-space, as is `templates/index.html`'s JS. Consistency within the file wins here. **If the user prefers 2-space for the new files, they override this line and the code blocks below are re-indented.**
- **Brackets:** every `if`/`else` body gets braces in JS, even single statements. Parenthesise sub-expressions where precedence could be ambiguous.
- **No new dependencies.** `sqlite3`, `threading`, `contextlib`, `time` are all stdlib. `requirements.txt` is not touched.
- **DB path:** `prompts.db`, relative to the project root, matching the existing relative `.cache/` and `logs/` dirs.
- **`_MAX_LEN = 2000`** — server-side truncation cap, mirrored as `maxlength="2000"` on the textarea.
- **History window: 25 prompts**, labels trimmed to 40 characters plus an ellipsis.
- **Always invoke pytest as `python -m pytest`, never bare `pytest`.** This repo has no pytest config and no root `conftest.py`, so only `python -m pytest` puts the project root on `sys.path`. Bare `pytest` fails at collection with `ModuleNotFoundError: No module named 'app'`. Prefix every run with `source venv/bin/activate &&`.
- Baseline before starting: **97 passing** (verified in this worktree).

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `services/prompt_store.py` | Create | The only module that knows SQLite exists. Two public functions: `add`, `recent`. |
| `tests/test_prompt_store.py` | Create | Unit tests for the store in isolation. |
| `tests/conftest.py` | Modify | Autouse fixture redirecting `_DB_PATH` to `tmp_path` for **every** test. |
| `app.py` | Modify | Records on submit; passes `prompts` to the index template. |
| `templates/index.html` | Modify | The `<select>`, its selection handling (fills the textarea on `change`, resets on `blur`), and the post-submit prepend. |
| `translations.py` | Modify | One key, `prompt_history`, en + de. |
| `.gitignore` | Modify | Add `prompts.db`. |

---

### Task 1: The prompt store

**Files:**
- Create: `services/prompt_store.py`
- Create: `tests/test_prompt_store.py`
- Modify: `tests/conftest.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `services.prompt_store.add(text: str) -> None`
  - `services.prompt_store.recent(n: int = 25) -> list[str]`
  - `services.prompt_store._DB_PATH: str` — module-level, read at call time so tests can monkeypatch it.
  - `services.prompt_store._MAX_LEN: int` — `2000`.

**Why the conftest change is in this task:** every existing test that POSTs `/generate` or GETs `/` will hit the store once Task 2 lands. Without the fixture they would write `prompts.db` into the repo root and leak state between runs. Landing the fixture here means Task 2 needs no test-infrastructure work.

- [ ] **Step 1: Add the DB file to `.gitignore`**

Append a line to `.gitignore` (current contents: `.envrc*`, `.cache/`, `.secrets.toml`, `.worktrees/`):

```
prompts.db
```

- [ ] **Step 2: Add the autouse fixture to `tests/conftest.py`**

Add the import at the top of the file, alongside the existing `from config import Config, ImageBackend`:

```python
from services import prompt_store
```

Then append this fixture to the end of the file:

```python
@pytest.fixture(autouse=True)
def _isolated_prompt_db(tmp_path, monkeypatch):
    """Every test gets a fresh, throwaway prompt DB outside the repo."""
    monkeypatch.setattr(prompt_store, "_DB_PATH", str(tmp_path / "prompts.db"))
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_prompt_store.py`:

```python
from services import prompt_store


def test_add_then_recent_returns_prompt():
    prompt_store.add("a sunset over water")
    assert prompt_store.recent() == ["a sunset over water"]


def test_readd_moves_to_front_without_duplicating():
    prompt_store.add("first")
    prompt_store.add("second")
    prompt_store.add("first")
    assert prompt_store.recent() == ["first", "second"]


def test_recent_is_newest_first_and_capped():
    for i in range(30):
        prompt_store.add(f"prompt {i}")
    result = prompt_store.recent(25)
    assert len(result) == 25
    assert result[0] == "prompt 29"
    assert result[-1] == "prompt 5"


def test_blank_prompts_are_ignored():
    prompt_store.add("")
    prompt_store.add("   ")
    assert prompt_store.recent() == []


def test_prompt_is_stripped_before_storing():
    prompt_store.add("  padded  ")
    assert prompt_store.recent() == ["padded"]


def test_long_prompt_is_truncated():
    prompt_store.add("x" * 5000)
    stored = prompt_store.recent()[0]
    assert len(stored) == prompt_store._MAX_LEN


def test_recent_on_empty_db_returns_empty_list():
    assert prompt_store.recent() == []
```

- [ ] **Step 4: Run the tests to verify they fail**

Run:

```bash
source venv/bin/activate && python -m pytest tests/test_prompt_store.py -v
```

Expected: collection error — `ImportError: cannot import name 'prompt_store' from 'services'`. The `conftest.py` import fails too, which is expected at this point.

- [ ] **Step 5: Write the implementation**

Create `services/prompt_store.py`:

```python
import sqlite3
import threading
from contextlib import contextmanager
from time import time

_DB_PATH = "prompts.db"
_MAX_LEN = 2000
_lock = threading.Lock()


@contextmanager
def _db():
    """Connect-per-call. Sidesteps sqlite3's thread-affinity rule entirely,
    and makes CREATE TABLE IF NOT EXISTS the only init step there is."""
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS prompts ("
                "  text TEXT PRIMARY KEY,"
                "  used_at REAL NOT NULL"
                ")"
            )
            yield conn
            conn.commit()
        finally:
            # sqlite3's own context manager commits but does not close.
            conn.close()


def add(text: str) -> None:
    """Record a prompt, bumping it to the front if already present."""
    # Truncate at the trust boundary: the app binds 0.0.0.0 and the textarea
    # is unbounded, so without a cap one POST loop fills the disk.
    text = text.strip()[:_MAX_LEN]
    if (not text):
        return
    with _db() as conn:
        conn.execute(
            "INSERT INTO prompts (text, used_at) VALUES (?, ?) "
            "ON CONFLICT(text) DO UPDATE SET used_at = excluded.used_at",
            (text, time()),
        )


def recent(n: int = 25) -> list[str]:
    """The n most recently used prompts, newest first."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT text FROM prompts ORDER BY used_at DESC LIMIT ?", (n,)
        ).fetchall()
    return [row[0] for row in rows]
```

Notes for the implementer:

- `text TEXT PRIMARY KEY` **is** the dedup, and `ON CONFLICT ... DO UPDATE` **is** the LRU bump. There is no id column and no dedup code by design — do not add either.
- The `_lock` is redundant with SQLite's own locking in the common case. It is one line of insurance against `database is locked` when two submits race, and it wraps the whole `_db()` body, connect through close.
- `ponytail:` two distinct prompts sharing their first 2000 characters collapse into one row. Accepted — real prompts are nowhere near that long.

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```bash
source venv/bin/activate && python -m pytest tests/test_prompt_store.py -v
```

Expected: 7 passed.

- [ ] **Step 7: Run the full suite to confirm nothing regressed**

Run:

```bash
source venv/bin/activate && python -m pytest -q
```

Expected: 104 passed (97 baseline + 7 new). Confirm no `prompts.db` appeared in the repo root:

```bash
test ! -e prompts.db && echo "clean" || echo "LEAK: prompts.db created"
```

Expected: `clean`.

- [ ] **Step 8: Commit**

```bash
git add services/prompt_store.py tests/test_prompt_store.py tests/conftest.py .gitignore
git commit -m "feat: add sqlite-backed prompt store"
```

---

### Task 2: Record prompts and expose them to the template

**Files:**
- Modify: `app.py:23` (import), `app.py:57-71` (`index`), `app.py:93-97` (`generate`)
- Modify: `tests/test_routes.py`

**Interfaces:**
- Consumes: `prompt_store.add(text)`, `prompt_store.recent(n)` from Task 1.
- Produces: the `index.html` template receives a `prompts` variable — a `list[str]`, newest first, at most 25 entries, possibly empty. Task 3 renders it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`. The file already imports `patch` from `unittest.mock` at line 3.

```python
def test_generate_records_prompt_in_history(client):
    from services import prompt_store

    with patch("app.image_gen.generate_image", return_value=b"png-bytes"):
        client.post("/generate", data={
            "output_type": "image",
            "prompt": "a lighthouse at dusk",
        })

    assert "a lighthouse at dusk" in prompt_store.recent()


def test_generate_records_prompt_even_when_request_is_rejected(client):
    """A prompt is worth keeping even if the request 400s — it's the one
    you want to retry."""
    from services import prompt_store

    client.post("/generate", data={
        "output_type": "image",
        "prompt": "rejected but memorable",
        "image_backend": "does-not-exist",
    })

    assert "rejected but memorable" in prompt_store.recent()


def test_generate_does_not_record_blank_prompt(client):
    from services import prompt_store

    with patch("app.image_gen.generate_image", return_value=b"png-bytes"):
        client.post("/generate", data={
            "output_type": "image",
            "prompt": "   ",
        })

    assert prompt_store.recent() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
source venv/bin/activate && python -m pytest tests/test_routes.py -k "history or record" -v
```

Expected: 3 failures — `assert 'a lighthouse at dusk' in []`, and similar. Nothing is being recorded yet.

- [ ] **Step 3: Add the import**

In `app.py`, change line 23 from:

```python
from services import job_store, image_gen, video_gen, sd_gen
```

to:

```python
from services import job_store, image_gen, video_gen, sd_gen, prompt_store
```

- [ ] **Step 4: Record the prompt in `/generate`**

In `app.py`, immediately after line 96 (`prompt = request.form.get("prompt", "").strip()`), insert:

```python
        prompt_store.add(prompt)
```

This must sit **before** the `abort(400)` checks further down (the `len(images) > _MAX_IMAGES` check at line 112 and the unknown-backend check at line 116), so a rejected request still leaves its prompt in the history.

- [ ] **Step 5: Pass the history to the index template**

In `app.py`, in `index()`, add one keyword argument to the `render_template` call so it reads:

```python
        return render_template(
            "index.html",
            t=t(),
            sd_enabled=bool(cfg.sd_api_url),
            image_backends=image_backends,
            image_default_backend=cfg.image_default_backend,
            video_models_image=cfg.video_model_image,
            video_models_text=cfg.video_model_text,
            prompts=prompt_store.recent(25),
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```bash
source venv/bin/activate && python -m pytest tests/test_routes.py -v
```

Expected: all pass, including the 3 new ones. The template ignores `prompts` for now — that is Task 3.

- [ ] **Step 7: Run the full suite**

Run:

```bash
source venv/bin/activate && python -m pytest -q
```

Expected: 107 passed.

- [ ] **Step 8: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: record submitted prompts and expose recent ones to the index template"
```

---

### Task 3: The dropdown

**Files:**
- Modify: `translations.py:2-26` (en block), `translations.py:27-51` (de block)
- Modify: `templates/index.html:22-31` (the prompt block)
- Modify: `tests/test_routes.py`

**Interfaces:**
- Consumes: the `prompts` template variable from Task 2 (`list[str]`, newest first, ≤25, possibly empty); `t.prompt_history` from the translations change below.
- Produces: nothing consumed by later tasks. This is the last task.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
def test_index_hides_history_select_when_empty(client):
    resp = client.get("/")
    assert b'id="prompt-history"' not in resp.data


def test_index_shows_history_select_when_populated(client):
    from services import prompt_store

    prompt_store.add("a previously used prompt")
    resp = client.get("/")
    assert b'id="prompt-history"' in resp.data
    assert b"a previously used prompt" in resp.data


def test_index_trims_long_history_labels(client):
    from services import prompt_store

    long_prompt = "z" * 100
    prompt_store.add(long_prompt)
    body = client.get("/").data.decode("utf-8")

    # Full text survives in the option value...
    assert f'value="{long_prompt}"' in body
    # ...but the visible label is trimmed to 40 chars plus an ellipsis.
    assert f'>{"z" * 40}…<' in body
    assert f'>{"z" * 41}' not in body


def test_index_escapes_history_entries(client):
    from services import prompt_store

    prompt_store.add('<script>alert("x")</script>')
    body = client.get("/").data.decode("utf-8")
    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
source venv/bin/activate && python -m pytest tests/test_routes.py -k "history or trims or escapes" -v
```

Expected: `test_index_hides_history_select_when_empty` passes trivially (nothing is rendered yet); the other three fail because `id="prompt-history"` is absent from the response.

- [ ] **Step 3: Add the translation key**

In `translations.py`, add to the `"en"` dict (alongside `"prompt_label"`):

```python
        "prompt_history": "Recent prompts",
```

And to the `"de"` dict:

```python
        "prompt_history": "Zuletzt verwendet",
```

- [ ] **Step 4: Render the select and cap the textarea**

In `templates/index.html`, replace the prompt block at lines 22–31:

```html
    <!-- Prompt -->
    <div>
      <label class="block text-lg font-semibold text-gray-700 mb-2">
        {{ t.prompt_label }}
      </label>
      <textarea name="prompt" rows="3" required
                class="w-full border border-gray-300 rounded-xl p-3 text-lg
                       focus:outline-none focus:ring-2 focus:ring-blue-400"
                placeholder="Describe what you want to create…"></textarea>
    </div>
```

with:

```html
    <!-- Recent prompts -->
    {% if prompts %}
    <div>
      <label class="block text-sm font-medium text-gray-600 mb-1">
        {{ t.prompt_history }}
      </label>
      <select id="prompt-history"
              class="w-full border border-gray-300 rounded-lg p-2 text-sm bg-white
                     focus:outline-none focus:ring-2 focus:ring-blue-400">
        <option value="">— {{ t.prompt_history }} —</option>
        {% for p in prompts %}
        <option value="{{ p }}">{{ p[:40] | replace('\n', ' ') }}{% if p | length > 40 %}…{% endif %}</option>
        {% endfor %}
      </select>
    </div>
    {% endif %}

    <!-- Prompt -->
    <div>
      <label class="block text-lg font-semibold text-gray-700 mb-2">
        {{ t.prompt_label }}
      </label>
      <textarea name="prompt" rows="3" required maxlength="2000"
                class="w-full border border-gray-300 rounded-xl p-3 text-lg
                       focus:outline-none focus:ring-2 focus:ring-blue-400"
                placeholder="Describe what you want to create…"></textarea>
    </div>
```

Notes for the implementer:

- The `<select>` deliberately has **no `name` attribute**, so it is never serialised into the form POST. Do not add one.
- Jinja autoescaping handles both the `value` attribute and the label text. Do not add `| e` or `| safe`.
- `maxlength="2000"` mirrors `prompt_store._MAX_LEN`. It is UX, not enforcement — the server-side truncation in `add()` is the real boundary.

- [ ] **Step 5: Add the select behaviour and the post-submit prepend**

In `templates/index.html`, insert this `<script>` block immediately **after** the closing `</div>` of the Prompt block you just edited, and **before** the `<!-- Image upload -->` comment:

```html
    <script>
      (function() {
        var sel = document.getElementById('prompt-history');
        var ta  = document.querySelector('textarea[name="prompt"]');
        var MAX = 25;

        function label(text) {
          var flat = text.replace(/\n/g, ' ');
          if (flat.length > 40) {
            return (flat.slice(0, 40) + '…');
          } else {
            return flat;
          }
        }

        if (sel) {
          sel.addEventListener('change', function() {
            if (this.value) {
              ta.value = this.value;
            }
          });

          sel.addEventListener('blur', function() {
            // Reset once focus leaves, so picking the same entry twice works.
            this.selectedIndex = 0;
          });
        }

        /* Keep the dropdown current: the form submits via htmx, so the page
         * never reloads and the server-rendered list would otherwise go stale.
         * A second htmx:configRequest listener is safe — listeners fire in
         * registration order and this one touches only the select, while the
         * upload handler below touches only evt.detail.parameters. */
        document.querySelector('form[hx-post]').addEventListener('htmx:configRequest', function() {
          // The select is absent until the first prompt is stored.
          if (!sel) {
            return;
          }
          var p = ta.value.trim();
          if (!p) {
            return;
          }
          // Drop any existing entry with the same text. Compare values directly
          // rather than building an attribute selector — CSS.escape escapes CSS
          // identifiers, not quoted selector strings, so a prompt containing a
          // double quote would break querySelector.
          for (var i = (sel.options.length - 1); i >= 1; i--) {
            if (sel.options[i].value === p) {
              sel.remove(i);
            }
          }
          var opt = document.createElement('option');
          opt.value       = p;
          opt.textContent = label(p);
          // options[1] is undefined when only the placeholder remains;
          // insertBefore(node, null) appends, which is what we want.
          sel.insertBefore(opt, (sel.options[1] || null));
          while (sel.options.length > (MAX + 1)) {
            sel.remove(sel.options.length - 1);
          }
        });
      })();
    </script>
```

Notes for the implementer:

- Use `sel.remove(index)`, not `sel.lastChild.remove()` — `lastChild` may be a whitespace text node left by Jinja.
- `ponytail:` if the server then rejects the request with `abort(400)`, the dropdown briefly shows an entry that *was* stored (Task 2 records before validating), so this stays consistent. If validation ever moves ahead of the `add()` call, this comment stops being true.

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```bash
source venv/bin/activate && python -m pytest tests/test_routes.py -v
```

Expected: all pass, including the 4 new ones.

- [ ] **Step 7: Run the full suite**

Run:

```bash
source venv/bin/activate && python -m pytest -q
```

Expected: 111 passed.

- [ ] **Step 8: Manual smoke test**

The JS is not covered by the test suite, so verify it by hand:

```bash
source venv/bin/activate && python app.py --port 5001
```

Then in a browser at `http://localhost:5001`:

1. On a fresh DB, confirm the wrapper renders but is not visible above the prompt field (it is present in the DOM with `hidden`, not absent). Submit a prompt and confirm the dropdown becomes visible **without** a reload, with no console error.
2. Reload. Confirm the dropdown still appears with your prompt in it.
3. Submit a second, different prompt. Confirm it appears at the top of the dropdown **without** a reload.
4. Re-submit the first prompt. Confirm it moves to the top and is not duplicated.
5. Pick an entry from the dropdown. Confirm the textarea fills with the **full** text (not the 40-char label) and gains focus. The select visibly resets to `— Recent prompts —` right away — the `change` handler calls `ta.focus()`, which synchronously fires `blur` on the select and runs the (untouched) blur listener. So the reset still looks immediate, just via a different mechanism than before (triggered by the code's own focus shift, not by you tabbing away).
6. Pick the *same* entry again. Confirm it still fills the textarea. No extra manual blur step is needed for this: step 5 already left the select's value reset to the placeholder, so re-picking the same visible label is a genuine value change and `change` fires normally.
7. Type a prompt into the textarea, focus the select, and press the Down-arrow key to browse without picking. Confirm what happens to the typed text, and specifically whether Ctrl+Z recovers it. Firefox is expected to honour `setRangeText` on the textarea's native undo stack; Chrome's behaviour needs confirming by hand.
8. Submit a prompt with a `"` and a `<` in it. Confirm no console error and no broken markup.

Stop the server when done.

- [ ] **Step 9: Commit**

```bash
git add templates/index.html translations.py tests/test_routes.py
git commit -m "feat: add recent-prompts dropdown above the prompt field"
```

---

## Verification

After all three tasks:

```bash
source venv/bin/activate && python -m pytest -q
```

Expected: **114 passed** (111 after Task 3, plus 3 more from the post-review fix wave: a blur-reset naming/quote-escaping pass and the final dropdown-visibility fixes).

```bash
git status --short
```

Expected: no `prompts.db` in the output — it is gitignored, and the test suite never creates one in the repo root anyway.

## Out of Scope

Not built, per the spec. Each is a small add later if wanted:

- Delete / clear-history UI
- Search or filter over history
- A `settings.toml` key for the DB path
- A retention cap or pruning job
- Per-language or per-backend scoping of history
- htmx out-of-band refresh of the dropdown
