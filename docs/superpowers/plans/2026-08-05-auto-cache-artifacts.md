# Auto-Cache Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically save every generated image/video to `.cache/YYYYMMDD/YYYYMMDD-HHMMSS-{job_id}.{ext}` when the job completes.

**Architecture:** A `_cache_artifact` helper in `app.py` writes bytes to disk. Background workers call it before marking the job done. `_poll_fal` is modified to return `video_data` (bytes) like other backends, making all video backends symmetric and eliminating the `video_url` code path.

**Tech Stack:** Python, Flask, pytest, stdlib `datetime`/`os`

## Global Constraints

- Cache write failure must never fail the job (wrap in try/except, log warning)
- `datetime.now()` called once per cache write (avoid midnight race)
- Two-space indentation, no tabs
- All existing tests must pass after each task

---

### Task 1: Add `.cache/` to `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add `.cache/` to `.gitignore`**

Edit `.gitignore` to add `.cache/` line:

```
.envrc*
.cache/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add .cache/ to .gitignore"
```

---

### Task 2: Make `_poll_fal` return `video_data` (bytes)

**Files:**
- Modify: `services/video_gen.py:82-87`
- Test: `tests/test_video_gen.py:62-68`

**Interfaces:**
- Consumes: nothing new
- Produces: `_poll_fal` now returns `{"status": "done", "video_data": <bytes>}` instead of `{"status": "done", "video_url": <str>}`

- [ ] **Step 1: Update the failing test**

Replace `test_poll_done` in `tests/test_video_gen.py` (lines 62–68) with:

```python
def test_poll_done(cfg):
    submit = {"status_url": "http://s", "response_url": "http://r"}
    status_resp = _mock_status("COMPLETED")
    result_resp = _mock_result("https://cdn.fal.ai/video.mp4")

    video_resp = MagicMock()
    video_resp.content = b"fake-mp4-bytes"
    video_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", side_effect=[status_resp, result_resp, video_resp]):
        result = poll_video_job(cfg, submit)
    assert result == {"status": "done", "video_data": b"fake-mp4-bytes"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_video_gen.py::test_poll_done -v`
Expected: FAIL — current `_poll_fal` returns `video_url`, not `video_data`

- [ ] **Step 3: Modify `_poll_fal` to fetch bytes**

In `services/video_gen.py`, replace the `COMPLETED` branch (lines 82–87):

```python
    if status == "COMPLETED":
        result = requests.get(response_url, headers=headers)
        result.raise_for_status()
        video_url = result.json()["video"]["url"]
        logger.info("fal video job complete | url={}", video_url)
        video_resp = requests.get(video_url)
        video_resp.raise_for_status()
        logger.info("fal video fetched | size={} bytes", len(video_resp.content))
        return {"status": "done", "video_data": video_resp.content}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_video_gen.py::test_poll_done -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add services/video_gen.py tests/test_video_gen.py
git commit -m "refactor: _poll_fal returns video_data (bytes) like other backends"
```

---

### Task 3: Remove `video_url` code path from routes and template

**Files:**
- Modify: `app.py:124-131` (status route, video branch)
- Modify: `app.py:152-164` (`serve_video`)
- Modify: `app.py:166-191` (`download`)
- Modify: `templates/partials/result_video.html:3` (video src)

Note: `_run_video_job` changes are handled in Task 5 (avoids redundant editing).

**Interfaces:**
- Consumes: `video_data` always present in job dict (from Task 2)
- Produces: simpler code with no `video_url` fallback, template uses `/video/<job_id>` endpoint

- [ ] **Step 1: Fix status route — remove `video_url` parameter**

In the `status` route (lines 124–131), change the video branch from:

```python
            else:
                return render_template("partials/result_video.html",
                                       job_id=job_id,
                                       video_url=job.get("video_url"),
                                       t=strings)
```

to:

```python
            else:
                return render_template("partials/result_video.html",
                                       job_id=job_id,
                                       t=strings)
```

- [ ] **Step 2: Fix `result_video.html` — use `/video/<job_id>` endpoint**

In `templates/partials/result_video.html`, change line 3 from:

```html
  <video src="{{ video_url }}" controls playsinline webkit-playsinline
```

to:

```html
  <video src="/video/{{ job_id }}" controls playsinline webkit-playsinline
```

- [ ] **Step 3: Simplify `serve_video`**

Replace `serve_video` (lines 152–164) with:

```python
    @app.get("/video/<job_id>")
    def serve_video(job_id):
        job = job_store.get_job(job_id)
        if not job or job.get("status") != "done" or job.get("output_type") != "video":
            abort(404)
        data = job["video_data"]
        return send_file(io.BytesIO(data), mimetype="video/mp4")
```

- [ ] **Step 4: Simplify `download`**

Replace the `download` function (lines 166–191) with:

```python
    @app.get("/download/<job_id>")
    def download(job_id):
        job = job_store.get_job(job_id)
        if not job or job.get("status") != "done":
            abort(404)
        if job["output_type"] == "image":
            return send_file(
                io.BytesIO(job["data"]),
                mimetype="image/png",
                as_attachment=True,
                download_name=f"{job_id}.png",
            )
        else:
            return send_file(
                io.BytesIO(job["video_data"]),
                mimetype="video/mp4",
                as_attachment=True,
                download_name=f"{job_id}.mp4",
            )
```

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add app.py templates/partials/result_video.html
git commit -m "refactor: drop video_url fallback, use /video/<job_id> endpoint"
```

---

### Task 4: Add `_cache_artifact` helper and tests

**Files:**
- Modify: `app.py:1-6` (add import)
- Modify: `app.py` (add helper function before `create_app`)
- Test: `tests/test_cache_artifact.py` (new file)

**Interfaces:**
- Consumes: `job_id` (str), `data` (bytes), `ext` (str)
- Produces: file at `.cache/YYYYMMDD/YYYYMMDD-HHMMSS-{job_id}.{ext}`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cache_artifact.py`:

```python
import os
import shutil
from unittest.mock import patch
from datetime import datetime


def setup_function():
    if os.path.exists(".cache"):
        shutil.rmtree(".cache")


def teardown_function():
    if os.path.exists(".cache"):
        shutil.rmtree(".cache")


def test_cache_artifact_writes_file():
    from app import _cache_artifact

    fixed_time = datetime(2026, 8, 5, 15, 18, 0)
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_time
        _cache_artifact("test-job-id", b"hello-bytes", "png")

    expected_path = ".cache/20260805/20260805-151800-test-job-id.png"
    assert os.path.exists(expected_path)
    with open(expected_path, "rb") as f:
        assert f.read() == b"hello-bytes"


def test_cache_artifact_creates_date_subdirectory():
    from app import _cache_artifact

    fixed_time = datetime(2026, 12, 25, 9, 30, 45)
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_time
        _cache_artifact("job-abc", b"\x89PNG", "png")

    assert os.path.isdir(".cache/20261225")
    assert os.path.exists(".cache/20261225/20261225-093045-job-abc.png")


def test_cache_artifact_video_extension():
    from app import _cache_artifact

    fixed_time = datetime(2026, 1, 1, 0, 0, 0)
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_time
        _cache_artifact("vid-job", b"fake-mp4", "mp4")

    expected_path = ".cache/20260101/20260101-000000-vid-job.mp4"
    assert os.path.exists(expected_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cache_artifact.py -v`
Expected: FAIL — `_cache_artifact` does not exist yet

- [ ] **Step 3: Add `datetime` import to `app.py`**

Add to the imports at the top of `app.py` (after `import io`):

```python
from datetime import datetime
```

- [ ] **Step 4: Add `_cache_artifact` helper to `app.py`**

Add this function after the imports and before `create_app`:

```python
def _cache_artifact(job_id: str, data: bytes, ext: str):
    """Write artifact bytes to .cache/YYYYMMDD/YYYYMMDD-HHMMSS-{job_id}.{ext}."""
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    ts = now.strftime("%Y%m%d-%H%M%S")
    cache_dir = os.path.join(".cache", today)
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{ts}-{job_id}.{ext}")
    with open(path, "wb") as f:
        f.write(data)
    logger.info("Cached artifact | path={} size={} bytes", path, len(data))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cache_artifact.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_cache_artifact.py
git commit -m "feat: add _cache_artifact helper with tests"
```

---

### Task 5: Wire `_cache_artifact` into background workers

**Files:**
- Modify: `app.py:200-208` (`_run_image_job`)
- Modify: `app.py:211-218` (`_run_sd_job`)
- Modify: `app.py:221-249` (`_run_video_job`)

**Interfaces:**
- Consumes: `_cache_artifact(job_id, data, ext)` from Task 4
- Produces: artifacts cached to disk on job completion

- [ ] **Step 1: Add cache call to `_run_image_job`**

Replace `_run_image_job` with:

```python
def _run_image_job(cfg: Config, job_id: str, prompt: str, image_bytes: bytes | None,
                   model: str, model_edit: str):
    try:
        data = image_gen.generate_image(cfg, prompt, image_bytes, model=model, model_edit=model_edit)
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

- [ ] **Step 2: Add cache call to `_run_sd_job`**

Replace `_run_sd_job` with:

```python
def _run_sd_job(cfg: Config, job_id: str, prompt: str, image_bytes: bytes | None):
    try:
        data = sd_gen.generate_image_sd(cfg, prompt, image_bytes)
        try:
            _cache_artifact(job_id, data, "png")
        except Exception:
            logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
        job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
        logger.info("SD job done | job_id={}", job_id)
    except Exception as exc:
        logger.exception("SD job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})
```

- [ ] **Step 3: Add cache call to `_run_video_job`**

Replace `_run_video_job` with:

```python
def _run_video_job(cfg: Config, job_id: str, prompt: str, image_bytes: bytes | None,
                   model_image: str, model_text: str):
    import time
    try:
        submit = video_gen.start_video_job(
            cfg, prompt, image_bytes,
            model_image=model_image, model_text=model_text,
        )
        for _ in range(300):
            time.sleep(2)
            result = video_gen.poll_video_job(cfg, submit)
            qp = result.get("queue_position")
            job_store.update_job(job_id, {
                "progress": "in_progress" if qp is None else str(qp)
            })
            if result["status"] == "done":
                try:
                    _cache_artifact(job_id, result["video_data"], "mp4")
                except Exception:
                    logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
                job_store.update_job(job_id, {
                    "status": "done", "output_type": "video",
                    "video_data": result["video_data"],
                })
                return
            if result["status"] == "error":
                raise RuntimeError(result.get("message", "Video generation failed"))
        raise TimeoutError("Video generation timed out after 10 minutes")
    except Exception as exc:
        logger.exception("Video job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})
```

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: auto-cache generated artifacts on job completion"
```
