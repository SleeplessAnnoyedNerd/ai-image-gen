# Multi-Backend Image Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `[image]` in `settings.toml` hold multiple backends (fal, dashscope, azure, openai) simultaneously, and let the user pick which one to use per request from a dropdown in the UI instead of editing config + restarting.

**Architecture:** `config.py` discovers backend subtables dynamically under `[image]`, builds an `ImageBackend` per subtable that has a non-empty `api_key`, and exposes them as `cfg.image_backends: dict[str, ImageBackend]` plus `cfg.image_default_backend: str`. `image_gen.py`'s `generate_image()` takes a `backend` parameter and resolves the matching `ImageBackend` before dispatching to the existing per-engine `_generate_*` functions (now narrowed to take `ImageBackend` instead of the whole `Config`). `app.py`'s `/generate` route reads `image_backend` from the submitted form and validates it; `index()` passes the backend→model map to the template. `templates/index.html` gets a new `Image Backend` `<select>` that drives the existing model dropdowns via a small JS rebuild on change. Scope is image generation only — `[video]` and `[sd]` are untouched.

**Tech Stack:** Python 3.11+ stdlib `tomllib`, Flask, Jinja2, vanilla JS (no build step), pytest.

## Global Constraints

- Spec source of truth: `docs/superpowers/specs/2026-08-10-multi-backend-image-config-design.md` — every task below implements one of its sections.
- Scope is **image generation only**. Do not touch `[video]`/`[sd]` config shape, `video_gen.py`, or `sd_gen.py`.
- `.secrets.toml` may only ever contain `api_key` per backend — never `api_url`/`model`/etc (spec: "Config Shape" section).
- Indentation: 4 spaces in Python (existing codebase convention — don't reformat to 2-space).
- No backward-compatibility shim for the old flat `image_api_url`/`image_api_key`/`image_backend`/`image_model`/`image_model_edit`/`image_api_version` fields — this is a single-user app, delete them outright.

---

### Task 1: `config.py` — `ImageBackend` dataclass and multi-backend loading

**Files:**
- Modify: `config.py` (full rewrite of the `Config` dataclass and everything below `_parse_list`)
- Modify: `tests/conftest.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `ImageBackend` dataclass (`name`, `api_url`, `api_key`, `model: list[str]`, `model_edit: list[str]`, `api_version`), importable as `from config import ImageBackend`.
- Produces: `Config.image_backends: dict[str, ImageBackend]` and `Config.image_default_backend: str`, replacing the old `image_api_url`/`image_api_key`/`image_backend`/`image_model`/`image_model_edit`/`image_api_version` fields (all deleted).
- Produces: `cfg` pytest fixture in `tests/conftest.py` built on the new shape, with a single `"openai"` backend (`model=["test/image-model"]`, `model_edit=["test/image-edit-model"]`) as `image_default_backend`. Later tasks' tests rely on this fixture.

- [ ] **Step 1: Write the new `tests/test_config.py` image-related tests (failing)**

Replace the `--- Config.from_settings ---` section (everything from `def _patch_settings` to the end of the file) with:

```python
def _patch_settings(monkeypatch, settings_data, secrets_data=None):
    """Patch config._settings with merged test data."""
    import config as cfg_module
    base = settings_data or {}
    override = secrets_data or {}
    merged = _merge(base, override)
    monkeypatch.setattr(cfg_module, "_settings", merged)


def test_from_settings_single_backend_single_models(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "default_backend": "openai",
            "openai": {
                "api_url": "https://img.example.com/v1",
                "model": ["my/image-model"],
                "model_edit": ["my/edit-model"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["my/vid-img-model"],
            "model_text": ["my/vid-txt-model"],
        },
    }, {
        "image": {"openai": {"api_key": "img-key"}},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert set(cfg.image_backends.keys()) == {"openai"}
    bc = cfg.image_backends["openai"]
    assert bc.model == ["my/image-model"]
    assert bc.model_edit == ["my/edit-model"]
    assert bc.api_key == "img-key"
    assert cfg.image_default_backend == "openai"
    assert cfg.video_model_image == ["my/vid-img-model"]
    assert cfg.video_model_text == ["my/vid-txt-model"]
    assert cfg.secret_key == "s3cr3t"


def test_from_settings_multiple_backends(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "default_backend": "fal",
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["model-a", "model-b"],
                "model_edit": ["edit-a"],
            },
            "fal": {
                "api_url": "https://fal.run",
                "model": ["fal-model"],
                "model_edit": ["fal-edit-model"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["my/vid-img-model"],
            "model_text": ["vid-x", "vid-y", "vid-z"],
        },
    }, {
        "image": {
            "dashscope": {"api_key": "ds-key"},
            "fal": {"api_key": "fal-key"},
        },
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert set(cfg.image_backends.keys()) == {"dashscope", "fal"}
    assert cfg.image_backends["dashscope"].model == ["model-a", "model-b"]
    assert cfg.image_backends["fal"].model == ["fal-model"]
    assert cfg.image_default_backend == "fal"
    assert cfg.video_model_text == ["vid-x", "vid-y", "vid-z"]


def test_from_settings_backend_without_api_key_excluded(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "default_backend": "dashscope",
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["m"],
                "model_edit": ["m"],
            },
            "fal": {
                "api_url": "https://fal.run",
                "model": ["fal-model"],
                "model_edit": ["fal-edit"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "ds-key"}},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert set(cfg.image_backends.keys()) == {"dashscope"}


def test_from_settings_default_backend_falls_back(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["m"],
                "model_edit": ["m"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "ds-key"}},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert cfg.image_default_backend == "dashscope"


def test_from_settings_no_image_backends_raises(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["m"],
                "model_edit": ["m"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "video": {"api_key": "vid-key"},
    })
    with pytest.raises(EnvironmentError, match=r"No \[image\.\*\] backend"):
        Config.from_settings()


def test_from_settings_backend_missing_models_raises(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "api_url": "https://img.example.com/v1",
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "ds-key"}},
        "video": {"api_key": "vid-key"},
    })
    with pytest.raises(EnvironmentError, match="dashscope.*model"):
        Config.from_settings()


def test_from_settings_backend_missing_api_url_raises(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "model": ["m"],
                "model_edit": ["m"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "ds-key"}},
        "video": {"api_key": "vid-key"},
    })
    with pytest.raises(EnvironmentError, match="dashscope.*api_url"):
        Config.from_settings()


def test_from_settings_defaults(monkeypatch):
    """Optional fields use defaults when not in TOML."""
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["m"],
                "model_edit": ["m"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "img-key"}},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert cfg.image_backends["dashscope"].api_version == "2024-02-01"
    assert cfg.video_backend == "fal"
    assert cfg.video_api_version == "2025-04-01-preview"
    assert cfg.sd_api_url == ""
    assert cfg.sd_model == ""


def test_from_settings_real_toml_files(tmp_path, monkeypatch):
    """Write actual TOML files and verify end-to-end loading."""
    import config as cfg_module

    settings_file = tmp_path / "settings.toml"
    settings_file.write_text(
        '[flask]\n'
        'secret_key = "test-secret"\n'
        'port = 5005\n'
        '\n'
        '[image]\n'
        'default_backend = "fal"\n'
        '\n'
        '[image.fal]\n'
        'api_url = "https://img.example.com"\n'
        'model = ["model-a", "model-b"]\n'
        'model_edit = ["edit-model"]\n'
        '\n'
        '[video]\n'
        'backend = "fal"\n'
        'api_url = "https://vid.example.com"\n'
        'model_image = ["vid-img"]\n'
        'model_text = ["vid-txt"]\n'
    )
    secrets_file = tmp_path / ".secrets.toml"
    secrets_file.write_text(
        '[image.fal]\n'
        'api_key = "real-img-key"\n'
        '\n'
        '[video]\n'
        'api_key = "real-vid-key"\n'
    )

    merged = _merge(
        _load_toml(str(settings_file)),
        _load_toml(str(secrets_file)),
    )
    monkeypatch.setattr(cfg_module, "_settings", merged)

    cfg = Config.from_settings()
    assert cfg.image_backends["fal"].api_key == "real-img-key"
    assert cfg.video_api_key == "real-vid-key"
    assert cfg.image_backends["fal"].model == ["model-a", "model-b"]
    assert cfg.image_default_backend == "fal"
    assert cfg.secret_key == "test-secret"
```

This deletes `test_from_settings_single_models`, `test_from_settings_multi_models`, and `test_from_settings_missing_required` (superseded by the tests above) and keeps everything above `_patch_settings` (the `_parse_list`/`_load_toml`/`_merge`/`_require`/`_get` unit tests) unchanged.

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'image_backends'` (the old `Config` dataclass doesn't have this field yet).

- [ ] **Step 3: Rewrite `config.py`**

Replace everything from the `@dataclass` for `Config` (currently starting at line 62) to the end of the file with:

```python
@dataclass
class ImageBackend:
    name: str
    api_url: str
    api_key: str
    model: list[str]         # text-to-image models; first is default
    model_edit: list[str]    # image+prompt-to-image models; first is default
    api_version: str         # only read by the azure backend; defaults to "2024-02-01" for all backends


def _load_image_backends() -> tuple[dict[str, "ImageBackend"], str]:
    """Build an ImageBackend per [image.<name>] subtable with a non-empty api_key.
    Returns (backends dict, default_backend name)."""
    image_section = _settings.get("image", {})
    backends: dict[str, ImageBackend] = {}
    for name, val in image_section.items():
        if not isinstance(val, dict):
            continue  # scalar keys like default_backend
        api_key = str(val.get("api_key", "")).strip()
        if not api_key:
            continue  # unconfigured backend, hide from selection
        api_url = str(val.get("api_url", "")).strip()
        if not api_url:
            raise EnvironmentError(f"[image.{name}] has an api_key but is missing api_url")
        model = _parse_list(val.get("model", []))
        model_edit = _parse_list(val.get("model_edit", []))
        if not model or not model_edit:
            raise EnvironmentError(f"[image.{name}] has an api_key but is missing model/model_edit")
        backends[name] = ImageBackend(
            name=name,
            api_url=api_url,
            api_key=api_key,
            model=model,
            model_edit=model_edit,
            api_version=str(val.get("api_version", "2024-02-01")),
        )
    if not backends:
        raise EnvironmentError("No [image.*] backend configured with an api_key")

    default_backend = str(image_section.get("default_backend", ""))
    if default_backend not in backends:
        default_backend = next(iter(backends))
    return backends, default_backend


@dataclass
class Config:
    image_backends: dict[str, ImageBackend]  # keyed by backend name; only backends with a non-empty api_key
    image_default_backend: str               # key into image_backends
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
        image_backends, image_default_backend = _load_image_backends()
        return cls(
            image_backends = image_backends,
            image_default_backend = image_default_backend,
            video_backend = str(_get("video", "backend", "fal")),
            video_api_url = str(_require("video", "api_url")),
            video_api_key = str(_require("video", "api_key")),
            video_api_version = str(_get("video", "api_version", "2025-04-01-preview")),
            video_azure_path = str(_get(
                "video", "azure_path",
                "openai/deployments/{deployment}/videos/generations",
            )),
            video_model_image = _parse_list(_require("video", "model_image")),
            video_model_text = _parse_list(_require("video", "model_text")),
            secret_key = str(_require("flask", "secret_key")),
            sd_api_url = str(_get("sd", "api_url", "")),
            sd_model = str(_get("sd", "model", "")),
        )
```

The `import tomllib`, `from dataclasses import dataclass`, `from pathlib import Path`, `_BASE_DIR`, `_load_toml`, `_merge`, `_settings`, `_require`, `_get`, `_parse_list` at the top of the file are unchanged.

- [ ] **Step 4: Update `tests/conftest.py`**

```python
import pytest
from app import create_app
from config import Config, ImageBackend


@pytest.fixture
def cfg():
    return Config(
        image_backends={
            "openai": ImageBackend(
                name="openai",
                api_url="https://image.example.com/v1",
                api_key="test-image-key",
                model=["test/image-model"],
                model_edit=["test/image-edit-model"],
                api_version="2024-02-01",
            ),
        },
        image_default_backend="openai",
        video_backend="fal",
        video_api_url="https://video.example.com",
        video_api_key="test-video-key",
        video_api_version="2025-04-01-preview",
        video_azure_path="openai/deployments/{deployment}/videos/generations",
        video_model_image=["test/video-image-model"],
        video_model_text=["test/video-text-model"],
        secret_key="test-secret",
        sd_api_url="",
        sd_model="",
    )


@pytest.fixture
def app(cfg):
    application = create_app(cfg)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()
```

- [ ] **Step 5: Run tests/test_config.py to confirm it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS, all tests green.

Note: `pytest` on the *full* suite will now fail in `tests/test_image_gen.py` and `tests/test_routes.py` — they still construct `Config(...)` with the old flat `image_api_url`/etc. fields directly. That's expected; Tasks 2 and 3 fix them. Don't chase those failures in this task.

- [ ] **Step 6: Commit**

```bash
git add config.py tests/conftest.py tests/test_config.py
git commit -m "feat: support multiple image backends in config.py"
```

---

### Task 2: `services/image_gen.py` — backend-aware dispatch

**Files:**
- Modify: `services/image_gen.py`
- Modify: `tests/test_image_gen.py`

**Interfaces:**
- Consumes: `Config.image_backends`, `Config.image_default_backend`, `ImageBackend` from Task 1.
- Produces: `generate_image(cfg, prompt, images=None, backend=None, model=None, model_edit=None) -> bytes` — `backend` is a new parameter; when omitted, defaults to `cfg.image_default_backend`. This signature is consumed by `app.py` in Task 3.

- [ ] **Step 1: Rewrite the Config-construction helpers and assertions in `tests/test_image_gen.py` (failing)**

Replace `_dashscope_cfg()`:

```python
from config import Config, ImageBackend


def _dashscope_cfg():
    """Helper to create a Config with a dashscope backend as default."""
    return Config(
        image_backends={
            "dashscope": ImageBackend(
                name="dashscope",
                api_url="https://ws-c2xbh4slyhwu4ifn.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                api_key="sk-test-key",
                model=["wan2.7-image"],
                model_edit=["wan2.7-image-pro"],
                api_version="",
            ),
        },
        image_default_backend="dashscope",
        video_backend="fal", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=[""], video_model_text=[""],
        secret_key="test", sd_api_url="", sd_model="",
    )
```

Replace the four `cfg.image_model[0]` / `cfg.image_model_edit[0]` assertions in `test_text_to_image_uses_cfg_default` and `test_image_to_image_uses_cfg_edit_default`:

```python
def test_text_to_image_uses_cfg_default(cfg):
    """When no model param passed, use the default backend's model[0]."""
    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.generate.return_value = _make_mock_response(FAKE_B64)

        result = generate_image(cfg, prompt="a cat")

        call_kwargs = instance.images.generate.call_args.kwargs
        assert call_kwargs["model"] == cfg.image_backends[cfg.image_default_backend].model[0]
        assert result == FAKE_PNG


def test_image_to_image_uses_cfg_edit_default(cfg):
    """When no model_edit param passed, use the default backend's model_edit[0]."""
    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.edit.return_value = _make_mock_response(FAKE_B64)

        result = generate_image(cfg, prompt="make it blue", images=[b"jpeg-data"])

        call_kwargs = instance.images.edit.call_args.kwargs
        assert call_kwargs["model"] == cfg.image_backends[cfg.image_default_backend].model_edit[0]
        assert result == FAKE_PNG
```

Replace `test_dashscope_missing_config_raises`:

```python
def test_dashscope_missing_config_raises():
    """DashScope backend: raises ValueError when api_url is empty."""
    cfg = Config(
        image_backends={
            "dashscope": ImageBackend(
                name="dashscope", api_url="", api_key="",
                model=["wan2.7-image"], model_edit=["wan2.7-image-pro"],
                api_version="",
            ),
        },
        image_default_backend="dashscope",
        video_backend="fal", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=[""], video_model_text=[""],
        secret_key="test", sd_api_url="", sd_model="",
    )
    with pytest.raises(ValueError, match="IMAGE_API_URL"):
        generate_image(cfg, prompt="a cat")
```

Replace `test_non_dashscope_receives_first_image_only`:

```python
def test_non_dashscope_receives_first_image_only():
    """OpenAI backend: only images[0] is passed when multiple provided."""
    cfg_openai = Config(
        image_backends={
            "openai": ImageBackend(
                name="openai", api_url="https://api.openai.com/v1", api_key="sk-test",
                model=["dall-e-3"], model_edit=["gpt-image-1"],
                api_version="",
            ),
        },
        image_default_backend="openai",
        video_backend="fal", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=[""], video_model_text=[""],
        secret_key="test", sd_api_url="", sd_model="",
    )

    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.edit.return_value = _make_mock_response(FAKE_B64)

        generate_image(cfg_openai, prompt="edit", images=[b"first-img", b"second-img", b"third-img"])

        call_kwargs = instance.images.edit.call_args.kwargs
        img_io = call_kwargs["image"]
        assert img_io.read() == b"first-img"
```

All other tests in the file (`test_text_to_image_uses_explicit_model`, `test_image_to_image_uses_explicit_model_edit`, the `test_dashscope_*` payload tests using `_dashscope_cfg()`, the `_mime_and_b64` tests) are unchanged — they already call `generate_image(cfg, ...)` without touching the removed flat fields directly.

- [ ] **Step 2: Run to confirm it fails**

Run: `pytest tests/test_image_gen.py -v`
Expected: FAIL — `TypeError: Config.__init__() got an unexpected keyword argument 'image_backends'` (current `image_gen.py` and its runtime `Config` still expect the old shape — actually by this point `config.py` already has the new shape from Task 1, so the failure will instead come from `generate_image()`'s internals still referencing `cfg.image_api_url`/`cfg.image_model` etc., which no longer exist → `AttributeError: 'Config' object has no attribute 'image_model'`).

- [ ] **Step 3: Rewrite `services/image_gen.py`**

```python
import base64
import io
import requests as _requests
from loguru import logger
from openai import OpenAI, AzureOpenAI
from config import Config, ImageBackend


def _mime_and_b64(img_bytes: bytes) -> str:
    """Return data URI string with best-effort MIME detection."""
    if ((len(img_bytes) >= 4) and (img_bytes[:4] == b'\x89PNG')):
        mime = "image/png"
    elif ((len(img_bytes) >= 3) and (img_bytes[:3] == b'\xff\xd8\xff')):
        mime = "image/jpeg"
    elif ((len(img_bytes) >= 12) and (img_bytes[:4] == b'RIFF') and (img_bytes[8:12] == b'WEBP')):
        mime = "image/webp"
    elif ((len(img_bytes) >= 6) and (img_bytes[:6] in (b'GIF87a', b'GIF89a'))):
        mime = "image/gif"
    else:
        mime = "application/octet-stream"
    b64 = base64.b64encode(img_bytes).decode()
    return f"data:{mime};base64,{b64}"


def generate_image(
    cfg: Config,
    prompt: str,
    images: list[bytes] | None = None,
    backend: str | None = None,
    model: str | None = None,
    model_edit: str | None = None,
) -> bytes:
    images = images or []
    backend = backend or cfg.image_default_backend
    bc = cfg.image_backends[backend]
    model = model or bc.model[0]
    model_edit = model_edit or bc.model_edit[0]
    first = images[0] if images else None
    if backend == "fal":
        return _generate_fal(bc, prompt, first, model, model_edit)
    if backend == "azure":
        return _generate_azure(bc, prompt, first, model, model_edit)
    if backend == "dashscope":
        return _generate_dashscope(bc, prompt, images, model, model_edit)
    return _generate_openai(bc, prompt, first, model, model_edit)


def _generate_azure(
    bc: ImageBackend,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
    model_edit: str,
) -> bytes:
    logger.info(
        "Azure config | endpoint={} api_version={} model={} model_edit={}",
        bc.api_url, bc.api_version, model, model_edit,
    )
    client = AzureOpenAI(
        api_key=bc.api_key,
        azure_endpoint=bc.api_url,
        api_version=bc.api_version,
    )

    if image_bytes is None:
        logger.info("Generating image (azure) | model={} prompt={!r}", model, prompt)
        response = client.images.generate(model=model, prompt=prompt, n=1)
    else:
        logger.info("Editing image (azure) | model={} prompt={!r}", model_edit, prompt)
        data_uri = _mime_and_b64(image_bytes)
        ext = "png" if data_uri.startswith("data:image/png") else "jpg"
        response = client.images.edit(
            model=model_edit,
            image=(f"image.{ext}", io.BytesIO(image_bytes), data_uri.split(";")[0].replace("data:", "")),
            prompt=prompt,
            n=1,
        )

    item = response.data[0]
    if item.b64_json:
        result = base64.b64decode(item.b64_json)
    else:
        img_resp = _requests.get(item.url)
        img_resp.raise_for_status()
        result = img_resp.content
    logger.info("Azure image generation complete | size={} bytes", len(result))
    return result


def _generate_openai(
    bc: ImageBackend,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
    model_edit: str,
) -> bytes:
    client = OpenAI(api_key=bc.api_key, base_url=bc.api_url)

    if image_bytes is None:
        logger.info("Generating image (openai) | model={} prompt={!r}", model, prompt)
        response = client.images.generate(
            model=model, prompt=prompt, response_format="b64_json", n=1,
        )
    else:
        logger.info("Editing image (openai) | model={} prompt={!r}", model_edit, prompt)
        response = client.images.edit(
            model=model_edit,
            image=io.BytesIO(image_bytes),
            prompt=prompt,
            response_format="b64_json",
            n=1,
        )

    result = base64.b64decode(response.data[0].b64_json)
    logger.info("Image generation complete | size={} bytes", len(result))
    return result


def _generate_fal(
    bc: ImageBackend,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
    model_edit: str,
) -> bytes:
    if image_bytes:
        payload: dict = {
            "prompt": prompt,
            "image_urls": [_mime_and_b64(image_bytes)],
        }
        active_model = model_edit
    else:
        payload = {"prompt": prompt}
        active_model = model

    url = f"{bc.api_url.rstrip('/')}/{active_model}"
    headers = {
        "Authorization": f"Key {bc.api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        "Generating image (fal) | url={} prompt={!r} has_image={}",
        url, prompt, image_bytes is not None,
    )
    resp = _requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()

    result_url = resp.json()["images"][0]["url"]
    logger.info("Fetching generated image from {}", result_url)
    img_resp = _requests.get(result_url)
    img_resp.raise_for_status()

    logger.info("Image generation complete | size={} bytes", len(img_resp.content))
    return img_resp.content


def _generate_dashscope(
    bc: ImageBackend,
    prompt: str,
    images: list[bytes],
    model: str,
    model_edit: str,
) -> bytes:
    if not bc.api_url or not bc.api_key:
        raise ValueError(
            "DashScope backend requires IMAGE_API_URL and IMAGE_API_KEY"
        )

    active_model = model_edit if images else model
    url = bc.api_url.rstrip("/")

    content = [{"text": prompt}]
    for img_bytes in images:
        content.append({"image": _mime_and_b64(img_bytes)})

    payload = {
        "model": active_model,
        "input": {
            "messages": [{
                "role": "user",
                "content": content,
            }]
        },
        "parameters": {
            "size": "1K",
            "n": 1,
        },
    }

    headers = {
        "Authorization": f"Bearer {bc.api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        "Generating image (dashscope) | model={} prompt={!r} n_images={}",
        active_model, prompt, len(images),
    )
    resp = _requests.post(url, json=payload, headers=headers)
    if not resp.ok:
        logger.error("DashScope image API error | status={} body={}", resp.status_code, resp.text)
        _raise_dashscope_error(resp)

    data = resp.json()
    choices = data.get("output", {}).get("choices", [])
    if not choices:
        raise RuntimeError(f"DashScope returned no choices: {data}")

    content_list = choices[0].get("message", {}).get("content", [])
    image_url = None
    for item in content_list:
        if item.get("type") == "image":
            image_url = item.get("image")
            break

    if not image_url:
        raise RuntimeError(f"DashScope returned no image in response: {data}")

    logger.info("Fetching generated image from {}", image_url)
    img_resp = _requests.get(image_url)
    img_resp.raise_for_status()

    logger.info("DashScope image generation complete | size={} bytes", len(img_resp.content))
    return img_resp.content


def _raise_dashscope_error(resp):
    """Parse DashScope error response and raise with the message field."""
    try:
        body = resp.json()
        message = body.get("message", resp.text)
    except Exception:
        message = resp.text
    raise RuntimeError(f"DashScope error {resp.status_code}: {message}")
```

- [ ] **Step 4: Run tests/test_image_gen.py to confirm it passes**

Run: `pytest tests/test_image_gen.py -v`
Expected: PASS, all tests green.

- [ ] **Step 5: Commit**

```bash
git add services/image_gen.py tests/test_image_gen.py
git commit -m "feat: dispatch image generation on a per-request backend param"
```

---

### Task 3: `app.py`, `templates/index.html`, `translations.py` — backend selection UI

**Files:**
- Modify: `app.py`
- Modify: `templates/index.html`
- Modify: `translations.py`
- Modify: `tests/test_routes.py`

**Interfaces:**
- Consumes: `generate_image(cfg, prompt, images, backend=..., model=..., model_edit=...)` from Task 2; `cfg.image_backends`, `cfg.image_default_backend` from Task 1.
- Produces: `/generate` accepts an `image_backend` form field; `abort(400)` when it doesn't match a key in `cfg.image_backends`. `index()` passes `image_backends: dict[str, {"model": [...], "model_edit": [...]}]` and `image_default_backend: str` to the template.

- [ ] **Step 1: Update `tests/test_routes.py` (failing)**

Replace `test_generate_dashscope_image` (it currently mutates flat `cfg.image_backend`/`cfg.image_api_url`/`cfg.image_api_key` attributes, which no longer exist):

```python
def test_generate_dashscope_image(client, cfg):
    """Full pipeline: POST /generate with dashscope image backend."""
    from config import ImageBackend
    cfg.image_backends["dashscope"] = ImageBackend(
        name="dashscope",
        api_url="https://ws.example.com/api/v1/services/aigc/multimodal-generation/generation",
        api_key="sk-test",
        model=["wan2.7-image"],
        model_edit=["wan2.7-image"],
        api_version="",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [{"type": "image", "image": "https://cdn.example.com/img.png"}]
                }
            }]
        },
        "request_id": "req-1",
    }
    mock_resp.raise_for_status = MagicMock()

    mock_img = MagicMock()
    mock_img.content = b"\x89PNG\r\n\x1a\nfake-png"
    mock_img.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_resp), \
         patch("services.image_gen._requests.get", return_value=mock_img):
        resp = client.post("/generate", data={
            "output_type": "image",
            "prompt": "a cat wearing a hat",
            "image_backend": "dashscope",
        })

    assert resp.status_code == 200
    assert b"Generating" in resp.data
```

Append these new tests at the end of the file:

```python
def test_generate_unknown_image_backend_returns_400(client):
    resp = client.post("/generate", data={
        "output_type": "image",
        "prompt": "a cat",
        "image_backend": "does-not-exist",
    })
    assert resp.status_code == 400


def test_generate_forwards_selected_backend(client, cfg):
    from config import ImageBackend
    cfg.image_backends["fal"] = ImageBackend(
        name="fal",
        api_url="https://fal.run",
        api_key="fal-key",
        model=["fal-model"],
        model_edit=["fal-edit-model"],
        api_version="",
    )

    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        client.post("/generate", data={
            "output_type": "image",
            "prompt": "a sunset",
            "image_backend": "fal",
        })

    assert mock_gen.called
    kwargs = mock_gen.call_args.kwargs
    assert kwargs.get("backend") == "fal"
    assert kwargs.get("model") == "fal-model"
    assert kwargs.get("model_edit") == "fal-edit-model"


def test_index_hides_backend_select_with_one_backend(client):
    resp = client.get("/")
    assert b'name="image_backend"' not in resp.data


def test_index_shows_backend_select_with_multiple_backends():
    from app import create_app
    from config import Config, ImageBackend
    cfg = Config(
        image_backends={
            "openai": ImageBackend(
                name="openai", api_url="https://a", api_key="k",
                model=["m1"], model_edit=["m1"], api_version="",
            ),
            "fal": ImageBackend(
                name="fal", api_url="https://b", api_key="k2",
                model=["m2"], model_edit=["m2"], api_version="",
            ),
        },
        image_default_backend="openai",
        video_backend="fal", video_api_url="https://v", video_api_key="k",
        video_api_version="", video_azure_path="",
        video_model_image=["m"], video_model_text=["m"],
        secret_key="s", sd_api_url="", sd_model="",
    )
    app = create_app(cfg)
    app.config["TESTING"] = True
    test_client = app.test_client()
    resp = test_client.get("/")
    assert b'name="image_backend"' in resp.data
```

All other tests in `tests/test_routes.py` are unchanged.

- [ ] **Step 2: Run to confirm the new/changed tests fail**

Run: `pytest tests/test_routes.py -v`
Expected: FAIL — `test_generate_dashscope_image` and `test_generate_forwards_selected_backend` fail because `/generate` doesn't read `image_backend` from the form yet; `test_index_shows_backend_select_with_multiple_backends` fails because `index()` doesn't render a backend `<select>` yet.

- [ ] **Step 3: Update `app.py`**

Replace the `index()` route:

```python
    @app.get("/")
    def index():
        image_backends = {
            name: {"model": bc.model, "model_edit": bc.model_edit}
            for name, bc in cfg.image_backends.items()
        }
        return render_template(
            "index.html",
            t=t(),
            sd_enabled=bool(cfg.sd_api_url),
            image_backends=image_backends,
            image_default_backend=cfg.image_default_backend,
            video_models_image=cfg.video_model_image,
            video_models_text=cfg.video_model_text,
        )
```

Replace the `/generate` route body (from `raw_files = request.files.getlist("images")` handling through the `image_model`/`image_model_edit`/thread-dispatch section — the file-size-limit loop and `abort(400)` for >10 images stay exactly as-is):

```python
        image_backend = request.form.get("image_backend") or cfg.image_default_backend
        if image_backend not in cfg.image_backends:
            abort(400)
        bc = cfg.image_backends[image_backend]

        image_model       = request.form.get("image_model")       or bc.model[0]
        image_model_edit  = request.form.get("image_model_edit")  or bc.model_edit[0]
        video_model_image = request.form.get("video_model_image") or cfg.video_model_image[0]
        video_model_text  = request.form.get("video_model_text")  or cfg.video_model_text[0]

        job_id = job_store.create_job()
        logger.info("Job created | job_id={} output_type={} prompt={!r} n_images={}", job_id, output_type, prompt, len(images))

        if output_type == "image":
            threading.Thread(
                target=_run_image_job,
                args=(cfg, job_id, prompt, images, image_backend, image_model, image_model_edit),
                daemon=True,
            ).start()
        elif output_type == "sd":
            threading.Thread(
                target=_run_sd_job,
                args=(cfg, job_id, prompt, images),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=_run_video_job,
                args=(cfg, job_id, prompt, images, video_model_image, video_model_text),
                daemon=True,
            ).start()

        return render_template(
            "partials/generating.html", job_id=job_id, t=t()
        )
```

(This slots in right after the existing `if len(images) > _MAX_IMAGES: abort(400)` line — don't duplicate that check.)

Replace `_run_image_job`:

```python
def _run_image_job(cfg: Config, job_id: str, prompt: str, images: list[bytes],
                   backend: str, model: str, model_edit: str):
    try:
        data = image_gen.generate_image(cfg, prompt, images, backend=backend, model=model, model_edit=model_edit)
        try:
            _cache_artifact(job_id, data, "png")
        except Exception:
            logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
        job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
        logger.info("Image job done | job_id={}", job_id)
    except Exception as exc:
        logger.exception("Image job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})
```

- [ ] **Step 4: Add the `model_image_backend` translation key**

In `translations.py`, add to the `"en"` dict (alongside the other `model_*` keys):

```python
        "model_image_backend": "Image backend",
```

And to the `"de"` dict:

```python
        "model_image_backend": "Bild-Backend",
```

- [ ] **Step 5: Update `templates/index.html`**

Replace the `image_model` and `image_model_edit` `<div>` blocks (currently lines 160–184, the two blocks guarded by `{% if image_models | length > 1 %}` and `{% if image_models_edit | length > 1 %}`) with:

```html
      {% if image_backends | length > 1 %}
      <div>
        <label class="block text-sm font-medium text-gray-600 mb-1">{{ t.model_image_backend }}</label>
        <select id="image-backend-select" name="image_backend"
                class="w-full border border-gray-300 rounded-lg p-2 text-sm bg-white
                       focus:outline-none focus:ring-2 focus:ring-blue-400">
          {% for name in image_backends.keys() %}
          <option value="{{ name }}" {% if name == image_default_backend %}selected{% endif %}>{{ name }}</option>
          {% endfor %}
        </select>
      </div>
      {% endif %}

      <div id="image-model-field" {% if image_backends[image_default_backend].model | length <= 1 %}class="hidden"{% endif %}>
        <label class="block text-sm font-medium text-gray-600 mb-1">{{ t.model_image }}</label>
        <select name="image_model" id="image-model-select"
                class="w-full border border-gray-300 rounded-lg p-2 text-sm bg-white
                       focus:outline-none focus:ring-2 focus:ring-blue-400">
          {% for m in image_backends[image_default_backend].model %}
          <option value="{{ m }}">{{ m }}</option>
          {% endfor %}
        </select>
      </div>

      <div id="image-model-edit-field" {% if image_backends[image_default_backend].model_edit | length <= 1 %}class="hidden"{% endif %}>
        <label class="block text-sm font-medium text-gray-600 mb-1">{{ t.model_image_edit }}</label>
        <select name="image_model_edit" id="image-model-edit-select"
                class="w-full border border-gray-300 rounded-lg p-2 text-sm bg-white
                       focus:outline-none focus:ring-2 focus:ring-blue-400">
          {% for m in image_backends[image_default_backend].model_edit %}
          <option value="{{ m }}">{{ m }}</option>
          {% endfor %}
        </select>
      </div>

      <script>
        (function() {
          var backendModels = {{ image_backends | tojson }};
          var backendSelect = document.getElementById('image-backend-select');
          if (!backendSelect) { return; }

          function rebuild(select, models) {
            select.innerHTML = '';
            models.forEach(function(m) {
              var opt = document.createElement('option');
              opt.value = m;
              opt.textContent = m;
              select.appendChild(opt);
            });
          }

          backendSelect.addEventListener('change', function() {
            var models = backendModels[backendSelect.value];
            var modelField = document.getElementById('image-model-field');
            var editField  = document.getElementById('image-model-edit-field');
            rebuild(document.getElementById('image-model-select'), models.model);
            rebuild(document.getElementById('image-model-edit-select'), models.model_edit);
            modelField.classList.toggle('hidden', models.model.length <= 1);
            editField.classList.toggle('hidden', models.model_edit.length <= 1);
          });
        })();
      </script>
```

The `image-model-field`/`image-model-edit-field` `<div>`s and the `<script>` render unconditionally — they use inline `class="hidden"` for the collapsed state, not a Jinja `{% if %}`, since the JS needs stable DOM nodes to toggle. Only the backend `<select>` itself is wrapped in `{% if image_backends | length > 1 %}...{% endif %}`.

The `video_models_text`/`video_models_image` blocks below (currently lines 186–210) are untouched — video model selection isn't part of this change.

- [ ] **Step 6: Run tests/test_routes.py to confirm it passes**

Run: `pytest tests/test_routes.py -v`
Expected: PASS, all tests green.

- [ ] **Step 7: Commit**

```bash
git add app.py templates/index.html translations.py tests/test_routes.py
git commit -m "feat: add image backend selector to the UI"
```

---

### Task 4: Migrate real config files and verify end-to-end

**Files:**
- Modify: `settings.toml`
- Modify: `settings.example.toml`
- Modify: `.secrets.toml` (gitignored — not committed)
- Modify: `.secrets.toml.example`

**Interfaces:**
- Consumes: everything from Tasks 1–3. This task only touches TOML files, no code.

- [ ] **Step 1: Rewrite `settings.toml`**

Current `[image]` section (`backend = "dashscope"`, Token Plan `api_url`, `model`/`model_edit`) becomes:

```toml
[image]
default_backend = "dashscope"

[image.dashscope]
api_url = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
model = ["wan2.7-image", "wan2.7-image-pro"]
model_edit = ["wan2.7-image"]
```

Leave `[flask]`, `[video]`, and `[sd]` exactly as they are today.

- [ ] **Step 2: Rewrite `.secrets.toml`**

Change the `[image]` section from a flat `api_key` to a nested `[image.dashscope]`:

```toml
[image.dashscope]
api_key = "<the existing Standard Plan (dietmar.schinnerl@outlook.com) key, unchanged>"
```

Keep any commented-out alternative keys as comments under `[image.dashscope]` rather than `[image]`. Leave `[video]` untouched.

- [ ] **Step 3: Rewrite `settings.example.toml`**

Restructure the four commented-out image backend blocks under nested headers instead of a bare `[image]`:

```toml
# ── fal.ai ──────────────────────────────────────────
# [image.fal]
# api_url = "https://fal.run"
# model = ["fal-ai/flux/schnell"]
# model_edit = ["fal-ai/gpt-image-1.5/edit"]

# ── OpenAI / OpenRouter ─────────────────────────────
# [image.openai]
# api_url = "https://api.openai.com/v1"
# model = ["dall-e-3"]
# model_edit = ["dall-e-2"]

# ── Azure OpenAI ────────────────────────────────────
# [image.azure]
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
# [image.dashscope]
# api_url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
# model = ["wan2.7-image", "wan2.7-image-pro"]
# model_edit = ["wan2.7-image"]

# [video]
# backend = "dashscope"
# api_url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
# model_image = ["wan2.7-r2v"]
# model_text = ["wan2.7-t2v"]
```

Add a one-line comment above the whole `[image.*]` group noting that multiple backend blocks can be uncommented at once now — e.g.:

```toml
# Settings reference — copy relevant sections to settings.toml
# API keys go in .secrets.toml (see .secrets.toml.example)
# Multiple [image.<backend>] blocks can be active at once — the app shows
# a dropdown to pick between any backend that also has an api_key set.
```

- [ ] **Step 4: Rewrite `.secrets.toml.example`**

```toml
# Copy to .secrets.toml and fill in your keys.
# Only api_key belongs here per backend — everything else (api_url, model, ...)
# stays in settings.toml.

# [image.dashscope]
# api_key = "your-api-key"

# [image.fal]
# api_key = "your-api-key"

# [video]
# api_key = "your-api-key"
```

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: PASS, all tests green (this is the first point where the full suite — not just one file — is green again).

- [ ] **Step 6: Manual verification**

Run: `python app.py` (or `python app.py --port <n>`), then in a browser:
1. Load `http://localhost:<port>/`, click "⚙ Advanced".
2. With only `[image.dashscope]` having a key in `.secrets.toml`, confirm no "Image backend" dropdown appears (single backend = hidden, matches today's behavior).
3. Temporarily add a second backend with a key (e.g. uncomment `[image.fal]` in `settings.toml` + add a `fal` `api_key` to `.secrets.toml`), restart the app, reload the page, confirm the "Image backend" dropdown now appears with both options, and that switching it rebuilds the Image model / Edit model dropdowns beneath it.
4. Revert the temporary `[image.fal]` addition if it was only for this manual check (unless you actually want fal configured going forward — in which case leave it and get a real fal.ai key into `.secrets.toml`).

- [ ] **Step 7: Commit**

```bash
git add settings.toml settings.example.toml .secrets.toml.example
git commit -m "chore: migrate settings to nested per-backend image config"
```

(`.secrets.toml` is gitignored — it won't show up in `git status` as a file to add, but double check with `git status` that it isn't accidentally tracked before committing.)
