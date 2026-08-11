# Final leak-fix report — data-dir branch

Worktree: `.worktrees/data-dir`, branch `data-dir`, started at `81eb86a`.

## Fix 1 (CRITICAL) — restore `patch("app._cache_artifact")` in `tests/test_dropdown_browser.py`'s `server` fixture

The prior commit `81eb86a` had dropped this patch on the theory that the autouse `_isolated_cwd`
chdir fixture already covered it. That's wrong: this fixture leaves `app.threading.Thread` real,
so every `_submit()` in every browser test fires a genuine `POST /generate`, which starts a
genuine unjoined daemon `_run_image_job` thread that calls the real `_cache_artifact()`.
`thread.join(timeout=5)` in the fixture only joins the `srv.serve_forever` wrapper thread, never
the job threads spawned per-request — so a job thread can still be sleeping/running after the
test (and the per-test `monkeypatch.chdir`) has unwound, and its write lands wherever the
process cwd has reverted to, which is the real data dir once no more tests re-chdir it away.

Restored `patch("app._cache_artifact")` alongside the existing
`patch("app.image_gen.generate_image", ...)` in the `with` statement — identical to the form at
`4a1dcd8` (`git show 4a1dcd8:tests/test_dropdown_browser.py`). Rewrote the fixture docstring to
state the correct rationale (mirroring the reasoning already in
`tests/test_routes.py:27-28`):

```python
@pytest.fixture
def server(cfg):
    """The real app on a background thread, with generation stubbed out.

    Patching `_cache_artifact` matters: each `_submit()` fires a real
    `POST /generate`, which starts a real, unjoined daemon `_run_image_job`
    thread. `thread.join()` below only joins the server thread, not job
    threads, so a job thread can outlive the test and write to .cache/ after
    the autouse `_isolated_cwd` fixture has already unwound its chdir.
    """
    port = _free_port()
    srv = make_server("127.0.0.1", port, create_app(cfg), threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    with patch("app.image_gen.generate_image", return_value=b"\x89PNG\r\n\x1a\n"), \
         patch("app._cache_artifact"):
        thread.start()
        yield f"http://127.0.0.1:{port}"
        srv.shutdown()
    thread.join(timeout=5)
```

Did not patch `app.threading.Thread` instead, and did not restructure/join the job threads —
exactly the smaller, prior-existing fix requested.

File: `tests/test_dropdown_browser.py`

## Fix 2 (Minor) — plan's thread inventory paragraph

`docs/superpowers/plans/2026-08-11-data-dir.md`, "Why these test changes are mandatory"
paragraph (around line 312). It named the four `test_routes.py` real-thread tests correctly, but
its `grep -n "threading.Thread" tests/test_routes.py` instruction was scoped only to that one
file (already fixed) and never mentioned `tests/test_dropdown_browser.py`'s `server` fixture —
the largest source of real daemon threads in the suite, and precisely the thing that regressed in
`81eb86a`.

Changes:
- Clarified the four named tests are "in `tests/test_routes.py`".
- Widened the suggested grep from `tests/test_routes.py` to `tests/` (`grep -rn`).
- Added a new paragraph explaining that `tests/test_dropdown_browser.py`'s `server` fixture is
  the other real source of unjoined daemon threads, that it is *not* fixed by making it
  synchronous (its `thread.join(timeout=5)` only joins the server thread), and that it is instead
  guarded by `patch("app._cache_artifact")` — with an explicit warning not to remove that guard
  on the theory that `_isolated_cwd`'s chdir makes it redundant.

File: `docs/superpowers/plans/2026-08-11-data-dir.md`

## Fix 3 (Minor) — plan Step 1's canary code block was the old, unshipped version

The plan's Task 3 / Step 1 code block still showed the pre-review canary:
`import config` / `config._BASE_DIR`, `set(cache_dir.iterdir())`, and an `.exists() == db_existed`
boolean check — none of which match the shipped test. It also told the reader to verify the
canary by editing a `_no_artifact_writes` fixture that no longer exists on this branch (isolation
is now done entirely by the autouse `_isolated_cwd` fixture in `tests/conftest.py`).

Changes:
- Replaced the entire code block with the canary exactly as shipped in
  `tests/test_routes.py::test_generate_does_not_write_into_the_project_root` (copied verbatim):
  `import app` / `app._DATA_DIR`, `set(cache_dir.rglob("*"))` at both snapshot and assertion
  sites, and a byte-content comparison of `prompts.db` (`read_bytes()` before/after) instead of
  an existence check.
- Rewrote the "Expected: PASS" line to reference the real, current guard
  (the autouse `_isolated_cwd` fixture) instead of the deleted `_no_artifact_writes` fixture.
- Rewrote the verification instruction: it now says to temporarily neutralise `_isolated_cwd` in
  `tests/conftest.py` (replace its body with a bare `pass`, i.e. stop calling
  `monkeypatch.chdir(tmp_path)`) rather than editing a fixture that was deleted, and explicitly
  notes the demonstration must be run with a `.cache/<today>/` subdirectory already present,
  since `_cache_artifact` writes beneath a dated subfolder rather than directly under `.cache/`.
- Updated the "Expected: FAIL" line to quote the shipped assertion message.

File: `docs/superpowers/plans/2026-08-11-data-dir.md`

---

## Full suite run

```
$ source venv/bin/activate && python -m pytest -q
........................................................................ [ 53%]
..............................................................           [100%]
134 passed in 17.97s
```

Re-ran once more after the scratch-copy experiments to confirm no regressions from the final
worktree state:

```
$ source venv/bin/activate && python -m pytest -q
........................................................................ [ 53%]
..............................................................           [100%]
134 passed in 17.29s
```

Firefox and outbound network (htmx CDN) were both available in this environment
(`which firefox` → `/usr/bin/firefox`), so the browser tests ran for real rather than skipping —
11 passed under `-m browser` in the normal suite run.

---

## Widened-race proof (throwaway copy only — never the main repo)

All of this ran against a `cp -a` throwaway copy at `/tmp/tmp.2UZPZd5CqX` (since deleted). The
main repo and its `.cache/20260811/` + `prompts.db` were never touched by any of these steps —
see "Real data confirmation" below.

### Setup

1. `cp -a .worktrees/data-dir/. /tmp/tmp.2UZPZd5CqX/repo` (copied the already-fixed worktree,
   including Fix 1).
2. Repointed the copy's config at a scratch data dir, isolated from everything real:
   `settings.toml`: `data_dir = "/tmp/tmp.2UZPZd5CqX/data"`.
3. Planted a known file to detect any leak, including deletion/corruption:
   `/tmp/tmp.2UZPZd5CqX/data/.cache/20260811/KNOWN-FILE.txt` containing
   `known-planted-file-do-not-touch`.
4. Widened the race window, in the copy's `app.py` only:
   ```python
   def _run_image_job(cfg: Config, job_id: str, prompt: str, images: list[bytes],
                      backend: str, model: str, model_edit: str):
       import time
       time.sleep(1.0)  # TEMP: widen the race window for the leak-fix proof
       try:
           data = image_gen.generate_image(...)
   ```
5. Appended a temporary last test to the copy's `tests/test_dropdown_browser.py` that sleeps 3s,
   so the pytest process stays alive long enough for a lingering daemon job thread's delayed
   write to have a real chance to land before the interpreter exits (daemon threads are killed
   outright at process exit, which would otherwise hide a leak rather than prove its absence).

### Negative control — proving the widened race is real

With the `patch("app._cache_artifact")` guard temporarily *removed* again (undoing Fix 1 in the
copy only) and the above widening in place:

```
$ python -m pytest -m browser -q
............                                                             [100%]
12 passed, 123 deselected in 19.62s

$ find /tmp/tmp.2UZPZd5CqX/data/.cache -type f
/tmp/tmp.2UZPZd5CqX/data/.cache/20260811/20260811-163038-6c9f27ba-0083-4ee1-bc52-4b861c8dbca2.png
/tmp/tmp.2UZPZd5CqX/data/.cache/20260811/20260811-163035-356826ec-4b6b-408e-915d-3ced56827146.png
/tmp/tmp.2UZPZd5CqX/data/.cache/20260811/KNOWN-FILE.txt
```

Two PNGs leaked into the scratch "real" data dir while pytest reported all green (`12 passed`).
This confirms the widened race genuinely reproduces the leak mechanism described in the brief,
and that a passing test run gives no signal that a leak occurred.

### Fix verification — 5 runs with the guard restored

Restored `patch("app._cache_artifact")` in the copy (matching the real Fix 1), deleted the two
leaked PNGs, re-snapshotted the scratch data dir, then ran `-m browser` five times in a row with
the same 1s widened window and the same tail-end 3s hold:

```
$ python -m pytest -m browser -q   (x5)
run 1: 12 passed, 123 deselected in 19.68s
run 2: 12 passed, 123 deselected in 19.60s
run 3: 12 passed, 123 deselected in 19.53s
run 4: 12 passed, 123 deselected in 19.42s
run 5: 12 passed, 123 deselected in 19.56s
```

### Before/after comparison of the scratch data dir

Before (after re-planting KNOWN-FILE.txt, before the 5 runs):
```
53c08d969a80963842592aacce31f04fa54e00b865c4c17c3cb5c2c2388522dc  /tmp/tmp.2UZPZd5CqX/data/.cache/20260811/KNOWN-FILE.txt
6345b10857d507647a687b44d3bce24968e675c02d0ee3d09717361855dd8df5  /tmp/tmp.2UZPZd5CqX/data/logs/app-5005.log
```

After (5/5 clean runs):
```
$ find /tmp/tmp.2UZPZd5CqX/data -type f
/tmp/tmp.2UZPZd5CqX/data/.cache/20260811/KNOWN-FILE.txt
/tmp/tmp.2UZPZd5CqX/data/logs/app-5005.log

$ sha256sum /tmp/tmp.2UZPZd5CqX/data/.cache/20260811/KNOWN-FILE.txt
53c08d969a80963842592aacce31f04fa54e00b865c4c17c3cb5c2c2388522dc  (unchanged)

$ find /tmp/tmp.2UZPZd5CqX/data -iname prompts.db
(nothing — no prompts.db was created)
```

`.cache/20260811/` contains exactly the one planted file, byte-identical to before. No new
files, no deletions, no `prompts.db`. The *only* file in the scratch data dir that changed at
all is `logs/app-5005.log`, which grew from normal app request logging — this is the
pre-existing, documented exception: `tests/conftest.py`'s `_isolated_cwd` docstring already notes
"It does NOT isolate logs/: loguru opens its file sink once at import time... test runs append to
the real logs/ regardless of any later chdir." This is unrelated to the `_cache_artifact` leak
this task fixes, applies identically on `master`, and is explicitly out of scope (the task's plan
doc, Task 2 Step 8, already documents `logs/` as untracked/ungitignored and out of scope).

**Conclusion:** the widened-race proof ran for real, and it worked — it caught the leak with the
guard removed (2/2 attempts leaked) and found zero leaks with the guard restored (5/5 clean),
under conditions strictly more adversarial than a normal test run (1s artificial delay in the job
thread, plus a 3s tail hold to give lingering daemon threads their best chance to write before
process exit).

The scratch copy and everything under `/tmp/tmp.2UZPZd5CqX` was deleted afterward
(`rm -rf /tmp/tmp.2UZPZd5CqX`).

---

## Real data confirmation

Main repo: `/srv/dev-disk-by-uuid-1242cbf2-b3bf-49d0-81a4-3a493ec519ed/space-ssd/home/dschinnerl/Documents/Private/Projects/ai-image-gen`
(branch `master`, a separate git worktree from `data-dir` — genuinely separate files, confirmed
via `git worktree list`).

Checksums, sizes and mtimes of the three PNGs and `prompts.db`, taken before any work in this
task and re-checked at the end, are identical:

```
265bfb57b5c62c150306095372982686cae2097c7b29641a210cece9c2169a3a  .cache/20260811/20260811-123648-94cd879f-82c2-4255-8fdc-3f35f945a840.png
fc2eeac9aca6260a6f7487fb2e12d89bd867dbadf51a58b9f6c903a48a0e1a67  .cache/20260811/20260811-123742-12bd1d66-7b5a-4c3c-a072-ba1cd9e5035d.png
bd4e03b71d9be37203f64661cf23e272b1a3b4231b9945d46030391887bc064e  .cache/20260811/20260811-123920-6c368e81-d440-4d6f-b89b-22a589a05c8b.png
657f855a27cf732297f9d094819771ef6b097015d306bfc718699dec51299f1e  prompts.db
```
Sizes: 1734317 / 1741677 / 1748236 bytes; mtimes 12:36:48.700908125 / 12:37:42.632466097 /
12:39:20.751661891 +0200 — all unchanged before vs. after.

Note: `git status --short` in the main repo shows a pre-existing unstaged local modification to
`docs/superpowers/plans/2026-08-11-data-dir.md` on `master` (different content from this branch's
version of that file) and several pre-existing untracked files (`ai-image-gen.md`,
`check-sora.sh`, `check.py`, `docs/plans/`, `list-all-models.sh`, `models.json`, `notes.txt`,
`probe_sora.py`, `settings.toml.20260810`). None of these were touched by this task — every
`Edit`/`Write`/`Bash` write in this session targeted only paths under `.worktrees/data-dir/` or
`/tmp/`. These are pre-existing local changes in the main repo from outside this session's scope.

---

## Files changed (worktree `data-dir`)

- `tests/test_dropdown_browser.py` — restored `patch("app._cache_artifact")` in the `server`
  fixture and corrected its docstring.
- `docs/superpowers/plans/2026-08-11-data-dir.md` — corrected the thread-inventory paragraph and
  replaced the Step 1 canary code block + verification instructions with the shipped version.

No changes to `config.py`, `app.py`, `settings.toml`, or `tests/conftest.py`. No second canary
added. No `.gitignore` change. No `pytest-randomly`. Job threads were not joined; the `server`
fixture was not restructured beyond restoring the one patch and its docstring.

## Concerns

- None regarding the fix itself — the widened-race proof (negative control leaking, 5/5 clean
  with the guard restored) gives strong confidence Fix 1 is correct and sufficient.
- The pre-existing modified/untracked files in the main repo (`master` branch) noted above are
  unrelated to this task and were left alone, per instructions not to touch the parent repo.
