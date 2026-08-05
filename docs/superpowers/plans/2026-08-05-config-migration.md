# Config Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate configuration from direnv-based `.envrc` to TOML files loaded by stdlib `tomllib`.

**Architecture:** Two TOML files — `settings.toml` (committed, non-secret config in nested sections) and `.secrets.toml` (gitignored, API keys only). The existing `Config` dataclass stays as the typed interface; only the loading mechanism changes from `os.environ` to `tomllib`. A `_load_toml` + `_merge` helper pair handles file loading and deep-merging.

**Tech Stack:** Python 3.11+ stdlib `tomllib`, TOML format, existing Flask/dataclass setup.

## Global Constraints

- Zero new dependencies — stdlib `tomllib` only
- `Config` dataclass fields and interface must not change (services untouched)
- `.secrets.toml` must be in `.gitignore` before any real keys are written
- All existing tests must pass after migration
- Use `key = value` with spaces around `=` for Python keyword arguments (user style preference)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `settings.toml` | Create | Committed non-secret config (nested sections) |
| `.secrets.toml` | Create | Gitignored API keys |
| `settings.example.toml` | Create | Committed reference for all backend options |
| `.secrets.toml.example` | Create | Committed minimal template |
| `config.py` | Modify | Add tomllib loader, rename `from_env()` → `from_settings()` |
| `app.py` | Modify | `Config.from_env()` → `Config.from_settings()`, port from TOML |
| `tests/test_config.py` | Modify | Rewrite tests for `from_settings()` |
| `.envrc` | Modify | Slim to `source venv/bin/activate` |
| `.gitignore` | Modify | Add `.secrets.toml` |

---

### Task 1: Create TOML config files

**Files:**
- Create: `settings.toml`
- Create: `.secrets.toml`
- Create: `settings.example.toml`
- Create: `.secrets.toml.example`

**Interfaces:**
- Produces: TOML files that `config.py` (Task 2) will load

- [ ] **Step 1: Create `settings.toml`**

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

- [ ] **Step 2: Create `.secrets.toml`**

Copy the actual API key values from the current `.envrc`:

```toml
[image]
api_key = "<copy IMAGE_API_KEY value from .envrc>"

[video]
api_key = "<copy VIDEO_API_KEY value from .envrc>"
```

- [ ] **Step 3: Create `settings.example.toml`**

```toml
# Settings reference — copy relevant sections to settings.toml
# API keys go in .secrets.toml (see .secrets.toml.example)

# ── fal.ai ──────────────────────────────────────────
# [image]
# backend = "fal"
# api_url = "https://fal.run"
# model = ["fal-ai/flux/schnell"]
# model_edit = ["fal-ai/gpt-image-1.5/edit"]

# ── OpenAI / OpenRouter ─────────────────────────────
# [image]
# backend = "openai"
# api_url = "https://api.openai.com/v1"
# model = ["dall-e-3"]
# model_edit = ["dall-e-2"]

# ── Azure OpenAI ────────────────────────────────────
# [image]
# backend = "azure"
# api_url = "https://<resource>.openai.azure.com/"
# model = ["gpt-image-1.5"]
# model_edit = ["gpt-image-1.5"]
# api_version = "2025-04-01-preview"

# [video]
# backend = "azure"
# api_url = "https://<resource>.openai.azure.com"
# model_image = ["sora-2"]
# model_text = ["sora-2"]
# azure_path = "openai/deployments/{deployment}/videos/generations"

# ── DashScope (Alibaba Cloud) ───────────────────────
# [image]
# backend = "dashscope"
# api_url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
# model = ["wan2.7-image", "wan2.7-image-pro"]
# model_edit = ["wan2.7-image"]

# [video]
# backend = "dashscope"
# api_url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
# model_image = ["wan2.7-r2v"]
# model_text = ["wan2.7-t2v"]
```

- [ ] **Step 4: Create `.secrets.toml.example`**

```toml
# Copy to .secrets.toml and fill in your keys

# [image]
# api_key = "your-api-key"

# [video]
# api_key = "your-api-key"
```

- [ ] **Step 5: Commit**

```bash
git add settings.toml settings.example.toml .secrets.toml.example
git commit -m "feat: add TOML config files (settings + examples)"
```

Note: `.secrets.toml` is NOT committed yet — `.gitignore` update happens in Task 4.

---

### Task 2: Rewrite `config.py` for tomllib loading

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `settings.toml` and `.secrets.toml` from Task 1
- Produces: `Config.from_settings()` classmethod, `_settings` module-level dict, `_load_toml()`, `_merge()`, `_require()`, `_get()`, `_parse_list()`

- [ ] **Step 1: Write failing tests for the new loading mechanism**

Replace the contents of `tests/test_config.py`:

```python
import os
import pytest
import tomllib
from config import Config, _parse_list, _load_toml, _merge, _require, _get


# --- unit tests for _parse_list ---

def test_parse_list_single():
    assert _parse_list("model-a") == ["model-a"]


def test_parse_list_multiple():
    assert _parse_list("model-a, model-b , model-c") == ["model-a", "model-b", "model-c"]


def test_parse_list_strips_whitespace():
    assert _parse_list("  x  ,  y  ") == ["x", "y"]


def test_parse_list_ignores_empty_segments():
    assert _parse_list("a,,b") == ["a", "b"]


def test_parse_list_from_toml_list():
    assert _parse_list(["model-a", "model-b"]) == ["model-a", "model-b"]


# --- unit tests for _load_toml ---

def test_load_toml_missing_file(tmp_path):
    result = _load_toml(str(tmp_path / "nonexistent.toml"))
    assert result == {}


def test_load_toml_existing_file(tmp_path):
    toml_file = tmp_path / "test.toml"
    toml_file.write_text('[section]\nkey = "value"\n')
    result = _load_toml(str(toml_file))
    assert result == {"section": {"key": "value"}}


# --- unit tests for _merge ---

def test_merge_disjoint():
    assert _merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_merge_override():
    assert _merge({"a": 1}, {"a": 2}) == {"a": 2}


def test_merge_deep():
    base = {"s": {"a": 1, "b": 2}}
    override = {"s": {"b": 3, "c": 4}}
    assert _merge(base, override) == {"s": {"a": 1, "b": 3, "c": 4}}


# --- unit tests for _require / _get (via _settings patching) ---

def test_require_present(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": "value"}})
    assert _require("section", "key") == "value"


def test_require_missing(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {})
    with pytest.raises(EnvironmentError, match="section.*key"):
        _require("section", "key")


def test_require_empty(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": "   "}})
    with pytest.raises(EnvironmentError, match="section.*key"):
        _require("section", "key")


def test_require_none(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": None}})
    with pytest.raises(EnvironmentError, match="section.*key"):
        _require("section", "key")


def test_get_present(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": "value"}})
    assert _get("section", "key") == "value"


def test_get_missing_default(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {})
    assert _get("section", "key", "fallback") == "fallback"


def test_get_none_returns_default(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": None}})
    assert _get("section", "key", "fallback") == "fallback"


# --- Config.from_settings ---

def _patch_settings(monkeypatch, settings_data, secrets_data=None):
    """Patch config._settings with merged test data."""
    import config as cfg_module
    base = settings_data or {}
    override = secrets_data or {}
    merged = _merge(base, override)
    monkeypatch.setattr(cfg_module, "_settings", merged)


def test_from_settings_single_models(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "api_url": "https://img.example.com/v1",
            "model": ["my/image-model"],
            "model_edit": ["my/edit-model"],
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["my/vid-img-model"],
            "model_text": ["my/vid-txt-model"],
        },
    }, {
        "image": {"api_key": "img-key"},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert cfg.image_model == ["my/image-model"]
    assert cfg.image_model_edit == ["my/edit-model"]
    assert cfg.video_model_image == ["my/vid-img-model"]
    assert cfg.video_model_text == ["my/vid-txt-model"]
    assert cfg.secret_key == "s3cr3t"


def test_from_settings_multi_models(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "api_url": "https://img.example.com/v1",
            "model": ["model-a", "model-b"],
            "model_edit": ["my/edit-model"],
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["my/vid-img-model"],
            "model_text": ["vid-x", "vid-y", "vid-z"],
        },
    }, {
        "image": {"api_key": "img-key"},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert cfg.image_model == ["model-a", "model-b"]
    assert cfg.video_model_text == ["vid-x", "vid-y", "vid-z"]


def test_from_settings_missing_required(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "api_url": "https://img.example.com/v1",
            "model": ["m"],
            "model_edit": ["m"],
            # missing api_key
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "video": {"api_key": "vid-key"},
    })
    with pytest.raises(EnvironmentError, match="image.*api_key"):
        Config.from_settings()


def test_from_settings_defaults(tmp_path, monkeypatch):
    """Optional fields use defaults when not in TOML."""
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "api_url": "https://img.example.com/v1",
            "model": ["m"],
            "model_edit": ["m"],
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"api_key": "img-key"},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert cfg.image_backend == "openai"
    assert cfg.video_backend == "fal"
    assert cfg.image_api_version == "2024-02-01"
    assert cfg.video_api_version == "2025-04-01-preview"
    assert cfg.sd_api_url == ""
    assert cfg.sd_model == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_config.py -v`
Expected: FAIL — `_load_toml`, `_merge`, `_require`, `_get`, `from_settings` not defined.

- [ ] **Step 3: Rewrite `config.py`**

Replace the entire contents of `config.py`:

```python
import tomllib
from dataclasses import dataclass
from pathlib import Path


def _load_toml(path: str) -> dict:
    p = Path(path)
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


def _require(section: str, key: str) -> str:
    try:
        val = _settings[section][key]
    except KeyError:
        raise EnvironmentError(f"Required config [{section}].{key} missing")
    if val is None or not str(val).strip():
        raise EnvironmentError(f"Required config [{section}].{key} is empty")
    return str(val).strip()


def _get(section: str, key: str, default: str = "") -> str:
    try:
        val = _settings[section][key]
    except KeyError:
        return default
    return str(val).strip() if val is not None else default


def _parse_list(val) -> list[str]:
    """Handle both TOML lists (list) and comma-separated strings."""
    if isinstance(val, list):
        return val
    return [m.strip() for m in str(val).split(",") if m.strip()]


@dataclass
class Config:
    image_api_url: str
    image_api_key: str
    image_model: list[str]        # text-to-image models; first is default
    image_model_edit: list[str]   # image+prompt-to-image models; first is default
    image_backend: str            # "openai", "azure", "fal", or "dashscope"
    image_api_version: str        # Azure API version (only used for azure backend)
    video_backend: str            # "fal", "azure", or "dashscope"
    video_api_url: str
    video_api_key: str
    video_api_version: str        # Azure API version (only used for azure backend)
    video_azure_path: str         # Azure path template
    video_model_image: list[str]  # image-to-video models; first is default
    video_model_text: list[str]   # text-to-video models; first is default
    secret_key: str
    sd_api_url: str               # InvokeAI base URL, empty = disabled
    sd_model: str                 # InvokeAI model name

    @classmethod
    def from_settings(cls) -> "Config":
        return cls(
            image_api_url = _require("image", "api_url"),
            image_api_key = _require("image", "api_key"),
            image_model = _parse_list(_require("image", "model")),
            image_model_edit = _parse_list(_require("image", "model_edit")),
            image_backend = _get("image", "backend", "openai"),
            image_api_version = _get("image", "api_version", "2024-02-01"),
            video_backend = _get("video", "backend", "fal"),
            video_api_url = _require("video", "api_url"),
            video_api_key = _require("video", "api_key"),
            video_api_version = _get("video", "api_version", "2025-04-01-preview"),
            video_azure_path = _get(
                "video", "azure_path",
                "openai/deployments/{deployment}/videos/generations",
            ),
            video_model_image = _parse_list(_require("video", "model_image")),
            video_model_text = _parse_list(_require("video", "model_text")),
            secret_key = _require("flask", "secret_key"),
            sd_api_url = _get("sd", "api_url", ""),
            sd_model = _get("sd", "model", ""),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_config.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: rewrite config.py to load from TOML via tomllib"
```

---

### Task 3: Update `app.py` for new config loading

**Files:**
- Modify: `app.py:8,42,267`

**Interfaces:**
- Consumes: `Config.from_settings()` from Task 2

- [ ] **Step 1: Update `app.py` imports and port loading (line 8)**

Replace line 8:

```python
_port = os.environ.get("PORT", "5000")
```

With:

```python
from config import _settings
_port = str(_settings.get("flask", {}).get("port", 5000))
```

- [ ] **Step 2: Update `create_app` (line 42)**

Replace:

```python
        cfg = Config.from_env()
```

With:

```python
        cfg = Config.from_settings()
```

- [ ] **Step 3: Update CLI port fallback (line 267)**

Replace:

```python
    port = args.port if args.port is not None else int(os.environ.get("PORT", 5000))
```

With:

```python
    port = args.port if args.port is not None else int(_settings.get("flask", {}).get("port", 5000))
```

- [ ] **Step 4: Run full test suite**

Run: `source venv/bin/activate && python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 5: Verify no remaining `os.environ` config reads**

Run: `grep -rn 'os\.environ' --include='*.py' | grep -v __pycache__ | grep -v venv`
Expected: Only `probe_sora.py` (standalone script, not part of the app).

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "refactor: app.py uses Config.from_settings() and TOML port"
```

---

### Task 4: Update `.gitignore` and `.envrc`

**Files:**
- Modify: `.gitignore`
- Modify: `.envrc`

**Interfaces:**
- Consumes: `.secrets.toml` from Task 1

- [ ] **Step 1: Add `.secrets.toml` to `.gitignore`**

Append to `.gitignore`:

```
.secrets.toml
```

The file should now contain:

```
.envrc*
.cache/
.secrets.toml
```

- [ ] **Step 2: Verify `.secrets.toml` is ignored**

Run: `git status --short .secrets.toml`
Expected: No output (file is ignored).

- [ ] **Step 3: Slim down `.envrc`**

Replace the entire contents of `.envrc` with:

```bash
source venv/bin/activate
```

- [ ] **Step 4: Reload direnv and verify**

Run: `direnv allow`
Expected: No errors. `echo $IMAGE_API_URL` should be empty (no longer set by `.envrc`).

- [ ] **Step 5: Commit**

```bash
git add .gitignore .envrc
git commit -m "chore: slim .envrc to venv activation, gitignore .secrets.toml"
```

---

### Task 5: Smoke test the running app

**Files:**
- None (manual verification)

**Interfaces:**
- Consumes: All previous tasks

- [ ] **Step 1: Start the app**

Run: `source venv/bin/activate && python app.py`
Expected: App starts on port 5005, no config errors in logs.

- [ ] **Step 2: Verify config loaded correctly**

Check the log file: `tail -5 logs/app-5005.log`
Expected: No `EnvironmentError` or missing config messages.

- [ ] **Step 3: Stop the app**

Press Ctrl+C.

- [ ] **Step 4: Run full test suite one final time**

Run: `source venv/bin/activate && python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 5: Final commit (if any cleanup needed)**

If everything works, no commit needed. If any adjustments were made:

```bash
git add -A
git commit -m "fix: post-migration config adjustments"
```
