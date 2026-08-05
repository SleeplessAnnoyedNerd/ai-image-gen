# Config Migration: .envrc → TOML + tomllib

## Overview

Replace the direnv-based `.envrc` configuration with TOML config files loaded by Python's stdlib `tomllib`. Secrets go in a dedicated `.secrets.toml` (gitignored), non-secret config in `settings.toml` (committed).

## Goals

1. **Remove plaintext secrets from `.envrc`** — API keys move to `.secrets.toml` (gitignored)
2. **Version-control non-secret config** — `settings.toml` is committed, making the repo self-documenting
3. **Cleaner config structure** — nested TOML sections instead of flat env vars with shell interpolation
4. **Zero new dependencies** — use stdlib `tomllib` (Python 3.11+), not dynaconf
5. **Minimal code changes** — keep the `Config` dataclass interface, only change the loading mechanism

## Current State

- `.envrc` (~170 lines, gitignored): direnv + venv activation + ~30 env vars including plaintext API keys + commented-out alternative configs + shell variable interpolation (`${AC_URL}`, `${AC_TOKEN}`)
- `config.py`: clean dataclass with `from_env()` reading from `os.environ`
- Usage: `Config.from_env()` called once in `app.py`, passed to services (`image_gen.py`, `video_gen.py`, `sd_gen.py`)

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| direnv after migration | Keep for venv activation only | `.envrc` = `source venv/bin/activate` |
| Config format | TOML with nested sections | `[flask]`, `[image]`, `[video]`, `[sd]` |
| Secret/non-secret split | `settings.toml` committed, `.secrets.toml` gitignored | API keys out of git |
| Reference docs | `settings.example.toml` (committed) | Documents all backend options |
| Config loader | stdlib `tomllib` | Zero dependency, ~15 lines, no magic |
| Config interface | Keep `Config` dataclass | Services unchanged |

## File Structure

```
.envrc                      # MODIFIED — 1 line: source venv/bin/activate
settings.toml               # NEW — committed, non-secret config
.secrets.toml               # NEW — gitignored, API keys only
settings.example.toml       # NEW — committed, documents all backends
.secrets.toml.example       # NEW — committed, minimal template
config.py                   # MODIFIED — tomllib loader + from_settings()
.gitignore                  # MODIFIED — add .secrets.toml
```

## TOML File Contents

### `settings.toml` (committed, active config)

```toml
[flask]
secret_key = "SpayzDajoz"
port = 5005

[image]
backend = "dashscope"
api_url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
model = ["wan2.6-image", "wan2.6-image-pro"]
model_edit = ["wan2.6-image"]
# api_version = "2024-02-01"  # only for azure backend

[video]
backend = "dashscope"
api_url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
model_image = ["wan2.7-r2v"]
model_text = ["wan2.7-t2v"]
# api_version = "2025-04-01-preview"  # only for azure backend
# azure_path = "openai/deployments/{deployment}/videos/generations"

[sd]
api_url = "http://192.168.0.78:9090"
model = "Juggernaut XL v9"
```

### `.secrets.toml` (gitignored)

```toml
[image]
api_key = "sk-ws-..."

[video]
api_key = "sk-ws-..."
```

### `settings.example.toml` (committed, reference)

Documents all backend options (fal, OpenAI, Azure, DashScope) as commented-out TOML sections.

### `.secrets.toml.example` (committed, minimal)

```toml
# Copy to .secrets.toml and fill in your keys
# [image]
# api_key = "your-api-key"
# [video]
# api_key = "your-api-key"
```

## `config.py` Changes

### Loading code (new)

```python
import tomllib
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent


def _load_toml(path: str) -> dict:
    p = _BASE_DIR / path
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def _merge(base: dict, override: dict) -> dict:
    result = {**base}
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _merge(result[key], val)
        else:
            result[key] = val
    return result


_settings = _merge(_load_toml("settings.toml"), _load_toml(".secrets.toml"))
```

### Helper functions (modified)

```python
def _require(section: str, key: str):
    """Return raw value. Raises EnvironmentError if missing/empty."""
    try:
        val = _settings[section][key]
    except KeyError:
        raise EnvironmentError(f"Required config [{section}].{key} missing")
    if val is None:
        raise EnvironmentError(f"Required config [{section}].{key} is empty")
    if isinstance(val, str) and not val.strip():
        raise EnvironmentError(f"Required config [{section}].{key} is empty")
    return val


def _get(section: str, key: str, default=""):
    """Return raw value, or default if missing/None."""
    try:
        val = _settings[section][key]
    except KeyError:
        return default
    if val is None:
        return default
    return val


def _parse_list(val) -> list[str]:
    if isinstance(val, list):
        return val
    return [m.strip() for m in str(val).split(",") if m.strip()]
```

### Config class

The `Config` dataclass fields stay the same. Only the factory method changes:

- `from_env()` → `from_settings()`
- Reads from `_settings` dict (tomllib-loaded) instead of `os.environ`
- `_require()` takes `(section, key)` instead of env var name
- `_get()` replaces `os.environ.get()` for optional values

### `app.py` change

```python
# Before
config = Config.from_env()

# After
config = Config.from_settings()
```

## What Doesn't Change

- `Config` dataclass fields
- All service files (`image_gen.py`, `video_gen.py`, `sd_gen.py`)
- All templates
- All routes and handlers

## Migration Steps

1. Create `settings.toml`, `.secrets.toml`, `settings.example.toml`, `.secrets.toml.example`
2. Update `config.py` — add tomllib loader, rename `from_env()` to `from_settings()`
3. Update `app.py` — call `Config.from_settings()` instead of `Config.from_env()`
4. Slim `.envrc` to `source venv/bin/activate`
5. Update `.gitignore` — add `.secrets.toml`
6. Update tests to use `from_settings()`
7. Verify: `grep -rn os.environ` — no config reads remain outside `app.py` port handling

## Security Notes

- `flask.secret_key` is committed in `settings.toml` — it's for session signing in dev, not a real secret
- API keys go in `.secrets.toml` only — never committed
- `sd.api_url` (local network IP `192.168.0.78`) is committed — acceptable for private repo
- Old `.envrc` with plaintext keys stays in git history — rotate keys if repo was ever public

## Edge Cases Handled

- **Missing `.secrets.toml`**: `_load_toml()` returns `{}` — app fails at `_require()` with clear error
- **Malformed TOML**: `tomllib.TOMLDecodeError` propagates at import time with clear traceback
- **Empty TOML file**: Valid TOML (returns empty dict), handled by `_load_toml()`
- **CWD-independent paths**: `_load_toml()` resolves paths relative to `config.py` via `_BASE_DIR`, not CWD
- **Present-but-empty values**: `_require()` checks `val is None` and empty string (only for `str` type)
- **TOML lists preserved**: `_require()` returns raw values — lists stay as lists, not `str()`-converted
- **TOML lists vs comma-separated strings**: `_parse_list()` handles both (TOML lists are native, comma-separated for migration safety)
- **`KeyError` vs `EnvironmentError`**: `_require()` catches `KeyError` and re-raises as `EnvironmentError` with a clear message
