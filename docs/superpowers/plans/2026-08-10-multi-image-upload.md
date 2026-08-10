# Multi-image Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to upload up to 10 reference images that are passed to DashScope vision models (image + video generation), with graceful single-image fallback for other backends.

**Architecture:** Frontend `<input multiple>` collects up to 10 files. `app.py` reads them into `list[bytes]` with server-side count/size validation. Service functions change from `image_bytes: bytes | None` to `images: list[bytes]`. DashScope backends iterate the full list; all other backends extract `images[0]`.

**Tech Stack:** Python, Flask, pytest, vanilla JS, Jinja2

## Global Constraints

- `images` parameter: `list[bytes] | None = None` at function signature level (for backward compat), normalized to `[]` immediately inside the function via `images = images or []`. Downstream code always works with `list[bytes]`.
- Server-side max 10 files, per-file max 10MB, per-file min 1 byte (skip empty), total request max 120MB.
- Non-DashScope backends that do MIME detection must use `_mime_and_b64` from `services.image_gen` instead of inline `[:4]` checks (avoids crash on tiny files).
- Two-space indentation, no tabs.
- All existing tests must pass after each task.
- Existing tests using `image_bytes=` must be updated to `images=` in the same task that changes the signature.

---

### Task 1: Add `_mime_and_b64` helper

**Files:**
- Modify: `services/image_gen.py`
- Test: `tests/test_image_gen.py`

**Interfaces:**
- Consumes: nothing
- Produces: `_mime_and_b64(img_bytes: bytes) -> str` — returns a `data:{mime};base64,{b64}` string

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_image_gen.py`:

```python
from services.image_gen import _mime_and_b64


def test_mime_and_b64_png():
    result = _mime_and_b64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    assert result.startswith("data:image/png;base64,")


def test_mime_and_b64_jpeg():
    result = _mime_and_b64(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    assert result.startswith("data:image/jpeg;base64,")


def test_mime_and_b64_webp():
    data = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 100
    result = _mime_and_b64(data)
    assert result.startswith("data:image/webp;base64,")


def test_mime_and_b64_gif():
    result = _mime_and_b64(b"GIF89a" + b"\x00" * 100)
    assert result.startswith("data:image/gif;base64,")


def test_mime_and_b64_unknown():
    result = _mime_and_b64(b"\x00\x01\x02\x03")
    assert result.startswith("data:application/octet-stream;base64,")


def test_mime_and_b64_tiny_file():
    """Files smaller than 4 bytes must not crash."""
    result = _mime_and_b64(b"\x89")
    assert result.startswith("data:application/octet-stream;base64,")


def test_mime_and_b64_empty():
    result = _mime_and_b64(b"")
    assert result.startswith("data:application/octet-stream;base64,")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_image_gen.py::test_mime_and_b64_png -v`
Expected: FAIL with `ImportError: cannot import name '_mime_and_b64'`

- [ ] **Step 3: Implement `_mime_and_b64`**

Add to `services/image_gen.py` after the imports (before `generate_image`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_image_gen.py -k "mime_and_b64" -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add services/image_gen.py tests/test_image_gen.py
git commit -m "feat: add _mime_and_b64 helper with multi-format MIME detection"
```

---

### Task 2: Change `image_gen.py` to `images: list[bytes]`

**Files:**
- Modify: `services/image_gen.py`
- Test: `tests/test_image_gen.py`

**Interfaces:**
- Consumes: `_mime_and_b64(img_bytes) -> str` from Task 1
- Produces: `generate_image(cfg, prompt, images: list[bytes], model, model_edit) -> bytes`

- [ ] **Step 1: Update `generate_image` signature and dispatcher**

Replace `generate_image` in `services/image_gen.py`:

```python
def generate_image(
    cfg: Config,
    prompt: str,
    images: list[bytes] | None = None,
    model: str | None = None,
    model_edit: str | None = None,
) -> bytes:
    images = images or []
    model = model or cfg.image_model[0]
    model_edit = model_edit or cfg.image_model_edit[0]
    first = images[0] if images else None
    if cfg.image_backend == "fal":
        return _generate_fal(cfg, prompt, first, model, model_edit)
    if cfg.image_backend == "azure":
        return _generate_azure(cfg, prompt, first, model, model_edit)
    if cfg.image_backend == "dashscope":
        return _generate_dashscope(cfg, prompt, images, model, model_edit)
    return _generate_openai(cfg, prompt, first, model, model_edit)
```

Note: `images` defaults to `None` for backward compat with callers, converted to `[]` immediately. DashScope gets the full list; all others get `first` (single bytes or None).

- [ ] **Step 2: Update `_generate_dashscope` to accept `images: list[bytes]`**

Replace the `_generate_dashscope` function signature and image handling:

```python
def _generate_dashscope(
    cfg: Config,
    prompt: str,
    images: list[bytes],
    model: str,
    model_edit: str,
) -> bytes:
    if not cfg.image_api_url or not cfg.image_api_key:
        raise ValueError(
            "DashScope backend requires IMAGE_API_URL and IMAGE_API_KEY"
        )

    active_model = model_edit if images else model
    url = cfg.image_api_url.rstrip("/")

    content = [{"text": prompt}]
    # ponytail: ~117MB for 10 x 5MB images
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
        "Authorization": f"Bearer {cfg.image_api_key}",
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
```

- [ ] **Step 3: Replace inline MIME detection in `_generate_azure` and `_generate_fal`**

In `_generate_azure`, replace the inline MIME detection (line ~49):

```python
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        ext = "png" if mime == "image/png" else "jpg"
```

with:

```python
        data_uri = _mime_and_b64(image_bytes)
        ext = "png" if data_uri.startswith("data:image/png") else "jpg"
```

and use `data_uri` wherever the base64 data URI is needed. The `image=` tuple for the Azure SDK call becomes:

```python
        response = client.images.edit(
            model=model_edit,
            image=(f"image.{ext}", io.BytesIO(image_bytes), data_uri.split(";")[0].replace("data:", "")),
            prompt=prompt,
            n=1,
        )
```

In `_generate_fal`, replace (line ~106-110):

```python
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        img_b64 = base64.b64encode(image_bytes).decode()
        payload: dict = {
            "prompt": prompt,
            "image_urls": [f"data:{mime};base64,{img_b64}"],
        }
```

with:

```python
        payload: dict = {
            "prompt": prompt,
            "image_urls": [_mime_and_b64(image_bytes)],
        }
```

- [ ] **Step 4: Update existing tests to use `images=` parameter**

In `tests/test_image_gen.py`, update these tests:

1. `test_text_to_image_uses_cfg_default`: `generate_image(cfg, prompt="a cat")` — no change needed (no image param).

2. `test_text_to_image_uses_explicit_model`: `generate_image(cfg, prompt="a cat", model="custom/model")` — no change needed.

3. `test_image_to_image_uses_cfg_edit_default`: change `image_bytes=b"jpeg-data"` to `images=[b"jpeg-data"]`.

4. `test_image_to_image_uses_explicit_model_edit`: change `image_bytes=b"jpeg-data"` to `images=[b"jpeg-data"]`.

5. `test_dashscope_text_to_image`: `generate_image(cfg, prompt="a cat wearing a hat")` — no change needed.

6. `test_dashscope_image_to_image`: change `image_bytes=FAKE_PNG` to `images=[FAKE_PNG]`.

7. `test_dashscope_missing_config_raises`: `generate_image(cfg, prompt="a cat")` — no change needed.

- [ ] **Step 5: Add new multi-image tests**

Add to `tests/test_image_gen.py`:

```python
def test_dashscope_multi_image_payload():
    """DashScope: 3 images produce 3 image entries in the payload."""
    cfg = _dashscope_cfg()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 50
    png2 = b"\x89PNG\r\n\x1a\n" + b"\xff" * 50

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [{"type": "image", "image": "https://cdn.example.com/img.png"}]
                }
            }]
        },
        "request_id": "req-multi",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response) as mock_post, \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        generate_image(cfg, prompt="blend these", images=[png, jpg, png2])

    payload = mock_post.call_args.kwargs["json"]
    content = payload["input"]["messages"][0]["content"]
    assert len(content) == 4  # 1 text + 3 images
    assert content[0] == {"text": "blend these"}
    assert content[1]["image"].startswith("data:image/png;base64,")
    assert content[2]["image"].startswith("data:image/jpeg;base64,")
    assert content[3]["image"].startswith("data:image/png;base64,")


def test_dashscope_zero_images_uses_text_model():
    """DashScope: empty images list uses text model, no image entries."""
    cfg = _dashscope_cfg()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [{"type": "image", "image": "https://cdn.example.com/img.png"}]
                }
            }]
        },
        "request_id": "req-zero",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response) as mock_post, \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        generate_image(cfg, prompt="a cat", images=[])

    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == cfg.image_model[0]  # text model, not edit
    content = payload["input"]["messages"][0]["content"]
    assert len(content) == 1  # text only
    assert content[0] == {"text": "a cat"}


def test_dashscope_ten_images():
    """DashScope: 10 images produce 10 entries (boundary test)."""
    cfg = _dashscope_cfg()
    imgs = [b"\x89PNG\r\n\x1a\n" + bytes([i]) * 50 for i in range(10)]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [{"type": "image", "image": "https://cdn.example.com/img.png"}]
                }
            }]
        },
        "request_id": "req-ten",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response) as mock_post, \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        generate_image(cfg, prompt="many refs", images=imgs)

    payload = mock_post.call_args.kwargs["json"]
    content = payload["input"]["messages"][0]["content"]
    assert len(content) == 11  # 1 text + 10 images


def test_non_dashscope_receives_first_image_only():
    """OpenAI backend: only images[0] is passed when multiple provided."""
    cfg_openai = Config(
        image_api_url="https://api.openai.com/v1",
        image_api_key="sk-test",
        image_model=["dall-e-3"], image_model_edit=["gpt-image-1"],
        image_backend="openai", image_api_version="",
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
        # The image param should be a BytesIO with only the first image's bytes
        img_io = call_kwargs["image"]
        assert img_io.read() == b"first-img"
```

- [ ] **Step 6: Run all image_gen tests**

Run: `pytest tests/test_image_gen.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add services/image_gen.py tests/test_image_gen.py
git commit -m "feat: image_gen accepts images: list[bytes], DashScope multi-image support"
```

---

### Task 3: Change `video_gen.py` to `images: list[bytes]`

**Files:**
- Modify: `services/video_gen.py`
- Test: `tests/test_video_gen.py`

**Interfaces:**
- Consumes: `_mime_and_b64` (import from `services.image_gen` or duplicate)
- Produces: `start_video_job(cfg, prompt, images: list[bytes], model_image, model_text) -> dict`

- [ ] **Step 1: Add `_mime_and_b64` import to `video_gen.py`**

Add at top of `services/video_gen.py`:

```python
from services.image_gen import _mime_and_b64
```

- [ ] **Step 2: Update `start_video_job` signature and dispatcher**

Replace `start_video_job`:

```python
def start_video_job(
    cfg: Config,
    prompt: str,
    images: list[bytes] | None = None,
    model_image: str | None = None,
    model_text: str | None = None,
) -> dict:
    """Submit a video generation job. Returns a submit-context dict for poll_video_job."""
    images = images or []
    model_image = model_image or cfg.video_model_image[0]
    model_text = model_text or cfg.video_model_text[0]
    first = images[0] if images else None
    if cfg.video_backend == "azure":
        return _start_azure(cfg, prompt, first, model_image, model_text)
    if cfg.video_backend == "dashscope":
        return _start_dashscope(cfg, prompt, images, model_image, model_text)
    return _start_fal(cfg, prompt, first, model_image, model_text)
```

- [ ] **Step 3: Rewrite `_start_dashscope` to pass `images` list**

Replace `_start_dashscope`:

```python
def _start_dashscope(
    cfg: Config,
    prompt: str,
    images: list[bytes],
    model_image: str,
    model_text: str,
) -> dict:
    if not cfg.video_api_url or not cfg.video_api_key:
        raise ValueError(
            "DashScope backend requires VIDEO_API_URL and VIDEO_API_KEY"
        )

    active_model = model_image if images else model_text
    url = cfg.video_api_url.rstrip("/")

    headers = {
        "Authorization": f"Bearer {cfg.video_api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    use_media = "wan2.6" not in active_model
    payload = _build_dashscope_video_payload(active_model, prompt, images, use_media=use_media)

    logger.info(
        "Submitting DashScope video job | model={} prompt={!r} n_images={} format={}",
        active_model, prompt, len(images), "media" if use_media else "img_url",
    )
    resp = requests.post(url, json=payload, headers=headers)
    if not resp.ok:
        logger.error("DashScope video API error | status={} body={}", resp.status_code, resp.text)
        _raise_dashscope_error(resp)

    data = resp.json()
    task_id = data["output"]["task_id"]
    logger.info("DashScope video job submitted | task_id={}", task_id)
    return {"task_id": task_id}
```

- [ ] **Step 4: Rewrite `_build_dashscope_video_payload` to accept `images: list[bytes]`**

Replace `_build_dashscope_video_payload`:

```python
def _build_dashscope_video_payload(
    model: str,
    prompt: str,
    images: list[bytes],
    use_media: bool,
) -> dict:
    """Build video generation payload. use_media=True for media[] format, False for img_url format."""
    payload: dict = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {
            "resolution": "720P",
            "duration": 5,
            "watermark": False,
        },
    }

    if images:
        # ponytail: ~117MB for 10 x 5MB images
        if use_media:
            payload["input"]["media"] = [
                {"type": "reference_image", "url": _mime_and_b64(img)} for img in images
            ]
        else:
            payload["input"]["img_url"] = _mime_and_b64(images[0])

    return payload
```

- [ ] **Step 5: Update existing video_gen tests to use `images=`**

In `tests/test_video_gen.py`, update:

1. `test_start_text_to_video`: change `image_bytes=None` to `images=[]`.
2. `test_start_image_to_video`: change `image_bytes=b"img-data"` to `images=[b"img-data"]`.
3. `test_start_fal_uses_cfg_default_text_model`: change `image_bytes=None` to `images=[]`.
4. `test_start_fal_uses_explicit_model_text`: change `image_bytes=None` to `images=[]`.
5. `test_start_fal_uses_explicit_model_image`: change `image_bytes=b"img"` to `images=[b"img"]`.
6. `test_dashscope_start_text_to_video`: change `image_bytes=None` to `images=[]`.
7. `test_dashscope_start_image_to_video`: change `image_bytes=b"\x89PNG\r\n\x1a\nfake"` to `images=[b"\x89PNG\r\n\x1a\nfake"]`.
8. `test_dashscope_missing_config_raises`: change `image_bytes=None` to `images=[]`.

- [ ] **Step 6: Add new multi-image video tests**

Add to `tests/test_video_gen.py`:

```python
def test_dashscope_multi_image_video_media():
    """DashScope: 3 images with wan2.7 model produce 3 media[] entries."""
    cfg = _dashscope_video_cfg()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 50
    png2 = b"\x89PNG\r\n\x1a\n" + b"\xff" * 50

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-multi", "task_status": "PENDING"},
        "request_id": "req-multi",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="blend these", images=[png, jpg, png2])

    assert result == {"task_id": "task-multi"}
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.7-r2v"
    assert len(payload["input"]["media"]) == 3
    assert payload["input"]["media"][0]["url"].startswith("data:image/png;base64,")
    assert payload["input"]["media"][1]["url"].startswith("data:image/jpeg;base64,")
    assert payload["input"]["media"][2]["url"].startswith("data:image/png;base64,")


def _dashscope_video_cfg_wan26():
    """Helper to create a Config with wan2.6 video model."""
    return Config(
        image_api_url="", image_api_key="",
        image_model=[""], image_model_edit=[""],
        image_backend="openai", image_api_version="",
        video_backend="dashscope",
        video_api_url="https://ws-c2xbh4slyhwu4ifn.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
        video_api_key="sk-test-key",
        video_api_version="", video_azure_path="",
        video_model_image=["wan2.6-r2v"],
        video_model_text=["wan2.6-t2v"],
        secret_key="test", sd_api_url="", sd_model="",
    )


def test_dashscope_video_wan26_single_image_only():
    """DashScope: wan2.6 model sends only first image via img_url, no media[]."""
    cfg = _dashscope_video_cfg_wan26()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 50

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-wan26", "task_status": "PENDING"},
        "request_id": "req-wan26",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="animate", images=[png, jpg])

    assert result == {"task_id": "task-wan26"}
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.6-r2v"
    assert "media" not in payload["input"]
    assert payload["input"]["img_url"].startswith("data:image/png;base64,")


def test_dashscope_video_zero_images():
    """DashScope: empty images list uses text model, no media/img_url."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-zero", "task_status": "PENDING"},
        "request_id": "req-zero",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="a flying bird", images=[])

    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.7-t2v"
    assert "media" not in payload["input"]
    assert "img_url" not in payload["input"]
```

- [ ] **Step 7: Run all video_gen tests**

Run: `pytest tests/test_video_gen.py -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add services/video_gen.py tests/test_video_gen.py
git commit -m "feat: video_gen accepts images: list[bytes], DashScope multi-image media[]"
```

---

### Task 4: Change `sd_gen.py` to `images: list[bytes]`

**Files:**
- Modify: `services/sd_gen.py`
- Test: `tests/test_sd_gen.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `generate_image_sd(cfg, prompt, images: list[bytes]) -> bytes`

- [ ] **Step 1: Write a minimal test for `generate_image_sd`**

Create `tests/test_sd_gen.py`:

```python
from unittest.mock import patch, MagicMock
from services.sd_gen import generate_image_sd


def test_sd_accepts_images_list(cfg):
    """generate_image_sd accepts images: list[bytes] and extracts first."""
    mock_model = {"key": "m", "hash": "m", "name": "TestModel", "base": "sdxl", "type": "main"}

    with patch("services.sd_gen._get_model", return_value=mock_model), \
         patch("services.sd_gen._upload_image", return_value="img-name") as mock_upload, \
         patch("services.sd_gen._img2img_graph", return_value={"id": "g"}) as mock_graph, \
         patch("services.sd_gen._enqueue", return_value="batch-1"), \
         patch("services.sd_gen._wait_and_fetch", return_value=b"png-bytes"):
        result = generate_image_sd(cfg, prompt="test", images=[b"first-img", b"second-img"])

    assert result == b"png-bytes"
    mock_upload.assert_called_once_with(cfg.sd_api_url, b"first-img")


def test_sd_empty_images_uses_txt2img(cfg):
    """generate_image_sd with empty list uses txt2img path."""
    mock_model = {"key": "m", "hash": "m", "name": "TestModel", "base": "sdxl", "type": "main"}

    with patch("services.sd_gen._get_model", return_value=mock_model), \
         patch("services.sd_gen._txt2img_graph", return_value={"id": "g"}) as mock_txt2img, \
         patch("services.sd_gen._enqueue", return_value="batch-1"), \
         patch("services.sd_gen._wait_and_fetch", return_value=b"png-bytes"):
        result = generate_image_sd(cfg, prompt="test", images=[])

    assert result == b"png-bytes"
    mock_txt2img.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sd_gen.py -v`
Expected: FAIL (signature mismatch — `generate_image_sd` still takes `image_bytes`)

- [ ] **Step 3: Update `generate_image_sd` signature**

Replace the function signature and image extraction in `services/sd_gen.py`:

```python
def generate_image_sd(cfg: Config, prompt: str, images: list[bytes] | None = None) -> bytes:
    images = images or []
    first = images[0] if images else None
    model = _get_model(cfg.sd_api_url, cfg.sd_model)
    base = model.get("base", "sd-1")
    size = _SDXL_SIZE if base == "sdxl" else _SD1_SIZE
    logger.info("SD generation | model={} base={} n_images={}", model["name"], base, len(images))

    if first is not None:
        image_name = _upload_image(cfg.sd_api_url, first)
        graph = _img2img_graph(model, prompt, image_name, size)
    else:
        graph = _txt2img_graph(model, prompt, size)

    batch_id = _enqueue(cfg.sd_api_url, graph)
    return _wait_and_fetch(cfg.sd_api_url, batch_id)
```

- [ ] **Step 4: Run all SD tests**

Run: `pytest tests/test_sd_gen.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add services/sd_gen.py tests/test_sd_gen.py
git commit -m "feat: sd_gen accepts images: list[bytes], extracts first image"
```

---

### Task 5: Update `app.py` — route changes and validation

**Files:**
- Modify: `app.py`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `generate_image(cfg, prompt, images, ...)`, `start_video_job(cfg, prompt, images, ...)`, `generate_image_sd(cfg, prompt, images)`
- Produces: validated `list[bytes]` from POST `/generate`

- [ ] **Step 1: Write failing route tests for validation**

Add to `tests/test_routes.py`:

```python
def test_generate_rejects_more_than_10_images(client):
    """POST with 11 image files returns 400."""
    files = [("images", (io.BytesIO(b"\x89PNG" + b"\x00" * 100), f"img{i}.png")) for i in range(11)]
    resp = client.post(
        "/generate",
        data=[("output_type", "image"), ("prompt", "test")] + files,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_generate_skips_oversized_files(client, monkeypatch):
    """Files exceeding size limit are skipped, remaining files are processed."""
    monkeypatch.setattr("app._MAX_FILE_SIZE", 100)  # 100 bytes for test
    big = b"\x89PNG" + b"\x00" * 200  # 204 bytes, over the 100-byte test limit
    small = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50  # 58 bytes, under limit

    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post(
            "/generate",
            data=[
                ("output_type", "image"),
                ("prompt", "test"),
                ("images", (io.BytesIO(big), "big.png")),
                ("images", (io.BytesIO(small), "small.png")),
            ],
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    assert mock_gen.called
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert len(images_arg) == 1
    assert len(images_arg[0]) == len(small)


def test_generate_empty_filename_filtered(client):
    """Files with empty filenames are filtered out."""
    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post(
            "/generate",
            data=[
                ("output_type", "image"),
                ("prompt", "test"),
                ("images", (io.BytesIO(b""), "")),
                ("images", (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "real.png")),
            ],
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    assert mock_gen.called
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert len(images_arg) == 1


def test_generate_no_images_sends_empty_list(client):
    """POST with no image files passes images=[] to the service."""
    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post("/generate", data={
            "output_type": "image",
            "prompt": "text only",
        })

    assert resp.status_code == 200
    assert mock_gen.called
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert images_arg == []


def test_generate_exactly_10_images_succeeds(client):
    """POST with exactly 10 image files returns 200 (boundary test)."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    files = [("images", (io.BytesIO(png), f"img{i}.png")) for i in range(10)]

    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post(
            "/generate",
            data=[("output_type", "image"), ("prompt", "test")] + files,
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert len(images_arg) == 10


def test_generate_multiple_images_passed(client):
    """POST with 3 images passes all 3 to the service."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post(
            "/generate",
            data=[
                ("output_type", "image"),
                ("prompt", "blend"),
                ("images", (io.BytesIO(png), "a.png")),
                ("images", (io.BytesIO(png), "b.png")),
                ("images", (io.BytesIO(png), "c.png")),
            ],
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert len(images_arg) == 3
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `pytest tests/test_routes.py::test_generate_rejects_more_than_10_images -v`
Expected: FAIL

- [ ] **Step 3: Update `app.py` generate route**

Add module-level constant near the top of `app.py` (after imports):

```python
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per file
_MAX_IMAGES = 10
```

Then replace the image reading section in `generate()`:

```python
@app.post("/generate")
def generate():
    output_type = request.form.get("output_type", "image")
    prompt = request.form.get("prompt", "").strip()

    # Read all uploaded files, filter empty filenames and empty/oversized files
    raw_files = request.files.getlist("images")
    images = []
    for f in raw_files:
        if not f.filename:
            continue
        data = f.read()
        if len(data) == 0:
            continue
        if len(data) > _MAX_FILE_SIZE:
            logger.warning("Skipping oversized file | name={} size={} bytes", f.filename, len(data))
            continue
        images.append(data)

    if len(images) > _MAX_IMAGES:
        abort(400)

    image_model       = request.form.get("image_model")       or cfg.image_model[0]
    image_model_edit  = request.form.get("image_model_edit")  or cfg.image_model_edit[0]
    video_model_image = request.form.get("video_model_image") or cfg.video_model_image[0]
    video_model_text  = request.form.get("video_model_text")  or cfg.video_model_text[0]

    job_id = job_store.create_job()
    logger.info("Job created | job_id={} output_type={} prompt={!r} n_images={}", job_id, output_type, prompt, len(images))

    if output_type == "image":
        threading.Thread(
            target=_run_image_job,
            args=(cfg, job_id, prompt, images, image_model, image_model_edit),
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

- [ ] **Step 4: Add `MAX_CONTENT_LENGTH` to `create_app`**

Add inside `create_app`, after `app = Flask(__name__)`:

```python
app.config["MAX_CONTENT_LENGTH"] = 120 * 1024 * 1024  # 120MB total request cap
```

- [ ] **Step 5: Update background workers to accept `images: list[bytes]`**

Replace the three worker functions:

```python
def _run_image_job(cfg: Config, job_id: str, prompt: str, images: list[bytes],
                   model: str, model_edit: str):
    try:
        data = image_gen.generate_image(cfg, prompt, images, model=model, model_edit=model_edit)
        try:
            _cache_artifact(job_id, data, "png")
        except Exception:
            logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
        job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
        logger.info("Image job done | job_id={}", job_id)
    except Exception as exc:
        logger.exception("Image job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})


def _run_sd_job(cfg: Config, job_id: str, prompt: str, images: list[bytes]):
    try:
        data = sd_gen.generate_image_sd(cfg, prompt, images)
        try:
            _cache_artifact(job_id, data, "png")
        except Exception:
            logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
        job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
        logger.info("SD job done | job_id={}", job_id)
    except Exception as exc:
        logger.exception("SD job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})


def _run_video_job(cfg: Config, job_id: str, prompt: str, images: list[bytes],
                   model_image: str, model_text: str):
    import time
    try:
        submit = video_gen.start_video_job(
            cfg, prompt, images,
            model_image=model_image, model_text=model_text,
        )
        # ... rest unchanged (polling loop)
```

- [ ] **Step 6: Run all route tests**

Run: `pytest tests/test_routes.py -v`
Expected: all PASS

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: app.py reads multiple images with count/size validation"
```

---

### Task 6: Update translation strings

**Files:**
- Modify: `translations.py`
- Test: `tests/test_translations.py`

- [ ] **Step 1: Update strings**

In `translations.py`, change:

```python
"upload_label": "Upload reference images (optional)",
```
(replace old `"Upload Image (optional)"`)

```python
"upload_label": "Referenzbilder hochladen (optional)",
```
(replace old `"Bild hochladen (optional)"`)

Add to both `"en"` and `"de"` dicts:

```python
"upload_max": "Maximum 10 images",
```
```python
"upload_max": "Maximal 10 Bilder",
```

- [ ] **Step 2: Run translation tests**

Run: `pytest tests/test_translations.py -v`
Expected: PASS (if tests check for key existence, they still pass; if they check exact values, update them)

- [ ] **Step 3: Commit**

```bash
git add translations.py
git commit -m "feat: update upload translations for multi-image support"
```

---

### Task 7: Frontend multi-image upload UI

**Files:**
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: `{{ t.upload_label }}`, `{{ t.upload_max }}`
- Produces: `<input name="images" multiple>` with thumbnail grid

- [ ] **Step 1: Replace the image upload section in `index.html`**

Replace the existing image upload `<div>` and its `<script>` (lines 34-60) with:

```html
    <!-- Image upload -->
    <div>
      <label class="block text-lg font-semibold text-gray-700 mb-2">
        {{ t.upload_label }}
      </label>
      <input type="file" name="images" accept="image/*" multiple id="images-input"
             class="block w-full text-lg text-gray-600
                    file:mr-4 file:py-2 file:px-4
                    file:rounded-xl file:border-0
                    file:text-lg file:font-semibold
                    file:bg-blue-50 file:text-blue-700
                    hover:file:bg-blue-100" />
      <p id="upload-max-hint" class="text-sm text-amber-600 mt-2 hidden">
        {{ t.upload_max }}
      </p>
      <div id="image-previews" class="flex flex-wrap gap-3 mt-3"></div>
    </div>
    <script>
      (function() {
        var MAX_IMAGES = 10;
        var selectedFiles = [];
        var input = document.getElementById('images-input');
        var grid = document.getElementById('image-previews');
        var hint = document.getElementById('upload-max-hint');

        input.addEventListener('change', function() {
          var newFiles = Array.from(this.files || []);
          var space = MAX_IMAGES - selectedFiles.length;
          selectedFiles = selectedFiles.concat(newFiles.slice(0, space));
          rebuildInput();
          renderPreviews();
        });

        function removeAt(idx) {
          selectedFiles.splice(idx, 1);
          rebuildInput();
          renderPreviews();
        }

        function rebuildInput() {
          var dt = new DataTransfer();
          selectedFiles.forEach(function(f) { dt.items.add(f); });
          input.files = dt.files;
          var atCap = selectedFiles.length >= MAX_IMAGES;
          hint.classList.toggle('hidden', !atCap);
          input.style.display = atCap ? 'none' : '';
        }

        function renderPreviews() {
          grid.innerHTML = '';
          selectedFiles.forEach(function(file, idx) {
            var wrap = document.createElement('div');
            wrap.className = 'relative';
            var img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.className = 'rounded-xl object-cover';
            img.style.width = '100px';
            img.style.height = '100px';
            img.onload = function() { URL.revokeObjectURL(this.src); };
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = '×';
            btn.className = 'absolute -top-2 -right-2 bg-red-500 text-white rounded-full w-6 h-6 text-sm leading-none flex items-center justify-center hover:bg-red-600';
            btn.onclick = function() { removeAt(idx); };
            wrap.appendChild(img);
            wrap.appendChild(btn);
            grid.appendChild(wrap);
          });
        }
      })();
    </script>
```

- [ ] **Step 2: Manual test**

Start the app: `python app.py`

Open browser, verify:
1. File picker allows selecting multiple images
2. Thumbnails appear in a grid with × remove buttons
3. Clicking × removes that thumbnail and updates the file input
4. At 10 images, the "Maximum 10 images" hint appears and no more can be added
5. Submitting the form with multiple images works end-to-end

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat: multi-image upload UI with thumbnail grid and remove buttons"
```

---

### Task 8: Final integration check

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 2: End-to-end manual test**

Start the app and verify:
1. Upload 2-3 images with a prompt → DashScope image generation receives all images
2. Upload 2-3 images with a prompt → DashScope video generation receives all images in `media[]`
3. Upload 0 images → text-only generation works
4. Upload 1 image → works as before (backward compatible)
5. Try uploading 11 images via curl → 400 response

- [ ] **Step 3: Commit any fixes**

```bash
git add app.py services/ templates/ tests/ translations.py
git commit -m "fix: integration fixes for multi-image upload"
```
