# Hand-off: Prompt Search & Usage Ranking

**Date:** 2026-08-13
**State:** Design and plan complete, reviewed, committed. **No implementation code written yet.**
**Your job:** execute the plan.

---

## What you are building

The app stores every prompt the user submits in a SQLite table and offers the 25
most recent back in a `<select>` dropdown. Two things are wrong with that in
practice:

- The live database holds 85 prompts averaging 411 characters, and many share
  the same long boilerplate prefix (`"Use the uploaded reference image as the
  primary identity reference…"`). The dropdown trims labels to 40 characters,
  so they are **indistinguishable from one another**.
- There is no search. LRU only surfaces what you used last; the prompt you
  actually hunt for is the one you used once, months ago.

You are replacing the dropdown with a search box over a result list that
highlights matches in context, and adding a usage counter that pins
frequently-used prompts above the recent ones.

---

## Read these, in this order

| Document | What it gives you |
|---|---|
| `docs/superpowers/specs/2026-08-13-prompt-search-design.md` | The design and, more usefully, the **rationale** — a decisions table explaining why each choice beat the alternatives. Read this before the plan. |
| `docs/superpowers/plans/2026-08-13-prompt-search.md` | Five tasks with near-complete code for every step. This is what you execute. |
| `docs/superpowers/specs/2026-08-11-prompt-history-design.md` | Background: why the current dropdown looks the way it does. Worth skimming — it explains decisions you must not accidentally undo. |

Relevant commits, newest first:

```
ade749b docs: apply DeepSeek review to prompt search plan
3f37d9d docs: add prompt search implementation plan
af11f24 docs: apply second DeepSeek review round to prompt search spec
8ebc472 docs: apply DeepSeek review to prompt search spec
02fc82d docs: add prompt search & usage ranking design spec
```

`1ec9f57` is the last commit containing application code. Everything after it is
documentation.

---

## Environment

```bash
source .envrc          # direnv config; sets project env vars
source venv/bin/activate
pytest -q              # 145 tests must pass before you start
```

- **Baseline is exactly 145 passing tests.** Confirm this before touching
  anything. If it is not 145, stop and report — something changed underneath
  this plan.
- Fast loop while working: `pytest -m "not browser" -q`.
- The browser tests drive real headless Firefox and pull htmx from a CDN. They
  **skip** cleanly without network or without Firefox. A skip is not a pass —
  if they skip, say so explicitly rather than reporting the task verified.
- Do not `git push`. The repo owner does that.

---

## House style (non-negotiable, from the owner's global CLAUDE.md)

- Two spaces for indentation. **Never tabs.**
- Round brackets around sub-expressions in conditions: `if ((a + b) > c)`, not
  `if (a + b > c)`. This looks unusual; the existing code follows it, match it.
- Curly braces on **every** `if`/`else` branch in JavaScript, including
  single-line ones. `if (!btn) { return; }`, never `if (!btn) return;`.
- No new dependencies. Everything needed is stdlib or already in
  `requirements.txt`.
- Comments explain *why*, not *what*. The existing codebase is unusually good
  about this — match its density, and when you write a comment, make it earn
  its place.

---

## Things that will bite you

These are the non-obvious ones. Every one of them was found by review, not by
intuition — three of them were found *after* the plan was already written.

1. **`prompts.db` is real and already exists with 85 rows.**
   `CREATE TABLE IF NOT EXISTS` is a **no-op** against it, so the new
   `use_count` column arrives only via the guarded `ALTER TABLE`. Task 1 Step 3
   has the exact code. Do not skip the `PRAGMA table_info` check.

2. **Tests never touch the real `prompts.db`.** The autouse `_isolated_cwd`
   fixture in `tests/conftest.py` chdirs every test into `tmp_path`, and
   `_DB_PATH` is relative. If you finish and `git status` shows `prompts.db`
   modified, test isolation broke — investigate, do not commit it.

3. **Never put user text through `|safe`.** Highlighting works by looping
   `(chunk, is_match)` pairs so Jinja autoescapes every chunk. Building a
   pre-highlighted HTML string in Python would need manual escaping, and that
   is where XSS bugs live. There are tests guarding this; do not "simplify"
   past them.

4. **The `execCommand('insertText')` in the pick handler is deliberate.** It
   looks like deprecated cruft. It is not: it is the only way to make a
   programmatic textarea edit land on the native undo stack, measured in
   Firefox 140. A plain `ta.value = …` destroys an in-progress prompt
   irrecoverably. `test_undo_after_picking_restores_typed_text` guards it.
   **Do not replace it with `value =` or `setRangeText`.**

5. **Matching uses `re` for keywords too, not `in` / `str.lower()`.** This
   looks like over-engineering and isn't: the same compiled patterns both
   filter rows *and* locate the spans to highlight, so the two can never
   disagree. `str.lower()` can change string length, which breaks the offset
   mapping. The spec's decisions table explains it.

6. **Snippet spans come from the full text, never from the window slice.**
   `/end$/` matches the full text but not a window cut short of the end, so
   slicing first would match a row and then highlight nothing.
   `test_anchored_regex_still_produces_highlighting` is the regression guard.

7. **The refresh after generating fires on `htmx:afterRequest`, not
   `htmx:configRequest`.** `configRequest` fires *before* the POST goes out, so
   the refresh `GET /prompts` would race the `POST /generate` that writes the
   prompt and usually return a list without it.

8. **`name="q"` on the search input is load-bearing.** htmx only sends an
   element's value when it has a `name`. Without it every request arrives with
   an empty query and the search silently does nothing — no error, no clue.

9. **`Config.prompt_min_use_count` must have a default and go last** in the
   dataclass. Ten places construct `Config(...)` by hand across the test suite;
   a required field `TypeError`s in the `cfg` fixture before any test runs.

10. **`min_use_count` defaults to 1, not 3.** After migration every row sits at
    1, so a higher default renders an empty list on day one. The owner
    originally suggested 3 and agreed to 1 once this was pointed out. The
    cutoff trims the **default list only** — search always sees every prompt,
    which is the central design decision. Do not "optimise" search to respect
    the cutoff.

---

## Executing

Use `superpowers:subagent-driven-development` (fresh subagent per task, review
between tasks) or `superpowers:executing-plans` (inline with checkpoints).
Either is fine; the plan is written for both.

Five tasks, each ending in a commit:

| Task | Deliverable | Green at commit? |
|---|---|---|
| 1 | `use_count` column, migration, `Row` NamedTuple, `recent()`/`top()` | Yes — 150 |
| 2 | `search()`, `_compile()`, `_segments()` | Yes — 164 |
| 3 | Config, `/prompts` route, shared partial, translations | Yes — 174 |
| 4 | `index.html`: search box replaces the dropdown, new JS | **Only under `-m "not browser"`** — 175 |
| 5 | Port the 11 select-driven Selenium tests | Yes — 174 |

Task 4 is the one commit point where `pytest -q` is not fully green, because it
removes the `<select>` that the browser tests still target. That is expected and
called out in the plan. Task 5 closes it. If you stop between 4 and 5, say so
clearly.

The plan contains actual code for every step, not descriptions. If a step seems
to be missing detail, re-read it — the detail is probably there. If it genuinely
isn't, that is a plan bug worth reporting rather than improvising around.

---

## Definition of done

- [ ] `source venv/bin/activate && pytest -q` — all pass, 174 tests. State the
      browser-test skip count if any skipped.
- [ ] `git status` — no stray files, and **`prompts.db` unmodified**.
- [ ] Run the real app against the real 85-row database and confirm the
      migration ran: every row shows `×1`, favourites block empty until
      something is reused.
- [ ] Search for a word you know is buried mid-prompt and confirm the snippet
      is centred on **that word**, not on the shared boilerplate prefix. This is
      the entire point of the feature — if the snippets still all look alike,
      the feature has failed regardless of what the tests say.

---

## If you disagree with the plan

The spec and plan went through three independent review rounds and several
findings changed the design, so the reasoning is more considered than it may
first appear — but it is not sacred, and reviews miss things. If you find a real
problem, say so and explain the reasoning rather than silently working around
it. Two specific asks:

- Do not expand scope. No FTS5, no pruning job, no fuzzy matching, no relevance
  ranking. All were considered and explicitly ruled out in the spec's non-goals.
- Do not delete a test without a replacement assertion. The plan names every
  test it removes and why.
