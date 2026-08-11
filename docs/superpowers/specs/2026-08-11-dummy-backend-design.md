# Dummy Generation Backend — Design

**Date:** 2026-08-11
**Status:** Approved

## Goal

Run the real app — real UI, real job pipeline, real artifact caching — without
calling a paid API. Click through the prompt dropdown, the upload grid, the
model selectors and the video spinner at zero cost and with no network.

**This is a product feature, not test scaffolding.** The test suite keeps using
`unittest.mock`; adding a dummy backend for its benefit would put a test-only
code path into production where it could ship by accident. That was considered
and rejected.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Image and video | Video is the slow, expensive one — the bigger win for clicking through the UI. Stable Diffusion already degrades gracefully (`/sd-status` reports offline and the button disables itself). |
| Image output | Solid PNG, colour seeded from `sha256(prompt)` | Each prompt yields a visibly different image, so you can see at a glance that the right text reached the backend. Deterministic: the same prompt always gives the same colour. |
| Image edit output | Echo back `images[0]` | One line, and it makes the upload grid and the edit path actually verifiable. |
| Echoed MIME type | Left wrong, knowingly | `serve_image` (`app.py:189`) hardcodes `mimetype="image/png"` for *every* backend, and `_cache_artifact` hardcodes the `.png` extension. Echoing a JPEG upload therefore serves JPEG bytes labelled PNG. Browsers sniff and render it. Pre-existing for all backends; the dummy only makes it easy to hit. Fixing it is a separate change. |
| PNG generation | `zlib` + `struct` (`zlib.crc32` for the chunk CRCs), ~12 lines | Stdlib writes a valid PNG. Pillow would be a 3MB dependency for a feature whose point is being cheap. |
| Video output | One tiny MP4 committed to the repo | An MP4 cannot reasonably be synthesized in stdlib. Generated once with the ffmpeg already on this host. |
| Video timing | Completes on the 3rd poll, queue position 2 then 1 | Exercises the spinner, the polling loop, and `partials/generating.html`'s `progress_queued` branch. Counts polls rather than sleeping — deterministic and no blocked threads. |
| Config registration | Ordinary `[image.dummy]` values | Satisfies `_load_image_backends()`'s existing api_key/api_url/model validation with **zero config-code changes**. No special-casing of a magic backend name. |

## Known asymmetry

The image backend is chosen **per request** — `request.form["image_backend"]`,
surfaced as the Advanced panel's dropdown. The video backend is
`cfg.video_backend`, a single global read from `settings.toml`
(`services/video_gen.py:20-24` and `:32-35`).

So selecting the dummy image backend is a dropdown click, while the dummy video
backend needs a `settings.toml` edit and a restart. Making the video backend
per-request is a larger change and is **out of scope**; this spec accepts the
asymmetry rather than hiding it.

## Components

### `settings.toml` and `settings.example.toml`

```toml
[image.dummy]
api_url    = "dummy://local"
api_key    = "dummy"
model      = ["dummy/instant"]
model_edit = ["dummy/instant"]
```

The values are inert placeholders that exist only to pass the existing
validation in `config.py:80-89`. `api_key = "dummy"` is not a secret and belongs
in the tracked `settings.toml`, not `.secrets.toml`.

To use dummy video, set `[video] backend = "dummy"` and restart.

### `services/image_gen.py`

A branch in `generate_image`, alongside the existing `fal` / `azure` /
`dashscope` checks at `:39-45`:

```python
if backend == "dummy":
    return _generate_dummy(prompt, images)
```

```python
def _generate_dummy(prompt: str, images: list[bytes]) -> bytes:
    """Local placeholder generator: no network, no cost."""
    # An edit echoes its input back, so the upload path stays verifiable.
    if images:
        return images[0]
    return _solid_png(prompt)


def _solid_png(prompt: str, size: int = 512) -> bytes:
    # sha256(prompt)[:3] -> RGB, so the colour is stable per prompt.
    # Raw scanlines are b"\x00" (filter: none) + size*RGB, repeated size times,
    # zlib-compressed into one IDAT.
    # Chunks: signature, IHDR (8-bit truecolour), IDAT, IEND —
    # each length(4) + tag(4) + data + crc32(4), big-endian.
```

### `services/video_gen.py`

Branches in both dispatchers, matching the existing shape:

```python
# in start_video_job, before the fal fallback
if cfg.video_backend == "dummy":
    return _start_dummy()

# in poll_video_job, before the fal fallback
if cfg.video_backend == "dummy":
    return _poll_dummy(submit)
```

```python
_DUMMY_POLLS_UNTIL_DONE = 3

def _start_dummy() -> dict:
    return {"dummy": True, "polls": 0}


def _poll_dummy(submit: dict) -> dict:
    # submit is the same dict on every poll (app.py:264 reuses it), so the
    # counter lives there — no module-level state, no cross-job interference.
    submit["polls"] += 1
    if submit["polls"] >= _DUMMY_POLLS_UNTIL_DONE:
        return {"status": "done", "video_data": _dummy_video_bytes()}
    return {"status": "pending",
            "queue_position": (_DUMMY_POLLS_UNTIL_DONE - submit["polls"])}


def _dummy_video_bytes() -> bytes:
    # Path is relative to this module's file, never to the working directory:
    # the app chdirs at startup under the data-dir design.
    return (Path(__file__).parent / "assets" / "dummy.mp4").read_bytes()
```

At 2 seconds per poll (`app.py:263`) that is roughly 6 seconds to completion,
showing queue position 2 then 1.

### `services/assets/dummy.mp4`

Generated once and committed:

```bash
ffmpeg -f lavfi -i color=c=black:s=320x240:d=1 -c:v libx264 -pix_fmt yuv420p \
       -movflags +faststart services/assets/dummy.mp4
```

Read with `pathlib` relative to the module file, **not** the working directory —
the app chdirs at startup under the data-dir design.

## Testing

**`tests/test_image_gen.py`**

- `_solid_png` output starts with the PNG signature and its IHDR declares
  512×512.
- The same prompt twice gives identical bytes; two different prompts give
  different bytes.
- `_generate_dummy` returns `images[0]` verbatim when images are supplied.
- `generate_image(..., backend="dummy")` makes no HTTP call — assert
  `requests.post` is never reached.

**`tests/test_video_gen.py`**

- `_start_dummy` returns a fresh counter.
- Polling the same submit dict yields pending/2, pending/1, then done with
  non-empty `video_data`.
- Two concurrent submits do not share a counter.

**`tests/test_dropdown_browser.py`** — one addition that the existing in-process
suite structurally cannot make: submit with the dummy backend selected and
assert the rendered `<img>` reports `naturalWidth === 512`. That proves a real
browser decodes the PNG we hand-assembled from zlib chunks, which no Python
assertion can establish.

This test must **not** patch `app.image_gen.generate_image` — the whole point is
to run the real dummy generator. It must still patch `app._cache_artifact`, as
the existing `server` fixture does: the dummy path completes successfully, so it
reaches the artifact write, and the server thread's working directory is
whatever was current when it started. Leave that patch in and the write cannot
escape regardless of whether the data-dir spec has shipped.

## Out of Scope

- A dummy Stable Diffusion backend. `/sd-status` already reports offline and the
  button disables itself, so there is nothing broken to work around.
- Making the video backend selectable per request.
- Rendering the prompt text onto the image (needs Pillow).
- Simulated failures, configurable latency, or configurable image size.
