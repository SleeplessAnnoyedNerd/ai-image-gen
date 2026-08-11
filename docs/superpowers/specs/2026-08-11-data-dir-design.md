# Data Directory and Test Isolation — Design

**Date:** 2026-08-11
**Status:** Approved

## Goal

Give the app one configurable directory for everything it writes, and stop the
test suite from touching the real one.

## The problem

`config.py:5` reads settings through an absolute `_BASE_DIR`, but every write
path is relative to the current working directory:

| Path | Written by | When |
|---|---|---|
| `logs/app-{port}.log` | `app.py:11` | **module import** |
| `.cache/YYYYMMDD/…` | `app.py:34` | every successful job |
| `prompts.db` | `services/prompt_store.py:6` | every submit and every `GET /` |

Reads are anchored, writes float. Two consequences, both observed:

1. **Tests write into real data.** This was patched reactively three separate
   times — `conftest.py` monkeypatching `_DB_PATH`, `test_routes.py` patching
   `_cache_artifact`, `test_cache_artifact.py` chdir'ing — and it still got
   through: `test_cache_artifact.py` called `shutil.rmtree(".cache")` on the
   real archive, destroying generated images on every run.
2. **`python app.py` from another directory** silently starts a second, empty
   prompt history and a second artifact cache.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Mechanism | `os.chdir(data_dir)` once at startup | Every existing relative write follows with no call-site changes: no `_cache_artifact` signature change, no `prompt_store` init step. |
| Test isolation | Autouse `monkeypatch.chdir(tmp_path)` in `tests/conftest.py` | The identical mechanism, so tests exercise the same path resolution production uses. |
| Anchoring | Resolve `data_dir` against `_BASE_DIR` | Matches how config itself is already anchored, and fixes the "second history" bug. |
| Default | `"."` | Current behaviour exactly — this change is a no-op for an existing install. |

Chdir is safe in this app specifically: `config.py` reads through `_BASE_DIR`,
and Flask resolves templates from the app's absolute `root_path`. Nothing else
depends on the working directory.

## Components

### `config.py`

```python
def resolve_data_dir() -> Path:
    # (_BASE_DIR / value).resolve() — an absolute configured value wins,
    # which is how pathlib joins already behave.
    # mkdir(parents=True, exist_ok=True) so chdir cannot fail on first run.
```

Reads `[paths] data_dir`, defaulting to `"."`.

### `app.py`

The chdir goes at the **very top of the module**, above the existing
`logger.add(f"logs/app-{_port}.log", …)` — otherwise the log handler opens
against the old working directory and stays there for the process's life.

That makes it an import-time side effect. This is deliberate and matches what
the module already does (the logger call is import-time too). It also means a
WSGI server importing `create_app` gets the same behaviour as `python app.py`,
which a `__main__`-only chdir would not.

No other change to `app.py`. `_cache_artifact` keeps its signature.

### `services/prompt_store.py`

Unchanged. `_DB_PATH` stays the relative `"prompts.db"`, resolved by
`sqlite3.connect` against the current working directory at call time — which is
now the data dir.

### `settings.toml` and `settings.example.toml`

```toml
[paths]
data_dir = "."
```

### `tests/conftest.py`

```python
@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Every test writes into a throwaway directory."""
    monkeypatch.chdir(tmp_path)
```

This **replaces** three existing fixtures, which are deleted:

- `_isolated_prompt_db` in `tests/conftest.py` — the relative `_DB_PATH` now
  resolves under `tmp_path` on its own.
- `_no_artifact_writes` in `tests/test_routes.py`.
- `_isolated_cwd` in `tests/test_cache_artifact.py` — moves up to `conftest.py`
  and applies to the whole suite.

Net effect is less test code than today, not more, and one mechanism instead of
three.

## Testing

- `tests/test_config.py` — `resolve_data_dir()` returns an absolute path;
  defaults to the project root; an absolute configured value is used verbatim;
  a relative one resolves against the project root; a missing directory is
  created.
- `tests/test_cache_artifact.py` — keeps its existing assertions, which now
  pass by virtue of the conftest fixture rather than its own.
- **A leak canary in `tests/test_routes.py`**, as a test rather than a manual
  check: plant a file under `config._BASE_DIR / ".cache"`, exercise `/generate`
  and `GET /`, then assert the planted file still exists and that the project
  root gained no `prompts.db` and no new `.cache` entries. It must read
  `config._BASE_DIR` rather than a relative path, since the test's own working
  directory is `tmp_path`. This is the assertion whose absence let the original
  bug survive.

## Out of Scope

- Separate directories per artifact type (`cache_dir`, `log_dir` as distinct
  keys). One `data_dir` covers the need; split it if that ever changes.
- Moving existing data. An install that sets a new `data_dir` starts empty
  there; relocating `prompts.db` and `.cache` is a manual `mv`.
- Making the log path anything other than `logs/` under the data dir.
