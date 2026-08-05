# DashScope Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Alibaba Cloud DashScope as a new backend for image and video generation alongside the existing fal/azure/openai backends.

**Architecture:** Add `dashscope` as a new branch in the existing backend dispatchers (`image_gen.py`, `video_gen.py`). Reuses existing config fields (`image_api_url`, `image_api_key`, `video_api_url`, `video_api_key`) — no new config fields needed. Image uses sync multimodal-generation API; video uses async video-synthesis API with task polling.

**Tech Stack:** Python 3, Flask, requests, pytest

## Global Constraints

- Single backend active at a time — no multi-provider UI
- Only configure models for the active backend in `.envrc`
- `IMAGE_API_URL` / `VIDEO_API_URL` contain the **full endpoint URL** (not a base URL)
- `IMAGE_API_KEY` / `VIDEO_API_KEY` contain the Bearer token
- Image content block format: `{"type": "text", "text": "..."}` / `{"type": "image_url", "image_url": {"url": "data:..."}}` (OpenAI-compatible format that DashScope follows)
- Resolution: `"720P"` (uppercase P)
- Watermark: `"watermark": false` on all video requests
- MIME detection from magic bytes: `image_bytes[:4] == b'\x89PNG'` → `image/png`, else `image/jpeg`

---

### Task 1: Image generation — add dashscope backend

**Files:**
- Modify: `services/image_gen.py`
- Modify: `tests/test_image_gen.py`

**Interfaces:**
- Consumes: `cfg.image_api_url` (full endpoint URL), `cfg.image_api_key` (Bearer token), `cfg.image_model`, `cfg.image_model_edit`, `cfg.image_backend`
- Produces: `generate_image()` returns `bytes` (PNG image data) — same contract as existing backends

- [ ] **Step 1: Write failing tests for dashscope image generation**

```python
# tests/test_image_gen.py — add at end of file

def _dashscope_cfg():
    """Helper to create a Config with dashscope backend."""
    return Config(
        image_api_url="https://ws-c2xbh4slyhwu4ifn.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        image_api_key="sk-test-key",
        image_model=["wan2.7-image"], image_model_edit=["wan2.7-image-pro"],
        image_backend="dashscope", image_api_version="",
        video_backend="fal", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=[""], video_model_text=[""],
        secret_key="test", sd_api_url="", sd_model="",
        # no dashscope-specific fields — reuses image_api_url/image_api_key
    )


def test_dashscope_text_to_image():
    """DashScope backend: text-only prompt generates image."""
    cfg = _dashscope_cfg()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [
                        {"type": "image", "image": "https://cdn.example.com/img.png"}
                    ]
                }
            }]
        },
        "request_id": "req-123",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response), \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        result = generate_image(cfg, prompt="a cat wearing a hat")

    assert result == FAKE_PNG


def test_dashscope_image_to_image():
    """DashScope backend: prompt + reference image generates edited image."""
    cfg = _dashscope_cfg()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [
                        {"type": "image", "image": "https://cdn.example.com/img.png"}
                    ]
                }
            }]
        },
        "request_id": "req-456",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response) as mock_post, \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        result = generate_image(cfg, prompt="make it blue", image_bytes=FAKE_PNG)

    assert result == FAKE_PNG

    # Verify the request included the image in the messages content
    payload = mock_post.call_args.kwargs["json"]
    content = payload["input"]["messages"][0]["content"]
    assert len(content) == 2
    assert content[0] == {"type": "text", "text": "make it blue"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_dashscope_missing_config_raises():
    """DashScope backend: raises ValueError when api_url is empty."""
    cfg = Config(
        image_api_url="", image_api_key="",
        image_model=["wan2.7-image"], image_model_edit=["wan2.7-image-pro"],
        image_backend="dashscope", image_api_version="",
        video_backend="fal", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=[""], video_model_text=[""],
        secret_key="test", sd_api_url="", sd_model="",
        # no dashscope-specific fields — reuses image_api_url/image_api_key
    )
    with pytest.raises(ValueError, match="IMAGE_API_URL"):
        generate_image(cfg, prompt="a cat")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_image_gen.py::test_dashscope_text_to_image -v`
Expected: FAIL — `image_backend="dashscope"` falls through to openai backend

- [ ] **Step 3: Implement _generate_dashscope in image_gen.py**

Add `dashscope` branch to `generate_image()`:

```python
def generate_image(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None = None,
    model: str | None = None,
    model_edit: str | None = None,
) -> bytes:
    model = model or cfg.image_model[0]
    model_edit = model_edit or cfg.image_model_edit[0]
    if cfg.image_backend == "fal":
        return _generate_fal(cfg, prompt, image_bytes, model, model_edit)
    if cfg.image_backend == "azure":
        return _generate_azure(cfg, prompt, image_bytes, model, model_edit)
    if cfg.image_backend == "dashscope":
        return _generate_dashscope(cfg, prompt, image_bytes, model, model_edit)
    return _generate_openai(cfg, prompt, image_bytes, model, model_edit)
```

Add the `_generate_dashscope()` function:

```python
def _generate_dashscope(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
    model_edit: str,
) -> bytes:
    if not cfg.image_api_url or not cfg.image_api_key:
        raise ValueError(
            "DashScope backend requires IMAGE_API_URL and IMAGE_API_KEY"
        )

    active_model = model_edit if image_bytes is not None else model
    url = cfg.image_api_url  # full endpoint URL, no path appending

    content = [{"type": "text", "text": prompt}]
    if image_bytes is not None:
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

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
        "Authorization": f"Bearer {cfg.image_api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        "Generating image (dashscope) | model={} prompt={!r} has_image={}",
        active_model, prompt, image_bytes is not None,
    )
    resp = _requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()

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
```

- [ ] **Step 4: Run dashscope image tests**

Run: `source venv/bin/activate && python -m pytest tests/test_image_gen.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run ALL tests**

Run: `source venv/bin/activate && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add services/image_gen.py tests/test_image_gen.py
git commit -m "feat: add dashscope image generation backend"
```

---

### Task 2: Video generation — add dashscope backend

**Files:**
- Modify: `services/video_gen.py`
- Modify: `tests/test_video_gen.py`

**Interfaces:**
- Consumes: `cfg.video_api_url` (full endpoint URL), `cfg.video_api_key` (Bearer token), `cfg.video_model_image`, `cfg.video_model_text`, `cfg.video_backend`
- Produces: `start_video_job()` returns `{"task_id": str}`, `poll_video_job()` returns `{"status": "pending"|"done"|"error", ...}` — same contract as existing backends

- [ ] **Step 1: Write failing tests for dashscope video generation**

```python
# tests/test_video_gen.py — add at end of file

def _dashscope_video_cfg():
    """Helper to create a Config with dashscope video backend."""
    return Config(
        image_api_url="", image_api_key="",
        image_model=[""], image_model_edit=[""],
        image_backend="openai", image_api_version="",
        video_backend="dashscope",
        video_api_url="https://ws-c2xbh4slyhwu4ifn.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
        video_api_key="sk-test-key",
        video_api_version="", video_azure_path="",
        video_model_image=["wan2.7-r2v"],
        video_model_text=["wan2.7-t2v"],
        secret_key="test", sd_api_url="", sd_model="",
        # no dashscope-specific fields — reuses image_api_url/image_api_key
    )


def test_dashscope_start_text_to_video():
    """DashScope backend: text-only video submission."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-abc", "task_status": "PENDING"},
        "request_id": "req-789",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="a cat walking", image_bytes=None)

    assert result == {"task_id": "task-abc"}

    # Verify correct model and payload
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.7-t2v"
    assert payload["input"]["prompt"] == "a cat walking"
    assert "media" not in payload["input"]
    assert payload["parameters"]["watermark"] is False
    assert payload["parameters"]["resolution"] == "720P"


def test_dashscope_start_image_to_video():
    """DashScope backend: reference image video submission."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-def", "task_status": "PENDING"},
        "request_id": "req-101",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="slow zoom", image_bytes=b"\x89PNG\r\n\x1a\nfake")

    assert result == {"task_id": "task-def"}

    # Verify correct model and payload includes media
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.7-r2v"
    assert len(payload["input"]["media"]) == 1
    assert payload["input"]["media"][0]["type"] == "reference_image"
    assert payload["input"]["media"][0]["url"].startswith("data:image/png;base64,")


def test_dashscope_poll_pending():
    """DashScope backend: poll returns pending status."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-abc", "task_status": "RUNNING"},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", return_value=mock_resp):
        result = poll_video_job(cfg, {"task_id": "task-abc"})

    assert result["status"] == "pending"


def test_dashscope_poll_done():
    """DashScope backend: poll returns done with video data."""
    cfg = _dashscope_video_cfg()

    mock_poll_resp = MagicMock()
    mock_poll_resp.status_code = 200
    mock_poll_resp.json.return_value = {
        "output": {
            "task_id": "task-abc",
            "task_status": "SUCCEEDED",
            "video_url": "https://cdn.example.com/video.mp4",
        },
    }
    mock_poll_resp.raise_for_status = MagicMock()

    mock_video_resp = MagicMock()
    mock_video_resp.content = b"fake-mp4-data"
    mock_video_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", side_effect=[mock_poll_resp, mock_video_resp]):
        result = poll_video_job(cfg, {"task_id": "task-abc"})

    assert result == {"status": "done", "video_data": b"fake-mp4-data"}


def test_dashscope_poll_failed():
    """DashScope backend: poll returns error on failure."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-abc", "task_status": "FAILED"},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", return_value=mock_resp):
        result = poll_video_job(cfg, {"task_id": "task-abc"})

    assert result["status"] == "error"


def test_dashscope_poll_canceled():
    """DashScope backend: poll returns error on CANCELED status."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-abc", "task_status": "CANCELED"},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", return_value=mock_resp):
        result = poll_video_job(cfg, {"task_id": "task-abc"})

    assert result["status"] == "error"
    assert "CANCELED" in result["message"]


def test_dashscope_missing_config_raises():
    """DashScope backend: raises ValueError when config is missing."""
    cfg = Config(
        image_api_url="", image_api_key="",
        image_model=[""], image_model_edit=[""],
        image_backend="openai", image_api_version="",
        video_backend="dashscope", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=["wan2.7-r2v"], video_model_text=["wan2.7-t2v"],
        secret_key="test", sd_api_url="", sd_model="",
        # no dashscope-specific fields — reuses image_api_url/image_api_key
    )
    with pytest.raises(ValueError, match="VIDEO_API_URL"):
        start_video_job(cfg, prompt="a cat", image_bytes=None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_video_gen.py::test_dashscope_start_text_to_video -v`
Expected: FAIL — `video_backend="dashscope"` falls through to fal backend

- [ ] **Step 3: Implement dashscope video backend in video_gen.py**

Add `dashscope` branches to `start_video_job()` and `poll_video_job()`:

```python
def start_video_job(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model_image: str | None = None,
    model_text: str | None = None,
) -> dict:
    """Submit a video generation job. Returns a submit-context dict for poll_video_job."""
    model_image = model_image or cfg.video_model_image[0]
    model_text = model_text or cfg.video_model_text[0]
    if cfg.video_backend == "azure":
        return _start_azure(cfg, prompt, image_bytes, model_image, model_text)
    if cfg.video_backend == "dashscope":
        return _start_dashscope(cfg, prompt, image_bytes, model_image, model_text)
    return _start_fal(cfg, prompt, image_bytes, model_image, model_text)


def poll_video_job(cfg: Config, submit: dict) -> dict:
    if cfg.video_backend == "azure":
        return _poll_azure(cfg, submit)
    if cfg.video_backend == "dashscope":
        return _poll_dashscope(cfg, submit)
    return _poll_fal(cfg, submit)
```

Add `from urllib.parse import urlparse` to the module-level imports at the top of `video_gen.py`.

Add `_start_dashscope()` and `_poll_dashscope()`:

```python
# ------------------------------------------------------------------ #
# DashScope (Alibaba Cloud) backend                                    #
# ------------------------------------------------------------------ #

def _start_dashscope(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model_image: str,
    model_text: str,
) -> dict:
    if not cfg.video_api_url or not cfg.video_api_key:
        raise ValueError(
            "DashScope backend requires VIDEO_API_URL and VIDEO_API_KEY"
        )

    active_model = model_image if image_bytes is not None else model_text
    url = cfg.video_api_url  # full endpoint URL, no path appending

    payload: dict = {
        "model": active_model,
        "input": {"prompt": prompt},
        "parameters": {
            "resolution": "720P",
            "duration": 5,
            "watermark": False,
        },
    }

    if image_bytes is not None:
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode()
        payload["input"]["media"] = [
            {"type": "reference_image", "url": f"data:{mime};base64,{b64}"}
        ]

    headers = {
        "Authorization": f"Bearer {cfg.video_api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    logger.info(
        "Submitting DashScope video job | model={} prompt={!r} has_image={}",
        active_model, prompt, image_bytes is not None,
    )
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()

    data = resp.json()
    task_id = data["output"]["task_id"]
    logger.info("DashScope video job submitted | task_id={}", task_id)
    return {"task_id": task_id}


def _poll_dashscope(cfg: Config, submit: dict) -> dict:
    task_id = submit["task_id"]
    # Poll URL is at a different path than submit: {hostname}/api/v1/tasks/{task_id}
    parsed = urlparse(cfg.video_api_url)
    url = f"{parsed.scheme}://{parsed.netloc}/api/v1/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {cfg.video_api_key}"}

    resp = requests.get(url, headers=headers)
    resp.raise_for_status()

    data = resp.json()
    status = data.get("output", {}).get("task_status", "UNKNOWN")
    logger.debug("DashScope video poll | task_id={} status={}", task_id, status)

    if status == "SUCCEEDED":
        video_url = data["output"].get("video_url")
        if not video_url:
            return {"status": "error", "message": "SUCCEEDED but no video_url in response"}
        logger.info("DashScope video job complete | task_id={} url={}", task_id, video_url)
        video_resp = requests.get(video_url)
        video_resp.raise_for_status()
        return {"status": "done", "video_data": video_resp.content}
    elif status in ("PENDING", "RUNNING"):
        return {"status": "pending", "queue_position": None}
    elif status == "FAILED":
        message = data.get("output", {}).get("message", "DashScope video generation failed")
        logger.error("DashScope video job failed | task_id={}", task_id)
        return {"status": "error", "message": message}
    else:
        # CANCELED, UNKNOWN, or any other status
        return {"status": "error", "message": f"DashScope video task status: {status}"}
```

- [ ] **Step 4: Run dashscope video tests**

Run: `source venv/bin/activate && python -m pytest tests/test_video_gen.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run ALL tests**

Run: `source venv/bin/activate && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add services/video_gen.py tests/test_video_gen.py
git commit -m "feat: add dashscope video generation backend"
```

---

### Task 3: Integration smoke test — verify full pipeline with mocked DashScope

**Files:**
- Modify: `tests/test_routes.py`

**Interfaces:**
- Consumes: All prior task outputs
- Produces: Confidence that the full request→generate→poll→serve pipeline works for dashscope

- [ ] **Step 1: Write integration test for dashscope image generation via /generate**

```python
# tests/test_routes.py — add at end of file

def test_generate_dashscope_image(client, cfg):
    """Full pipeline: POST /generate with dashscope image backend."""
    from unittest.mock import patch, MagicMock

    cfg.image_backend = "dashscope"
    cfg.image_api_url = "https://ws.example.com/api/v1/services/aigc/multimodal-generation/generation"
    cfg.image_api_key = "sk-test"

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
        })

    assert resp.status_code == 200
    assert b"job_id" in resp.data
```

- [ ] **Step 2: Run integration test**

Run: `source venv/bin/activate && python -m pytest tests/test_routes.py::test_generate_dashscope_image -v`
Expected: PASS

- [ ] **Step 3: Run ALL tests**

Run: `source venv/bin/activate && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_routes.py
git commit -m "test: add dashscope integration smoke test"
```

---

### Task 4: .envrc — add DashScope config example

**Files:**
- Modify: `.envrc`

**Interfaces:**
- None (documentation only)

- [ ] **Step 1: Add commented-out DashScope section to .envrc**

Add the following block to `.envrc`, after the existing video backend section:

```bash
# ------------------------------------------------------------------ #
# DashScope backend (Alibaba Cloud)                                    #
# ------------------------------------------------------------------ #
#
# Models:
#   Image: wan2.7-image, wan2.7-image-pro (multimodal-generation API)
#   Video: wan2.7-t2v (text-to-video), wan2.7-r2v (reference-to-video)
#
# API URLs: use the full endpoint URL for your region/workspace:
#   International: https://<workspace-id>.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/...
#   Beijing:       https://<workspace-id>.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/...
#
# export IMAGE_BACKEND=dashscope
# export VIDEO_BACKEND=dashscope
# export IMAGE_API_URL=${AC_URL_PAY_AS_YOU_GO}/api/v1/services/aigc/multimodal-generation/generation
# export IMAGE_API_KEY=${AC_TOKEN_PAY_AS_YOU_GO}
# export VIDEO_API_URL=${AC_URL_PAY_AS_YOU_GO}/api/v1/services/aigc/video-generation/video-synthesis
# export VIDEO_API_KEY=${AC_TOKEN_PAY_AS_YOU_GO}
# export IMAGE_MODEL=wan2.7-image,wan2.7-image-pro
# export IMAGE_MODEL_EDIT=wan2.7-image-pro
# export VIDEO_MODEL_IMAGE=wan2.7-r2v
# export VIDEO_MODEL_TEXT=wan2.7-t2v
```

- [ ] **Step 2: Verify .envrc syntax is valid**

Run: `bash -n .envrc`
Expected: no output (syntax OK)

- [ ] **Step 3: Commit**

```bash
git add .envrc
git commit -m "docs: add dashscope backend config example to .envrc"
```
