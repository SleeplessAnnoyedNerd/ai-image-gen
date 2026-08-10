# Multi-Backend Image Config: select-at-request-time backend

## Overview

Today `[image]` in `settings.toml` configures exactly one backend (`backend = "dashscope"`); switching to fal or Azure means editing the file and restarting the app. This changes `[image]` to hold **all** configured backends simultaneously (each in its own subtable), and lets the user pick which one to use per request via a dropdown in the UI, since some backends/models produce better results than others.

Scope: **image generation only**. `[video]` and `[sd]` are untouched — they keep their current single-backend shape.

## Goals

1. Configure multiple image backends (fal, dashscope, azure, openai) at once, each with its own URL/key/models.
2. Pick the active backend per request from the UI, no restart needed.
3. A backend only appears as selectable if it has a non-empty `api_key`.
4. Minimal churn: dispatch functions in `image_gen.py` keep their per-backend shape, just take a narrower config object.

## Config Shape

`[image]` becomes a container: an optional `default_backend` key plus one subtable per backend, named by engine type (`dashscope`, `fal`, `azure`, `openai`). Discovery is dynamic — `config.py` treats any dict-valued entry under `[image]` as a backend, no hardcoded backend list. The subtable name doubles as the dispatch key: `generate_image()` still branches on it against the four known engine types (`fal`/`azure`/`dashscope`/else-openai), so a subtable must be named one of those four to route correctly — naming it anything else silently falls through to the OpenAI-compatible dispatch branch.

### `settings.toml`

```toml
[image]
default_backend = "dashscope"

[image.dashscope]
api_url = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
model = ["wan2.7-image", "wan2.7-image-pro"]
model_edit = ["wan2.7-image"]

[image.fal]
api_url = "https://fal.run"
model = ["fal-ai/flux/schnell"]
model_edit = ["fal-ai/gpt-image-1.5/edit"]
```

### `.secrets.toml`

```toml
[image.dashscope]
api_key = "sk-..."

[image.fal]
api_key = "..."
```

`_merge()` already deep-merges nested dicts recursively, so `.secrets.toml`'s `[image.dashscope].api_key` merges into the matching subtable from `settings.toml` without any loader changes.

**`.secrets.toml` must only ever contain `api_key` per backend.** Because the merge now happens one level deeper (inside each `[image.<name>]` subtable, not just inside `[image]`), any other key placed in `.secrets.toml` — e.g. an `api_url` — would silently override `settings.toml`'s value for that backend, since `_merge()` can't distinguish "secret override" from "accidental duplicate". The flat pre-change format couldn't do this (secrets only ever had `api_key`).

### `settings.example.toml`

Same four backend blocks it documents today (fal, OpenAI, Azure, DashScope), rewritten under `[image.<name>]` headers instead of a single commented-out `[image]`.

## `config.py` Changes

New dataclass:

```python
@dataclass
class ImageBackend:
    name: str
    api_url: str
    api_key: str
    model: list[str]
    model_edit: list[str]
    api_version: str  # only read by the azure backend; defaults to "2024-02-01" for all backends
```

`Config` gains:

```python
image_backends: dict[str, ImageBackend]  # only backends with a non-empty api_key
image_default_backend: str               # falls back to first key in image_backends if unset/invalid
```

and loses `image_api_url`, `image_api_key`, `image_backend`, `image_model`, `image_model_edit`, `image_api_version`.

Loading logic in `from_settings()`:

```python
image_section = _settings.get("image", {})
backends = {}
for name, val in image_section.items():
    if not isinstance(val, dict):
        continue  # skip scalar keys like default_backend
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
```

`[video]` and `[sd]` loading is unchanged (still flat, still `_require`/`_get` on top-level keys).

## `image_gen.py` Changes

`generate_image()` gains a `backend` parameter and resolves the `ImageBackend` before dispatching; each `_generate_*` helper takes that `ImageBackend` (call it `bc`) instead of the whole `Config`, e.g. `bc.api_url`/`bc.api_key`/`bc.api_version` instead of `cfg.image_api_url`/etc. No change to the actual request-building logic in any `_generate_*` function.

```python
def generate_image(cfg, prompt, images=None, backend=None, model=None, model_edit=None) -> bytes:
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
```

## `app.py` Changes

`/generate`: read `image_backend` from the form, default to `cfg.image_default_backend`, `abort(400)` if it's not a key in `cfg.image_backends`. Resolve `bc = cfg.image_backends[image_backend]` and default `image_model`/`image_model_edit` from `bc.model[0]`/`bc.model_edit[0]` instead of `cfg.image_model[0]`/`cfg.image_model_edit[0]`. Thread `image_backend` through to `_run_image_job` → `image_gen.generate_image(..., backend=image_backend, ...)`.

`index()`: pass the template a plain dict built from `cfg.image_backends` (name → `{model, model_edit}` lists) plus `cfg.image_default_backend`, instead of the flat `image_models`/`image_models_edit` lists.

## Template Changes (`templates/index.html`)

Add an `Image Backend` `<select name="image_backend">` in the advanced panel, populated from `cfg.image_backends.keys()`, shown only when more than one backend is configured (same `| length > 1` convention already used for the model dropdowns). Label it "Image Backend", not just "Backend" — the advanced panel is shared with the video model dropdowns, and this selector has no effect on video generation. The per-backend model lists are embedded as JSON (`{{ image_backends | tojson }}`); a small JS snippet, mirroring the existing inline `<script>` pattern in this file, rebuilds the `image_model`/`image_model_edit` `<option>` lists on backend change and shows/hides each dropdown based on whether the selected backend has more than one model — same rule as today, just re-evaluated per backend instead of fixed at page load.

## What Doesn't Change

- `[video]` and `[sd]` config shape, loading, and dispatch (`video_gen.py`, `sd_gen.py` untouched).
- The `_generate_fal`/`_generate_azure`/`_generate_dashscope`/`_generate_openai` request-building bodies — only their first parameter's type narrows from `Config` to `ImageBackend`.
- `job_store.py`, translations, routes other than `/` and `/generate`.

## Migration Steps

1. Add `ImageBackend` dataclass and rework `Config.image_*` fields/loading in `config.py`.
2. Update `image_gen.py`: `generate_image()` signature + backend resolution; narrow `_generate_*` helpers to take `ImageBackend`.
3. Update `app.py`: `/generate` route reads/validates `image_backend`, threads it to the worker; `index()` passes the new backend dict to the template.
4. Update `templates/index.html`: add backend `<select>`, JS to rebuild model options on change.
5. Rewrite `settings.toml`, `settings.example.toml`, `.secrets.toml`, `.secrets.toml.example` into the nested `[image.<backend>]` shape (current live values: `[image.dashscope]` with the Token Plan URL and `wan2.7-image`/`wan2.7-image-pro` models; add a `[image.fal]` block from `settings.example.toml` if the user wants it selectable immediately).
6. Update `tests/test_config.py`, `tests/test_image_gen.py`, `tests/test_routes.py` for the new `Config`/`generate_image()` shapes. Explicitly cover:
   - Backend with an `api_key` but missing `model`/`model_edit` → `EnvironmentError` at startup.
   - Backend with an `api_key` but missing/blank `api_url` → `EnvironmentError` at startup.
   - Backend without an `api_key` → excluded from `cfg.image_backends`.
   - `default_backend` missing or pointing at an unconfigured backend → falls back to the first configured backend.
   - `/generate` submits an `image_backend` not present in `cfg.image_backends` → `400`.
   - Only one backend configured → backend `<select>` not rendered.
7. Verify: `pytest -q` passes; manually load the app, confirm the backend dropdown appears (once ≥2 backends have keys) and switching it re-populates the model dropdown.

## Edge Cases Handled

- **Backend configured but no `api_key`**: silently excluded from `cfg.image_backends` — never shown in the dropdown, never selectable.
- **Backend has a key but missing `model`/`model_edit`**: `EnvironmentError` at startup (misconfiguration, not a silent failure at generation time).
- **`default_backend` missing or pointing at an unconfigured/keyless backend**: falls back to the first backend in `image_backends` (dict insertion order = TOML declaration order).
- **Zero backends with a key configured**: `EnvironmentError` at startup — same fail-fast behavior as today's `_require`.
- **Client submits an unknown/stale `image_backend` value** (e.g. stale form after a config reload removed a backend): `/generate` validates against `cfg.image_backends` and `abort(400)`.
- **Only one backend configured**: dropdown hidden (same convention as the existing model dropdowns), behavior identical to today.
