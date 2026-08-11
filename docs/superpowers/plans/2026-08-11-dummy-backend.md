# Dummy Generation Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the real app — real UI, real job pipeline, real artifact caching — at zero cost and with no network. Image generates a deterministic colour from the prompt hash; video fakes a short queue and returns a committed MP4.

**Architecture:** One branch in `image_gen.generate_image` for `backend=="dummy"`, two branches in `video_gen.start_video_job`/`poll_video_job` for `cfg.video_backend=="dummy"`. `[image.dummy]` satisfies the existing config validation with zero code changes to `config.py`. The MP4 is a 2.3 KB asset committed to `services/assets/`.

**Tech Stack:** Python 3.14, `hashlib`, `struct`, `zlib` (all stdlib), Flask, htmx, Selenium, ffmpeg (asset generation only).

**Spec:** `docs/superpowers/specs/2026-08-11-dummy-backend-design.md`

## Global Constraints

- **Indentation: 4 spaces** for Python. Every existing file in this repo uses it. Not 2 spaces, not tabs.
- **Parenthesise sub-expressions** where precedence could be ambiguous — the repo owner's style.
- **No new Python dependencies.** `hashlib`, `struct`, `zlib`, `pathlib` are stdlib. `requirements.txt` is not touched.
- **This is a product feature, not test scaffolding.** The test suite keeps using `unittest.mock`. Do not add a way for the dummy backend to be selected automatically in tests — it is selected by the user via the UI dropdown or by setting `[video] backend = "dummy"` in `settings.toml`.
- **Run tests as `source venv/bin/activate && python -m pytest -q`** from the project root. Bare `pytest` also works (there is a `pytest.ini`).
- **Do NOT modify `tests/conftest.py`.** Adding "dummy" to the shared `cfg` fixture breaks 3 existing tests that depend on having exactly one backend (`test_index_hides_backend_select_with_one_backend`, `test_generate_unknown_image_backend_returns_400`, `test_generate_forwards_selected_backend`). Each dummy test creates its own local Config instead.
- **Do NOT patch `app.image_gen.generate_image`** in any test that is meant to exercise the real dummy generator. That would defeat the purpose. The dummy backend makes no HTTP calls, so `requests.post` being unpatched is harmless — the code path simply never calls it.
- **The `server` fixture in `tests/test_dropdown_browser.py` must keep `patch("app._cache_artifact")`.** That fixture starts real unjoined daemon threads. The autouse `_isolated_cwd` chdir does NOT contain them — a job thread outliving its test writes to the restored cwd, which is the real data dir. This was proven by adversarial testing on the data-dir branch; the docstring at `tests/test_dropdown_browser.py:65-70` explains the reasoning. Do not remove the patch, even if it looks redundant.
- Baseline before starting: **134 tests passing**. After: **145**.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `services/assets/dummy.mp4` | Create | 2.3 KB black-screen MP4, committed once. Already generated on this host. |
| `services/image_gen.py` | Modify | `_solid_png()`, `_generate_dummy()`, dispatch branch. |
| `services/video_gen.py` | Modify | `_start_dummy()`, `_poll_dummy()`, `_dummy_video_bytes()`, two dispatch branches. |
| `settings.toml`, `settings.example.toml` | Modify | `[image.dummy]` config block. |
| `tests/test_image_gen.py` | Modify | 6 new tests for the dummy image path. |
| `tests/test_video_gen.py` | Modify | 5 new tests for the dummy video path. |
| `tests/test_dropdown_browser.py` | Modify | 1 new browser test with its own `dummy_server` fixture. |

---

### Task 1: The image backend

**Files:**
- Modify: `services/image_gen.py` (add at end of file, and add dispatch branch in `generate_image`)
- Modify: `settings.toml`, `settings.example.toml`
- Modify: `tests/test_image_gen.py`

**Interfaces:**
- Consumes: existing `generate_image` dispatch at `services/image_gen.py:25-45`; existing `_load_image_backends` validation at `config.py:72-104`.
- Produces: `services.image_gen._solid_png(prompt: str, size: int = 512) -> bytes`; `services.image_gen._generate_dummy(prompt: str, images: list[bytes]) -> bytes`. Later tasks do not call these — the user does, via the UI.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_image_gen.py`. Add `from config import Config, ImageBackend` at line 5 if not already present (it is already imported — keep it). Also add the new imports at the end of the file's import block:

```python
from services.image_gen import _solid_png, _generate_dummy
```

Then append these tests:

```python
# --- Dummy backend tests ---


def _dummy_cfg():
    """Minimal Config with only a dummy backend, for testing in isolation."""
    return Config(
        image_backends={
            "dummy": ImageBackend(
                name="dummy",
                api_url="dummy://local",
                api_key="dummy",
                model=["dummy/instant"],
                model_edit=["dummy/instant"],
                api_version="2024-02-01",
            ),
        },
        image_default_backend="dummy",
        video_backend="fal", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=[""], video_model_text=[""],
        secret_key="test", sd_api_url="", sd_model="",
    )


def test_solid_png_starts_with_png_signature():
    data = _solid_png("test")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_solid_png_ihdr_declares_512x512():
    import struct
    data = _solid_png("test")
    # IHDR: sig(8) + length(4) + tag "IHDR"(4) + width(4) + height(4)
    width, height = struct.unpack(">II", data[16:24])
    assert width == 512
    assert height == 512


def test_solid_png_deterministic():
    """Same prompt gives identical bytes."""
    assert _solid_png("a cat") == _solid_png("a cat")


def test_solid_png_varies_by_prompt():
    """Different prompts give different colours."""
    assert _solid_png("a cat") != _solid_png("a dog")


def test_generate_dummy_echoes_image_on_edit():
    """When images are supplied (edit path), echo the first back."""
    original = b"\x89PNG\r\n\x1a\nfake-png-data"
    assert _generate_dummy("make it blue", [original]) == original


def test_generate_dummy_makes_no_http_call():
    """The entire point: no network, no cost."""
    cfg = _dummy_cfg()
    with patch("services.image_gen._requests.post") as mock_post, \
         patch("services.image_gen._requests.get") as mock_get:
        result = generate_image(cfg, prompt="a sunset", backend="dummy")
    assert result[:8] == b"\x89PNG\r\n\x1a\n"
    mock_post.assert_not_called()
    mock_get.assert_not_called()
```

Note for the implementer: `_dummy_cfg()` creates a Config with only a "dummy" backend. This is intentional — each dummy test is self-contained and does not modify the shared `cfg` fixture. The `_requests` module is `services.image_gen._requests` (aliased from `requests` at `services/image_gen.py:6`). The `_solid_png` and `_generate_dummy` functions are called directly (not via `generate_image`) in the first four tests to isolate the pure logic from the dispatch.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_image_gen.py -k dummy -v
```

Expected: 6 errors — `ImportError: cannot import name '_solid_png'`.

- [ ] **Step 3: Add the `[image.dummy]` config**

At the end of the `[image.*]` sections in `settings.toml` (after the `[image.dashscope]` block), add:

```toml
[image.dummy]
api_url    = "dummy://local"
api_key    = "dummy"
model      = ["dummy/instant"]
model_edit = ["dummy/instant"]
```

Add the identical block to `settings.example.toml`, uncommented, alongside the other example backend blocks. The values are inert placeholders that exist only to pass `config.py:80-89`'s validation. `api_key = "dummy"` is not a secret and belongs in the tracked file, not `.secrets.toml`.

- [ ] **Step 4: Implement the dummy image backend**

In `services/image_gen.py`, add a dispatch branch in `generate_image` before the existing `if backend == "fal":` at line 39:

```python
    if backend == "dummy":
        return _generate_dummy(prompt, images)
```

Then append to the end of the file:

```python
# ------------------------------------------------------------------ #
# Dummy backend — no network, no cost                                 #
# ------------------------------------------------------------------ #

def _generate_dummy(prompt: str, images: list[bytes]) -> bytes:
    """Local placeholder generator: no network, no cost."""
    # An edit echoes its input back, so the upload path stays verifiable.
    if images:
        return images[0]
    return _solid_png(prompt)


def _solid_png(prompt: str, size: int = 512) -> bytes:
    """A solid-colour PNG whose colour is seeded from sha256(prompt).

    Same prompt → same colour.  The PNG is hand-assembled from raw
    zlib-compressed scanlines — no Pillow dependency.
    """
    import hashlib
    import struct
    import zlib

    rgb = hashlib.sha256(prompt.encode()).digest()[:3]

    # Raw scanlines: b"\x00" (filter: none) + size*RGB, repeated.
    raw = b"".join(b"\x00" + rgb * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")

    return sig + ihdr + idat + iend
```

The `import` statements are inside the function body because these are stdlib modules used nowhere else in the file. The existing code imports nothing at the top except `requests`, `loguru`, and `config` — keep it that way.

Note for the implementer: the `chunk()` helper computes `zlib.crc32(body)` on `tag + data` (not just `data`), which matches the PNG spec's chunk CRC definition. The `& 0xFFFFFFFF` masks to an unsigned 32-bit value — Python's `crc32` can return negative values on some platforms without it.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
source venv/bin/activate && python -m pytest tests/test_image_gen.py -k dummy -v
```

Expected: 6 passed.

- [ ] **Step 6: Run the full suite**

```bash
source venv/bin/activate && python -m pytest -q
```

Expected: 140 passed (134 baseline + 6 new).

- [ ] **Step 7: Commit**

```bash
git add services/image_gen.py settings.toml settings.example.toml tests/test_image_gen.py
git commit -m "feat: add dummy image backend for cost-free local use"
```

---

### Task 2: The video backend

**Files:**
- Create: `services/assets/dummy.mp4` (already generated, 2.3 KB)
- Modify: `services/video_gen.py` (add at end of file, and add dispatch branches)
- Modify: `tests/test_video_gen.py`

**Interfaces:**
- Consumes: existing `start_video_job` at `services/video_gen.py:8-25`; existing `poll_video_job` at `services/video_gen.py:27-37`; `app.py:260-266` reuses the same `submit` dict on every poll, which is how the dummy carries its counter.
- Produces: `services.video_gen._start_dummy() -> dict`; `services.video_gen._poll_dummy(submit: dict) -> dict`; `services.video_gen._dummy_video_bytes() -> bytes`.

- [ ] **Step 1: Commit the MP4 asset**

The asset already exists at `services/assets/dummy.mp4` (2.3 KB, 320×240, 1 second, black screen). Verify and commit:

```bash
ls -la services/assets/dummy.mp4
file services/assets/dummy.mp4
git add services/assets/dummy.mp4
git commit -m "feat: add dummy MP4 asset for the fake video backend"
```

Expected: `ISO Media, MP4 Base Media v1`, ~2.3 KB.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_video_gen.py`. Add `from config import Config` alongside the existing imports (line 3 area) if not already present.

```python
# --- Dummy backend tests ---


def _dummy_video_cfg():
    """Config with dummy video backend, isolated from the shared fixture."""
    return Config(
        image_backends={}, image_default_backend="",
        video_backend="dummy",
        video_api_url="https://unused.example.com",
        video_api_key="unused",
        video_api_version="", video_azure_path="",
        video_model_image=["m"], video_model_text=["m"],
        secret_key="test", sd_api_url="", sd_model="",
    )


def test_dummy_start_returns_fresh_counter():
    cfg = _dummy_video_cfg()
    result = start_video_job(cfg, prompt="a cat")
    assert result == {"dummy": True, "polls": 0}


def test_dummy_poll_sequence():
    """Pending twice (queue positions 2 then 1), then done with video data."""
    cfg = _dummy_video_cfg()
    submit = start_video_job(cfg, prompt="a cat")

    r1 = poll_video_job(cfg, submit)
    assert r1 == {"status": "pending", "queue_position": 2}

    r2 = poll_video_job(cfg, submit)
    assert r2 == {"status": "pending", "queue_position": 1}

    r3 = poll_video_job(cfg, submit)
    assert r3["status"] == "done"
    assert r3["video_data"][:4] == b"\x00\x00\x00"  # MP4 ftyp box


def test_dummy_poll_counter_independent():
    """Two submits do not share a poll counter."""
    cfg = _dummy_video_cfg()
    s1 = start_video_job(cfg, prompt="a")
    s2 = start_video_job(cfg, prompt="b")

    poll_video_job(cfg, s1)
    poll_video_job(cfg, s1)

    # s2 should still be at poll 0 — not at poll 2
    r = poll_video_job(cfg, s2)
    assert r == {"status": "pending", "queue_position": 2}


def test_dummy_poll_completes_in_exactly_three_polls():
    cfg = _dummy_video_cfg()
    submit = start_video_job(cfg, prompt="a bird")
    for _ in range(2):
        poll_video_job(cfg, submit)
    result = poll_video_job(cfg, submit)
    assert result["status"] == "done"
    assert len(result["video_data"]) > 0
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_video_gen.py -k dummy -v
```

Expected: 4 errors — the dispatch still falls through to fal, so `_start_dummy` is not found and/or the poll receives a fal-shaped submit dict.

- [ ] **Step 4: Add `pathlib` import**

At the top of `services/video_gen.py`, add `from pathlib import Path` alongside the existing imports (after line 5):

```python
from pathlib import Path
```

- [ ] **Step 5: Implement the dummy video backend**

In `services/video_gen.py`, add a dispatch branch in `start_video_job` before the `return _start_fal(...)` fallback (line 25):

```python
    if cfg.video_backend == "dummy":
        return _start_dummy()
```

And in `poll_video_job`, add before the `return _poll_fal(...)` fallback (line 37):

```python
    if cfg.video_backend == "dummy":
        return _poll_dummy(submit)
```

Then append to the end of the file:

```python
# ------------------------------------------------------------------ #
# Dummy backend — no network, no cost                                 #
# ------------------------------------------------------------------ #

_DUMMY_POLLS_UNTIL_DONE = 3


def _start_dummy() -> dict:
    """Submit a dummy video job.  The counter lives in the returned dict —
    poll_video_job reuses it on every call (app.py:264), so no module-level
    state, no cross-job interference."""
    return {"dummy": True, "polls": 0}


def _poll_dummy(submit: dict) -> dict:
    submit["polls"] += 1
    if submit["polls"] >= _DUMMY_POLLS_UNTIL_DONE:
        return {"status": "done", "video_data": _dummy_video_bytes()}
    return {"status": "pending",
            "queue_position": (_DUMMY_POLLS_UNTIL_DONE - submit["polls"])}


def _dummy_video_bytes() -> bytes:
    """Read the committed MP4 asset.  Path is relative to this module's file,
    never to the working directory — the app chdirs at startup under the
    data-dir design."""
    return (Path(__file__).parent / "assets" / "dummy.mp4").read_bytes()
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
source venv/bin/activate && python -m pytest tests/test_video_gen.py -k dummy -v
```

Expected: 4 passed.

- [ ] **Step 7: Run the full suite**

```bash
source venv/bin/activate && python -m pytest -q
```

Expected: 144 passed (134 baseline + 6 image + 4 video).

- [ ] **Step 8: Commit**

```bash
git add services/video_gen.py tests/test_video_gen.py
git commit -m "feat: add dummy video backend with 3-poll fake queue"
```

---

### Task 3: Browser test

**Files:**
- Modify: `tests/test_dropdown_browser.py`

**Interfaces:**
- Consumes: `services.image_gen._generate_dummy` (real, unpatched); the existing `browser` fixture (module-scoped Firefox, `tests/test_dropdown_browser.py:47-59`); the existing `_TEXTAREA`, `_SUBMIT` locators; `_js_errors`, `_values` helpers.

**Key design decision:** the existing `server` fixture (`tests/test_dropdown_browser.py:61-80`) patches `app.image_gen.generate_image`, which would intercept the dummy path. The dummy browser test needs the real `_generate_dummy` to run, so it uses a **separate** `dummy_server` fixture that patches `_cache_artifact` only. All fixtures in this file are non-autouse, so adding a new one does not affect existing tests.

- [ ] **Step 1: Write the failing test**

Add a new fixture and test to `tests/test_dropdown_browser.py`. Place the fixture near the existing `server` fixture, and the test at the end of the file.

The fixture:

```python
@pytest.fixture
def dummy_server(cfg):
    """Like the regular server fixture, but does NOT patch generate_image —
    the real _generate_dummy must run for the browser to decode it.

    Still patches _cache_artifact: the server runs in a real thread with
    threaded=True, so unjoined job threads can outlive the test and write
    after _isolated_cwd has unwound.  The docstring at :65-70 explains
    the full reasoning.
    """
    cfg.image_backends["dummy"] = ImageBackend(
        name="dummy", api_url="dummy://local", api_key="dummy",
        model=["dummy/instant"], model_edit=["dummy/instant"],
        api_version="2024-02-01",
    )
    port = _free_port()
    srv = make_server("127.0.0.1", port, create_app(cfg), threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    with patch("app._cache_artifact"):
        thread.start()
        yield f"http://127.0.0.1:{port}"
        srv.shutdown()
    thread.join(timeout=5)
```

Add `from config import ImageBackend` at the top of the file (alongside the existing imports) if not already present.

The test:

```python
def test_dummy_backend_renders_a_decodable_512x512_png(browser, dummy_server):
    """The in-process suite asserts the PNG bytes start with the right
    signature, but only a real browser can tell us whether the
    zlib-compressed hand-assembled chunks actually decode into a visible
    512×512 image.  """
    browser.get(dummy_server)
    if browser.execute_script("return typeof window.htmx") == "undefined":
        pytest.skip("htmx CDN unreachable")
    browser.execute_script(
        "window.__errs = [];"
        "window.addEventListener('error', function(e) { window.__errs.push(String(e.message)); });"
    )

    field = browser.find_element(By.CSS_SELECTOR, "textarea[name='prompt']")
    field.clear()
    field.send_keys("dummy backend smoke test")

    # Inject a hidden input to select the dummy backend — the form has no
    # visible selector for it in the default one-backend config.
    browser.execute_script(
        "var f = document.querySelector('form[hx-post]');"
        "var inp = document.createElement('input');"
        "inp.type = 'hidden'; inp.name = 'image_backend'; inp.value = 'dummy';"
        "f.appendChild(inp);"
    )

    browser.find_element(By.CSS_SELECTOR, "button[value='image']").click()
    # Wait for the <img> to appear and decode.
    WebDriverWait(browser, 10).until(
        lambda d: d.execute_script(
            "var img = document.querySelector('#result-area img');"
            "return img && img.naturalWidth > 0;"
        )
    )

    width = browser.execute_script(
        "var img = document.querySelector('#result-area img');"
        "return img ? img.naturalWidth : -1;"
    )
    assert width == 512, f"expected 512px wide image, got {width}"
    assert browser.execute_script("return window.__errs || []") == []
```

Note for the implementer: `dummy_server` mutates `cfg.image_backends` to add the "dummy" backend — this is safe because the `cfg` fixture is function-scoped (fresh per test). The `_cache_artifact` patch is required; do not remove it. The hidden input injection is necessary because the server's config has two backends but the test needs to select `"dummy"` explicitly — without the hidden input, the form submits with no `image_backend` field and Flask's `request.form.get("image_backend")` falls back to the default backend.

- [ ] **Step 2: Run it to verify it passes**

```bash
source venv/bin/activate && python -m pytest tests/test_dropdown_browser.py::test_dummy_backend_renders_a_decodable_512x512_png -v
```

Expected: PASS. If Firefox or the htmx CDN is unavailable, it skips — report that honestly rather than claiming a pass.

- [ ] **Step 3: Run the full suite**

```bash
source venv/bin/activate && python -m pytest -q
```

Expected: 145 passed (134 baseline + 6 image + 4 video + 1 browser). If the browser test was skipped, 144.

- [ ] **Step 4: Manual smoke test**

The dummy backend is a product feature — verify it works in a real browser:

```bash
source venv/bin/activate && python app.py --port 5098
```

Then in a browser at `http://localhost:5098`:

1. **Image generation:** type any prompt, leave the default backend, click "Generate Image". Confirm you get a solid-colour square whose colour changes when you change the prompt.
2. **Edit flow:** upload an image, confirm it comes back unchanged.
3. **Dummy video:** stop the server, edit `settings.toml` to set `[video] backend = "dummy"`, restart. Select "Generate Video". Confirm you see the spinner, queue positions 2 then 1, and then a video. Confirm it completes in ~6 seconds (3 polls × 2s).

Stop the server when done.

- [ ] **Step 5: Commit**

```bash
git add tests/test_dropdown_browser.py
git commit -m "test: add browser test for the dummy image backend"
```

---

## Verification

After all three tasks:

```bash
source venv/bin/activate && python -m pytest -q
```

Expected: **145 passed** (or 144 if the browser test was skipped).

```bash
git status --short
```

Expected: no stray files.

```bash
git log --oneline master..HEAD
```

Expected: 4 commits (MP4 asset, image backend, video backend, browser test).

## Out of Scope

Per the spec:

- A dummy Stable Diffusion backend.
- Making the video backend selectable per request.
- Rendering the prompt text onto the image (needs Pillow).
- Simulated failures, configurable latency, or configurable image size.
- Changing `serve_image`'s hardcoded `mimetype="image/png"` (pre-existing for all backends).
